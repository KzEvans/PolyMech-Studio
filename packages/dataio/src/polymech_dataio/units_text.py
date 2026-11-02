"""Recognise unit strings as written by instruments."""

from __future__ import annotations

from polymech_mechanics.errors import UnitDimensionError
from polymech_mechanics.units import kind_of, parse_unit

_EXTRA_DIMENSIONLESS = {"1", "-", "—", "%", "mm/mm", "m/m", "a.u.", "无量纲", "比值", "ratio"}


def normalize_unit_text(text: str) -> str:
    t = text.strip().strip("()[]（）【】")
    t = t.replace("²", "^2").replace("³", "^3").replace("·", "*").replace("℃", "°C")
    return t


def looks_like_unit(text: str) -> bool:
    t = normalize_unit_text(text)
    if not t or len(t) > 15:
        return False
    if t.lower() in _EXTRA_DIMENSIONLESS:
        return True
    try:
        u = parse_unit(t)
    except UnitDimensionError:
        return False
    return kind_of(u) is not None


def unit_for_pint(text: str | None) -> str | None:
    """Map instrument unit text to a Pint-parsable string; None stays None."""
    if text is None:
        return None
    t = normalize_unit_text(text)
    if t.lower() in {"1", "-", "—", "mm/mm", "m/m", "a.u.", "无量纲", "比值", "ratio"}:
        return "dimensionless"
    return t
