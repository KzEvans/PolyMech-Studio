"""Literature records: validated, idempotent import of curated JSON files (SPEC §7.3).

File format `polymech-literature/1`:

    {"format": "polymech-literature/1",
     "sources":   {"<key>": {title, authors, year, doi?, kind, institution?, notes?}},
     "materials": {"<name>": {polymer_type?, structure_type?, phase_structure?, description?}},
     "records":   [{source, material, quantity, value | lower_bound | upper_bound, unit,
                    extraction_method: "reported" | "digitized", page, figure?, table?,
                    test_type?, approximate?, conditions?, reported_text, notes?}]}

Values are given in the unit printed in the source and converted to SI here. Only numbers
printed in the source may be `reported`; read-off-a-figure numbers must be `digitized` and
cite the figure. Nothing is filled in: a missing quantity is simply absent.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from polymech_database.errors import DatabaseError
from polymech_database.models import LiteratureSource, Material, MechanicalProperty
from polymech_database.repository import PROPERTY_UNITS, PropertyValue, add_literature_value
from polymech_mechanics.errors import MechanicsError
from polymech_mechanics.units import to_si

FORMAT = "polymech-literature/1"
_KIND = {"Pa": "stress", "J/m^3": "energy_density", "J/m^2": "energy_per_area", "K": "temperature"}
_KIND_DEFAULT = "dimensionless"
_TEST_TYPES = {
    "uniaxial",
    "cyclic",
    "pure_shear",
    "fatigue",
    "dma",
    "peel_t",
    "peel_trouser",
    "",
}


class LiteratureImportError(DatabaseError):
    """The file violates the literature format; nothing is imported."""


@dataclass(frozen=True)
class ImportSummary:
    sources: int
    materials_created: int
    records_added: int
    records_updated: int  # same citation, corrected content in the file
    records_skipped: int  # already present and unchanged


def _err(i: int | None, msg: str) -> LiteratureImportError:
    return LiteratureImportError(f"第 {i + 1} 条记录：{msg}" if i is not None else msg)


Identity = tuple[str, str, str, str, str, str, str, str]


def content_hash(rec: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def _identity(
    src: Mapping[str, Any],
    material: str,
    quantity: str,
    page: str,
    figure: str,
    table: str,
    text: str,
) -> Identity:
    """A record is the same citation when source, material, quantity, location and the quoted
    wording agree; its other fields (conditions, notes) may be corrected by a later import."""
    return (src["title"], src["authors"], material, quantity, page, figure, table, text)


def _si(i: int, quantity: str, v: Any, unit: str) -> float | None:
    if v is None:
        return None
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise _err(i, f"数值必须是数字，得到 {v!r}")
    kind = _KIND.get(PROPERTY_UNITS[quantity], _KIND_DEFAULT)
    try:
        return float(to_si([v], unit, kind)[0])
    except MechanicsError as e:
        raise _err(i, f"{quantity} 的单位 {unit!r} 不可用：{e}") from e


def validate(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Check the whole file before touching the database; returns records with SI values."""
    if payload.get("format") != FORMAT:
        raise _err(None, f"文件格式必须为 {FORMAT}")
    sources = payload.get("sources") or {}
    materials = payload.get("materials") or {}
    for key, src in sources.items():
        for f in ("title", "authors", "kind"):
            if not src.get(f):
                raise _err(None, f"文献 {key} 缺少 {f}")
    out = []
    seen: dict[Identity, int] = {}
    for i, rec in enumerate(payload.get("records") or []):
        if rec.get("source") not in sources:
            raise _err(i, f"未定义的文献 {rec.get('source')!r}")
        if rec.get("material") not in materials:
            raise _err(i, f"未定义的材料 {rec.get('material')!r}")
        q = rec.get("quantity")
        if q not in PROPERTY_UNITS:
            raise _err(i, f"未知物理量 {q!r}")
        method = rec.get("extraction_method")
        if method not in ("reported", "digitized"):
            raise _err(
                i, "extraction_method 必须是 reported（原文报告值）或 digitized（图形数字化）"
            )
        if not str(rec.get("page", "")).strip():
            raise _err(i, "必须给出页码")
        if method == "digitized" and not rec.get("figure"):
            raise _err(i, "图形数字化估计值必须注明图号")
        if method == "reported" and not rec.get("reported_text"):
            raise _err(i, "原文报告值必须附原文数值写法（reported_text）以便核对")
        if rec.get("test_type", "") not in _TEST_TYPES:
            raise _err(i, f"未知测试类型 {rec.get('test_type')!r}")
        unit = rec.get("unit", "")
        v = _si(i, q, rec.get("value"), unit)
        lo = _si(i, q, rec.get("lower_bound"), unit)
        hi = _si(i, q, rec.get("upper_bound"), unit)
        if v is None and lo is None and hi is None:
            raise _err(i, "数值、下界、上界至少给出一个（缺失的指标不要登记）")
        ident = _identity(
            sources[rec["source"]],
            rec["material"],
            q,
            str(rec["page"]),
            rec.get("figure", ""),
            rec.get("table", ""),
            rec.get("reported_text", ""),
        )
        if ident in seen:
            raise _err(i, f"与第 {seen[ident] + 1} 条记录引用位置与原文写法完全相同（重复登记）")
        seen[ident] = i
        out.append(rec | {"_si": (v, lo, hi), "_id": ident, "_hash": content_hash(rec)})
    return out


def _existing(s: Session) -> dict[Identity, MechanicalProperty]:
    rows = s.scalars(
        select(MechanicalProperty).where(MechanicalProperty.literature_measurement_id.is_not(None))
    )
    out = {}
    for p in rows:
        lm = p.literature_measurement
        assert lm is not None
        src = {"title": lm.source.title, "authors": lm.source.authors}
        text = str(p.conditions.get("reported_text", ""))
        out[_identity(src, lm.material.name, p.quantity, lm.page, lm.figure, lm.table, text)] = p
    return out


def import_literature(s: Session, payload: Mapping[str, Any]) -> ImportSummary:
    """Validate everything, then add new records in the caller's transaction."""
    records = validate(payload)
    srcs: dict[str, LiteratureSource] = {}
    for key, d in payload["sources"].items():
        src = s.scalar(
            select(LiteratureSource).where(
                LiteratureSource.title == d["title"], LiteratureSource.authors == d["authors"]
            )
        )
        if src is None:
            src = LiteratureSource(
                title=d["title"],
                authors=d["authors"],
                year=d.get("year"),
                doi=d.get("doi") or None,
                kind=d["kind"],
                institution=d.get("institution", ""),
                notes=d.get("notes", ""),
            )
            s.add(src)
            s.flush()
        srcs[key] = src
    mats: dict[str, Material] = {}
    created = 0
    for name, d in payload["materials"].items():
        m = s.scalar(select(Material).where(Material.name == name))
        if m is None:
            m = Material(
                name=name,
                origin="literature",
                polymer_type=d.get("polymer_type", ""),
                structure_type=d.get("structure_type", ""),
                phase_structure=d.get("phase_structure", ""),
                description=d.get("description", ""),
                tags=list(d.get("tags", [])),
            )
            s.add(m)
            s.flush()
            created += 1
        elif m.origin != "literature":
            raise _err(None, f"材料名“{name}”已被实验材料使用，请为文献材料改名以免混淆")
        mats[name] = m

    have = _existing(s)
    added = updated = skipped = 0
    for rec in records:
        v, lo, hi = rec["_si"]
        cond = dict(rec.get("conditions") or {}) | {
            "content_hash": rec["_hash"],
            "reported_text": rec.get("reported_text", ""),
            "reported_unit": rec.get("unit", ""),
            "approximate": bool(rec.get("approximate", False)),
        }
        old = have.get(rec["_id"])
        if old is not None:
            if old.conditions.get("content_hash") == rec["_hash"]:
                skipped += 1
                continue
            lm = old.literature_measurement
            assert lm is not None
            old.value, old.lower_bound, old.upper_bound = v, lo, hi
            old.unit = PROPERTY_UNITS[rec["quantity"]]
            old.conditions = cond
            lm.extraction_method = rec["extraction_method"]
            lm.test_type = rec.get("test_type", "")
            lm.notes = rec.get("notes", "")
            updated += 1
            continue
        lm = add_literature_value(
            s,
            source=srcs[rec["source"]],
            material=mats[rec["material"]],
            extraction_method=rec["extraction_method"],
            page=str(rec["page"]),
            figure=rec.get("figure", ""),
            table=rec.get("table", ""),
            test_type=rec.get("test_type", ""),
            notes=rec.get("notes", ""),
            values=[
                PropertyValue(rec["quantity"], v, lower_bound=lo, upper_bound=hi, conditions=cond)
            ],
        )
        have[rec["_id"]] = lm.properties[0]
        added += 1
    return ImportSummary(len(srcs), created, added, updated, skipped)
