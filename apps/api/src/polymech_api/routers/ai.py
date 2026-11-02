"""AI endpoints. Every call first has a preview of exactly what would be sent (SPEC §8.5)."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from polymech_ai.providers import ClaudeCLI, CodexCLI, ProviderError
from polymech_ai.structured import AIValidationError
from polymech_ai.tasks import benchmark_ai, quality_notes_ai, suggest_mapping_ai
from polymech_api.deps import get_state
from polymech_api.routers.imports import MappingIn, _suggest, _table
from polymech_api.serialization import to_jsonable
from polymech_api.services import ai as svc
from polymech_api.services.compare import literature_candidates
from polymech_api.state import AppState
from polymech_database.models import AnalysisRun, Material
from polymech_database.repository import get
from polymech_dataio.mapping import MappedColumn
from polymech_dataio.metadata import TestType
from polymech_dataio.normalize import normalize
from polymech_dataio.quality import check_quality

router = APIRouter(prefix="/api/ai", tags=["ai"])
State = Annotated[AppState, Depends(get_state)]
ProviderName = Literal["codex", "claude", "api"]


@router.get("/providers")
def providers(state: State) -> dict[str, Any]:
    s = state.settings()
    out = {"enabled": s["ai_enabled"], "selected": s["ai_provider"], "providers": []}
    for p in (CodexCLI(), ClaudeCLI(), svc.provider_from_settings(s | {"ai_provider": "api"})):
        out["providers"].append(to_jsonable(p.status()))
    return out


class MappingAIIn(BaseModel):
    raw_file_id: int
    table_index: int = 0
    n_rows: int = Field(default=5, ge=0, le=50)
    provider: ProviderName | None = None


@router.post("/mapping/preview")
def mapping_preview(state: State, body: MappingAIIn) -> dict[str, Any]:
    _, t = _table(state, body.raw_file_id, body.table_index)
    s = state.settings()
    return {
        "provider": body.provider or s["ai_provider"],
        "payload": svc.table_payload(t, body.n_rows),
        "note": "以下内容将发送到云端模型（CLI Provider 同样会发送到 OpenAI/Anthropic 服务器）",
    }


@router.post("/mapping")
def mapping(state: State, body: MappingAIIn) -> dict[str, Any]:
    s = state.settings()
    svc.require_enabled(s)
    _, t = _table(state, body.raw_file_id, body.table_index)
    rules, profile = _suggest(state, t)
    provider = svc.provider_from_settings(s, body.provider)
    try:
        res = suggest_mapping_ai(provider, svc.table_payload(t, body.n_rows), svc.vocabulary())
    except (ProviderError, AIValidationError) as e:
        svc.log_call(state.data_dir, "column_mapping", provider.name, "", 0, 0, False, str(e))
        return {
            "fallback": True,
            "error": str(e),
            "suggestions": [r.to_dict() for r in rules],
            "message": "AI 不可用或输出无效，已回退到规则识别结果",
        }
    svc.log_call(
        state.data_dir, "column_mapping", res.provider, res.model, res.elapsed_s, res.attempts, True
    )
    merged = svc.merge(rules, res.value, res.provider)
    return {
        "fallback": False,
        "provider": res.provider,
        "model": res.model,
        "elapsed_s": round(res.elapsed_s, 1),
        "attempts": res.attempts,
        "profile": profile,
        "suggestions": [m.to_dict() for m in merged],
        "ai_raw": res.value.model_dump(),
    }


class QualityAIIn(BaseModel):
    raw_file_id: int
    table_index: int = 0
    test_type: TestType
    mappings: list[MappingIn]
    provider: ProviderName | None = None
    dry_run: bool = False


def _quality_payload(state: AppState, body: QualityAIIn) -> dict[str, Any]:
    _, t = _table(state, body.raw_file_id, body.table_index)
    data = normalize(t, [MappedColumn(m.column_index, m.quantity, m.unit) for m in body.mappings])
    issues = check_quality(data, body.test_type, t)
    stats = {}
    for q, v in data.columns.items():
        f = v[np.isfinite(v)]
        stats[q.value] = {
            "si_unit": next(c.to_unit for c in data.conversions if c.quantity is q),
            "n": int(v.size),
            "n_missing": int(v.size - f.size),
            **(
                {
                    "min": float(f.min()),
                    "max": float(f.max()),
                    "first": float(f[0]),
                    "last": float(f[-1]),
                    "argmax_fraction": round(float(np.argmax(f)) / max(f.size - 1, 1), 3),
                }
                if f.size
                else {}
            ),
        }
    return {
        "test_type": body.test_type.value,
        "rule_findings": [
            {"code": i.code, "severity": i.severity, "message": i.message} for i in issues
        ],
        "column_statistics": stats,
    }


@router.post("/quality")
def quality(state: State, body: QualityAIIn) -> dict[str, Any]:
    payload = _quality_payload(state, body)
    if body.dry_run:
        return {"payload": payload}
    s = state.settings()
    svc.require_enabled(s)
    provider = svc.provider_from_settings(s, body.provider)
    try:
        res = quality_notes_ai(provider, payload)
    except (ProviderError, AIValidationError) as e:
        svc.log_call(state.data_dir, "quality_notes", provider.name, "", 0, 0, False, str(e))
        return {"fallback": True, "error": str(e), "rule_findings": payload["rule_findings"]}
    svc.log_call(
        state.data_dir, "quality_notes", res.provider, res.model, res.elapsed_s, res.attempts, True
    )
    known = {f["code"] for f in payload["rule_findings"]}
    items = [
        i.model_dump() | {"related_rule_codes": [c for c in i.related_rule_codes if c in known]}
        for i in res.value.items
    ]
    return {
        "fallback": False,
        "provider": res.provider,
        "model": res.model,
        "elapsed_s": round(res.elapsed_s, 1),
        "items": items,
        "overall": res.value.overall,
        "rule_findings": payload["rule_findings"],
        "disclaimer": "AI 提示仅供参考，不修改任何数据；确定性计算结果不受影响",
    }


class BenchmarkIn(BaseModel):
    run_id: int
    include_values: bool = False
    provider: ProviderName | None = None
    dry_run: bool = False


_HIDDEN_CONDITIONS = {"content_hash", "record_key"}
# a number with a unit: AI-written material values (record ids and page numbers are fine)
_VALUE = re.compile(r"[-−]?\d+(?:\.\d+)?\s*(?:[kMG]?Pa|k?J|°C|℃|K\b|%|Hz|倍|[nμm]m\b)")


def _benchmark_payload(
    state: AppState, body: BenchmarkIn
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with state.db.session() as s:
        run = get(s, AnalysisRun, body.run_id)
        mat = s.get(Material, run.experiment.specimen.material_id)
        cands = literature_candidates(s, run)
        own = [
            {
                "property_id": p.id,
                "quantity": p.quantity,
                "unit_si": p.unit,
                "conditions": {
                    k: v for k, v in p.conditions.items() if k not in _HIDDEN_CONDITIONS
                },
                **(
                    {
                        "value_si": p.value,
                        "lower_bound_si": p.lower_bound,
                        "upper_bound_si": p.upper_bound,
                    }
                    if body.include_values
                    else {}
                ),
            }
            for p in run.properties
        ]
        experiment = {
            "analysis_method": run.method,
            "test_type": run.experiment.test_type,
            "material_descriptors": {
                "polymer_type": mat.polymer_type if mat else "",
                "structure_type": mat.structure_type if mat else "",
                "phase_structure": mat.phase_structure if mat else "",
            },
            "own_properties": own,
            "values_included": body.include_values,
        }

    return {"experiment": experiment, "candidates": cands}, cands


@router.post("/benchmark")
def benchmark(state: State, body: BenchmarkIn) -> dict[str, Any]:
    """Literature benchmarking (SPEC §8.3): rule-based candidates always; the AI may only
    recommend among them, and every number shown comes from the database by record id."""
    payload, cands = _benchmark_payload(state, body)
    base = {
        "candidates": cands,
        "note": "本实验的材料名与原始数据不会发送；"
        + (
            "将发送本实验的性能数值"
            if body.include_values
            else "默认不发送本实验的性能数值，只发送指标名称与测试条件"
        ),
    }
    if body.dry_run:
        return base | {"payload": payload}
    if not cands:
        return base | {"fallback": True, "message": "文献库中没有与该结果同类指标的记录，无法对标"}
    s = state.settings()
    svc.require_enabled(s)
    provider = svc.provider_from_settings(s, body.provider)
    try:
        res = benchmark_ai(provider, payload)
    except (ProviderError, AIValidationError) as e:
        svc.log_call(state.data_dir, "literature_benchmark", provider.name, "", 0, 0, False, str(e))
        return base | {
            "fallback": True,
            "error": str(e),
            "message": "AI 不可用或输出无效，以下为规则检索与可比性结果",
        }
    svc.log_call(
        state.data_dir,
        "literature_benchmark",
        res.provider,
        res.model,
        res.elapsed_s,
        res.attempts,
        True,
    )
    by_id = {c["record_id"]: c for c in cands}
    recs = []
    for item in res.value.recommendations:
        ids = [i for i in item.record_ids if i in by_id]
        materials = {by_id[i]["material"] for i in ids}
        problems = []
        if not ids:
            problems.append("没有引用任何候选记录")
        if materials and materials != {item.material}:
            problems.append(
                f"材料名“{item.material}”与所引用记录的材料（{'、'.join(sorted(materials))}）不一致"
            )
        texts = [item.reason, item.comparability_note, *item.condition_differences]
        recs.append(
            item.model_dump()
            | {
                "records": [by_id[i] for i in ids],
                "rejected": bool(problems),
                "problems": problems,
                "contains_values": any(_VALUE.search(t) for t in texts),
            }
        )
    return base | {
        "fallback": False,
        "provider": res.provider,
        "model": res.model,
        "elapsed_s": round(res.elapsed_s, 1),
        "recommendations": recs,
        "limitations": res.value.limitations,
        "summary": res.value.summary,
        "disclaimer": "推荐与说明由 AI 生成，仅供参考；数值与来源均来自本地数据库记录，可比性以规则判断为准",
    }
