"""Pure-shear fracture toughness (SPEC §4.3, docs/SCIENTIFIC_METHODS.md §3).

G_c = H0 · W(λc), with W(λ) = ∫₁^λ σ_nom dλ from the UN-notched specimen and λc from the
notched specimen (陈 式 2-71 p.34; 刘 p.77).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike

from polymech_mechanics._numeric import as_1d, same_length
from polymech_mechanics.errors import InvalidInputError, MissingGeometryError, OutOfRangeError
from polymech_mechanics.flags import Flag, warning
from polymech_mechanics.statistics import ReplicateSummary, summarize
from polymech_mechanics.uniaxial import (
    StressStretchCurve,
    UniaxialParams,
    UniaxialResult,
    analyze_uniaxial,
)
from polymech_mechanics.units import Q_

_LABELS = {
    "height_m": "可拉伸高度 H0",
    "width_m": "样品宽度 w0",
    "thickness_m": "样品厚度 t0",
    "notch_length_m": "预切裂纹长度 c0",
}

PROCESS_ZONE_WARN_RATIO = 0.5
"""R_p ~ G/W_f is an order-of-magnitude scaling, so only clearly large ratios are flagged."""

CriticalMethod = Literal["manual", "photo", "video_frame", "time_sync", "force_peak_candidate"]
LambdaCDefinition = Literal["crack_onset", "steady_propagation"]
"""刘 p.77: crack just starts to grow; 陈 p.34: crack starts steady propagation."""


@dataclass(frozen=True)
class PureShearGeometry:
    height_m: float | None = None
    width_m: float | None = None
    thickness_m: float | None = None
    notch_length_m: float | None = None

    def require(self, *names: str) -> None:
        missing = [
            _LABELS[n] for n in names if getattr(self, n) is None or not getattr(self, n) > 0
        ]
        if missing:
            raise MissingGeometryError(f"缺少或无效的纯剪切样品尺寸：{'、'.join(missing)}")


def curve_from_force_displacement(
    force_n: ArrayLike, displacement_m: ArrayLike, geometry: PureShearGeometry
) -> StressStretchCurve:
    """λ = 1 + Δh/H0, σ_nom = F/(w0·t0)."""
    geometry.require("height_m", "width_m", "thickness_m")
    assert geometry.height_m and geometry.width_m and geometry.thickness_m
    f = as_1d("力", force_n)
    d = as_1d("位移", displacement_m)
    same_length(force=f, displacement=d)
    return StressStretchCurve(
        1.0 + d / geometry.height_m, f / (geometry.width_m * geometry.thickness_m)
    )


@dataclass(frozen=True)
class CriticalStretch:
    value: float
    method: CriticalMethod
    confirmed: bool
    note: str = ""


def critical_stretch_candidate(notched: StressStretchCurve) -> CriticalStretch:
    """Stretch at the notched specimen's force maximum — only a *candidate* for λc.

    Crack onset usually precedes the force peak, so the user must confirm or replace it
    (photo, video frame, synchronised time, manual entry).
    """
    i = int(np.argmax(notched.nominal_stress_pa))
    return CriticalStretch(
        float(notched.stretch[i]),
        "force_peak_candidate",
        confirmed=False,
        note="有裂纹样品力峰值处的拉伸比，仅作候选，需结合图像确认裂纹开始扩展的时刻",
    )


def critical_stretch_from_time(
    time_s: ArrayLike, stretch: ArrayLike, crack_onset_time_s: float, method: CriticalMethod
) -> CriticalStretch:
    """λc from the time at which crack growth was observed (synchronised photo/video)."""
    t = as_1d("时间", time_s)
    lam = as_1d("拉伸比", stretch)
    same_length(time=t, stretch=lam)
    if np.any(np.diff(t) <= 0):
        raise InvalidInputError("时间序列必须严格递增")
    if not t[0] <= crack_onset_time_s <= t[-1]:
        raise OutOfRangeError("裂纹萌生时刻不在试验记录时间范围内")
    return CriticalStretch(
        float(np.interp(crack_onset_time_s, t, lam)),
        method,
        confirmed=True,
        note=f"t = {crack_onset_time_s:g} s",
    )


@dataclass(frozen=True)
class FractureToughnessResult:
    toughness_j_m2: float
    critical_stretch: CriticalStretch
    lambda_c_definition: LambdaCDefinition
    strain_energy_density_at_critical_j_m3: float
    height_m: float
    unnotched: UniaxialResult
    process_zone_to_height_ratio: float
    """R_p/H0 with R_p ≈ G_c/W_f (陈 p.32–33), i.e. W(λc)/W_f; small-scale inelasticity needs
    ≪ 1. Always reported; a warning is raised above PROCESS_ZONE_WARN_RATIO."""
    flags: tuple[Flag, ...] = field(default=())

    @property
    def provisional(self) -> bool:
        return not self.critical_stretch.confirmed


def strain_energy_at(result: UniaxialResult, stretch: float) -> float:
    """Interpolate W(λ) on the pre-fracture part of an unnotched curve; never extrapolate."""
    ib = result.break_index
    lam = result.stretch[: ib + 1]
    w = result.strain_energy_density_j_m3[: ib + 1]
    if np.any(np.diff(lam) <= 0):
        order = np.argsort(lam, kind="stable")
        lam, w = lam[order], w[order]
    if not lam[0] <= stretch <= lam[-1]:
        raise OutOfRangeError(
            f"λ = {stretch:.4g} 超出无裂纹样品断裂前的拉伸比范围 [{lam[0]:.4g}, {lam[-1]:.4g}]，"
            "不能外推 W(λ)"
        )
    return float(np.interp(stretch, lam, w))


def fracture_toughness(
    unnotched: StressStretchCurve,
    geometry: PureShearGeometry,
    critical: CriticalStretch,
    lambda_c_definition: LambdaCDefinition = "crack_onset",
    unnotched_params: UniaxialParams | None = None,
    hysteresis_ratio: float | None = None,
) -> FractureToughnessResult:
    geometry.require("height_m")
    assert geometry.height_m is not None
    if critical.value < 1.0:
        raise InvalidInputError("临界拉伸比必须 ≥ 1")
    base = analyze_uniaxial(unnotched, unnotched_params)
    w_c = strain_energy_at(base, critical.value)

    # dimensional check: m × J/m³ must convert to J/m²
    gc = float((Q_(geometry.height_m, "m") * Q_(w_c, "J/m**3")).to("J/m**2").magnitude)

    flags: list[Flag] = list(base.flags)
    if not critical.confirmed:
        flags.append(
            warning("lambda_c_unconfirmed", "临界拉伸比尚未确认（当前为候选值），结果为临时值")
        )
    if critical.value >= 0.95 * base.break_stretch:
        flags.append(
            warning(
                "lambda_c_near_unnotched_break",
                "λc 接近无裂纹样品的断裂拉伸比：可能对缺口不敏感，纯剪切 Gc 的解释需谨慎",
            )
        )
    wf = base.work_of_fracture_j_m3
    rp_ratio = (gc / wf) / geometry.height_m if wf > 0 else float("nan")
    if not rp_ratio < PROCESS_ZONE_WARN_RATIO:
        flags.append(
            warning(
                "large_process_zone",
                f"估计的非弹性区尺寸 Rp≈Gc/Wf 约为 H0 的 {rp_ratio:.2f} 倍，"
                "小尺度非弹性假设可能不成立",
            )
        )
    if geometry.width_m is not None and geometry.width_m < 4 * geometry.height_m:
        flags.append(
            warning("geometry_not_pure_shear", "宽高比 w0/H0 < 4，不满足纯剪切 w0 ≫ H0 的几何要求")
        )
    if geometry.thickness_m is not None and geometry.thickness_m > 0.2 * geometry.height_m:
        flags.append(
            warning("geometry_thick", "厚度 t0 与高度 H0 相比不够小（t0 > 0.2·H0），偏离 H0 ≫ t0")
        )
    if geometry.notch_length_m is not None:
        if geometry.notch_length_m <= geometry.height_m:
            flags.append(warning("notch_short", "预切裂纹长度 c0 ≤ H0（陈 p.34 要求 c0 大于 h0）"))
        if geometry.width_m is not None and geometry.notch_length_m > 0.5 * geometry.width_m:
            flags.append(
                warning("notch_long", "预切裂纹超过样品宽度的一半，剩余韧带可能不足以形成稳态扩展")
            )
    if hysteresis_ratio is not None and hysteresis_ratio > 0.2:
        flags.append(
            warning(
                "viscoelastic",
                f"材料滞后比 {hysteresis_ratio:.2f} 较大：远场耗散会计入 Gc，"
                "请注明加载速率并谨慎与其他材料比较",
            )
        )
    return FractureToughnessResult(
        toughness_j_m2=gc,
        critical_stretch=critical,
        lambda_c_definition=lambda_c_definition,
        strain_energy_density_at_critical_j_m3=w_c,
        height_m=geometry.height_m,
        unnotched=base,
        process_zone_to_height_ratio=rp_ratio,
        flags=tuple(flags),
    )


def summarize_toughness(results: Sequence[FractureToughnessResult]) -> ReplicateSummary:
    defs = {r.lambda_c_definition for r in results}
    if len(defs) > 1:
        raise InvalidInputError("不同 λc 定义的断裂韧性不能合并统计")
    if any(r.provisional for r in results):
        raise InvalidInputError("存在未确认临界拉伸比的结果，不能进行重复统计")
    return summarize([r.toughness_j_m2 for r in results])
