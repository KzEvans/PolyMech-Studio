"""Materials database, properties and dashboard summary."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from polymech_api.deps import get_state
from polymech_api.services.compare import comparison_json
from polymech_api.state import AppState
from polymech_database.literature import import_literature
from polymech_database.models import (
    AnalysisRun,
    Experiment,
    LiteratureMeasurement,
    LiteratureSource,
    Material,
    MechanicalProperty,
    OriginJob,
)
from polymech_database.repository import get
from polymech_mechanics.errors import InvalidInputError

router = APIRouter(prefix="/api", tags=["materials"])
State = Annotated[AppState, Depends(get_state)]


def prop_json(p: MechanicalProperty) -> dict[str, Any]:
    src: dict[str, Any]
    if p.analysis_run_id is not None:
        run: AnalysisRun | None = p.analysis_run
        src = {"kind": "analysis", "run_id": p.analysis_run_id, "entry": f"run:{p.analysis_run_id}"}
        if run is not None:  # enough to tell versions apart in the materials database
            src |= {
                "experiment_id": run.experiment_id,
                "specimen": run.experiment.specimen.label,
                "test_type": run.experiment.test_type,
                "method": run.method,
                "version": run.version,
                "status": run.status,
                "created_at": run.created_at.isoformat(),
                "params": run.params,
            }
    else:
        lm: LiteratureMeasurement | None = p.literature_measurement
        assert lm is not None
        src = {
            "kind": "literature",
            "extraction_method": lm.extraction_method,
            "page": lm.page,
            "figure": lm.figure,
            "table": lm.table,
            "title": lm.source.title,
            "authors": lm.source.authors,
            "year": lm.source.year,
            "doi": lm.source.doi,
            "kind_of_source": lm.source.kind,
            "test_type": lm.test_type,
            "notes": lm.notes,
            "entry": f"lit:{lm.id}",
        }
    return {
        "id": p.id,
        "material_id": p.material_id,
        "quantity": p.quantity,
        "value": p.value,
        "unit": p.unit,
        "uncertainty": p.uncertainty,
        "uncertainty_kind": p.uncertainty_kind,
        "lower_bound": p.lower_bound,
        "upper_bound": p.upper_bound,
        "n_replicates": p.n_replicates,
        "conditions": p.conditions,
        "source": src,
    }


@router.get("/materials")
def materials(
    state: State, origin: str | None = None, q: str | None = None
) -> list[dict[str, Any]]:
    with state.db.session() as s:
        stmt = select(Material).order_by(Material.name)
        if origin:
            stmt = stmt.where(Material.origin == origin)
        if q:
            stmt = stmt.where(Material.name.contains(q))
        out = []
        for m in s.scalars(stmt):
            n_props = (
                s.scalar(select(func.count()).where(MechanicalProperty.material_id == m.id)) or 0
            )
            out.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "origin": m.origin,
                    "polymer_type": m.polymer_type,
                    "structure_type": m.structure_type,
                    "phase_structure": m.phase_structure,
                    "block_count": m.block_count,
                    "tags": m.tags,
                    "n_properties": n_props,
                    "components": [
                        {"name": c.name, "role": c.role, "block_label": c.block_label}
                        for c in m.components
                    ],
                }
            )
        return out


@router.get("/materials/{material_id}")
def material(state: State, material_id: int) -> dict[str, Any]:
    with state.db.session() as s:
        m = get(s, Material, material_id)
        props = s.scalars(select(MechanicalProperty).where(MechanicalProperty.material_id == m.id))
        return {
            "id": m.id,
            "name": m.name,
            "origin": m.origin,
            "polymer_type": m.polymer_type,
            "structure_type": m.structure_type,
            "phase_structure": m.phase_structure,
            "block_count": m.block_count,
            "description": m.description,
            "tags": m.tags,
            "components": [
                {
                    "name": c.name,
                    "role": c.role,
                    "block_label": c.block_label,
                    "molar_mass_kg_mol": c.molar_mass_kg_mol,
                    "fraction": c.fraction,
                    "fraction_basis": c.fraction_basis,
                }
                for c in m.components
            ],
            "properties": [prop_json(p) for p in props],
        }


@router.get("/properties")
def properties(
    state: State, quantity: str | None = None, material_id: int | None = None
) -> list[dict[str, Any]]:
    with state.db.session() as s:
        stmt = select(MechanicalProperty)
        if quantity:
            stmt = stmt.where(MechanicalProperty.quantity == quantity)
        if material_id is not None:
            stmt = stmt.where(MechanicalProperty.material_id == material_id)
        return [prop_json(p) for p in s.scalars(stmt)]


@router.get("/properties/quantities")
def property_quantities(state: State) -> list[dict[str, Any]]:
    """Quantities present in the database (axis choices for the comparison chart)."""
    with state.db.session() as s:
        rows = s.execute(
            select(MechanicalProperty.quantity, MechanicalProperty.unit, func.count())
            .group_by(MechanicalProperty.quantity, MechanicalProperty.unit)
            .order_by(MechanicalProperty.quantity)
        ).all()
        return [{"quantity": q, "unit": u, "n": n} for q, u, n in rows]


def _entry_label(p: MechanicalProperty, material_name: str) -> str:
    if p.analysis_run is not None:
        r = p.analysis_run
        return f"{material_name} v{r.version}"
    lm = p.literature_measurement
    return (
        f"{lm.source.authors.split(',')[0].split('，')[0]} {lm.source.year or ''}".strip()
        if lm
        else ""
    )


@router.get("/properties/pairs")
def property_pairs(
    state: State,
    x: str,
    y: str,
    pairing: Literal["entry", "material"] = "entry",
    latest_only: bool = True,
) -> dict[str, Any]:
    """Points for a property–property comparison chart (Ashby-style).

    entry: x and y from the same analysis version or literature record (same specimen and
    conditions). material: every x of a material with every y of that material — values from
    different tests; the response says so. Provisional analyses are excluded; bounds-only
    values cannot be placed and are listed. Values are SI; the client converts for display."""
    if x == y:
        raise InvalidInputError("横轴和纵轴需要两项不同的性能")
    with state.db.session() as s:
        props = s.scalars(
            select(MechanicalProperty).where(MechanicalProperty.quantity.in_([x, y]))
        ).all()
        runs = [p.analysis_run for p in props if p.analysis_run is not None]
        newest: dict[tuple[int, str], int] = {}
        for r in runs:
            k = (r.experiment_id, r.method)
            newest[k] = max(newest.get(k, 0), r.version)
        keep = []
        for p in props:
            pr = p.analysis_run
            if pr is not None and (
                pr.status != "ok"
                or (latest_only and pr.version != newest[(pr.experiment_id, pr.method)])
            ):
                continue
            keep.append(p)
        groups: dict[tuple[int, str], list[MechanicalProperty]] = {}
        names: dict[int, tuple[str, str]] = {}
        for p in keep:
            key = p.material_id if pairing == "material" else None
            entry = prop_json(p)["source"]["entry"]
            groups.setdefault((p.material_id, "" if key is not None else entry), []).append(p)
            if p.material_id not in names:
                m = get(s, Material, p.material_id)
                names[p.material_id] = (m.name, m.origin)
        points: list[dict[str, Any]] = []
        omitted: list[str] = []
        for (mid, _), ps in groups.items():
            xs = [p for p in ps if p.quantity == x]
            ys = [p for p in ps if p.quantity == y]
            for p in xs + ys:
                if p.value is None:
                    omitted.append(
                        f"{names[mid][0]}（{_entry_label(p, names[mid][0])}）只有上/下界"
                    )
            for px in xs:
                for py in ys:
                    if px.value is None or py.value is None:
                        continue
                    same = px.analysis_run_id == py.analysis_run_id and (
                        px.literature_measurement_id == py.literature_measurement_id
                    )
                    lx, ly = _entry_label(px, names[mid][0]), _entry_label(py, names[mid][0])
                    points.append(
                        {
                            "material_id": mid,
                            "material": names[mid][0],
                            "origin": names[mid][1],
                            "label": lx if same or lx == ly else f"{lx} × {ly}",
                            "x": px.value,
                            "y": py.value,
                            "x_uncertainty": px.uncertainty,
                            "y_uncertainty": py.uncertainty,
                            "x_property_id": px.id,
                            "y_property_id": py.id,
                            "same_entry": same,
                        }
                    )
        units = {p.quantity: p.unit for p in props}
        return {
            "x": x,
            "y": y,
            "x_unit": units.get(x, ""),
            "y_unit": units.get(y, ""),
            "pairing": pairing,
            "points": points,
            "omitted": sorted(set(omitted)),
            "caution": "数值来自不同来源与测试条件，直接比较前请使用“可比性检查”"
            + ("；按材料配对时，横纵坐标可能来自不同的实验" if pairing == "material" else ""),
        }


@router.get("/dashboard")
def dashboard(state: State) -> dict[str, Any]:
    with state.db.session() as s:
        recent_runs = s.scalars(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(8)).all()
        recent_exps = s.scalars(select(Experiment).order_by(Experiment.id.desc()).limit(8)).all()
        jobs = s.scalars(select(OriginJob).order_by(OriginJob.id.desc()).limit(5)).all()
        return {
            "counts": {
                "materials": s.scalar(select(func.count()).select_from(Material)) or 0,
                "literature_materials": s.scalar(
                    select(func.count())
                    .select_from(Material)
                    .where(Material.origin == "literature")
                )
                or 0,
                "experiments": s.scalar(select(func.count()).select_from(Experiment)) or 0,
                "analyses": s.scalar(select(func.count()).select_from(AnalysisRun)) or 0,
            },
            "recent_experiments": [
                {
                    "id": e.id,
                    "test_type": e.test_type,
                    "specimen": e.specimen.label,
                    "created_at": e.created_at.isoformat(),
                    "n_runs": len(e.runs),
                }
                for e in recent_exps
            ],
            "recent_analyses": [
                {
                    "id": r.id,
                    "experiment_id": r.experiment_id,
                    "method": r.method,
                    "version": r.version,
                    "status": r.status,
                    "created_at": r.created_at.isoformat(),
                }
                for r in recent_runs
            ],
            "provisional_analyses": s.scalar(
                select(func.count())
                .select_from(AnalysisRun)
                .where(AnalysisRun.status == "provisional")
            )
            or 0,
            "origin_jobs": [
                {
                    "id": j.id,
                    "status": j.status,
                    "template_id": j.template_id,
                    "requested_at": j.requested_at.isoformat(),
                    "opju_path": j.opju_path,
                }
                for j in jobs
            ],
        }


@router.post("/literature/import")
def literature_import(state: State, payload: dict[str, Any]) -> dict[str, Any]:
    """Import a curated `polymech-literature/1` file. The whole file is validated first;
    re-importing the same records is a no-op. No network access: only what the user supplies."""
    with state.db.session() as s:
        out = import_literature(s, payload)
    return {
        "sources": out.sources,
        "materials_created": out.materials_created,
        "records_added": out.records_added,
        "records_updated": out.records_updated,
        "records_skipped": out.records_skipped,
    }


@router.get("/literature/sources")
def literature_sources(state: State) -> list[dict[str, Any]]:
    with state.db.session() as s:
        out = []
        for src in s.scalars(select(LiteratureSource).order_by(LiteratureSource.year)):
            n = s.scalar(
                select(func.count())
                .select_from(LiteratureMeasurement)
                .where(LiteratureMeasurement.source_id == src.id)
            )
            out.append(
                {
                    "id": src.id,
                    "title": src.title,
                    "authors": src.authors,
                    "year": src.year,
                    "doi": src.doi,
                    "kind": src.kind,
                    "institution": src.institution,
                    "n_records": n or 0,
                }
            )
        return out


class ComparabilityIn(BaseModel):
    reference_id: int
    property_ids: list[int] = Field(min_length=1)


@router.post("/comparability")
def comparability(state: State, body: ComparabilityIn) -> dict[str, Any]:
    """Rule-based comparability of each property against the reference (SPEC §7.5)."""
    with state.db.session() as s:
        ref = get(s, MechanicalProperty, body.reference_id)
        others = [
            get(s, MechanicalProperty, i) for i in body.property_ids if i != body.reference_id
        ]
        return comparison_json(s, ref, others)
