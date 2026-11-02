"""Cyclic tension analysis (SPEC §4.2, docs/SCIENTIFIC_METHODS.md §2).

A cycle = loading segment (stretch rising from a valley to a peak) + unloading segment
(peak to the next valley). Integrals use nominal stress vs stretch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import ArrayLike
from scipy import signal

from polymech_mechanics._numeric import FloatArray, as_1d, require_points, same_length, trapezoid
from polymech_mechanics.errors import CycleSegmentationError, InvalidInputError
from polymech_mechanics.flags import Flag, info, warning


@dataclass(frozen=True)
class CyclicParams:
    min_amplitude_fraction: float = 0.05
    """Turning points must have a stretch prominence ≥ this fraction of the total stretch
    range (rejects noise); lower it for very small cycles."""
    closure_stretch_tol: float = 0.01
    """A cycle is 'closed' when the unloading end returns within this stretch of the loading
    start and stress is back within `closure_stress_fraction` of the peak."""
    closure_stress_fraction: float = 0.02
    residual_stress_threshold_pa: float = 0.0
    """Residual strain is read where unloading stress first drops to this value."""
    modulus_fraction: float = 0.1
    """Per-cycle loading modulus = slope over the first fraction of the loading stretch span."""
    amplitude_group_tol: float = 0.02
    """Cycles whose peak stretches differ by less than this are treated as the same amplitude."""

    def __post_init__(self) -> None:
        if not 0 < self.min_amplitude_fraction < 1:
            raise InvalidInputError("最小循环幅度比例必须在 0 与 1 之间")
        if not 0 < self.modulus_fraction <= 1:
            raise InvalidInputError("模量拟合比例必须在 (0, 1] 内")


@dataclass(frozen=True)
class CycleResult:
    index: int  # 1-based cycle number
    loading_slice: tuple[int, int]  # [start, stop) indices into the input arrays
    unloading_slice: tuple[int, int] | None
    stretch_start: float
    stretch_max: float
    peak_stress_pa: float
    loading_work_j_m3: float
    unloading_work_j_m3: float | None
    hysteresis_j_m3: float | None
    """W_load − W_unload; equals the dissipated energy density only when `closed`."""
    hysteresis_ratio: float | None  # W_hys / W_load
    closed: bool
    residual_strain: float | None  # λ_residual − 1
    stress_returns_to_threshold: bool
    loading_modulus_pa: float | None
    complete: bool  # False when the record ends before unloading finished


@dataclass(frozen=True)
class AmplitudeGroup:
    stretch_max: float
    cycle_indices: tuple[int, ...]
    peak_stress_retention: tuple[float, ...]  # peak stress / first cycle's peak stress
    hysteresis_retention: tuple[float | None, ...]


@dataclass(frozen=True)
class CyclicResult:
    cycles: tuple[CycleResult, ...]
    cumulative_hysteresis_j_m3: tuple[float, ...]  # over complete cycles, in order
    amplitude_groups: tuple[AmplitudeGroup, ...]
    flags: tuple[Flag, ...] = field(default=())


def segment_cycles(stretch: FloatArray, params: CyclicParams) -> list[tuple[int, int, int | None]]:
    """Return (start, peak, end) index triples; end is None if the record stops at a peak."""
    rng = float(stretch.max() - stretch.min())
    if rng <= 0:
        raise CycleSegmentationError("拉伸比没有变化，无法分割循环")
    prom = params.min_amplitude_fraction * rng
    last = len(stretch) - 1
    peaks = list(signal.find_peaks(stretch, prominence=prom)[0])
    valleys = list(signal.find_peaks(-stretch, prominence=prom)[0])
    # find_peaks ignores the record ends: treat a final rise as an (unfinished) peak and a
    # final fall as the closing valley.
    base = valleys[-1] if valleys and (not peaks or valleys[-1] > peaks[-1]) else 0
    if (not peaks or base > peaks[-1]) and stretch[last] - stretch[base] >= prom:
        peaks.append(last)
    elif (
        peaks
        and (not valleys or valleys[-1] < peaks[-1])
        and stretch[peaks[-1]] - stretch[last] >= prom
    ):
        valleys.append(last)
    if not peaks:
        raise CycleSegmentationError("未找到任何加载峰值，无法分割循环（可尝试减小最小幅度比例）")

    out: list[tuple[int, int, int | None]] = []
    for k, p in enumerate(peaks):
        prev_peak = peaks[k - 1] if k else -1
        next_peak = peaks[k + 1] if k + 1 < len(peaks) else last + 1
        before = [v for v in valleys if prev_peak < v < p]
        after = [v for v in valleys if p < v < next_peak]
        if k and not before:
            raise CycleSegmentationError(f"第 {k} 与第 {k + 1} 个峰之间没有卸载谷，无法分割循环")
        if not after and k + 1 < len(peaks):
            raise CycleSegmentationError(f"第 {k + 1} 个循环缺少卸载段，无法分割")
        start = before[-1] if before else 0
        out.append((int(start), int(p), int(after[0]) if after else None))
    return out


def _loading_modulus(lam: FloatArray, sig: FloatArray, frac: float) -> float | None:
    span = lam[-1] - lam[0]
    sel = lam <= lam[0] + frac * span
    if sel.sum() < 3:
        return None
    return float(np.polyfit(lam[sel], sig[sel], 1)[0])


def _residual(lam_u: FloatArray, sig_u: FloatArray, threshold: float) -> tuple[float, bool]:
    """Stretch where unloading stress first reaches `threshold` (linear interpolation)."""
    below = np.nonzero(sig_u <= threshold)[0]
    if len(below) == 0:
        return float(lam_u[-1]), False
    j = int(below[0])
    if j == 0:
        return float(lam_u[0]), True
    s0, s1 = sig_u[j - 1], sig_u[j]
    t = (s0 - threshold) / (s0 - s1) if s0 != s1 else 0.0
    return float(lam_u[j - 1] + t * (lam_u[j] - lam_u[j - 1])), True


def analyze_cyclic(
    stretch: ArrayLike, nominal_stress_pa: ArrayLike, params: CyclicParams | None = None
) -> CyclicResult:
    params = params or CyclicParams()
    lam = as_1d("拉伸比", stretch)
    sig = as_1d("名义应力", nominal_stress_pa)
    same_length(stretch=lam, stress=sig)
    require_points(len(lam), 5, "循环拉伸数据")
    flags: list[Flag] = []

    cycles: list[CycleResult] = []
    for k, (a, p, e) in enumerate(segment_cycles(lam, params), start=1):
        lam_l, sig_l = lam[a : p + 1], sig[a : p + 1]
        w_load = trapezoid(sig_l, lam_l)
        mod = _loading_modulus(lam_l, sig_l, params.modulus_fraction)
        peak = float(sig_l.max())
        if e is None:
            cycles.append(
                CycleResult(
                    k,
                    (a, p + 1),
                    None,
                    float(lam[a]),
                    float(lam[p]),
                    peak,
                    w_load,
                    None,
                    None,
                    None,
                    False,
                    None,
                    False,
                    mod,
                    False,
                )
            )
            flags.append(
                warning("incomplete_cycle", f"第 {k} 个循环没有卸载段（记录在峰值处结束）")
            )
            continue
        lam_u, sig_u = lam[p : e + 1], sig[p : e + 1]
        # unloading integral taken in the direction of increasing stretch → positive work
        w_unload = -trapezoid(sig_u, lam_u)
        w_hys = w_load - w_unload
        closed = bool(
            abs(lam[e] - lam[a]) <= params.closure_stretch_tol
            and abs(sig[e] - sig[a]) <= params.closure_stress_fraction * max(abs(peak), 1e-300)
        )
        lam_res, returned = _residual(lam_u, sig_u, params.residual_stress_threshold_pa)
        cycles.append(
            CycleResult(
                index=k,
                loading_slice=(a, p + 1),
                unloading_slice=(p, e + 1),
                stretch_start=float(lam[a]),
                stretch_max=float(lam[p]),
                peak_stress_pa=peak,
                loading_work_j_m3=w_load,
                unloading_work_j_m3=w_unload,
                hysteresis_j_m3=w_hys,
                hysteresis_ratio=w_hys / w_load if w_load > 0 else None,
                closed=closed,
                residual_strain=lam_res - 1.0,
                stress_returns_to_threshold=returned,
                loading_modulus_pa=mod,
                complete=True,
            )
        )
        if not closed:
            flags.append(
                info(
                    "open_cycle",
                    f"第 {k} 个循环未闭合（起点 λ={lam[a]:.4g}，终点 λ={lam[e]:.4g}）："
                    "滞后能按 W_load − W_unload 报告，不等同于完整热耗散",
                )
            )
        if not returned:
            flags.append(
                warning(
                    "stress_not_returned",
                    f"第 {k} 个循环卸载时应力未降至阈值，残余应变取卸载终点，可能偏大",
                )
            )

    complete = [c for c in cycles if c.hysteresis_j_m3 is not None]
    cumulative = tuple(float(v) for v in np.cumsum([c.hysteresis_j_m3 for c in complete]))
    return CyclicResult(
        cycles=tuple(cycles),
        cumulative_hysteresis_j_m3=cumulative,
        amplitude_groups=_group_by_amplitude(cycles, params.amplitude_group_tol),
        flags=tuple(flags),
    )


def _group_by_amplitude(cycles: Sequence[CycleResult], tol: float) -> tuple[AmplitudeGroup, ...]:
    groups: list[list[CycleResult]] = []
    for c in cycles:
        for g in groups:
            if abs(g[0].stretch_max - c.stretch_max) <= tol:
                g.append(c)
                break
        else:
            groups.append([c])
    out = []
    for g in groups:
        first = g[0]
        h0 = first.hysteresis_j_m3
        out.append(
            AmplitudeGroup(
                stretch_max=first.stretch_max,
                cycle_indices=tuple(c.index for c in g),
                peak_stress_retention=tuple(c.peak_stress_pa / first.peak_stress_pa for c in g),
                hysteresis_retention=tuple(
                    (c.hysteresis_j_m3 / h0) if (c.hysteresis_j_m3 is not None and h0) else None
                    for c in g
                ),
            )
        )
    return tuple(out)
