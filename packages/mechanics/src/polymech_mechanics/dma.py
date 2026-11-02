"""Dynamic mechanical analysis (SPEC §4.5, docs/SCIENTIFIC_METHODS.md §5).

tan δ = E″/E′. Every Tg candidate carries its definition (tan δ peak, E″ peak, E′ onset) and
frequency; candidates of different definitions are never merged. Peaks are only found inside
the measured range (no extrapolation), and a second peak of comparable prominence makes the
candidate ambiguous instead of silently picking one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import ndimage, signal

from polymech_mechanics._numeric import FloatArray, as_1d, require_points, same_length
from polymech_mechanics.errors import InvalidInputError
from polymech_mechanics.flags import Flag, info, warning

TgDefinition = Literal["tan_delta_peak", "loss_modulus_peak", "storage_modulus_onset"]
LossSource = Literal["measured", "tan_delta × storage", "absent"]
TanSource = Literal["measured", "loss / storage", "absent"]
TG_LABELS: dict[str, str] = {
    "tan_delta_peak": "tan δ 峰",
    "loss_modulus_peak": "损耗模量峰",
    "storage_modulus_onset": "储能模量下降起始（切线交点）",
}
QUANTITY_LABELS = {"storage": "储能模量", "loss": "损耗模量", "tan_delta": "tan δ"}


@dataclass(frozen=True)
class DMAParams:
    consistency_tolerance: float = 0.05
    """Median relative deviation between a measured tan δ and E″/E′ above which a warning is
    raised (e.g. columns from different runs, or E and G mixed)."""
    spike_threshold: float = 6.0
    """Robust z-score (residual from a running median / MAD) above which an isolated point is
    reported as an anomalous spike."""
    spike_window: int = 7
    peak_prominence_fraction: float = 0.1
    """A local maximum counts as a peak when its prominence ≥ this fraction of the curve range."""
    secondary_peak_ratio: float = 0.5
    """A second peak with prominence ≥ this fraction of the main one makes the Tg ambiguous."""
    tg_window_k: tuple[float, float] | None = None
    """Restrict Tg search to this temperature window (used to resolve ambiguous peaks)."""
    onset_baseline_k: tuple[float, float] | None = None
    """Glassy-plateau window for the E′ onset baseline; default: lowest 10 % of the span."""
    frequency_tolerance: float = 0.01
    """Relative difference below which frequencies belong to the same series."""
    reference_temperatures_k: tuple[float, ...] = (298.15,)
    """E′, E″ and tan δ are reported at these temperatures (interpolated, never extrapolated)."""
    deformation_mode: Literal["tension", "shear", "unknown"] = "tension"
    """Tension → E′/E″, shear → G′/G″. Recorded with every result; not used in the maths."""

    def __post_init__(self) -> None:
        if self.spike_window < 3 or self.spike_window % 2 == 0:
            raise InvalidInputError("异常点检测窗口必须是 ≥ 3 的奇数")
        if not 0 < self.peak_prominence_fraction < 1:
            raise InvalidInputError("峰显著性比例必须在 0 与 1 之间")
        for name, w in (("Tg 搜索", self.tg_window_k), ("基线", self.onset_baseline_k)):
            if w is not None and not w[0] < w[1]:
                raise InvalidInputError(f"{name}温度区间下限必须小于上限")


@dataclass(frozen=True)
class TgCandidate:
    definition: TgDefinition
    temperature_k: float
    frequency_hz: float | None
    value: float | None  # tan δ or E″ at the peak; None for the onset
    prominence: float | None
    ambiguous: bool
    other_peaks_k: tuple[float, ...]  # further peaks found (shown, never averaged in)


@dataclass(frozen=True)
class Spike:
    index: int  # into the input arrays
    quantity: Literal["storage", "loss", "tan_delta"]
    temperature_or_frequency: float
    robust_z: float


@dataclass(frozen=True)
class ReferenceValue:
    temperature_k: float
    frequency_hz: float | None
    storage_modulus_pa: float
    loss_modulus_pa: float | None
    loss_factor: float | None


@dataclass(frozen=True)
class DMASeries:
    frequency_hz: float | None
    n_points: int
    x_min: float
    x_max: float
    tg: tuple[TgCandidate, ...]
    reference_values: tuple[ReferenceValue, ...]


@dataclass(frozen=True)
class DMAResult:
    mode: Literal["temperature_sweep", "frequency_sweep"]
    deformation_mode: str
    loss_modulus_source: LossSource
    loss_factor_source: TanSource
    consistency_deviation: float | None
    series: tuple[DMASeries, ...]
    spikes: tuple[Spike, ...]
    order: NDArray[np.int64]
    """Input indices sorted by series, then by temperature (or frequency)."""
    series_index: NDArray[np.int64]  # per input point
    loss_modulus_pa: FloatArray | None  # aligned with the input
    loss_factor: FloatArray | None
    flags: tuple[Flag, ...] = field(default=())


# --------------------------------------------------------------------------- helpers
def _group_frequencies(f: FloatArray, tol: float) -> tuple[NDArray[np.int64], list[float]]:
    """Cluster frequencies whose relative difference ≤ tol; returns labels and centres."""
    uniq = np.unique(f)
    centres: list[list[float]] = []
    for u in uniq:
        if centres and abs(u - centres[-1][-1]) <= tol * max(abs(u), 1e-300):
            centres[-1].append(float(u))
        else:
            centres.append([float(u)])
    edges = [c[-1] for c in centres]
    labels = np.searchsorted(np.array(edges), f, side="left").astype(np.int64)
    return labels, [float(np.median(c)) for c in centres]


def _spikes(y: FloatArray, window: int, threshold: float) -> list[tuple[int, float]]:
    """Isolated points far from the running median.

    The noise scale comes from the MAD of second differences: a running median reproduces a
    monotonic transition exactly (zero residual), so the MAD of the residuals themselves would
    underestimate the noise and turn ordinary scatter into "spikes".
    """
    if len(y) < window + 2:
        return []
    r = y - ndimage.median_filter(y, size=window, mode="nearest")
    d2 = y[1:-1] - 0.5 * (y[:-2] + y[2:])
    s = 1.4826 * float(np.median(np.abs(d2 - np.median(d2)))) / np.sqrt(1.5)
    if s <= 0:
        return []
    z = r / s
    out = []
    for i in np.nonzero(np.abs(z) > threshold)[0]:
        nb = [j for j in (i - 1, i + 1) if 0 <= j < len(z)]
        if all(abs(z[j]) < threshold / 2 for j in nb):  # one point, not a narrow real feature
            out.append((int(i), float(z[i])))
    return out


def _dedup(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Average values at repeated abscissae (e.g. heating + cooling over the same range)."""
    xu, inv = np.unique(x, return_inverse=True)
    return xu, np.bincount(inv, weights=y) / np.bincount(inv)


def _vertex(x: FloatArray, y: FloatArray, i: int) -> tuple[float, float]:
    """Parabola through the peak and its neighbours; clamped to the neighbour interval."""
    if i == 0 or i == len(x) - 1:
        return float(x[i]), float(y[i])
    xs, ys = x[i - 1 : i + 2], y[i - 1 : i + 2]
    a, b, c = np.polyfit(xs - xs[1], ys, 2)
    if a >= 0:
        return float(x[i]), float(y[i])
    t = float(np.clip(-b / (2 * a), xs[0] - xs[1], xs[2] - xs[1]))
    return float(xs[1] + t), float(a * t * t + b * t + c)


def _peak_candidate(
    definition: TgDefinition,
    x: FloatArray,
    y: FloatArray,
    freq: float | None,
    p: DMAParams,
) -> tuple[TgCandidate | None, list[Flag]]:
    label = TG_LABELS[definition]
    fl = _freq_label(freq)
    x, y = _dedup(x, y)
    if len(y) < 5:
        return None, [info(f"{definition}_too_few", f"{fl}{label}：数据点不足，未识别")]
    span = float(y.max() - y.min())
    if span <= 0:
        return None, [info(f"{definition}_flat", f"{fl}{label}：曲线无变化，未识别")]
    peaks, props = signal.find_peaks(y, prominence=p.peak_prominence_fraction * span)
    if len(peaks) == 0:
        return None, [
            info(
                f"{definition}_none",
                f"{fl}在测量温度范围内未找到{label}（峰可能在范围外，不外推）",
            )
        ]
    prom = props["prominences"]
    order = np.argsort(prom)[::-1]
    main = int(peaks[order[0]])
    t, v = _vertex(x, y, main)
    others = tuple(_vertex(x, y, int(peaks[k]))[0] for k in order[1:])
    ambiguous = len(order) > 1 and prom[order[1]] >= p.secondary_peak_ratio * prom[order[0]]
    flags = []
    if ambiguous:
        flags.append(
            warning(
                f"{definition}_multiple",
                f"{fl}{label}存在多个显著峰（"
                + "、".join(f"{k - 273.15:.1f} °C" for k in sorted((t, *others)))
                + "），Tg 有多种解释：未自动选定，请限定搜索温度区间或人工判断",
            )
        )
    return TgCandidate(definition, t, freq, v, float(prom[order[0]]), ambiguous, others), flags


def _onset(
    x: FloatArray, log_e: FloatArray, freq: float | None, p: DMAParams
) -> tuple[TgCandidate | None, list[Flag]]:
    """Intersection of the glassy-plateau tangent and the tangent at the steepest descent of
    log10 E′ (cf. ASTM E1640 storage-modulus onset)."""
    fl = _freq_label(freq)
    label = TG_LABELS["storage_modulus_onset"]
    x, log_e = _dedup(x, log_e)
    if len(x) < 8:
        return None, [info("storage_modulus_onset_too_few", f"{fl}{label}：数据点不足，未识别")]
    if p.onset_baseline_k is not None:
        base = (x >= p.onset_baseline_k[0]) & (x <= p.onset_baseline_k[1])
    else:
        base = x <= x[0] + 0.1 * (x[-1] - x[0])
    if base.sum() < 3:
        return None, [info("storage_modulus_onset_baseline", f"{fl}{label}：基线区间内点数不足")]
    b_slope, b_icpt = np.polyfit(x[base], log_e[base], 1)
    d = np.gradient(log_e, x)
    after = x > x[base].max()
    if not after.any():
        return None, [info("storage_modulus_onset_baseline", f"{fl}{label}：基线之后没有数据")]
    i = int(np.nonzero(after)[0][np.argmin(d[after])])
    drop = float(log_e[base].mean() - log_e[i:].min())
    if i >= len(x) - 2 or d[i] >= b_slope or drop < 0.3:
        return None, [
            info(
                "storage_modulus_onset_none",
                f"{fl}{label}：储能模量没有明显的转变段（下降不足 0.3 个数量级或位于端点），未识别",
            )
        ]
    t = float((log_e[i] - d[i] * x[i] - b_icpt) / (b_slope - d[i]))
    if not x[base].max() <= t <= x[i]:
        return None, [
            info("storage_modulus_onset_none", f"{fl}{label}：切线交点不在基线与拐点之间，未识别")
        ]
    return TgCandidate("storage_modulus_onset", t, freq, None, None, False, ()), []


def _freq_label(freq: float | None) -> str:
    return f"{freq:g} Hz：" if freq is not None else ""


def _interp(x: FloatArray, y: FloatArray | None, at: float) -> float | None:
    if y is None or not x[0] <= at <= x[-1]:
        return None
    return float(np.interp(at, x, y))


# --------------------------------------------------------------------------- analysis
def analyze_dma(
    storage_modulus_pa: ArrayLike,
    *,
    temperature_k: ArrayLike | None = None,
    loss_modulus_pa: ArrayLike | None = None,
    loss_factor: ArrayLike | None = None,
    frequency_hz: ArrayLike | None = None,
    params: DMAParams | None = None,
) -> DMAResult:
    p = params or DMAParams()
    e1 = as_1d("储能模量", storage_modulus_pa)
    n = len(e1)
    require_points(n, 5, "DMA 数据")
    temp = as_1d("温度", temperature_k) if temperature_k is not None else None
    e2 = as_1d("损耗模量", loss_modulus_pa) if loss_modulus_pa is not None else None
    tan_m = as_1d("损耗因子", loss_factor) if loss_factor is not None else None
    freq = as_1d("频率", frequency_hz) if frequency_hz is not None else None
    same_length(
        storage=e1,
        **{
            k: v
            for k, v in {"temperature": temp, "loss": e2, "tan": tan_m, "freq": freq}.items()
            if v is not None
        },
    )
    flags: list[Flag] = []

    positive = e1 > 0
    if not positive.all():
        flags.append(
            warning(
                "nonpositive_storage",
                f"{int((~positive).sum())} 个点储能模量 ≤ 0（无物理意义），不参与 tan δ 与 Tg 计算",
            )
        )
    safe_e1 = np.where(positive, e1, np.nan)

    # tan δ and E″: measured, derived from each other, or absent
    deviation = None
    e2_src: LossSource
    tan_src: TanSource
    tan: FloatArray | None
    loss: FloatArray | None
    if e2 is not None and tan_m is not None:
        e2_src, tan_src = "measured", "measured"
        tan, loss = tan_m, e2
        calc = e2 / safe_e1
        ok = np.isfinite(calc) & (np.abs(calc) > 0)
        if ok.any():
            deviation = float(np.median(np.abs(tan_m[ok] - calc[ok]) / np.abs(calc[ok])))
            if deviation > p.consistency_tolerance:
                flags.append(
                    warning(
                        "loss_factor_inconsistent",
                        f"测得的 tan δ 与 E″/E′ 中位相对偏差 {deviation:.1%}，超过 "
                        f"{p.consistency_tolerance:.0%}：请检查列映射与单位（是否混用了 E 与 G）",
                    )
                )
    elif e2 is not None:
        e2_src, tan_src = "measured", "loss / storage"
        loss, tan = e2, e2 / safe_e1
    elif tan_m is not None:
        e2_src, tan_src = "tan_delta × storage", "measured"
        tan, loss = tan_m, tan_m * safe_e1
    else:
        e2_src, tan_src = "absent", "absent"
        tan = loss = None
        flags.append(info("no_loss_data", "没有损耗模量或 tan δ 列：只能按储能模量变化识别 Tg"))
    if tan is not None and np.nanmin(tan) < 0:
        flags.append(warning("negative_tan_delta", "存在 tan δ < 0 的点，请检查仪器相位校准"))

    # mode and series
    labels, centres = (
        _group_frequencies(freq, p.frequency_tolerance)
        if freq is not None
        else (np.zeros(n, dtype=np.int64), [])
    )
    multi_freq = len(centres) > 1
    isothermal = temp is None or float(np.ptp(temp)) < 2.0
    if multi_freq and isothermal:
        mode: Literal["temperature_sweep", "frequency_sweep"] = "frequency_sweep"
        assert freq is not None
        labels = np.zeros(n, dtype=np.int64)  # one series vs frequency
        x_all = freq
        series_freqs: list[float | None] = [None]
    elif temp is None:
        raise InvalidInputError("DMA 温度扫描需要温度列；频率扫描需要频率列且频率有变化")
    else:
        mode = "temperature_sweep"
        x_all = temp
        series_freqs = list(centres) if centres else [None]
        steps = np.diff(temp)
        if min((steps > 0.2).sum(), (steps < -0.2).sum()) > 0.05 * len(steps):
            flags.append(
                warning(
                    "temperature_not_monotonic",
                    "温度既有升高也有降低（可能混有升温与降温段）：按温度排序后分析，请确认",
                )
            )

    order = np.lexsort((x_all, labels)).astype(np.int64)
    spikes: list[Spike] = []
    series: list[DMASeries] = []
    for s_idx, f_c in enumerate(series_freqs):
        idx = order[labels[order] == s_idx]
        x = x_all[idx]
        # anomaly scan on each quantity (moduli in log space)
        bad = np.zeros(len(idx), dtype=bool)
        scans: list[tuple[Literal["storage", "loss", "tan_delta"], FloatArray]] = [
            ("storage", np.log10(safe_e1[idx]))
        ]
        if e2_src == "measured" and loss is not None:
            scans.append(("loss", np.log10(np.where(loss[idx] > 0, loss[idx], np.nan))))
        if tan_src == "measured" and tan is not None:
            scans.append(("tan_delta", tan[idx]))
        for qname, y in scans:
            fin = np.isfinite(y)
            for j, z in _spikes(y[fin], p.spike_window, p.spike_threshold):
                k = int(np.nonzero(fin)[0][j])
                bad[k] = True
                spikes.append(Spike(int(idx[k]), qname, float(x[k]), z))
        use = ~bad & positive[idx]
        xs = x[use]
        tg: list[TgCandidate] = []
        refs: list[ReferenceValue] = []
        if mode == "temperature_sweep":
            win = (
                (xs >= p.tg_window_k[0]) & (xs <= p.tg_window_k[1])
                if p.tg_window_k
                else np.ones(len(xs), dtype=bool)
            )
            if tan is not None:
                c, fl = _peak_candidate("tan_delta_peak", xs[win], tan[idx][use][win], f_c, p)
                flags += fl
                tg += [c] if c else []
            if loss is not None:
                c, fl = _peak_candidate("loss_modulus_peak", xs[win], loss[idx][use][win], f_c, p)
                flags += fl
                tg += [c] if c else []
            c, fl = _onset(xs, np.log10(e1[idx][use]), f_c, p)
            flags += fl
            tg += [c] if c else []
            for t_ref in p.reference_temperatures_k:
                e_ref = _interp(xs, e1[idx][use], t_ref)
                if e_ref is not None:
                    refs.append(
                        ReferenceValue(
                            t_ref,
                            f_c,
                            e_ref,
                            _interp(xs, None if loss is None else loss[idx][use], t_ref),
                            _interp(xs, None if tan is None else tan[idx][use], t_ref),
                        )
                    )
        series.append(
            DMASeries(f_c, len(idx), float(x.min()), float(x.max()), tuple(tg), tuple(refs))
        )
    if spikes:
        flags.append(
            warning(
                "dma_spikes",
                f"检测到 {len(spikes)} 个孤立异常点（"
                + "、".join(sorted({QUANTITY_LABELS[s.quantity] for s in spikes}))
                + "）：已在图中标出，不参与 Tg 识别；原始数据未修改",
            )
        )
    if mode == "frequency_sweep":
        flags.append(info("frequency_sweep", "等温频率扫描：不报告 Tg；曲线按频率绘制"))
    elif multi_freq:
        flags.append(
            info(
                "multi_frequency",
                f"包含 {len(series_freqs)} 个频率，各频率分别识别 Tg（Tg 随频率变化，不合并）",
            )
        )

    return DMAResult(
        mode=mode,
        deformation_mode=p.deformation_mode,
        loss_modulus_source=e2_src,
        loss_factor_source=tan_src,
        consistency_deviation=deviation,
        series=tuple(series),
        spikes=tuple(spikes),
        order=order,
        series_index=labels,
        loss_modulus_pa=loss,
        loss_factor=tan,
        flags=tuple(flags),
    )
