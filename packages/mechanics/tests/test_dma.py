"""Benchmarks for DMA (SPEC §4.5, §11.1 "构造已知损耗因子的DMA数据"). All data are synthetic.

E′(T): sigmoidal glass → rubber step in log10 E′ (1 GPa → 1 MPa around T_m = 265 K), so that
E″ = tan δ · E′ has an interior peak below the tan δ peak, as in real elastomers.
tan δ(T): baseline + Gaussian peak at T_p (known), E″ = tan δ · E′.
"""

import numpy as np
import pytest

from polymech_mechanics.dma import DMAParams, analyze_dma
from polymech_mechanics.errors import InvalidInputError

T = np.arange(200.0, 380.0 + 1e-9, 0.5)


def storage(t: np.ndarray, tm: float = 265.0) -> np.ndarray:
    return 10 ** (6 + 3 / (1 + np.exp((t - tm) / 5.0)))


def tan_delta(t: np.ndarray, tp: float = 260.2, amp: float = 1.0) -> np.ndarray:
    return 0.05 + amp * np.exp(-(((t - tp) / 8.0) ** 2))


def tg(res, definition: str, series: int = 0) -> float:  # type: ignore[no-untyped-def]
    return next(c.temperature_k for c in res.series[series].tg if c.definition == definition)


def codes(res) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.code for f in res.flags}


def test_loss_factor_computed_from_moduli_matches_known() -> None:
    e1, tan = storage(T), tan_delta(T)
    res = analyze_dma(e1, temperature_k=T, loss_modulus_pa=tan * e1)
    assert res.loss_factor_source == "loss / storage"
    np.testing.assert_allclose(res.loss_factor, tan, rtol=1e-12)
    assert res.mode == "temperature_sweep"
    assert res.spikes == ()


def test_loss_modulus_derived_from_tan_delta() -> None:
    e1, tan = storage(T), tan_delta(T)
    res = analyze_dma(e1, temperature_k=T, loss_factor=tan)
    assert res.loss_modulus_source == "tan_delta × storage"
    np.testing.assert_allclose(res.loss_modulus_pa, tan * e1, rtol=1e-12)


def test_tan_delta_peak_recovered_between_grid_points() -> None:
    e1, tan = storage(T), tan_delta(T, tp=260.2)
    res = analyze_dma(e1, temperature_k=T, loss_modulus_pa=tan * e1, loss_factor=tan)
    assert tg(res, "tan_delta_peak") == pytest.approx(260.2, abs=0.05)
    c = next(c for c in res.series[0].tg if c.definition == "tan_delta_peak")
    assert not c.ambiguous and c.value == pytest.approx(1.05, abs=1e-3)
    assert res.consistency_deviation == pytest.approx(0.0, abs=1e-12)


def test_loss_modulus_peak_matches_dense_truth() -> None:
    e1, tan = storage(T), tan_delta(T)
    dense = np.linspace(200, 380, 360001)
    truth = dense[np.argmax(tan_delta(dense) * storage(dense))]
    res = analyze_dma(e1, temperature_k=T, loss_modulus_pa=tan * e1)
    assert tg(res, "loss_modulus_peak") == pytest.approx(truth, abs=0.1)
    # E″ peaks below the tan δ peak for a falling E′ (definitions differ → kept apart)
    assert tg(res, "loss_modulus_peak") < tg(res, "tan_delta_peak")


def test_storage_onset_is_tangent_intersection() -> None:
    log_e = np.piecewise(
        T, [T < 240, (T >= 240) & (T < 270), T >= 270], [9, lambda t: 9 - 0.1 * (t - 240), 6]
    )
    res = analyze_dma(10**log_e, temperature_k=T)
    assert tg(res, "storage_modulus_onset") == pytest.approx(240.0, abs=1e-6)
    assert "no_loss_data" in codes(res)
    assert {c.definition for c in res.series[0].tg} == {"storage_modulus_onset"}


def test_no_transition_no_onset() -> None:
    res = analyze_dma(np.full(len(T), 1e6) * (1 - 1e-4 * (T - 200)), temperature_k=T)
    assert res.series[0].tg == ()
    assert "storage_modulus_onset_none" in codes(res)


def test_inconsistent_tan_delta_flagged() -> None:
    e1, tan = storage(T), tan_delta(T)
    res = analyze_dma(e1, temperature_k=T, loss_modulus_pa=tan * e1, loss_factor=2 * tan)
    assert res.consistency_deviation == pytest.approx(1.0)
    assert "loss_factor_inconsistent" in codes(res)


def test_two_comparable_peaks_are_ambiguous_until_window_given() -> None:
    e1 = storage(T)
    tan = 0.05 + np.exp(-(((T - 240) / 6) ** 2)) + 0.9 * np.exp(-(((T - 320) / 6) ** 2))
    res = analyze_dma(e1, temperature_k=T, loss_factor=tan)
    c = next(c for c in res.series[0].tg if c.definition == "tan_delta_peak")
    assert c.ambiguous and c.other_peaks_k == (pytest.approx(320, abs=0.1),)
    assert "tan_delta_peak_multiple" in codes(res)
    res2 = analyze_dma(
        e1, temperature_k=T, loss_factor=tan, params=DMAParams(tg_window_k=(290, 350))
    )
    c2 = next(c for c in res2.series[0].tg if c.definition == "tan_delta_peak")
    assert not c2.ambiguous and c2.temperature_k == pytest.approx(320, abs=0.1)


def test_minor_shoulder_is_not_ambiguous() -> None:
    tan = tan_delta(T) + 0.2 * np.exp(-(((T - 330) / 6) ** 2))
    res = analyze_dma(storage(T), temperature_k=T, loss_factor=tan)
    c = next(c for c in res.series[0].tg if c.definition == "tan_delta_peak")
    assert not c.ambiguous and c.other_peaks_k == (pytest.approx(330, abs=0.2),)


def test_peak_outside_range_is_not_extrapolated() -> None:
    tan = tan_delta(T, tp=420.0)
    res = analyze_dma(storage(T), temperature_k=T, loss_factor=tan)
    assert all(c.definition != "tan_delta_peak" for c in res.series[0].tg)
    assert "tan_delta_peak_none" in codes(res)


def test_spikes_detected_flagged_and_excluded() -> None:
    rng = np.random.default_rng(1)
    e1 = storage(T) * (1 + 0.002 * rng.standard_normal(len(T)))
    tan = tan_delta(T) + 0.002 * rng.standard_normal(len(T))
    clean = analyze_dma(e1, temperature_k=T, loss_factor=tan)
    assert clean.spikes == ()  # no false alarms on smooth noisy data
    e1[50] *= 3.0
    i_peak = int(np.argmin(np.abs(T - 300)))
    tan[i_peak] += 2.0  # a spike higher than the real peak
    res = analyze_dma(e1, temperature_k=T, loss_factor=tan)
    assert {(s.index, s.quantity) for s in res.spikes} == {(50, "storage"), (i_peak, "tan_delta")}
    assert "dma_spikes" in codes(res)
    assert tg(res, "tan_delta_peak") == pytest.approx(260.2, abs=0.5)


def test_multi_frequency_series_kept_apart() -> None:
    t2 = np.concatenate([T, T])
    f = np.concatenate([np.full(len(T), 1.0), np.full(len(T), 10.0)])
    tan = np.concatenate([tan_delta(T, tp=260.0), tan_delta(T, tp=266.0)])
    e1 = np.concatenate([storage(T), storage(T, tm=271)])
    perm = np.random.default_rng(0).permutation(len(t2))  # interleaved rows
    res = analyze_dma(e1[perm], temperature_k=t2[perm], loss_factor=tan[perm], frequency_hz=f[perm])
    assert [s.frequency_hz for s in res.series] == [1.0, 10.0]
    assert tg(res, "tan_delta_peak", 0) == pytest.approx(260.0, abs=0.05)
    assert tg(res, "tan_delta_peak", 1) == pytest.approx(266.0, abs=0.05)
    assert "multi_frequency" in codes(res)
    # order: series 0 by temperature, then series 1
    ordered_f = f[perm][res.order]
    assert np.all(ordered_f[: len(T)] == 1.0) and np.all(np.diff(t2[perm][res.order][: len(T)]) > 0)


def test_frequency_sweep_mode_reports_no_tg() -> None:
    f = np.logspace(-1, 2, 40)
    e1 = 1e6 * (1 + 0.3 * np.log10(f / 0.1))
    res = analyze_dma(
        e1, temperature_k=np.full(40, 298.15), loss_factor=np.full(40, 0.1), frequency_hz=f
    )
    assert res.mode == "frequency_sweep"
    assert res.series[0].tg == () and res.series[0].x_min == pytest.approx(0.1)
    assert "frequency_sweep" in codes(res)


def test_reference_values_interpolated_not_extrapolated() -> None:
    e1, tan = storage(T), tan_delta(T)
    res = analyze_dma(
        e1,
        temperature_k=T,
        loss_factor=tan,
        params=DMAParams(reference_temperatures_k=(298.15, 500.0)),
    )
    (ref,) = res.series[0].reference_values
    assert ref.temperature_k == 298.15
    assert ref.loss_factor == pytest.approx(float(np.interp(298.15, T, tan)))
    assert ref.storage_modulus_pa == pytest.approx(float(np.interp(298.15, T, e1)))


def test_unit_scale_does_not_change_tg() -> None:
    e1, tan = storage(T), tan_delta(T)
    a = analyze_dma(e1, temperature_k=T, loss_modulus_pa=tan * e1)
    b = analyze_dma(e1 * 1e-6, temperature_k=T, loss_modulus_pa=tan * e1 * 1e-6)
    for d in ("tan_delta_peak", "loss_modulus_peak", "storage_modulus_onset"):
        assert tg(a, d) == pytest.approx(tg(b, d), abs=1e-9)


def test_mixed_heating_cooling_and_nonpositive_flagged() -> None:
    t = np.concatenate([T, T[::-1]])
    e1 = np.concatenate([storage(T), storage(T)[::-1]])
    e1[3] = -1.0
    res = analyze_dma(e1, temperature_k=t, loss_factor=np.concatenate([tan_delta(T)] * 2))
    assert {"temperature_not_monotonic", "nonpositive_storage"} <= codes(res)


def test_requires_temperature_or_frequency_sweep() -> None:
    with pytest.raises(InvalidInputError):
        analyze_dma(storage(T))
    with pytest.raises(InvalidInputError):
        DMAParams(spike_window=4)
    with pytest.raises(InvalidInputError):
        DMAParams(tg_window_k=(300, 250))
