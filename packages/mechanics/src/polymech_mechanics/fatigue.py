"""Cyclic pure-shear fatigue (SPEC §4.4, docs/SCIENTIFIC_METHODS.md §4).

G = H0 · W(λ) with W from the steady-state loading branch of an UN-notched specimen;
dc/dN ≈ Δc/ΔN from the notched specimen. Observations below the detection limit
(resolution / ΔN) are censored: they are never stored as 0 and never enter the regression.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike
from scipy import stats

from polymech_mechanics._numeric import as_1d, require_points
from polymech_mechanics.cyclic import CyclicParams, analyze_cyclic
from polymech_mechanics.errors import InsufficientDataError, InvalidInputError
from polymech_mechanics.fitting import LinearFit, linear_fit
from polymech_mechanics.flags import Flag, info, warning
from polymech_mechanics.units import Q_

GConvention = Literal["G_max", "delta_G"]
"""G_max: W integrated over the loading branch from its minimum stretch (papers: λ_min = 1).
delta_G: user-defined range convention. Rates with different conventions are never merged."""


# --------------------------------------------------------------------------- steady state
@dataclass(frozen=True)
class SteadyStateEnergy:
    stretch_min: float
    stretch_max: float
    energy_density_j_m3: float
    cycle_index: int
    n_complete_cycles: int
    stabilized: bool
    relative_change: float
    """|W_last − W_ref| / W_last, W_ref = loading work `compare_back` cycles earlier."""
    flags: tuple[Flag, ...] = field(default=())


def steady_state_energy(
    stretch: ArrayLike,
    nominal_stress_pa: ArrayLike,
    compare_back: int = 10,
    tolerance: float = 0.01,
    params: CyclicParams | None = None,
) -> SteadyStateEnergy:
    """Loading-branch strain energy of the last complete cycle of an un-notched specimen.

    陈 p.78 cycles 1000 times, 刘 p.77 500 times before reading W(λ); this function checks
    that the loading work has stopped changing rather than trusting a fixed count.
    """
    res = analyze_cyclic(stretch, nominal_stress_pa, params)
    complete = [c for c in res.cycles if c.complete]
    require_points(len(complete), 2, "稳态判定所需的完整循环")
    last = complete[-1]
    ref = complete[max(0, len(complete) - 1 - compare_back)]
    rel = abs(last.loading_work_j_m3 - ref.loading_work_j_m3) / last.loading_work_j_m3
    flags = list(res.flags)
    stabilized = rel <= tolerance
    if not stabilized:
        flags.append(
            warning(
                "not_steady",
                f"最后 {len(complete) - complete.index(ref) - 1} 个循环的加载功变化 {rel:.1%}，"
                f"超过 {tolerance:.1%}：应力–拉伸曲线可能尚未稳定",
            )
        )
    if abs(last.stretch_start - 1.0) > 0.01:
        flags.append(
            info(
                "lambda_min_not_one",
                f"稳态循环加载起点 λ = {last.stretch_start:.4g}（不为 1），W 为该加载段积分",
            )
        )
    return SteadyStateEnergy(
        stretch_min=last.stretch_start,
        stretch_max=last.stretch_max,
        energy_density_j_m3=last.loading_work_j_m3,
        cycle_index=last.index,
        n_complete_cycles=len(complete),
        stabilized=stabilized,
        relative_change=rel,
        flags=tuple(flags),
    )


def energy_release_rate(height_m: float, energy_density_j_m3: float) -> float:
    if not height_m > 0:
        raise InvalidInputError("H0 必须为正")
    return float((Q_(height_m, "m") * Q_(energy_density_j_m3, "J/m**3")).to("J/m**2").magnitude)


@dataclass(frozen=True)
class FatigueLoading:
    stretch_min: float
    stretch_max: float
    energy_release_rate_j_m2: float
    convention: GConvention
    frequency_hz: float | None = None
    load_ratio: float | None = None


def loading_from_steady_state(
    steady: SteadyStateEnergy,
    height_m: float,
    convention: GConvention = "G_max",
    frequency_hz: float | None = None,
) -> FatigueLoading:
    return FatigueLoading(
        stretch_min=steady.stretch_min,
        stretch_max=steady.stretch_max,
        energy_release_rate_j_m2=energy_release_rate(height_m, steady.energy_density_j_m3),
        convention=convention,
        frequency_hz=frequency_hz,
    )


# --------------------------------------------------------------------------- crack growth
CrackStatus = Literal["measured", "below_detection_limit"]


@dataclass(frozen=True)
class CrackGrowthRate:
    loading: FatigueLoading
    status: CrackStatus
    dc_dn_m_per_cycle: float | None  # None when censored — never 0
    detection_limit_m_per_cycle: float
    delta_c_m: float
    delta_n_cycles: float
    n_observations: int
    regression_slope_m_per_cycle: float | None
    regression_stderr_m_per_cycle: float | None
    resolution_m: float

    @property
    def upper_bound_m_per_cycle(self) -> float | None:
        return self.detection_limit_m_per_cycle if self.status == "below_detection_limit" else None


def crack_growth_rate(
    cycles: ArrayLike, crack_length_m: ArrayLike, loading: FatigueLoading, resolution_m: float
) -> CrackGrowthRate:
    """dc/dN = Δc/ΔN over the observation window; detection limit = resolution/ΔN.

    Example (刘 p.77): 20 μm resolution over 50 000 cycles → 0.4 nm/cycle.
    """
    n = as_1d("循环次数", cycles)
    c = as_1d("裂纹长度", crack_length_m)
    if len(n) != len(c):
        raise InvalidInputError("循环次数与裂纹长度数量不一致")
    require_points(len(n), 2, "裂纹长度观测")
    if not resolution_m > 0:
        raise InvalidInputError("裂纹位置测量分辨率必须为正")
    order = np.argsort(n, kind="stable")
    n, c = n[order], c[order]
    dn = float(n[-1] - n[0])
    if dn <= 0:
        raise InvalidInputError("观测循环次数没有增加")
    dc = float(c[-1] - c[0])
    if dc < -resolution_m:
        raise InvalidInputError("裂纹长度减小超过测量分辨率，请检查数据或测量基准")
    limit = resolution_m / dn
    slope = stderr = None
    if len(n) >= 3:
        fit = linear_fit(n, c, what="裂纹长度–循环次数回归")
        slope, stderr = fit.slope, fit.slope_stderr
    if dc < resolution_m:
        return CrackGrowthRate(
            loading,
            "below_detection_limit",
            None,
            limit,
            dc,
            dn,
            len(n),
            slope,
            stderr,
            resolution_m,
        )
    return CrackGrowthRate(
        loading, "measured", dc / dn, limit, dc, dn, len(n), slope, stderr, resolution_m
    )


# --------------------------------------------------------------------------- threshold
@dataclass(frozen=True)
class ThresholdFit:
    reportable: bool
    refusal_reasons: tuple[str, ...]
    threshold_j_m2: float | None  # G0 where the fitted line reaches dc/dN = 0
    threshold_stderr_j_m2: float | None
    ci95_j_m2: tuple[float, float] | None  # bootstrap percentile interval
    fit: LinearFit | None
    g_range_j_m2: tuple[float, float] | None
    extrapolation_distance_j_m2: float | None
    n_measured_used: int
    n_censored: int
    convention: GConvention
    bootstrap_samples: int
    bootstrap_seed: int
    flags: tuple[Flag, ...] = field(default=())


def _single_convention(rates: Sequence[CrackGrowthRate]) -> GConvention:
    conv = {r.loading.convention for r in rates}
    if len(conv) != 1:
        raise InvalidInputError(f"能量释放率约定不一致（{sorted(conv)}），不能合并分析")
    return next(iter(conv))


def fit_threshold(
    rates: Sequence[CrackGrowthRate],
    g_range_j_m2: tuple[float, float] | None = None,
    min_points: int = 3,
    min_r_squared: float = 0.9,
    curvature_alpha: float = 0.05,
    n_bootstrap: int = 2000,
    seed: int = 0,
) -> ThresholdFit:
    """Linear extrapolation dc/dN = b·(G − G0) of measured points within `g_range_j_m2`.

    Refuses (reportable=False, threshold None) when there are too few points, the slope is
    not positive, G0 ≤ 0, R² is low, or a quadratic term is statistically significant.
    """
    if not rates:
        raise InsufficientDataError("没有裂纹扩展速率数据")
    conv = _single_convention(rates)
    measured = [r for r in rates if r.status == "measured"]
    censored = [r for r in rates if r.status == "below_detection_limit"]
    if g_range_j_m2 is not None:
        lo, hi = g_range_j_m2
        measured = [r for r in measured if lo <= r.loading.energy_release_rate_j_m2 <= hi]
    g = np.array([r.loading.energy_release_rate_j_m2 for r in measured])
    y = np.array([r.dc_dn_m_per_cycle for r in measured], dtype=float)

    def refuse(*reasons: str, fit: LinearFit | None = None) -> ThresholdFit:
        return ThresholdFit(
            False,
            reasons,
            None,
            None,
            None,
            fit,
            g_range_j_m2,
            None,
            len(measured),
            len(censored),
            conv,
            0,
            seed,
        )

    if len(measured) < min_points:
        return refuse(f"拟合区间内只有 {len(measured)} 个可测扩展速率，至少需要 {min_points} 个")
    if len(np.unique(g)) < 2:
        return refuse("拟合点的 G 值相同，无法确定斜率")
    fit = linear_fit(g, y, what="dc/dN–G 拟合")
    reasons: list[str] = []
    if fit.slope <= 0:
        reasons.append("dc/dN 随 G 不增加（斜率 ≤ 0），阈值不可辨识")
    if fit.r_squared < min_r_squared:
        reasons.append(f"线性拟合 R² = {fit.r_squared:.3f} < {min_r_squared}")
    if len(measured) >= 4 and len(np.unique(g)) >= 3:
        p = _curvature_p_value(g, y)
        if p < curvature_alpha:
            reasons.append(f"二次项显著（F 检验 p = {p:.3g}），dc/dN–G 关系明显非线性")
    if reasons:
        return refuse(*reasons, fit=fit)
    g0 = -fit.intercept / fit.slope
    if g0 <= 0:
        return refuse(f"外推得到的阈值 G0 = {g0:.4g} J/m² ≤ 0，无物理意义", fit=fit)

    # delta method: G0 = −a/b
    var_a, var_b = fit.intercept_stderr**2, fit.slope_stderr**2
    var_g0 = (var_a + g0**2 * var_b + 2 * g0 * fit.cov_slope_intercept) / fit.slope**2
    se = float(np.sqrt(max(var_g0, 0.0)))

    # pairs bootstrap with a fixed seed (reproducible)
    rng = np.random.default_rng(seed)
    boots: list[float] = []
    for _ in range(n_bootstrap):
        idx = rng.integers(0, len(g), len(g))
        if len(np.unique(g[idx])) < 2:
            continue
        b, a = np.polyfit(g[idx], y[idx], 1)
        if b > 0:
            boots.append(-a / b)
    flags: list[Flag] = []
    ci = None
    if len(boots) >= 0.9 * n_bootstrap:
        ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))
    else:
        flags.append(
            warning("bootstrap_unstable", "超过 10% 的 bootstrap 重抽样斜率非正，未给出置信区间")
        )

    span = float(g.max() - g.min())
    extrap = float(g.min() - g0)
    if extrap > span:
        flags.append(
            warning(
                "long_extrapolation",
                f"外推距离 {extrap:.4g} J/m² 大于拟合区间宽度 {span:.4g} J/m²，阈值不确定度大",
            )
        )
    for r in censored:
        gi = r.loading.energy_release_rate_j_m2
        predicted = fit.slope * (gi - g0)
        if gi > g0 and predicted > r.detection_limit_m_per_cycle:
            flags.append(
                warning(
                    "censored_conflict",
                    f"G = {gi:.4g} J/m² 处未检出扩展，但线性模型预测 {predicted:.3g} m/cycle "
                    "高于检测限：数据与线性外推不一致",
                )
            )
    return ThresholdFit(
        True,
        (),
        float(g0),
        se,
        ci,
        fit,
        g_range_j_m2,
        extrap,
        len(measured),
        len(censored),
        conv,
        n_bootstrap,
        seed,
        tuple(flags),
    )


def _curvature_p_value(g: np.ndarray, y: np.ndarray) -> float:
    """F-test p-value for adding a quadratic term to the linear model."""
    n = len(g)
    r1 = y - np.polyval(np.polyfit(g, y, 1), g)
    r2 = y - np.polyval(np.polyfit(g, y, 2), g)
    rss1, rss2 = float(r1 @ r1), float(r2 @ r2)
    dof = n - 3
    scale = max(float(y @ y), 1e-300)
    if dof <= 0 or rss1 <= 1e-24 * scale:
        return 1.0  # nothing to test / the line is already exact
    if rss2 <= 1e-24 * scale:
        return 0.0  # a parabola fits exactly while the line does not
    f = (rss1 - rss2) / (rss2 / dof)
    return float(stats.f.sf(f, 1, dof))


@dataclass(frozen=True)
class ThresholdBracket:
    lower_bound_j_m2: float | None  # highest G with no detectable growth (below all growth)
    upper_bound_j_m2: float | None  # lowest G with measurable growth
    cycles_at_lower_bound: float | None
    detection_limit_at_lower_bound_m_per_cycle: float | None
    statement: str
    flags: tuple[Flag, ...] = field(default=())


def threshold_bracket(rates: Sequence[CrackGrowthRate]) -> ThresholdBracket:
    """Experimental interval for G_th from growth / no-growth observations.

    Wording never claims the material cannot fatigue: only that no growth was detected
    within ΔN cycles at the stated detection limit.
    """
    if not rates:
        raise InsufficientDataError("没有裂纹扩展速率数据")
    _single_convention(rates)
    growth = [r for r in rates if r.status == "measured"]
    none_ = [r for r in rates if r.status == "below_detection_limit"]
    upper = min((r.loading.energy_release_rate_j_m2 for r in growth), default=None)
    flags: list[Flag] = []
    below = [r for r in none_ if upper is None or r.loading.energy_release_rate_j_m2 < upper]
    conflicting = [r for r in none_ if r not in below]
    if conflicting:
        flags.append(
            warning(
                "nogrowth_above_growth",
                "存在高于最低扩展 G 的未检出观测（可能为循环次数不足或测量问题），已不计入下界",
            )
        )
    lb_rate = max(below, key=lambda r: r.loading.energy_release_rate_j_m2, default=None)
    lower = lb_rate.loading.energy_release_rate_j_m2 if lb_rate else None
    if lb_rate is not None:
        dl_nm = lb_rate.detection_limit_m_per_cycle * 1e9
        text = (
            f"在 G = {lower:.4g} J/m²、{lb_rate.delta_n_cycles:.0f} 次循环内未检出裂纹扩展"
            f"（检测限 {dl_nm:.3g} nm/cycle）"
        )
        text += (
            f"；在 G = {upper:.4g} J/m² 检出扩展。疲劳阈值的实验区间为 "
            f"[{lower:.4g}, {upper:.4g}] J/m²。"
            if upper is not None
            else "；仅能给出阈值下界，不代表材料在更多循环下不会发生疲劳。"
        )
    elif upper is not None:
        text = f"所有观测均检出扩展；疲劳阈值低于 {upper:.4g} J/m²（仅上界）。"
    else:  # pragma: no cover - rates is non-empty so one branch above applies
        text = ""
    return ThresholdBracket(
        lower,
        upper,
        lb_rate.delta_n_cycles if lb_rate else None,
        lb_rate.detection_limit_m_per_cycle if lb_rate else None,
        text,
        tuple(flags),
    )
