from typing import Any

import pytest

from polymech_dataio.mapping import (
    ImportProfile,
    MappedColumn,
    Quantity,
    apply_profile,
    profile_from_mapping,
    suggest_mapping,
)
from polymech_dataio.reader import read_bytes, read_file
from polymech_dataio.units_text import unit_for_pint

from .conftest import FIXTURES


def _tables(manifest):
    for entry in manifest:
        for t in read_file(FIXTURES / entry["file"]):
            if entry["sheet"] in (None, t.sheet):
                yield entry, t


def test_rules_never_auto_accept_a_wrong_mapping(manifest: list[dict[str, Any]]) -> None:
    """Safety property: whatever is NOT flagged for confirmation must be correct."""
    for entry, t in _tables(manifest):
        for s in suggest_mapping(t):
            truth = entry["columns"][s.header]
            if not s.needs_confirmation:
                assert s.quantity is not None
                assert s.quantity.value == truth["quantity"], (entry["file"], s.header)
                assert unit_for_pint(s.unit) == unit_for_pint(truth["unit"]), (
                    entry["file"],
                    s.header,
                )


def test_rule_accuracy_on_fixture_set(manifest: list[dict[str, Any]]) -> None:
    total = correct = 0
    for entry, t in _tables(manifest):
        for s in suggest_mapping(t):
            total += 1
            correct += (
                s.quantity is not None
                and s.quantity.value == entry["columns"][s.header]["quantity"]
            )
    assert correct / total >= 0.9


def test_strain_header_with_stretch_values_needs_confirmation() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_ambiguous_strain.csv")
    s = suggest_mapping(t)[0]
    assert s.needs_confirmation
    assert any("拉伸比" in a for a in s.ambiguities)


def test_generic_stress_requires_confirmation() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_strain_percent.txt")
    stress = suggest_mapping(t)[1]
    assert stress.quantity is Quantity.NOMINAL_STRESS
    assert stress.needs_confirmation


def test_missing_unit_is_never_assumed() -> None:
    (t,) = read_bytes(b"Force,Displacement\n0,0\n1,1\n2,2\n3,3\n", "x.csv")
    for s in suggest_mapping(t):
        assert s.unit is None
        assert s.needs_confirmation


def test_wrong_dimension_unit_lowers_confidence() -> None:
    (t,) = read_bytes(b"Stress (N/m),Strain\n0,0\n1,0.1\n2,0.2\n3,0.3\n", "x.csv")
    s = suggest_mapping(t)[0]
    assert s.needs_confirmation
    assert any("量纲" in a for a in s.ambiguities)


def test_duplicate_quantities_flagged() -> None:
    (t,) = read_bytes(b"Force (N),Load (N)\n0,0\n1,1\n2,2\n3,3\n", "x.csv")
    out = suggest_mapping(t)
    assert all(s.needs_confirmation for s in out)


def test_profile_roundtrip_and_application() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_ambiguous_strain.csv")
    mapping = [
        MappedColumn(0, Quantity.STRETCH, "dimensionless"),
        MappedColumn(1, Quantity.NOMINAL_STRESS, "MPa"),
    ]
    prof = profile_from_mapping("SYNTH UTM", "Synthetic", t, mapping)
    again = ImportProfile.from_dict(prof.to_dict())
    assert again == prof
    assert again.matches(t)
    out = apply_profile(t, again)
    assert [s.quantity for s in out] == [Quantity.STRETCH, Quantity.NOMINAL_STRESS]
    assert not any(s.needs_confirmation for s in out)
    assert out[0].source == "profile:SYNTH UTM"


@pytest.mark.parametrize(
    ("header", "quantity"),
    [
        ("tan δ", Quantity.LOSS_FACTOR),
        ("E'", Quantity.STORAGE_MODULUS),
        ("E''", Quantity.LOSS_MODULUS),
        ("Peel force (N)", Quantity.PEEL_FORCE),
        ("裂纹扩展 (μm)", Quantity.CRACK_EXTENSION),
        ("Energy release rate (J/m^2)", Quantity.ENERGY_RELEASE_RATE),
        ("真实应力 (MPa)", Quantity.TRUE_STRESS),
        ("Frequency (Hz)", Quantity.FREQUENCY),
    ],
)
def test_named_quantities(header: str, quantity: Quantity) -> None:
    body = "\n".join(f"{i},{i}" for i in range(1, 6))
    (t,) = read_bytes(f"{header},Time (s)\n{body}\n".encode(), "x.csv")
    assert suggest_mapping(t)[0].quantity is quantity


@pytest.mark.parametrize("suffix", ["", "4"])
def test_chinese_instrument_headers_with_and_without_specimen_number(suffix: str) -> None:
    """Regression: “力4” was unmatched and “应力” was taken for force (both end in 力)."""
    names = ["时间", "力", "位移", "应力", "应变"]
    rows = [",".join(n + suffix for n in names)] + [
        f"{0.05 * i},{0.001 * i},{0.01 * i},{0.0012 * i},{0.0005 * i}" for i in range(20)
    ]
    (t,) = read_bytes("\n".join(rows).encode(), "x.csv")
    assert [s.quantity for s in suggest_mapping(t)] == [
        Quantity.TIME,
        Quantity.FORCE,
        Quantity.DISPLACEMENT,
        Quantity.NOMINAL_STRESS,
        Quantity.ENGINEERING_STRAIN,
    ]
