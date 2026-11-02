"""Comparability rules (SPEC §7.5) on records shaped like the stored literature/analysis values."""

from typing import Any

from polymech_database.comparability import Record, compare


def rec(
    i: int,
    quantity: str,
    test_type: str,
    kind: str = "literature",
    value: float | None = 1.0,
    **cond: Any,
) -> Record:
    return Record(i, f"R{i}", quantity, value, None, None, test_type, kind, cond)  # type: ignore[arg-type]


def aspects(c) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {f.aspect: f.level for f in c.findings}


TG = {"tg_definition": "tan_delta_peak", "frequency_hz": 1.0}


def test_same_definition_and_frequency_is_direct() -> None:
    c = compare(
        rec(1, "glass_transition_temperature", "dma", **TG),
        rec(2, "glass_transition_temperature", "dma", "analysis", **TG),
    )
    assert c.verdict == "direct" and c.verdict_label == "可直接比较"


def test_tg_definitions_never_mixed() -> None:
    c = compare(
        rec(1, "glass_transition_temperature", "dma", **TG),
        rec(
            2,
            "glass_transition_temperature",
            "dma",
            tg_definition="loss_modulus_peak",
            frequency_hz=1.0,
        ),
    )
    assert c.verdict == "not_recommended" and aspects(c)["Tg 定义"] == "not_recommended"


def test_tg_frequency_missing_or_different() -> None:
    c = compare(
        rec(1, "glass_transition_temperature", "dma", **TG),
        rec(2, "glass_transition_temperature", "dma", tg_definition="tan_delta_peak"),
    )
    assert c.verdict == "insufficient"
    c = compare(
        rec(1, "glass_transition_temperature", "dma", **TG),
        rec(
            2,
            "glass_transition_temperature",
            "dma",
            tg_definition="tan_delta_peak",
            frequency_hz=10.0,
        ),
    )
    assert c.verdict == "conditional"


def test_loss_factor_needs_same_temperature() -> None:
    a = rec(1, "loss_factor", "dma", temperature_k=298.15, frequency_hz=1.0)
    assert (
        compare(a, rec(2, "loss_factor", "dma", temperature_k=298.15, frequency_hz=1.0)).verdict
        == "direct"
    )
    assert (
        compare(a, rec(2, "loss_factor", "dma", temperature_k=320.0, frequency_hz=1.0)).verdict
        == "not_recommended"
    )
    assert compare(a, rec(2, "loss_factor", "dma", frequency_hz=1.0)).verdict == "insufficient"


def test_equal_units_but_different_indicator() -> None:
    c = compare(rec(1, "elastic_modulus", "uniaxial"), rec(2, "tensile_strength", "uniaxial"))
    assert c.verdict == "not_recommended" and [f.aspect for f in c.findings] == ["指标类型"]
    c = compare(rec(1, "true_break_stress", "uniaxial"), rec(2, "break_stress", "uniaxial"))
    assert aspects(c)["应力定义"] == "not_recommended"


def test_stretch_vs_elongation_is_conditional() -> None:
    c = compare(
        rec(1, "ultimate_stretch", "uniaxial", stretch_rate_per_s=0.05),
        rec(2, "elongation_at_break", "uniaxial", stretch_rate_per_s=0.05),
    )
    assert aspects(c)["指标类型"] == "conditional"


def test_modulus_stress_basis_and_rate() -> None:
    lit = rec(
        1,
        "elastic_modulus",
        "uniaxial",
        stress_basis="true",
        stretch_rate_per_s=0.0167,
        temperature_k=298.15,
    )
    ana = rec(
        2, "elastic_modulus", "uniaxial", "analysis", stretch_rate_per_s=0.1, temperature_k=298.15
    )
    c = compare(lit, ana)
    assert aspects(c)["应力定义"] == "conditional" and aspects(c)["加载速度"] == "conditional"
    fast = rec(
        3, "elastic_modulus", "uniaxial", "analysis", stretch_rate_per_s=1.0, temperature_k=298.15
    )
    assert compare(lit, fast).verdict == "not_recommended"  # 60× rate difference


def test_toughness_methods_lambda_c_and_height() -> None:
    chen = rec(
        1,
        "fracture_toughness",
        "pure_shear",
        method="pure_shear",
        lambda_c_definition="rupture",
        height_m=0.01,
    )
    liu = rec(
        2,
        "fracture_toughness",
        "pure_shear",
        method="pure_shear",
        lambda_c_definition="crack_onset",
        height_m=0.01,
    )
    c = compare(chen, liu)
    assert c.verdict == "conditional" and aspects(c)["临界拉伸比定义"] == "conditional"
    rcurve = Record(
        3,
        "R3",
        "fracture_toughness",
        None,
        120e3,
        None,
        "pure_shear",
        "literature",
        {"method": "resistance_curve", "height_m": 0.02},
    )
    c = compare(chen, rcurve)
    assert c.verdict == "not_recommended"
    assert aspects(c)["应变能计算方法"] == "not_recommended"
    ana = rec(
        4,
        "fracture_toughness",
        "pure_shear",
        "analysis",
        lambda_c_definition="crack_onset",
        height_m=0.01,
        stretch_rate_per_s=0.5,
    )
    assert "应变能计算方法" not in aspects(
        compare(liu, ana)
    )  # analysis is pure shear by construction


def test_fatigue_threshold_methods() -> None:
    lin = rec(
        1,
        "fatigue_threshold",
        "fatigue",
        method="linear_extrapolation",
        steady_state_cycles=1000,
        detection_limit_m_per_cycle=4e-10,
    )
    lin2 = rec(
        2,
        "fatigue_threshold",
        "fatigue",
        method="linear_extrapolation",
        steady_state_cycles=500,
        detection_limit_m_per_cycle=4e-10,
    )
    arrest = rec(3, "fatigue_threshold", "fatigue", method="crack_arrest")
    c = compare(lin, lin2)
    assert c.verdict == "conditional" and aspects(c)["预循环次数"] == "conditional"
    assert compare(lin, arrest).verdict == "not_recommended"
    assert compare(lin, rec(4, "fatigue_threshold", "fatigue")).verdict == "insufficient"


def test_residual_strain_amplitude() -> None:
    a = rec(1, "residual_strain", "cyclic", stretch_max=3.0, recovery_time_s=28800)
    b = rec(2, "residual_strain", "cyclic", stretch_max=2.0, recovery_time_s=300)
    assert compare(a, b).verdict == "not_recommended"


def test_bounds_and_approximate_values_are_conditional() -> None:
    a = rec(1, "interfacial_toughness", "peel_t", method="peel_t", approximate=True)
    b = Record(
        2,
        "R2",
        "interfacial_toughness",
        None,
        1e4,
        None,
        "peel_t",
        "literature",
        {"method": "peel_t"},
    )
    c = compare(a, b)
    assert c.verdict == "conditional"
    assert sum(f.aspect == "数值形式" for f in c.findings) == 2


def test_test_type_mismatch() -> None:
    c = compare(
        rec(1, "interfacial_toughness", "peel_t"), rec(2, "interfacial_toughness", "peel_trouser")
    )
    assert aspects(c)["实验类型"] == "not_recommended"
