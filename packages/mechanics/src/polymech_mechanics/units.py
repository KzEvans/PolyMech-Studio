"""Shared Pint unit registry and SI conversion helpers.

Internal convention: SI base/derived units only (N, m, Pa, J/m^3, J/m^2, s, K, Hz).
Display units (MPa, kJ/m^2, °C ...) are applied at the presentation layer.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pint
from numpy.typing import ArrayLike, NDArray

from polymech_mechanics.errors import UnitDimensionError

ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
ureg.define("percent_strain = 0.01 = pct_strain")
Q_ = ureg.Quantity

# Canonical SI unit per physical quantity kind used by the engine.
SI_UNITS: dict[str, str] = {
    "force": "N",
    "length": "m",
    "stress": "Pa",
    "energy_density": "J/m**3",
    "energy_per_area": "J/m**2",
    "time": "s",
    "temperature": "K",
    "frequency": "Hz",
    "dimensionless": "dimensionless",
}

_DIMENSIONALITY: dict[str, Any] = {
    kind: ureg.Unit(u).dimensionality for kind, u in SI_UNITS.items()
}


def parse_unit(text: str) -> pint.Unit:
    """Parse a unit string such as 'MPa', 'kN', 'μm', '°C', 'kJ/m^2', '%'."""
    cleaned = text.strip().replace("^", "**").replace("µ", "u").replace("μ", "u")
    aliases = {"%": "percent", "℃": "degC", "°C": "degC", "": "dimensionless", "-": "dimensionless"}
    cleaned = aliases.get(cleaned, cleaned)
    try:
        return ureg.Unit(cleaned)
    except Exception as e:  # pint raises many types (TokenError, AttributeError, ...) for junk
        raise UnitDimensionError(f"无法识别的单位：{text!r}") from e


def kind_of(unit: pint.Unit) -> str | None:
    """Return the quantity kind ('stress', 'force', ...) matching a unit's dimension, or None."""
    dim = unit.dimensionality
    for kind, d in _DIMENSIONALITY.items():
        if d == dim:
            return kind
    return None


def to_si(values: ArrayLike, unit: str | pint.Unit, kind: str) -> NDArray[np.float64]:
    """Convert values in `unit` to the SI unit of `kind`, checking the dimension first.

    Note: J/m^3 and Pa share a dimension, as do J/m^2 and N/m; the caller's `kind` decides
    the meaning, which is why the kind is explicit rather than inferred.
    """
    if kind not in SI_UNITS:
        raise ValueError(f"unknown quantity kind {kind!r}")
    u = parse_unit(unit) if isinstance(unit, str) else unit
    if u.dimensionality != _DIMENSIONALITY[kind]:
        raise UnitDimensionError(
            f"单位 {u:~P} 的量纲 {u.dimensionality} 与 {kind}（{SI_UNITS[kind]}）不一致"
        )
    arr = np.asarray(values, dtype=float)
    return np.asarray(Q_(arr, u).to(SI_UNITS[kind]).magnitude, dtype=float)
