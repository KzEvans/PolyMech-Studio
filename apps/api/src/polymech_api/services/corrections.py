"""User-selected data corrections (SPEC §3.5) applied on top of the archived raw data.

A correction is stored with the inputs needed to re-apply it (quantity, algorithm, parameters)
plus what it computed (offset, slope, contact index). Every analysis load re-applies the
active corrections of the raw file in creation order; the archived file is never changed and
the corrections used enter the analysis inputs (and so its input hash).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field

from polymech_database.models import DataCorrection, RawDataFile
from polymech_dataio import corrections as corr
from polymech_dataio.errors import DataIOError
from polymech_dataio.mapping import QUANTITIES, Quantity
from polymech_dataio.normalize import NormalizedData

Q = Quantity
X_CANDIDATES = (
    Q.DISPLACEMENT,
    Q.STRETCH,
    Q.ENGINEERING_STRAIN,
    Q.TEMPERATURE,
    Q.FREQUENCY,
    Q.TIME,
    Q.CYCLE,
)


class ZeroOffset(BaseModel):
    algorithm: Literal["zero_offset"]
    quantity: Quantity
    n_points: int = Field(ge=1, le=10000)


class ShiftToContact(BaseModel):
    algorithm: Literal["shift_to_contact"]
    quantity: Literal[Quantity.DISPLACEMENT]
    reference: Literal[Quantity.FORCE, Quantity.NOMINAL_STRESS] = Quantity.FORCE
    threshold: float = Field(gt=0)  # SI (N or Pa)


class LinearBaseline(BaseModel):
    algorithm: Literal["linear_baseline"]
    quantity: Quantity
    x_quantity: Quantity
    x_min: float  # SI units of x_quantity
    x_max: float


class Smooth(BaseModel):
    algorithm: Literal["savgol", "moving_average"]
    quantity: Quantity
    window: int = Field(ge=3, le=1001)
    polyorder: int = Field(default=3, ge=1, le=6)


CorrectionIn = Annotated[
    ZeroOffset | ShiftToContact | LinearBaseline | Smooth, Field(discriminator="algorithm")
]


def _col(data: NormalizedData, q: Quantity) -> NDArray[np.float64]:
    v = data.get(q)
    if v is None:
        raise DataIOError(f"数据中没有“{QUANTITIES[q].label}”列，无法修正")
    return v


def apply_one(
    data: NormalizedData, c: dict[str, Any], operator: str
) -> tuple[NormalizedData, dict[str, Any]]:
    """Apply one correction; returns the new data and the full parameter record."""
    q = Quantity(c["quantity"])
    y = _col(data, q)
    algo = c["algorithm"]
    if algo == "zero_offset":
        out, rec = corr.zero_offset(y, int(c["n_points"]), operator)
    elif algo == "shift_to_contact":
        ref = _col(data, Quantity(c.get("reference", Q.FORCE.value)))
        out, rec = corr.shift_to_contact(y, ref, float(c["threshold"]), operator)
        rec.params["reference"] = c.get("reference", Q.FORCE.value)
    elif algo == "linear_baseline":
        x = _col(data, Quantity(c["x_quantity"]))
        lo, hi = float(c["x_min"]), float(c["x_max"])
        if not lo < hi:
            raise DataIOError("基线区间下限必须小于上限")
        inside = np.nonzero((x >= lo) & (x <= hi))[0]
        if len(inside) < 2:
            raise DataIOError("基线区间内少于 2 个数据点")
        start, stop = int(inside[0]), int(inside[-1]) + 1
        out, rec = corr.linear_baseline(x, y, start, stop, operator)
        rec.params.update({"x_quantity": c["x_quantity"], "x_min": lo, "x_max": hi})
    elif algo in ("savgol", "moving_average"):
        out, rec = corr.smooth(y, algo, int(c["window"]), operator, int(c.get("polyorder", 3)))
    else:
        raise DataIOError(f"未知的修正算法：{algo}")
    cols = dict(data.columns)
    cols[q] = out
    return replace(data, columns=cols), {
        "quantity": q.value,
        "algorithm": rec.algorithm,
        "params": rec.params,
    }


def _spec(c: DataCorrection) -> dict[str, Any]:
    return {"quantity": c.quantity, "algorithm": c.algorithm, **c.params}


def active(raw: RawDataFile) -> list[DataCorrection]:
    return sorted((c for c in raw.corrections if c.active), key=lambda c: c.id)


def apply_active(data: NormalizedData, raw: RawDataFile) -> NormalizedData:
    for c in active(raw):
        data, _ = apply_one(data, _spec(c), c.operator)
    return data


def provenance(raw: RawDataFile) -> list[dict[str, Any]]:
    return [
        {
            "id": c.id,
            "quantity": c.quantity,
            "algorithm": c.algorithm,
            "params": c.params,
            "operator": c.operator,
        }
        for c in active(raw)
    ]


def x_for(data: NormalizedData, q: Quantity) -> tuple[str, NDArray[np.float64]]:
    for cand in X_CANDIDATES:
        if cand is not q and (v := data.get(cand)) is not None:
            return cand.value, v
    return "index", np.arange(data.n_rows, dtype=float)


def correction_json(c: DataCorrection) -> dict[str, Any]:
    return {
        "id": c.id,
        "quantity": c.quantity,
        "quantity_label": QUANTITIES[Quantity(c.quantity)].label,
        "algorithm": c.algorithm,
        "params": c.params,
        "operator": c.operator,
        "timestamp": c.timestamp,
        "active": c.active,
    }
