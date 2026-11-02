"""File upload, table preview, mapping suggestions, mapping check (normalise + quality)."""

from __future__ import annotations

from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from polymech_api.deps import get_state
from polymech_api.serialization import lttb, to_jsonable
from polymech_api.state import AppState
from polymech_database.models import ImportProfileRecord, RawDataFile
from polymech_database.repository import add_raw_file, get, save_profile
from polymech_database.storage import read_archived
from polymech_dataio.errors import DataIOError
from polymech_dataio.mapping import (
    QUANTITIES,
    ImportProfile,
    MappedColumn,
    Quantity,
    apply_profile,
    suggest_mapping,
)
from polymech_dataio.metadata import TEST_TYPE_LABELS, TestType
from polymech_dataio.normalize import normalize
from polymech_dataio.quality import check_quality
from polymech_dataio.reader import RawTable, read_bytes

router = APIRouter(prefix="/api", tags=["imports"])
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
State = Annotated[AppState, Depends(get_state)]


def table_json(
    t: RawTable, index: int, suggestions: list[Any], profile: str | None
) -> dict[str, Any]:
    return {
        "index": index,
        "source": t.source,
        "sheet": t.sheet,
        "encoding": t.encoding,
        "delimiter": t.delimiter,
        "decimal_comma": t.decimal_comma,
        "n_rows": t.n_rows,
        "preamble": list(t.preamble),
        "preamble_fields": t.preamble_fields,
        "warnings": list(t.warnings),
        "columns": [
            {
                "index": c.index,
                "header": c.header,
                "name": c.name,
                "unit_text": c.unit_text,
                "n_missing": c.n_missing,
                "n_non_numeric": c.n_non_numeric,
                "preview": to_jsonable(c.values[:8]),
            }
            for c in t.columns
        ],
        "suggestions": [s.to_dict() for s in suggestions],
        "profile": profile,
    }


def _suggest(state: AppState, t: RawTable) -> tuple[list[Any], str | None]:
    with state.db.session() as s:
        profiles = [
            ImportProfile.from_dict({"name": p.name, "instrument": p.instrument, "rules": p.rules})
            for p in s.scalars(select(ImportProfileRecord))
        ]
    for p in profiles:
        if p.matches(t):
            return apply_profile(t, p), p.name
    return suggest_mapping(t), None


@router.get("/vocabulary")
def vocabulary() -> dict[str, Any]:
    return {
        "quantities": [
            {"id": q.value, "label": i.label, "kind": i.kind} for q, i in QUANTITIES.items()
        ],
        "test_types": [{"id": t.value, "label": label} for t, label in TEST_TYPE_LABELS.items()],
    }


@router.post("/imports")
async def upload(state: State, files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for f in files:
        name = f.filename or "upload"
        data = await f.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            errors.append({"file": name, "error": "文件超过 200 MB 上限"})
            continue
        try:
            tables = read_bytes(data, name)
        except DataIOError as e:
            errors.append({"file": name, "error": str(e)})
            continue
        with state.db.session() as s:
            rf = add_raw_file(
                s,
                state.data_dir,
                data,
                name,
                encoding=tables[0].encoding,
                delimiter=tables[0].delimiter,
                preamble_fields=tables[0].preamble_fields,
            )
            rid, sha = rf.id, rf.sha256
        tj = []
        for i, t in enumerate(tables):
            sugg, prof = _suggest(state, t)
            tj.append(table_json(t, i, sugg, prof))
        out.append({"raw_file_id": rid, "file_name": name, "sha256": sha, "tables": tj})
    return {"files": out, "errors": errors}


def _table(state: AppState, raw_file_id: int, index: int) -> tuple[RawDataFile, RawTable]:
    with state.db.session() as s:
        rf = get(s, RawDataFile, raw_file_id)
    tables = read_bytes(read_archived(state.data_dir, rf.archive_path, rf.sha256), rf.original_name)
    if not 0 <= index < len(tables):
        raise DataIOError(f"表格序号 {index} 不存在")
    return rf, tables[index]


@router.get("/imports/{raw_file_id}/tables/{index}")
def table(state: State, raw_file_id: int, index: int) -> dict[str, Any]:
    _, t = _table(state, raw_file_id, index)
    sugg, prof = _suggest(state, t)
    return table_json(t, index, sugg, prof)


class MappingIn(BaseModel):
    column_index: int
    quantity: Quantity
    unit: str


class CheckIn(BaseModel):
    test_type: TestType
    mappings: list[MappingIn]


@router.post("/imports/{raw_file_id}/tables/{index}/check")
def check(state: State, raw_file_id: int, index: int, body: CheckIn) -> dict[str, Any]:
    """Normalise with the user's mapping and run quality checks; returns a preview."""
    _, t = _table(state, raw_file_id, index)
    data = normalize(t, [MappedColumn(m.column_index, m.quantity, m.unit) for m in body.mappings])
    issues = check_quality(data, body.test_type, t)
    preview: dict[str, Any] = {}
    cols = data.columns
    x_key = next(
        (
            q
            for q in (
                Quantity.STRETCH,
                Quantity.ENGINEERING_STRAIN,
                Quantity.DISPLACEMENT,
                Quantity.TIME,
                Quantity.CYCLE,
                Quantity.TEMPERATURE,
            )
            if q in cols
        ),
        None,
    )
    if x_key is not None:
        x = cols[x_key]
        for q, v in cols.items():
            ok = np.isfinite(x) & np.isfinite(v)
            idx = np.nonzero(ok)[0][lttb(x[ok], v[ok], 1500)] if ok.any() else np.arange(0)
            preview[q.value] = {"x": to_jsonable(x[idx]), "y": to_jsonable(v[idx])}
    return {
        "n_rows": data.n_rows,
        "conversions": to_jsonable(list(data.conversions)),
        "issues": to_jsonable(issues),
        "x_quantity": x_key.value if x_key else None,
        "preview": preview,
    }


class ProfileIn(BaseModel):
    name: str
    instrument: str = ""
    raw_file_id: int
    table_index: int
    mappings: list[MappingIn]


@router.get("/profiles")
def profiles(state: State) -> list[dict[str, Any]]:
    with state.db.session() as s:
        return [
            {"id": p.id, "name": p.name, "instrument": p.instrument, "rules": p.rules}
            for p in s.scalars(select(ImportProfileRecord).order_by(ImportProfileRecord.name))
        ]


@router.post("/profiles")
def create_profile(state: State, body: ProfileIn) -> dict[str, Any]:
    _, t = _table(state, body.raw_file_id, body.table_index)
    by_index = {m.column_index: m for m in body.mappings}
    rules = [
        {
            "header": c.header,
            "quantity": by_index[c.index].quantity.value if c.index in by_index else None,
            "unit": by_index[c.index].unit if c.index in by_index else None,
        }
        for c in t.columns
    ]
    with state.db.session() as s:
        p = save_profile(s, body.name, body.instrument, rules)
        return {"id": p.id, "name": p.name, "instrument": p.instrument, "rules": p.rules}
