"""Apply a confirmed column mapping and convert to SI (SPEC §3.3).

Units go through Pint with a dimension check against the quantity's kind; percent strain
becomes a fraction. The raw table is never modified.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from polymech_dataio.errors import MappingError
from polymech_dataio.mapping import QUANTITIES, MappedColumn, Quantity
from polymech_dataio.reader import RawTable
from polymech_dataio.units_text import unit_for_pint
from polymech_mechanics.errors import UnitDimensionError
from polymech_mechanics.units import SI_UNITS, to_si


@dataclass(frozen=True)
class Conversion:
    quantity: Quantity
    column_index: int
    header: str
    from_unit: str
    to_unit: str


@dataclass(frozen=True)
class NormalizedData:
    source: str
    columns: dict[Quantity, NDArray[np.float64]]  # SI values, same length, NaN preserved
    conversions: tuple[Conversion, ...]

    def get(self, q: Quantity) -> NDArray[np.float64] | None:
        return self.columns.get(q)

    @property
    def n_rows(self) -> int:
        return len(next(iter(self.columns.values()))) if self.columns else 0


def normalize(table: RawTable, mapping: Sequence[MappedColumn]) -> NormalizedData:
    seen: dict[Quantity, int] = {}
    cols = {c.index: c for c in table.columns}
    out: dict[Quantity, NDArray[np.float64]] = {}
    conv: list[Conversion] = []
    for m in mapping:
        if m.column_index not in cols:
            raise MappingError(f"列序号 {m.column_index} 不存在")
        if m.quantity in seen:
            raise MappingError(
                f"{QUANTITIES[m.quantity].label}被映射到多个列（第 {seen[m.quantity] + 1} 与 "
                f"{m.column_index + 1} 列）"
            )
        seen[m.quantity] = m.column_index
        info = QUANTITIES[m.quantity]
        unit = unit_for_pint(m.unit)
        if not unit:
            raise MappingError(f"“{cols[m.column_index].header}”未指定单位")
        if m.quantity is Quantity.STRETCH and unit in {"%", "percent"}:
            raise MappingError("拉伸比不能使用百分数单位；若该列是百分数应变，请映射为工程应变")
        try:
            values = to_si(cols[m.column_index].values, unit, info.kind)
        except UnitDimensionError as e:
            raise MappingError(f"“{cols[m.column_index].header}”：{e}") from e
        out[m.quantity] = values
        conv.append(
            Conversion(
                m.quantity, m.column_index, cols[m.column_index].header, unit, SI_UNITS[info.kind]
            )
        )
    if not out:
        raise MappingError("没有任何列被映射")
    return NormalizedData(table.source, out, tuple(conv))
