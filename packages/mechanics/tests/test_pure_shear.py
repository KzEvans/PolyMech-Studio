"""Analytic benchmarks for pure-shear fracture toughness (SPEC §4.3, §11.1). Synthetic data."""

import numpy as np
import pytest

from polymech_mechanics.errors import (
    InvalidInputError,
    MissingGeometryError,
    OutOfRangeError,
)
from polymech_mechanics.pure_shear import (
    CriticalStretch,
    PureShearGeometry,
    critical_stretch_candidate,
    critical_stretch_from_time,
    curve_from_force_displacement,
    fracture_toughness,
    summarize_toughness,
)
from polymech_mechanics.uniaxial import StressStretchCurve

E = 1.0e6
MU = 0.3e6
H0 = 0.010
GEOM = PureShearGeometry(height_m=H0, width_m=0.060, thickness_m=0.001, notch_length_m=0.015)


def unnotched_linear(lam_b: float = 3.0) -> StressStretchCurve:
    lam = np.linspace(1.0, lam_b, 2001)
    tail = lam_b + 0.001 * np.arange(1, 11)
    return StressStretchCurve(
        np.concatenate([lam, tail]), np.concatenate([E * (lam - 1), np.full(10, 1.0)])
    )


def confirmed(value: float) -> CriticalStretch:
    return CriticalStretch(value, "manual", confirmed=True)


def test_linear_material_toughness_exact() -> None:
    res = fracture_toughness(unnotched_linear(), GEOM, confirmed(2.0))
    # W(2) = E·1²/2 ; Gc = H0·W
    assert res.strain_energy_density_at_critical_j_m3 == pytest.approx(E / 2, rel=1e-9)
    assert res.toughness_j_m2 == pytest.approx(H0 * E / 2, rel=1e-9)
    assert not res.provisional
    assert not [f for f in res.flags if f.severity == "warning"]


def test_neo_hookean_like_closed_form() -> None:
    # pure-shear neo-Hookean nominal stress: σ = μ(λ − λ⁻³), W = μ(λ²/2 + λ⁻²/2 − 1)
    lam = np.linspace(1.0, 5.0, 4001)
    sig = MU * (lam - lam**-3)
    curve = StressStretchCurve(
        np.concatenate([lam, [5.001, 5.002]]), np.concatenate([sig, [0.0, 0.0]])
    )
    lc = 2.7
    res = fracture_toughness(curve, GEOM, confirmed(lc))
    w = MU * (lc**2 / 2 + lc**-2 / 2 - 1)
    assert res.toughness_j_m2 == pytest.approx(H0 * w, rel=1e-5)


def test_missing_height_stops() -> None:
    with pytest.raises(MissingGeometryError):
        fracture_toughness(unnotched_linear(), PureShearGeometry(width_m=0.06), confirmed(2.0))


def test_no_extrapolation_beyond_unnotched_break() -> None:
    with pytest.raises(OutOfRangeError):
        fracture_toughness(unnotched_linear(3.0), GEOM, confirmed(3.5))


def test_lambda_c_below_one_rejected() -> None:
    with pytest.raises(InvalidInputError):
        fracture_toughness(unnotched_linear(), GEOM, confirmed(0.9))


def test_candidate_is_provisional_and_not_summarised() -> None:
    lam = np.linspace(1.0, 2.5, 501)
    notched = StressStretchCurve(lam, E * (lam - 1) * np.exp(-((lam - 1) ** 2)))
    cand = critical_stretch_candidate(notched)
    assert not cand.confirmed and cand.method == "force_peak_candidate"
    assert cand.value == pytest.approx(1 + 1 / np.sqrt(2), abs=2e-3)  # argmax of x·e^{-x²}
    res = fracture_toughness(unnotched_linear(), GEOM, cand)
    assert res.provisional
    assert any(f.code == "lambda_c_unconfirmed" for f in res.flags)
    with pytest.raises(InvalidInputError):
        summarize_toughness([res])


def test_critical_stretch_from_synchronised_time() -> None:
    t = np.linspace(0, 100, 101)
    lam = 1 + 0.02 * t
    c = critical_stretch_from_time(t, lam, 37.5, "video_frame")
    assert c.value == pytest.approx(1.75)
    assert c.confirmed
    with pytest.raises(OutOfRangeError):
        critical_stretch_from_time(t, lam, 200.0, "photo")


def test_geometry_and_applicability_warnings() -> None:
    bad = PureShearGeometry(height_m=H0, width_m=0.02, thickness_m=0.004, notch_length_m=0.005)
    res = fracture_toughness(unnotched_linear(3.0), bad, confirmed(2.95), hysteresis_ratio=0.4)
    codes = {f.code for f in res.flags}
    assert {
        "geometry_not_pure_shear",
        "geometry_thick",
        "notch_short",
        "lambda_c_near_unnotched_break",
        "large_process_zone",
        "viscoelastic",
    } <= codes


def test_force_displacement_conversion() -> None:
    disp = np.linspace(0, 0.02, 11)  # up to λ = 3 for H0 = 10 mm
    force = np.linspace(0, 60.0, 11)
    c = curve_from_force_displacement(force, disp, GEOM)
    assert c.stretch[-1] == pytest.approx(3.0)
    assert c.nominal_stress_pa[-1] == pytest.approx(60.0 / (0.06 * 0.001))


def test_replicates() -> None:
    results = [fracture_toughness(unnotched_linear(), GEOM, confirmed(v)) for v in (1.9, 2.0, 2.1)]
    s = summarize_toughness(results)
    assert s.n == 3
    assert s.mean == pytest.approx(np.mean([H0 * E * (v - 1) ** 2 / 2 for v in (1.9, 2.0, 2.1)]))
    other = fracture_toughness(
        unnotched_linear(), GEOM, confirmed(2.0), lambda_c_definition="steady_propagation"
    )
    with pytest.raises(InvalidInputError):
        summarize_toughness([*results, other])
