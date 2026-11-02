"""AI-assisted mapping and quality notes, merged with (never replacing) the rule system."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from polymech_ai.providers import (
    AnthropicAPI,
    ClaudeCLI,
    CodexCLI,
    OpenAICompatibleAPI,
    Provider,
    ProviderError,
)
from polymech_ai.structured import AIValidationError
from polymech_ai.tasks import AIMapping, mapping_payload
from polymech_api.secrets_store import get_secret
from polymech_dataio.mapping import AUTO_ACCEPT_CONFIDENCE, QUANTITIES, ColumnSuggestion, Quantity
from polymech_dataio.reader import RawTable
from polymech_dataio.units_text import unit_for_pint
from polymech_mechanics.errors import UnitDimensionError
from polymech_mechanics.units import kind_of, parse_unit


class AIDisabledError(Exception):
    """AI is switched off in Settings (HTTP 409)."""


def vocabulary() -> list[dict[str, str]]:
    return [{"id": q.value, "label": i.label, "kind": i.kind} for q, i in QUANTITIES.items()]


def provider_from_settings(settings: dict[str, Any], override: str | None = None) -> Provider:
    name = override or settings.get("ai_provider", "codex")
    model = settings.get("ai_model", "")
    effort = settings.get("ai_effort", "")
    if name == "codex":
        return CodexCLI(model, effort)
    if name == "claude":
        return ClaudeCLI(model, effort)
    if name == "api":
        if settings.get("ai_api_kind") == "openai_compatible":
            return OpenAICompatibleAPI(
                get_secret("openai_api_key"), model, settings.get("ai_api_base_url", ""), effort
            )
        return AnthropicAPI(
            get_secret("anthropic_api_key"), model, settings.get("ai_api_base_url", ""), effort
        )
    raise ValueError(f"未知的 AI Provider：{name}")


def require_enabled(settings: dict[str, Any]) -> None:
    if not settings.get("ai_enabled", True):
        raise AIDisabledError("AI 功能已在设置中关闭；规则识别与全部计算不受影响")


def table_payload(table: RawTable, n_rows: int) -> dict[str, Any]:
    cols = [{"index": c.index, "header": c.header, "unit_text": c.unit_text} for c in table.columns]
    n = min(n_rows, table.n_rows)
    rows = [
        [None if not np.isfinite(c.values[i]) else float(c.values[i]) for c in table.columns]
        for i in range(n)
    ]
    return mapping_payload(table.source.split("#")[0], cols, rows, list(table.preamble_fields))


def _unit_kind(unit: str | None) -> str | None:
    u = unit_for_pint(unit)
    if u is None:
        return None
    if u in ("%", "percent"):
        return "dimensionless"
    try:
        return kind_of(parse_unit(u))
    except UnitDimensionError:
        return None


def merge(rule: Sequence[ColumnSuggestion], ai: AIMapping, provider: str) -> list[ColumnSuggestion]:
    by_index = {c.column_index: c for c in ai.columns}
    out: list[ColumnSuggestion] = []
    for r in rule:
        a = by_index.get(r.column_index)
        if a is None or a.quantity == "unknown" or a.quantity not in Quantity._value2member_map_:
            note = "AI 未能判断该列" if a is not None else "AI 未返回该列"
            out.append(_with(r, ambiguities=(*r.ambiguities, note)))
            continue
        q = Quantity(a.quantity)
        info = QUANTITIES[q]
        amb = [f"AI：{x}" for x in a.ambiguities]
        unit = a.unit
        ukind = _unit_kind(unit)
        if unit is None:
            if info.kind == "dimensionless":
                unit = r.unit if r.quantity is q else "dimensionless"
            else:
                amb.append(f"AI 未给出单位，{info.label}需要指定单位")
        elif ukind != info.kind:
            amb.append(f"AI 给出的单位“{unit}”与{info.label}的量纲不一致")
        agree = r.quantity is q and unit_for_pint(r.unit) == unit_for_pint(unit)
        if agree:
            conf = min(0.99, max(r.confidence, a.confidence))
            amb = list(r.ambiguities) + amb
            rationale = (*r.rationale, f"AI（{provider}）判断一致：{a.rationale}")
        else:
            rule_desc = (
                f"{QUANTITIES[r.quantity].label} {r.unit or ''}" if r.quantity else "无法识别"
            )
            amb.append(f"规则与 AI 判断不一致：规则 = {rule_desc}，AI = {info.label} {unit or ''}")
            conf = min(a.confidence, 0.79)
            rationale = (f"AI（{provider}）：{a.rationale}", *r.rationale)
        needs = bool(amb) or conf < AUTO_ACCEPT_CONFIDENCE
        out.append(
            ColumnSuggestion(
                r.column_index,
                r.header,
                q,
                unit,
                round(conf, 3),
                rationale,
                tuple(amb),
                needs,
                r.alternatives,
                f"ai:{provider}" if not agree else f"rules+ai:{provider}",
            )
        )
    return out


def _with(s: ColumnSuggestion, **kw: Any) -> ColumnSuggestion:
    d = {f: getattr(s, f) for f in ColumnSuggestion.__dataclass_fields__}
    return ColumnSuggestion(**(d | kw))


def log_call(
    data_dir: Path,
    task: str,
    provider: str,
    model: str,
    elapsed_s: float,
    attempts: int,
    ok: bool,
    error: str = "",
) -> None:
    """Metadata only (never prompt or response content) — for the course evaluation."""
    rec = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "task": task,
        "provider": provider,
        "model": model,
        "elapsed_s": round(elapsed_s, 2),
        "attempts": attempts,
        "ok": ok,
        "error": error[:200],
    }
    with (data_dir / "ai_calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


__all__ = [
    "AIDisabledError",
    "AIValidationError",
    "ProviderError",
    "log_call",
    "merge",
    "provider_from_settings",
    "require_enabled",
    "table_payload",
    "vocabulary",
]
