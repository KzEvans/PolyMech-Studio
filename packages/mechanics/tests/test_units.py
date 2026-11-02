import numpy as np
import pytest

from polymech_mechanics.errors import UnitDimensionError
from polymech_mechanics.units import kind_of, parse_unit, to_si


@pytest.mark.parametrize(
    ("value", "unit", "kind", "expected"),
    [
        (1.5, "MPa", "stress", 1.5e6),
        (2.0, "GPa", "stress", 2.0e9),
        (300.0, "kPa", "stress", 3.0e5),
        (250.0, "mN", "force", 0.25),
        (1.2, "kN", "force", 1200.0),
        (20.0, "mm", "length", 0.02),
        (650.0, "μm", "length", 650e-6),
        (650.0, "µm", "length", 650e-6),
        (2.0, "min", "time", 120.0),
        (1.0, "h", "time", 3600.0),
        (25.0, "°C", "temperature", 298.15),
        (25.0, "℃", "temperature", 298.15),
        (300.0, "K", "temperature", 300.0),
        (50.0, "%", "dimensionless", 0.5),
        (1.2, "MJ/m^3", "energy_density", 1.2e6),
        (3.4, "kJ/m^2", "energy_per_area", 3400.0),
        (3.4, "kJ/m²".replace("²", "^2"), "energy_per_area", 3400.0),
        (5.0, "N/mm", "energy_per_area", 5000.0),
        (1.0, "Hz", "frequency", 1.0),
    ],
)
def test_to_si(value: float, unit: str, kind: str, expected: float) -> None:
    assert to_si([value], unit, kind)[0] == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize(
    ("unit", "kind"),
    [("N/m", "stress"), ("MPa", "energy_per_area"), ("mm", "force"), ("N", "length")],
)
def test_dimension_mismatch_is_rejected(unit: str, kind: str) -> None:
    with pytest.raises(UnitDimensionError):
        to_si([1.0], unit, kind)


def test_unknown_unit() -> None:
    with pytest.raises(UnitDimensionError):
        parse_unit("bananas")


def test_kind_of() -> None:
    assert kind_of(parse_unit("kN")) == "force"
    assert kind_of(parse_unit("MPa")) == "stress"  # same dimension as J/m^3: caller decides
    assert kind_of(parse_unit("kJ/m^2")) == "energy_per_area"


def test_arrays_preserved() -> None:
    out = to_si(np.array([1.0, 2.0, 3.0]), "MPa", "stress")
    np.testing.assert_allclose(out, [1e6, 2e6, 3e6])
