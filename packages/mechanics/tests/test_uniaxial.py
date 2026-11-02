"""Analytic benchmarks for uniaxial tension (SPEC §11.1). All data here are synthetic."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from polymech_mechanics.errors import (
    InsufficientDataError,
    InvalidInputError,
    MissingGeometryError,
)
from polymech_mechanics.uniaxial import (
    StressStretchCurve,
    TensileGeometry,
    UniaxialParams,
    analyze_uniaxial,
    curve_from_engineering_strain,
    curve_from_force_displacement,
    summarize_replicates,
)

E = 1.0e6  # Pa
MU = 0.5e6  # Pa


def _with_fracture(lam: np.ndarray, sig: np.ndarray, tail: int = 20) -> StressStretchCurve:
    """Append a post-fracture tail (stress ≈ 0) after the last loading point."""
    step = lam[1] - lam[0]
    lam_t = lam[-1] + step * np.arange(1, tail + 1)
    sig_t = np.full(tail, 1e-3 * sig.max())
    return StressStretchCurve(np.concatenate([lam, lam_t]), np.concatenate([sig, sig_t]))


def neo_hookean(lam: np.ndarray) -> np.ndarray:
    return MU * (lam - lam**-2)


def neo_hookean_w(lam: np.ndarray) -> np.ndarray:
    return MU * (lam**2 / 2 + 1 / lam - 1.5)


def test_linear_material_exact() -> None:
    lam = np.linspace(1.0, 2.0, 1001)
    res = analyze_uniaxial(_with_fracture(lam, E * (lam - 1)))
    assert res.break_detected
    assert res.break_index == 1000
    assert res.initial_modulus_pa == pytest.approx(E, rel=1e-9)
    assert res.modulus_fit.r_squared == pytest.approx(1.0, abs=1e-12)
    assert res.break_stretch == pytest.approx(2.0)
    assert res.elongation_at_break_percent == pytest.approx(100.0)
    assert res.max_stress_pa == pytest.approx(E)
    assert res.break_stress_pa == pytest.approx(E)
    # trapezoid is exact for a linear integrand
    assert res.work_of_fracture_j_m3 == pytest.approx(E / 2, rel=1e-12)
    np.testing.assert_allclose(res.true_stress_pa, res.stretch * res.nominal_stress_pa)
    assert not [f for f in res.flags if f.severity == "warning"]


@pytest.mark.parametrize("break_stretch", [3.0, 4.0])
def test_manual_fracture_uses_loading_branch_before_post_fracture_retraction(
    break_stretch: float,
) -> None:
    loading = np.linspace(1.0, 4.0, 301)
    curve = StressStretchCurve(
        np.concatenate([loading, loading[::-1]]),
        np.concatenate([E * (loading - 1.0), np.zeros(len(loading))]),
    )
    res = analyze_uniaxial(curve, UniaxialParams(break_stretch=break_stretch))
    assert res.break_stretch == pytest.approx(break_stretch)
    assert res.break_stress_pa == pytest.approx(E * (break_stretch - 1.0))
    assert res.work_of_fracture_j_m3 == pytest.approx(E * (break_stretch - 1.0) ** 2 / 2)
    assert res.break_index < len(loading)


def test_neo_hookean_strain_energy_matches_closed_form() -> None:
    lam = np.linspace(1.0, 4.0, 3001)
    res = analyze_uniaxial(_with_fracture(lam, neo_hookean(lam)))
    w = res.strain_energy_density_j_m3[: res.break_index + 1]
    # trapezoid error per step ~ h/3 relative near λ = 1, so compare against the curve scale
    np.testing.assert_allclose(w, neo_hookean_w(lam), rtol=1e-5, atol=1e-7 * w.max())
    assert res.work_of_fracture_j_m3 == pytest.approx(neo_hookean_w(np.array([4.0]))[0], rel=1e-6)
    assert res.work_of_fracture_numerical_error_j_m3 < 1e-5 * res.work_of_fracture_j_m3


def test_neo_hookean_initial_modulus_is_3mu_for_small_range() -> None:
    lam = np.linspace(1.0, 1.5, 5001)
    res = analyze_uniaxial(
        _with_fracture(lam, neo_hookean(lam)), UniaxialParams(modulus_stretch_range=(1.0, 1.005))
    )
    assert res.initial_modulus_pa == pytest.approx(3 * MU, rel=0.01)


def test_true_stress_is_not_integrated() -> None:
    """W must come from nominal stress; integrating true stress would overestimate it."""
    lam = np.linspace(1.0, 3.0, 2001)
    res = analyze_uniaxial(_with_fracture(lam, neo_hookean(lam)))
    w_true = np.trapezoid(res.true_stress_pa[: res.break_index + 1], lam)
    assert res.work_of_fracture_j_m3 == pytest.approx(neo_hookean_w(np.array([3.0]))[0], rel=1e-5)
    assert w_true > 1.5 * res.work_of_fracture_j_m3


def test_differential_modulus_neo_hookean() -> None:
    lam = np.linspace(1.0, 3.0, 4001)
    res = analyze_uniaxial(_with_fracture(lam, neo_hookean(lam)))
    d = res.differential_modulus_pa[1 : res.break_index]
    np.testing.assert_allclose(d, MU * (1 + 2 * lam[1:-1] ** -3), rtol=1e-4)
    assert res.hardening is not None and not res.hardening.present


def test_hardening_detected() -> None:
    lam = np.linspace(1.0, 4.0, 3001)
    sig = neo_hookean(lam) + 0.2 * MU * (lam - 1) ** 3
    res = analyze_uniaxial(_with_fracture(lam, sig))
    assert res.hardening is not None and res.hardening.present
    assert 1.05 < res.hardening.stretch_at_min_modulus < 3.0
    assert res.hardening.ratio_final_to_min > 1.1


def test_force_displacement_conversion() -> None:
    geom = TensileGeometry(gauge_length_m=0.020, width_m=0.002, thickness_m=0.001)
    disp = np.linspace(0, 0.020, 201)  # up to λ = 2
    force = E * (disp / 0.020) * geom.area_m2
    curve = curve_from_force_displacement(force, disp, geom)
    np.testing.assert_allclose(curve.stretch[-1], 2.0)
    np.testing.assert_allclose(curve.nominal_stress_pa, E * (curve.stretch - 1))


@pytest.mark.parametrize(
    "geom",
    [
        TensileGeometry(gauge_length_m=0.02, width_m=0.002),
        TensileGeometry(width_m=0.002, thickness_m=0.001),
        TensileGeometry(gauge_length_m=0.02, width_m=0.0, thickness_m=0.001),
    ],
)
def test_missing_geometry_stops_calculation(geom: TensileGeometry) -> None:
    with pytest.raises(MissingGeometryError):
        curve_from_force_displacement([0.0, 1.0, 2.0], [0.0, 0.001, 0.002], geom)


def test_engineering_strain_input() -> None:
    c = curve_from_engineering_strain([0.0, 0.5, 1.0], [0.0, 1.0, 2.0])
    np.testing.assert_allclose(c.stretch, [1.0, 1.5, 2.0])


def test_break_not_detected_uses_last_point_and_flags() -> None:
    lam = np.linspace(1.0, 2.0, 501)
    res = analyze_uniaxial(StressStretchCurve(lam, E * (lam - 1)))
    assert not res.break_detected
    assert res.break_index == 500
    assert any(f.code == "break_not_detected" for f in res.flags)


def test_user_break_override() -> None:
    lam = np.linspace(1.0, 2.0, 1001)
    res = analyze_uniaxial(_with_fracture(lam, E * (lam - 1)), UniaxialParams(break_stretch=1.5))
    assert res.break_stretch == pytest.approx(1.5)
    assert res.work_of_fracture_j_m3 == pytest.approx(E * 0.5**2 / 2, rel=1e-9)


def test_gradual_fracture_over_several_points() -> None:
    lam = np.linspace(1.0, 2.0, 1001)
    sig = E * (lam - 1)
    drop = np.array([0.7, 0.3, 0.05]) * sig[-1]
    lam2 = np.concatenate([lam, lam[-1] + 0.001 * np.arange(1, 4)])
    res = analyze_uniaxial(StressStretchCurve(lam2, np.concatenate([sig, drop])))
    assert res.break_index == 1000


def test_yield_flag() -> None:
    lam = np.linspace(1.0, 3.0, 2001)
    sig = np.where(lam < 1.5, E * (lam - 1), E * 0.5 - 0.3 * E * (lam - 1.5))
    res = analyze_uniaxial(_with_fracture(lam, sig))
    assert any(f.code == "yield_or_necking" for f in res.flags)


def test_slip_flag() -> None:
    lam = np.linspace(1.0, 2.0, 1001)
    sig = E * (lam - 1)
    sig[400:] -= 0.15 * E * 0.4  # sudden drop of ~15 % at λ = 1.4, then keeps rising
    res = analyze_uniaxial(_with_fracture(lam, sig))
    assert any(f.code == "possible_slip" for f in res.flags)


def test_zero_offset_flag() -> None:
    lam = np.linspace(1.0, 2.0, 1001)
    res = analyze_uniaxial(_with_fracture(lam, E * (lam - 1) + 0.05 * E))
    assert any(f.code == "zero_offset" for f in res.flags)


def test_too_few_points_in_fit_range() -> None:
    lam = np.linspace(1.0, 2.0, 11)  # only one point in [1, 1.05]
    with pytest.raises(InsufficientDataError):
        analyze_uniaxial(_with_fracture(lam, E * (lam - 1)))


def test_invalid_inputs() -> None:
    with pytest.raises(InvalidInputError):
        StressStretchCurve(np.array([1.0, np.nan]), np.array([0.0, 1.0]))
    with pytest.raises(InvalidInputError):
        StressStretchCurve(np.array([1.0, 2.0]), np.array([0.0]))
    with pytest.raises(InvalidInputError):
        UniaxialParams(modulus_stretch_range=(1.05, 1.0))
    with pytest.raises(InvalidInputError):
        UniaxialParams(smoothing_window=4)


def test_smoothing_reduces_noise_in_differential_modulus() -> None:
    rng = np.random.default_rng(0)
    lam = np.linspace(1.0, 2.0, 2001)
    sig = E * (lam - 1) + rng.normal(0, 1e-4 * E, lam.size)
    raw = analyze_uniaxial(_with_fracture(lam, sig))
    smooth = analyze_uniaxial(_with_fracture(lam, sig), UniaxialParams(smoothing_window=51))
    sl = slice(100, 1900)
    assert np.nanstd(smooth.differential_modulus_pa[sl]) < 0.2 * np.nanstd(
        raw.differential_modulus_pa[sl]
    )


def test_replicate_summary() -> None:
    lam = np.linspace(1.0, 2.0, 1001)
    results = [analyze_uniaxial(_with_fracture(lam, k * E * (lam - 1))) for k in (0.9, 1.0, 1.1)]
    s = summarize_replicates(results)
    assert s.initial_modulus_pa.mean == pytest.approx(E)
    assert s.initial_modulus_pa.std == pytest.approx(0.1 * E)
    assert s.work_of_fracture_j_m3.n == 3


@settings(max_examples=40, deadline=None)
@given(k=st.floats(1e-3, 1e3), lam_max=st.floats(1.2, 8.0))
def test_scaling_property(k: float, lam_max: float) -> None:
    """Scaling stress by k scales modulus, strength and W by k; stretches are unchanged."""
    lam = np.linspace(1.0, lam_max, 801)
    base = analyze_uniaxial(_with_fracture(lam, neo_hookean(lam)))
    scaled = analyze_uniaxial(_with_fracture(lam, k * neo_hookean(lam)))
    assert scaled.initial_modulus_pa == pytest.approx(k * base.initial_modulus_pa, rel=1e-9)
    assert scaled.work_of_fracture_j_m3 == pytest.approx(k * base.work_of_fracture_j_m3, rel=1e-9)
    assert scaled.break_stretch == base.break_stretch


@settings(max_examples=40, deadline=None)
@given(split=st.floats(0.1, 0.9))
def test_strain_energy_is_additive(split: float) -> None:
    lam = np.linspace(1.0, 3.0, 2001)
    res = analyze_uniaxial(_with_fracture(lam, neo_hookean(lam)))
    w = res.strain_energy_density_j_m3
    i = int(split * 2000)
    part2 = np.trapezoid(res.nominal_stress_pa[i:2001], lam[i:2001])
    assert w[i] + part2 == pytest.approx(w[2000], rel=1e-12)
