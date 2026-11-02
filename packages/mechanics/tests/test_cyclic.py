"""Analytic benchmarks for cyclic tension (SPEC §4.2, §11.1). All data are synthetic.

Loading branch  σ_L = E(λ−1) + c(λ−1)(λm−λ)
Unloading branch σ_U = E(λ−1)                 (closed cycle)
⇒ W_load = E a²/2 + c a³/6, W_unload = E a²/2, W_hys = c a³/6, a = λm − 1.
"""

import numpy as np
import pytest

from polymech_mechanics.cyclic import CyclicParams, analyze_cyclic
from polymech_mechanics.errors import CycleSegmentationError

E = 1.0e6
C = 2.0e6
N = 501


def closed_cycle(lam_m: float, softening: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    up = np.linspace(1.0, lam_m, N)
    down = up[::-1][1:]
    s_up = softening * (E * (up - 1) + C * (up - 1) * (lam_m - up))
    s_down = softening * E * (down - 1)
    return np.concatenate([up, down]), np.concatenate([s_up, s_down])


def record(*cycles: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    lam = [cycles[0][0]] + [c[0][1:] for c in cycles[1:]]
    sig = [cycles[0][1]] + [c[1][1:] for c in cycles[1:]]
    return np.concatenate(lam), np.concatenate(sig)


def w_hys(lam_m: float) -> float:
    return C * (lam_m - 1) ** 3 / 6


def test_closed_cycles_match_analytic_hysteresis() -> None:
    lam, sig = record(closed_cycle(2.0), closed_cycle(2.0), closed_cycle(2.0))
    res = analyze_cyclic(lam, sig)
    assert len(res.cycles) == 3
    for c in res.cycles:
        assert c.complete and c.closed
        assert c.hysteresis_j_m3 == pytest.approx(w_hys(2.0), rel=1e-5)
        assert c.loading_work_j_m3 == pytest.approx(E / 2 + C / 6, rel=1e-5)
        assert c.residual_strain == pytest.approx(0.0, abs=1e-12)
        assert c.stretch_max == pytest.approx(2.0)
    assert res.cumulative_hysteresis_j_m3[-1] == pytest.approx(3 * w_hys(2.0), rel=1e-5)
    assert len(res.amplitude_groups) == 1
    assert res.amplitude_groups[0].cycle_indices == (1, 2, 3)
    assert not [f for f in res.flags if f.severity == "warning"]


def test_loading_modulus_per_cycle() -> None:
    lam, sig = record(closed_cycle(2.0))
    res = analyze_cyclic(lam, sig, CyclicParams(modulus_fraction=0.01))
    # dσ_L/dλ at λ=1 is E + C·a
    assert res.cycles[0].loading_modulus_pa == pytest.approx(E + C, rel=0.02)


def test_step_increasing_amplitudes() -> None:
    lam, sig = record(closed_cycle(1.5), closed_cycle(2.0), closed_cycle(2.5))
    res = analyze_cyclic(lam, sig)
    assert [round(c.stretch_max, 6) for c in res.cycles] == [1.5, 2.0, 2.5]
    for c, m in zip(res.cycles, (1.5, 2.0, 2.5), strict=True):
        assert c.hysteresis_j_m3 == pytest.approx(w_hys(m), rel=1e-5)
    assert len(res.amplitude_groups) == 3


def test_softening_retention() -> None:
    lam, sig = record(closed_cycle(2.0), closed_cycle(2.0, 0.9), closed_cycle(2.0, 0.8))
    res = analyze_cyclic(lam, sig)
    g = res.amplitude_groups[0]
    assert g.peak_stress_retention == pytest.approx((1.0, 0.9, 0.8))
    assert g.hysteresis_retention == pytest.approx((1.0, 0.9, 0.8))


def test_open_cycle_residual_strain() -> None:
    lam_m, lam_r = 2.0, 1.2
    up = np.linspace(1.0, lam_m, N)
    s_up = E * (up - 1) + C * (up - 1) * (lam_m - up)
    down = np.linspace(lam_m, lam_r, N)[1:]
    k = E * (lam_m - 1) / (lam_m - lam_r)  # continuous at the peak
    s_down = k * (down - lam_r)
    res = analyze_cyclic(np.concatenate([up, down]), np.concatenate([s_up, s_down]))
    (c,) = res.cycles
    assert not c.closed
    assert c.residual_strain == pytest.approx(lam_r - 1, abs=1e-9)
    assert c.unloading_work_j_m3 == pytest.approx(k * (lam_m - lam_r) ** 2 / 2, rel=1e-6)
    assert c.hysteresis_j_m3 == pytest.approx(c.loading_work_j_m3 - c.unloading_work_j_m3)
    assert any(f.code == "open_cycle" for f in res.flags)


def test_stress_not_returned_flag() -> None:
    up = np.linspace(1.0, 2.0, N)
    down = np.linspace(2.0, 1.5, N)[1:]
    res = analyze_cyclic(np.concatenate([up, down]), np.concatenate([E * (up - 1), E * (down - 1)]))
    (c,) = res.cycles
    assert not c.stress_returns_to_threshold
    assert c.residual_strain == pytest.approx(0.5)
    assert any(f.code == "stress_not_returned" for f in res.flags)


def test_record_ending_at_peak_is_incomplete() -> None:
    lam, sig = record(closed_cycle(2.0))
    up = np.linspace(1.0, 2.0, N)[1:]
    res = analyze_cyclic(np.concatenate([lam, up]), np.concatenate([sig, E * (up - 1)]))
    assert len(res.cycles) == 2
    assert res.cycles[0].complete and not res.cycles[1].complete
    assert res.cycles[1].hysteresis_j_m3 is None
    assert len(res.cumulative_hysteresis_j_m3) == 1
    assert any(f.code == "incomplete_cycle" for f in res.flags)


def test_noise_does_not_create_spurious_cycles() -> None:
    rng = np.random.default_rng(1)
    lam, sig = record(*(closed_cycle(2.0) for _ in range(5)))
    noisy = lam + rng.normal(0, 2e-3, lam.size)
    res = analyze_cyclic(noisy, sig)
    assert len(res.cycles) == 5
    for c in res.cycles:
        assert c.hysteresis_j_m3 == pytest.approx(w_hys(2.0), rel=0.05)


def test_flat_stretch_rejected() -> None:
    with pytest.raises(CycleSegmentationError):
        analyze_cyclic(np.ones(10), np.zeros(10))
