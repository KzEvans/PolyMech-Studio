"""Benchmarks for cyclic pure-shear fatigue (SPEC §4.4, §11.1). Synthetic data only."""

import numpy as np
import pytest

from polymech_mechanics.errors import InvalidInputError
from polymech_mechanics.fatigue import (
    FatigueLoading,
    crack_growth_rate,
    energy_release_rate,
    fit_threshold,
    loading_from_steady_state,
    steady_state_energy,
    threshold_bracket,
)

E = 1.0e6
H0 = 0.010
K = 1e-11  # m/cycle per J/m²
G0 = 100.0  # J/m²


def softening_record(n_cycles: int, lam_m: float = 1.5, tau: float = 5.0):
    lam, sig = [], []
    for k in range(n_cycles):
        f = 1 - 0.3 * np.exp(-k / tau)
        up = np.linspace(1.0, lam_m, 201)
        down = up[::-1][1:]
        s_up = f * E * (up - 1)
        s_down = 0.8 * f * E * (down - 1)
        if k:
            up, s_up = up[1:], s_up[1:]
        lam += [up, down]
        sig += [s_up, s_down]
    return np.concatenate(lam), np.concatenate(sig)


def loading(g: float, conv: str = "G_max") -> FatigueLoading:
    return FatigueLoading(1.0, 1.5, g, conv)  # type: ignore[arg-type]


def growth(g: float, rate: float | None, dn: float = 50_000, res: float = 20e-6):
    dc = 0.0 if rate is None else rate * dn
    return crack_growth_rate([0, dn], [1e-3, 1e-3 + dc], loading(g), res)


def test_steady_state_energy_and_g() -> None:
    lam, sig = softening_record(60)
    st = steady_state_energy(lam, sig)
    f_last = 1 - 0.3 * np.exp(-59 / 5.0)
    assert st.stabilized
    assert st.n_complete_cycles == 60
    assert st.energy_density_j_m3 == pytest.approx(f_last * E * 0.5**2 / 2, rel=1e-6)
    ld = loading_from_steady_state(st, H0)
    assert ld.energy_release_rate_j_m2 == pytest.approx(H0 * st.energy_density_j_m3)
    assert ld.convention == "G_max" and ld.stretch_min == pytest.approx(1.0)


def test_not_yet_steady_is_flagged() -> None:
    lam, sig = softening_record(4, tau=2.0)
    st = steady_state_energy(lam, sig, compare_back=3)
    assert not st.stabilized
    assert any(f.code == "not_steady" for f in st.flags)


def test_energy_release_rate_units() -> None:
    assert energy_release_rate(0.01, 1.0e5) == pytest.approx(1000.0)
    with pytest.raises(InvalidInputError):
        energy_release_rate(0.0, 1.0)


def test_detection_limit_spec_example() -> None:
    """SPEC §4.4: 20 μm resolution over 50 000 cycles → 0.4 nm/cycle."""
    r = growth(150.0, None)
    assert r.detection_limit_m_per_cycle == pytest.approx(0.4e-9)
    assert r.status == "below_detection_limit"
    assert r.dc_dn_m_per_cycle is None  # never 0
    assert r.upper_bound_m_per_cycle == pytest.approx(0.4e-9)


def test_measured_growth_rate() -> None:
    r = growth(300.0, 2e-9)
    assert r.status == "measured"
    assert r.dc_dn_m_per_cycle == pytest.approx(2e-9)
    assert r.upper_bound_m_per_cycle is None


def test_regression_slope_with_multiple_observations() -> None:
    n = np.array([0, 10_000, 20_000, 30_000, 40_000, 50_000])
    c = 1e-3 + 3e-9 * n
    r = crack_growth_rate(n, c, loading(300.0), 20e-6)
    assert r.regression_slope_m_per_cycle == pytest.approx(3e-9)
    assert r.dc_dn_m_per_cycle == pytest.approx(3e-9)


def test_crack_shrinking_rejected() -> None:
    with pytest.raises(InvalidInputError):
        crack_growth_rate([0, 1000], [1e-3, 0.9e-3], loading(100.0), 20e-6)


def _linear_rates(gs, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    return [growth(g, K * (g - G0) * (1 + noise * rng.normal())) for g in gs]


def test_threshold_exact_recovery_and_censored_excluded() -> None:
    rates = [*_linear_rates([150, 200, 250, 300, 350, 400]), growth(80, None), growth(90, None)]
    fit = fit_threshold(rates)
    assert fit.reportable
    assert fit.threshold_j_m2 == pytest.approx(G0, rel=1e-6)
    assert fit.n_measured_used == 6 and fit.n_censored == 2
    assert fit.ci95_j_m2 is not None
    assert fit.ci95_j_m2[0] <= G0 <= fit.ci95_j_m2[1]
    assert fit.extrapolation_distance_j_m2 == pytest.approx(50.0, rel=1e-6)


def test_threshold_with_noise_ci_covers_truth() -> None:
    fit = fit_threshold(_linear_rates(np.linspace(150, 500, 10), noise=0.03, seed=3))
    assert fit.reportable and fit.ci95_j_m2 is not None
    assert fit.ci95_j_m2[0] < G0 < fit.ci95_j_m2[1]
    assert fit.threshold_stderr_j_m2 is not None and fit.threshold_stderr_j_m2 > 0


def test_fit_range_restricts_points() -> None:
    fit = fit_threshold(_linear_rates([150, 200, 250, 300, 350, 400]), g_range_j_m2=(140, 260))
    assert fit.n_measured_used == 3


def test_refuses_with_too_few_points() -> None:
    fit = fit_threshold(_linear_rates([200, 300]))
    assert not fit.reportable and fit.threshold_j_m2 is None
    assert "至少需要" in fit.refusal_reasons[0]


def test_refuses_significant_curvature() -> None:
    gs = np.linspace(150, 500, 8)
    rates = [growth(g, 1e-14 * (g - G0) ** 2) for g in gs]
    fit = fit_threshold(rates)
    assert not fit.reportable
    assert any("非线性" in r for r in fit.refusal_reasons)


def test_refuses_non_positive_slope() -> None:
    rates = [growth(g, 5e-9 - 1e-12 * g) for g in (150, 200, 250, 300)]
    fit = fit_threshold(rates, min_r_squared=0.0)
    assert not fit.reportable


def test_refuses_negative_threshold() -> None:
    rates = [growth(g, K * (g + 50)) for g in (150, 200, 250, 300)]
    fit = fit_threshold(rates)
    assert not fit.reportable and "≤ 0" in fit.refusal_reasons[0]


def test_censored_conflict_flag() -> None:
    rates = [*_linear_rates([150, 200, 250, 300]), growth(280, None)]
    fit = fit_threshold(rates)
    assert fit.reportable
    assert any(f.code == "censored_conflict" for f in fit.flags)


def test_mixed_conventions_rejected() -> None:
    a = growth(200, 1e-9)
    b = crack_growth_rate([0, 50_000], [0, 1e-4], loading(300, "delta_G"), 20e-6)
    with pytest.raises(InvalidInputError):
        fit_threshold([a, b])
    with pytest.raises(InvalidInputError):
        threshold_bracket([a, b])


def test_bracket_interval() -> None:
    rates = [growth(90, None), growth(120, None), growth(150, 5e-10), growth(200, 1e-9)]
    br = threshold_bracket(rates)
    assert br.lower_bound_j_m2 == 120 and br.upper_bound_j_m2 == 150
    assert br.cycles_at_lower_bound == 50_000
    assert "未检出" in br.statement and "[120, 150]" in br.statement
    assert "永不" not in br.statement


def test_bracket_lower_bound_only() -> None:
    br = threshold_bracket([growth(90, None), growth(120, None)])
    assert br.lower_bound_j_m2 == 120 and br.upper_bound_j_m2 is None
    assert "不代表" in br.statement


def test_bracket_flags_nogrowth_above_growth() -> None:
    br = threshold_bracket([growth(150, 5e-10), growth(180, None)])
    assert br.lower_bound_j_m2 is None and br.upper_bound_j_m2 == 150
    assert any(f.code == "nogrowth_above_growth" for f in br.flags)
