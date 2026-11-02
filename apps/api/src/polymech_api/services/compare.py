"""Stored properties → comparability records; deterministic literature candidates for a run."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from polymech_api.serialization import to_jsonable
from polymech_database.comparability import METHOD_TEST_TYPE, RANK, Record, compare
from polymech_database.models import AnalysisRun, Material, MechanicalProperty

# quantities that may be benchmarked against each other (§7.5 decides how comparable)
RELATED = {
    "ultimate_stretch": {"ultimate_stretch", "elongation_at_break"},
    "elongation_at_break": {"ultimate_stretch", "elongation_at_break"},
}


def record_of(s: Session, p: MechanicalProperty) -> Record:
    material = s.get(Material, p.material_id)
    name = material.name if material else f"材料 #{p.material_id}"
    if p.analysis_run_id is not None:
        run = p.analysis_run
        assert run is not None
        return Record(
            p.id,
            f"{name}（分析 #{run.id} v{run.version}）",
            p.quantity,
            p.value,
            p.lower_bound,
            p.upper_bound,
            METHOD_TEST_TYPE.get(run.method, ""),
            "analysis",
            dict(p.conditions),
        )
    lm = p.literature_measurement
    assert lm is not None
    return Record(
        p.id,
        f"{name}（{lm.source.authors} {lm.source.year} p.{lm.page}）",
        p.quantity,
        p.value,
        p.lower_bound,
        p.upper_bound,
        lm.test_type,
        "literature",
        dict(p.conditions),
    )


def comparison_json(
    s: Session, ref: MechanicalProperty, others: list[MechanicalProperty]
) -> dict[str, Any]:
    a = record_of(s, ref)
    rows = []
    for p in others:
        b = record_of(s, p)
        c = compare(a, b)
        rows.append(
            {
                "property_id": p.id,
                "label": b.label,
                "quantity": b.quantity,
                "value": b.value,
                "lower_bound": b.lower_bound,
                "upper_bound": b.upper_bound,
                "unit": p.unit,
                "verdict": c.verdict,
                "verdict_label": c.verdict_label,
                "findings": [to_jsonable(f) for f in c.findings],
            }
        )
    return {
        "reference": {
            "property_id": ref.id,
            "label": a.label,
            "quantity": a.quantity,
            "value": a.value,
            "unit": ref.unit,
        },
        "rows": rows,
    }


def literature_candidates(s: Session, run: AnalysisRun) -> list[dict[str, Any]]:
    """One entry per literature value of a quantity the run reports, with the rule verdict
    against each of the run's own values of that quantity (best verdict first)."""
    lit = list(
        s.scalars(
            select(MechanicalProperty).where(
                MechanicalProperty.literature_measurement_id.is_not(None)
            )
        )
    )
    own = [
        (p, record_of(s, p))
        for p in run.properties
        if not (p.value is None and p.lower_bound is None and p.upper_bound is None)
    ]
    out = []
    for p in lit:
        comps: list[dict[str, Any]] = []
        for o, a in own:
            if p.quantity not in RELATED.get(o.quantity, {o.quantity}):
                continue
            c = compare(a, record_of(s, p))
            comps.append(
                {
                    "own_property_id": o.id,
                    "own_quantity": o.quantity,
                    "own_definition": o.conditions.get("tg_definition")
                    or o.conditions.get("method")
                    or "",
                    "verdict": c.verdict,
                    "verdict_label": c.verdict_label,
                    "findings": [f.message for f in c.findings],
                }
            )
        if not comps:
            continue
        comps.sort(key=lambda x: RANK[x["verdict"]])
        lm = p.literature_measurement
        assert lm is not None
        mat = s.get(Material, p.material_id)
        out.append(
            {
                "record_id": p.id,
                "quantity": p.quantity,
                "test_type": lm.test_type,
                "material": mat.name if mat else "",
                "polymer_type": mat.polymer_type if mat else "",
                "structure_type": mat.structure_type if mat else "",
                "phase_structure": mat.phase_structure if mat else "",
                "value_si": p.value,
                "lower_bound_si": p.lower_bound,
                "upper_bound_si": p.upper_bound,
                "unit_si": p.unit,
                "reported_text": p.conditions.get("reported_text", ""),
                "conditions": {
                    k: v for k, v in p.conditions.items() if k not in ("content_hash", "record_key")
                },
                "source": {
                    "title": lm.source.title,
                    "authors": lm.source.authors,
                    "year": lm.source.year,
                    "doi": lm.source.doi,
                    "page": lm.page,
                    "figure": lm.figure,
                    "table": lm.table,
                    "extraction_method": lm.extraction_method,
                },
                "best_verdict": comps[0]["verdict"],
                "best_verdict_label": comps[0]["verdict_label"],
                "comparisons": comps,
            }
        )
    out.sort(key=lambda x: (x["quantity"], RANK[x["best_verdict"]]))
    return out
