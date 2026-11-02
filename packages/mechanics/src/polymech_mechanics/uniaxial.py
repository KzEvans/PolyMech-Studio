"""Uniaxial tension analysis (SPEC §4.1, docs/SCIENTIFIC_METHODS.md §1).

All inputs/outputs are SI: stretch (dimensionless), stress Pa, strain energy density J/m^3.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import ArrayLike
from scipy import integrate, signal

from polymech_mechanics._numeric import (
    FloatArray,
    as_1d,
    cumulative_trapezoid,
    require_points,
    same_length,
)
from polymech_mechanics.errors import InvalidInputError, MissingGeometryError
from polymech_mechanics.fitting import LinearFit, linear_fit
from polymech_mechanics.flags import Flag, info, warning
from polymech_mechanics.statistics import ReplicateSummary, summarize

_GEOMETRY_LABELS = {
    "gauge_length_m": "初始标距 L0",
    "width_m": "样品宽度",
    "thickness_m": "样品厚度",
}


@dataclass(frozen=True)
class TensileGeometry:
    """Specimen dimensions in metres. None means "not recorded" — never defaulted."""

    gauge_length_m: float | None = None
    width_m: float | None = None
    thickness_m: float | None = None

    def require(self, *names: str) -> None:
        missing = [
            _GEOMETRY_LABELS[n]
            for n in names
            if getattr(self, n) is None or not getattr(self, n) > 0
        ]
        if missing:
            raise MissingGeometryError(
                f"缺少或无效的样品尺寸：{'、'.join(missing)}，请补充后再计算"
            )

    @property
    def area_m2(self) -> float:
        self.require("width_m", "thickness_m")
        assert self.width_m is not None and self.thickness_m is not None
        return self.width_m * self.thickness_m


@dataclass(frozen=True)
class StressStretchCurve:
    """Nominal stress vs stretch in loading order."""

    stretch: FloatArray
    nominal_stress_pa: FloatArray

    def __post_init__(self) -> None:
        s = as_1d("拉伸比", self.stretch)
        p = as_1d("名义应力", self.nominal_stress_pa)
        same_length(stretch=s, stress=p)
        require_points(len(s), 2, "应力–拉伸比曲线")
        if np.any(s <= 0):
            raise InvalidInputError("拉伸比必须为正数")
        object.__setattr__(self, "stretch", s)
        object.__setattr__(self, "nominal_stress_pa", p)


def curve_from_force_displacement(
    force_n: ArrayLike, displacement_m: ArrayLike, geometry: TensileGeometry
) -> StressStretchCurve:
    """λ = 1 + Δl/L0, σ_nom = F/A0 (A0 = width × thickness)."""
    geometry.require("gauge_length_m", "width_m", "thickness_m")
    assert geometry.gauge_length_m is not None
    f = as_1d("力", force_n)
    d = as_1d("位移", displacement_m)
    same_length(force=f, displacement=d)
    return StressStretchCurve(1.0 + d / geometry.gauge_length_m, f / geometry.area_m2)


def curve_from_engineering_strain(
    strain: ArrayLike, nominal_stress_pa: ArrayLike
) -> StressStretchCurve:
    """λ = 1 + ε, with ε as a fraction (convert percent upstream)."""
    return StressStretchCurve(1.0 + as_1d("工程应变", strain), as_1d("名义应力", nominal_stress_pa))


@dataclass(frozen=True)
class UniaxialParams:
    modulus_stretch_range: tuple[float, float] = (1.0, 1.05)
    """Stretch interval for the initial-modulus fit (刘 p.77: 1.05 elastomers / 1.02 plastics)."""
    break_drop_fraction: float = 0.5
    """Fracture = the last stress peak after which stress falls below (1 - fraction) of the
    peak value within `break_drop_window` samples and never exceeds the peak again."""
    break_drop_window: int = 5
    break_stretch: float | None = None
    """User-confirmed fracture stretch; overrides automatic detection."""
    smoothing_window: int | None = None
    """Savitzky–Golay window (points, odd ≥ 5) applied before differentiation; None = raw."""

    def __post_init__(self) -> None:
        lo, hi = self.modulus_stretch_range
        if not (lo < hi):
            raise InvalidInputError("模量拟合区间下限必须小于上限")
        if not 0 < self.break_drop_fraction < 1:
            raise InvalidInputError("断裂判据的应力下降比例必须在 0 与 1 之间")
        if self.smoothing_window is not None and (
            self.smoothing_window < 5 or self.smoothing_window % 2 == 0
        ):
            raise InvalidInputError("平滑窗口必须是不小于 5 的奇数")


@dataclass(frozen=True)
class HardeningResult:
    present: bool
    stretch_at_min_modulus: float
    min_differential_modulus_pa: float
    final_differential_modulus_pa: float
    ratio_final_to_min: float


@dataclass(frozen=True)
class UniaxialResult:
    # Full processed curves (same length as input); quantities beyond break_index are post-fracture
    # (differential modulus is NaN there).
    stretch: FloatArray
    nominal_stress_pa: FloatArray
    true_stress_pa: FloatArray
    strain_energy_density_j_m3: FloatArray
    differential_modulus_pa: FloatArray
    break_index: int
    break_detected: bool
    modulus_fit: LinearFit
    max_stress_pa: float
    stretch_at_max_stress: float
    break_stress_pa: float
    break_stretch: float
    elongation_at_break_percent: float
    work_of_fracture_j_m3: float
    work_of_fracture_numerical_error_j_m3: float
    hardening: HardeningResult | None
    flags: tuple[Flag, ...] = field(default=())

    @property
    def initial_modulus_pa(self) -> float:
        return self.modulus_fit.slope


def _differential_modulus(stretch: FloatArray, stress: FloatArray) -> FloatArray:
    """dσ/dλ by central differences on a possibly non-uniform grid; NaN where dλ == 0."""
    out = np.full_like(stress, np.nan)
    n = len(stress)
    if n < 2:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        dl = np.diff(stretch)
        ds = np.diff(stress)
        fwd = np.where(dl != 0, ds / dl, np.nan)
        out[0] = fwd[0]
        out[-1] = fwd[-1]
        if n > 2:
            span = stretch[2:] - stretch[:-2]
            out[1:-1] = np.where(span != 0, (stress[2:] - stress[:-2]) / span, np.nan)
    return out


def detect_break(stress: FloatArray, params: UniaxialParams) -> int | None:
    """Index of the fracture point (see UniaxialParams.break_drop_fraction), or None."""
    imax = int(np.argmax(stress))
    smax = stress[imax]
    if smax <= 0:
        return None
    keep = 1.0 - params.break_drop_fraction
    n = len(stress)
    run: list[int] = []
    for i in range(imax, n - 1):
        window = stress[i + 1 : i + 1 + params.break_drop_window]
        is_candidate = (
            stress[i] >= 0.05 * smax
            and window.min() < keep * stress[i]
            and stress[i + 1 :].max() < stress[i]
        )
        if is_candidate:
            run.append(i)
        elif run:
            break
    if not run:
        return None
    return run[int(np.argmax(stress[run]))]


def analyze_uniaxial(
    curve: StressStretchCurve, params: UniaxialParams | None = None
) -> UniaxialResult:
    params = params or UniaxialParams()
    lam = curve.stretch
    sig = curve.nominal_stress_pa
    flags: list[Flag] = []

    if np.any(np.diff(lam) < 0):
        flags.append(
            warning("non_monotonic_stretch", "拉伸比存在回退（非单调加载），单轴分析假定单调加载")
        )

    # --- fracture point
    if params.break_stretch is not None:
        if params.break_stretch < lam[0]:
            raise InvalidInputError("指定的断裂拉伸比小于曲线起点")
        crossings = np.nonzero(lam >= params.break_stretch)[0]
        if len(crossings) == 0:
            raise InvalidInputError("指定的断裂拉伸比超过曲线的最大拉伸比")
        ib = int(crossings[0])
        if lam[ib] > params.break_stretch:
            ib -= 1
        detected = True
        flags.append(
            info("break_user_defined", f"断裂点由用户指定（λ = {params.break_stretch:g}）")
        )
    else:
        found = detect_break(sig, params)
        if found is None:
            ib, detected = len(sig) - 1, False
            flags.append(
                warning(
                    "break_not_detected", "未检测到明确的断裂点，使用最后一个数据点；请人工确认"
                )
            )
        else:
            ib, detected = found, True

    lam_b, sig_b = lam[: ib + 1], sig[: ib + 1]
    imax = int(np.argmax(sig_b))

    # --- initial modulus
    lo, hi = params.modulus_stretch_range
    loading = np.arange(len(lam)) <= imax
    sel = loading & (lam >= lo) & (lam <= hi)
    fit = linear_fit(lam[sel], sig[sel], what=f"模量拟合区间 λ∈[{lo:g}, {hi:g}] 内")
    if fit.n_points < 8:
        flags.append(warning("modulus_few_points", f"模量拟合只使用了 {fit.n_points} 个点"))
    if fit.r_squared < 0.98:
        flags.append(
            warning(
                "modulus_low_r2",
                f"模量拟合 R² = {fit.r_squared:.4f}，初始段线性较差，请检查区间或零点",
            )
        )
    offset = fit.intercept + fit.slope * 1.0
    if abs(offset) > 0.1 * abs(fit.slope) * (hi - lo):
        flags.append(
            warning("zero_offset", "拟合直线在 λ=1 处应力明显不为零，可能存在预载或零点偏移")
        )

    # --- curves
    true_stress = lam * sig
    w = cumulative_trapezoid(sig, lam)
    # differentiate (and smooth) only the pre-fracture curve so the drop does not leak in
    smoothed = sig_b
    if params.smoothing_window is not None and len(sig_b) > params.smoothing_window:
        smoothed = signal.savgol_filter(sig_b, params.smoothing_window, polyorder=3)
    dmod = np.full_like(sig, np.nan)
    dmod[: ib + 1] = _differential_modulus(lam_b, smoothed)

    # --- work of fracture and its discretisation error
    wf = float(w[ib])
    wf_err = abs(wf - float(integrate.simpson(sig_b, x=lam_b))) if len(lam_b) >= 3 else float("nan")

    # --- quality flags
    if imax < ib and sig[ib] < 0.95 * sig[imax]:
        flags.append(
            warning(
                "yield_or_necking",
                "最大应力出现在断裂之前且其后应力下降超过 5%，疑似屈服、颈缩或局部失稳",
            )
        )
    pre = sig[: imax + 1]
    if len(pre) > 1:
        drops = (pre[:-1] - pre[1:]) / np.maximum(np.abs(pre[:-1]), 1e-300)
        if np.any((drops > 0.1) & (pre[:-1] > 0.05 * sig[imax])):
            flags.append(
                warning("possible_slip", "加载段出现超过 10% 的突然应力下降，疑似夹具打滑")
            )

    hardening = _hardening(lam_b, dmod[: ib + 1], hi)

    return UniaxialResult(
        stretch=lam,
        nominal_stress_pa=sig,
        true_stress_pa=true_stress,
        strain_energy_density_j_m3=w,
        differential_modulus_pa=dmod,
        break_index=ib,
        break_detected=detected,
        modulus_fit=fit,
        max_stress_pa=float(sig[imax]),
        stretch_at_max_stress=float(lam[imax]),
        break_stress_pa=float(sig[ib]),
        break_stretch=float(lam[ib]),
        elongation_at_break_percent=float((lam[ib] - 1.0) * 100.0),
        work_of_fracture_j_m3=wf,
        work_of_fracture_numerical_error_j_m3=wf_err,
        hardening=hardening,
        flags=tuple(flags),
    )


def _hardening(stretch: FloatArray, dmod: FloatArray, fit_hi: float) -> HardeningResult | None:
    """Strain hardening: differential modulus rises again after its minimum.

    Searched beyond the modulus-fit interval so the initial elastic region is excluded.
    """
    mask = (stretch > fit_hi) & np.isfinite(dmod)
    if mask.sum() < 5:
        return None
    lam, d = stretch[mask], dmod[mask]
    i_min = int(np.argmin(d))
    d_min, d_final = float(d[i_min]), float(d[-1])
    ratio = d_final / d_min if d_min > 0 else float("nan")
    present = bool(d_min > 0 and i_min < len(d) - 1 and d_final > 1.1 * d_min)
    return HardeningResult(present, float(lam[i_min]), d_min, d_final, ratio)


@dataclass(frozen=True)
class UniaxialReplicateSummary:
    initial_modulus_pa: ReplicateSummary
    max_stress_pa: ReplicateSummary
    break_stress_pa: ReplicateSummary
    break_stretch: ReplicateSummary
    work_of_fracture_j_m3: ReplicateSummary


def summarize_replicates(results: Sequence[UniaxialResult]) -> UniaxialReplicateSummary:
    return UniaxialReplicateSummary(
        initial_modulus_pa=summarize([r.initial_modulus_pa for r in results]),
        max_stress_pa=summarize([r.max_stress_pa for r in results]),
        break_stress_pa=summarize([r.break_stress_pa for r in results]),
        break_stretch=summarize([r.break_stretch for r in results]),
        work_of_fracture_j_m3=summarize([r.work_of_fracture_j_m3 for r in results]),
    )
