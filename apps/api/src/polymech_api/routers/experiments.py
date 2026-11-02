"""Experiments: create from an imported table + confirmed mapping + metadata; list; detail."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from polymech_api.deps import get_state
from polymech_api.routers.imports import MappingIn, _table
from polymech_api.serialization import lttb, to_jsonable
from polymech_api.services import corrections, deletion
from polymech_api.services.analysis import load_experiment_data
from polymech_api.state import AppState
from polymech_database.models import DataCorrection, Experiment, Material, RawDataFile, SampleBatch
from polymech_database.repository import (
    add_correction,
    create_experiment,
    create_specimen,
    get,
    get_or_create_material,
    set_mappings,
)
from polymech_dataio.mapping import QUANTITIES, MappedColumn, Quantity
from polymech_dataio.metadata import FIELD_LABELS, TestType, required_fields
from polymech_dataio.normalize import normalize
from polymech_mechanics.errors import InvalidInputError

router = APIRouter(prefix="/api", tags=["experiments"])
State = Annotated[AppState, Depends(get_state)]

GEOMETRY = ("thickness_m", "width_m", "gauge_length_m", "height_m", "notch_length_m")
EXPERIMENT_FIELDS = (
    "instrument",
    "test_date",
    "temperature_k",
    "stretch_rate_per_s",
    "cycle_frequency_hz",
    "precycles",
    "fixture",
    "operator",
    "notes",
)


class MappingConfirmed(MappingIn):
    source: str = "user"
    confidence: float | None = None


class ExperimentIn(BaseModel):
    raw_file_id: int
    table_index: int = 0
    mappings: list[MappingConfirmed]
    material_name: str = Field(min_length=1)
    batch: str = ""
    specimen_label: str = Field(min_length=1)
    test_type: TestType
    instrument: str = ""
    test_date: str = ""
    temperature_k: float | None = None
    thickness_m: float | None = Field(default=None, gt=0)
    width_m: float | None = Field(default=None, gt=0)
    gauge_length_m: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)
    notch_length_m: float | None = Field(default=None, gt=0)
    fixture: str = ""
    stretch_rate_per_s: float | None = None
    cycle_frequency_hz: float | None = None
    precycles: int | None = None
    crack_resolution_m: float | None = Field(default=None, gt=0)
    operator: str = ""
    notes: str = ""


class ExperimentPatch(BaseModel):
    thickness_m: float | None = Field(default=None, gt=0)
    width_m: float | None = Field(default=None, gt=0)
    gauge_length_m: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)
    notch_length_m: float | None = Field(default=None, gt=0)
    instrument: str | None = None
    test_date: str | None = None
    temperature_k: float | None = None
    stretch_rate_per_s: float | None = None
    cycle_frequency_hz: float | None = None
    precycles: int | None = None
    crack_resolution_m: float | None = Field(default=None, gt=0)
    fixture: str | None = None
    notes: str | None = None


def missing_metadata(exp: Experiment) -> list[dict[str, str]]:
    quantities = {Quantity(m.quantity) for rf in exp.raw_files for m in rf.mappings}
    out = []
    for name in required_fields(TestType(exp.test_type), quantities):
        if name == "material_name":
            continue
        v = (
            exp.extra.get(name)
            if name == "crack_resolution_m"
            else getattr(exp.specimen, name, None)
        )
        if v is None or not v > 0:
            out.append({"field": name, "label": FIELD_LABELS[name]})
    return out


def experiment_json(s: Session, exp: Experiment, detail: bool = False) -> dict[str, Any]:
    sp = exp.specimen
    material = s.get_one(Material, sp.material_id)
    d: dict[str, Any] = {
        "id": exp.id,
        "test_type": exp.test_type,
        "material": {"id": material.id, "name": material.name},
        "specimen": {"id": sp.id, "label": sp.label, **{g: getattr(sp, g) for g in GEOMETRY}},
        "batch": s.get_one(SampleBatch, sp.batch_id).label if sp.batch_id else "",
        "created_at": exp.created_at.isoformat(),
        "n_runs": len(exp.runs),
        "latest_run": (
            {
                "id": exp.runs[-1].id,
                "method": exp.runs[-1].method,
                "version": exp.runs[-1].version,
                "status": exp.runs[-1].status,
            }
            if exp.runs
            else None
        ),
        "missing_metadata": missing_metadata(exp),
        **{f: getattr(exp, f) for f in EXPERIMENT_FIELDS},
        "crack_resolution_m": exp.extra.get("crack_resolution_m"),
    }
    if detail:
        d["raw_files"] = [
            {
                "id": rf.id,
                "original_name": rf.original_name,
                "sha256": rf.sha256,
                "sheet": rf.sheet,
                "encoding": rf.encoding,
                "size_bytes": rf.size_bytes,
                "imported_at": rf.imported_at.isoformat(),
                "mappings": [
                    {
                        "column_index": m.column_index,
                        "header": m.header,
                        "quantity": m.quantity,
                        "unit": m.unit,
                        "source": m.source,
                        "confidence": m.confidence,
                    }
                    for m in rf.mappings
                ],
            }
            for rf in exp.raw_files
        ]
        d["runs"] = [
            {
                "id": r.id,
                "method": r.method,
                "version": r.version,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "operator": r.operator,
                "parent_run_id": r.parent_run_id,
                "result_sha256": r.result_sha256,
            }
            for r in exp.runs
        ]
    return d


@router.get("/metadata/required")
def required(test_type: TestType, quantities: str = "") -> list[dict[str, str]]:
    """Fields the analysis of `test_type` will need given these mapped quantities (comma list)."""
    qs = {Quantity(q) for q in quantities.split(",") if q}
    return [{"field": f, "label": FIELD_LABELS[f]} for f in required_fields(test_type, qs)]


@router.post("/experiments")
def create(state: State, body: ExperimentIn) -> dict[str, Any]:
    rf_src, table = _table(state, body.raw_file_id, body.table_index)
    mapped = [MappedColumn(m.column_index, m.quantity, m.unit) for m in body.mappings]
    normalize(table, mapped)  # validates units/dimensions before anything is stored
    headers = {c.index: c.header for c in table.columns}
    with state.db.session() as s:
        material = get_or_create_material(s, body.material_name)
        batch_id = None
        if body.batch:
            b = s.scalar(
                select(SampleBatch).where(
                    SampleBatch.material_id == material.id, SampleBatch.label == body.batch
                )
            )
            if b is None:
                b = SampleBatch(material_id=material.id, label=body.batch)
                s.add(b)
                s.flush()
            batch_id = b.id
        sp = create_specimen(
            s,
            material,
            body.specimen_label,
            batch_id=batch_id,
            **{g: getattr(body, g) for g in GEOMETRY},
        )
        extra = {"crack_resolution_m": body.crack_resolution_m} if body.crack_resolution_m else {}
        exp = create_experiment(
            s,
            sp,
            body.test_type.value,
            extra=extra,
            **{f: getattr(body, f) for f in EXPERIMENT_FIELDS},
        )
        rf = s.get_one(RawDataFile, rf_src.id)
        if rf.experiment_id is not None or rf.sheet not in (None, table.sheet):
            rf = RawDataFile(
                original_name=rf.original_name,
                sha256=rf.sha256,
                size_bytes=rf.size_bytes,
                archive_path=rf.archive_path,
                encoding=rf.encoding,
                delimiter=rf.delimiter,
                preamble_fields=rf.preamble_fields,
            )
            s.add(rf)
        rf.experiment_id = exp.id
        rf.sheet = table.sheet
        s.flush()
        set_mappings(
            s,
            rf,
            [
                {
                    "column_index": m.column_index,
                    "header": headers[m.column_index],
                    "quantity": m.quantity.value,
                    "unit": m.unit,
                    "source": m.source,
                    "confidence": m.confidence,
                    "confirmed_by": body.operator,
                }
                for m in body.mappings
            ],
        )
        s.refresh(exp)
        return experiment_json(s, exp, detail=True)


@router.get("/experiments")
def list_experiments(
    state: State, material_id: int | None = None, test_type: str | None = None
) -> list[dict[str, Any]]:
    with state.db.session() as s:
        q = select(Experiment).order_by(Experiment.id.desc())
        if test_type:
            q = q.where(Experiment.test_type == test_type)
        exps = list(s.scalars(q))
        if material_id is not None:
            exps = [e for e in exps if e.specimen.material_id == material_id]
        return [experiment_json(s, e) for e in exps]


@router.get("/experiments/{experiment_id}")
def detail(state: State, experiment_id: int) -> dict[str, Any]:
    with state.db.session() as s:
        return experiment_json(s, get(s, Experiment, experiment_id), detail=True)


@router.patch("/experiments/{experiment_id}")
def patch(state: State, experiment_id: int, body: ExperimentPatch) -> dict[str, Any]:
    """Metadata are analysis inputs; changing them affects only future runs (each run stores
    the geometry it used)."""
    with state.db.session() as s:
        exp = get(s, Experiment, experiment_id)
        for k, v in body.model_dump(exclude_unset=True).items():
            if k in GEOMETRY:
                setattr(exp.specimen, k, v)
            elif k == "crack_resolution_m":
                exp.extra = exp.extra | {"crack_resolution_m": v}
            else:
                setattr(exp, k, v)
        s.flush()
        return experiment_json(s, exp, detail=True)


# --------------------------------------------------------------------------- corrections
def _raw(exp: Experiment) -> RawDataFile:
    if not exp.raw_files:
        raise InvalidInputError("该实验没有关联的原始数据文件")
    return exp.raw_files[0]


@router.delete("/experiments/{experiment_id}")
def delete_experiment(state: State, experiment_id: int) -> dict[str, Any]:
    """User-confirmed deletion (UI asks first); refused while other analyses depend on it."""
    with state.db.session() as s:
        return deletion.delete_experiment(s, state.data_dir, experiment_id)


@router.get("/experiments/{experiment_id}/corrections")
def list_corrections(state: State, experiment_id: int) -> dict[str, Any]:
    with state.db.session() as s:
        raw = _raw(get(s, Experiment, experiment_id))
        return {
            "quantities": [
                {"id": m.quantity, "label": QUANTITIES[Quantity(m.quantity)].label}
                for m in raw.mappings
            ],
            "corrections": [corrections.correction_json(c) for c in raw.corrections],
        }


class CorrectionBody(BaseModel):
    correction: corrections.CorrectionIn
    operator: str = ""


def _preview(state: AppState, s: Session, exp: Experiment, body: CorrectionBody) -> dict[str, Any]:
    data, _ = load_experiment_data(state.data_dir, exp)  # active corrections already applied
    spec = body.correction.model_dump(mode="json")
    after, record = corrections.apply_one(data, spec, body.operator or state.settings()["operator"])
    q = body.correction.quantity
    before_y, after_y = data.columns[q], after.columns[q]
    x_key, x = corrections.x_for(after, q)
    ok = np.isfinite(x) & np.isfinite(before_y) & np.isfinite(after_y)
    idx = np.nonzero(ok)[0]
    if len(idx) > 1500:
        idx = idx[lttb(x[ok], before_y[ok], 1500)]
    return {
        "record": record,
        "x_key": x_key,
        "x": to_jsonable(x[idx]),
        "before": to_jsonable(before_y[idx]),
        "after": to_jsonable(after_y[idx]),
        "n_points": int(ok.sum()),
    }


@router.post("/experiments/{experiment_id}/corrections/preview")
def preview_correction(state: State, experiment_id: int, body: CorrectionBody) -> dict[str, Any]:
    """Curve before/after the proposed correction (on top of the active ones); nothing saved."""
    with state.db.session() as s:
        return _preview(state, s, get(s, Experiment, experiment_id), body)


@router.post("/experiments/{experiment_id}/corrections")
def save_correction(state: State, experiment_id: int, body: CorrectionBody) -> dict[str, Any]:
    """Save a correction. It applies to analyses run from now on; earlier versions are unchanged."""
    with state.db.session() as s:
        exp = get(s, Experiment, experiment_id)
        record = _preview(state, s, exp, body)["record"]
        c = add_correction(
            s,
            _raw(exp).id,
            record["quantity"],
            {
                "algorithm": record["algorithm"],
                "params": record["params"],
                "operator": body.operator or state.settings()["operator"],
                "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        return corrections.correction_json(c)


@router.post("/corrections/{correction_id}/deactivate")
def deactivate_correction(state: State, correction_id: int) -> dict[str, Any]:
    """Stop applying a correction to new analyses; the record stays as history."""
    with state.db.session() as s:
        c = get(s, DataCorrection, correction_id)
        c.active = False
        return corrections.correction_json(c)
