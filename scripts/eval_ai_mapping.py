"""Evaluate column mapping: rules vs AI providers vs merged, on the SYNTHETIC fixture set.

Real provider calls (they send headers + 5 sample rows of synthetic data to the cloud model).
Writes:
  reports/data/ai_eval/mapping_eval_<date>.json   metrics + per-column outcomes
  fixtures/ai/recorded/<provider>/<table>.json      raw validated responses (contract tests)

Run:  uv run python scripts/eval_ai_mapping.py [codex] [claude]
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from polymech_ai.providers import ClaudeCLI, CodexCLI, ProviderError
from polymech_ai.structured import AIValidationError
from polymech_ai.tasks import AIMapping, suggest_mapping_ai
from polymech_api.services.ai import merge, table_payload, vocabulary
from polymech_dataio.mapping import ColumnSuggestion, suggest_mapping
from polymech_dataio.reader import read_file
from polymech_dataio.units_text import unit_for_pint

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "import"
OUT = ROOT / "reports" / "data" / "ai_eval"
REC = ROOT / "fixtures" / "ai" / "recorded"


def outcome(
    s: ColumnSuggestion | dict[str, Any], truth: dict[str, str], auto: bool | None = None
) -> dict[str, Any]:
    if isinstance(s, ColumnSuggestion):
        q, u, needs = (s.quantity.value if s.quantity else None), s.unit, s.needs_confirmation
    else:
        q, u, needs = s["quantity"], s["unit"], not auto
    q_ok = q == truth["quantity"]
    # a null unit is correct for a dimensionless column (stretch, cycle number, tan δ)
    unit = "dimensionless" if u is None and truth["unit"] == "dimensionless" else u
    u_ok = q_ok and unit_for_pint(unit) == unit_for_pint(truth["unit"])
    return {
        "quantity": q,
        "unit": u,
        "quantity_ok": q_ok,
        "unit_ok": u_ok,
        "needs_confirmation": needs,
        "auto_accepted_wrong": (not needs) and not u_ok,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {
        "columns": n,
        "quantity_accuracy": round(sum(r["quantity_ok"] for r in rows) / n, 4),
        "quantity_and_unit_accuracy": round(sum(r["unit_ok"] for r in rows) / n, 4),
        "needs_confirmation_rate": round(sum(r["needs_confirmation"] for r in rows) / n, 4),
        "auto_accepted_wrong": sum(r["auto_accepted_wrong"] for r in rows),
        "auto_accepted_correct": sum((not r["needs_confirmation"]) and r["unit_ok"] for r in rows),
    }


def main(names: list[str]) -> None:
    providers = {"codex": CodexCLI(), "claude": ClaudeCLI()}
    chosen = [providers[n] for n in names or ["codex", "claude"]]
    manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    vocab = vocabulary()
    per: dict[str, list[dict[str, Any]]] = {"rules": []}
    for p in chosen:
        per[f"ai_raw:{p.name}"] = []
        per[f"merged:{p.name}"] = []
    calls: list[dict[str, Any]] = []
    for entry in manifest:
        tables = [t for t in read_file(FIX / entry["file"]) if entry["sheet"] in (None, t.sheet)]
        t = tables[0]
        truth = entry["columns"]
        rules = suggest_mapping(t)
        for s in rules:
            per["rules"].append(
                {"table": t.source, "header": s.header} | outcome(s, truth[s.header])
            )
        payload = table_payload(t, 5)
        for p in chosen:
            t0 = time.perf_counter()
            try:
                res = suggest_mapping_ai(p, payload, vocab, timeout_s=240)
            except (ProviderError, AIValidationError) as e:
                calls.append(
                    {
                        "table": t.source,
                        "provider": p.name,
                        "ok": False,
                        "error": str(e)[:200],
                        "elapsed_s": round(time.perf_counter() - t0, 1),
                    }
                )
                print(f"  {p.name:6s} {t.source}: FAILED {e}", flush=True)
                continue
            calls.append(
                {
                    "table": t.source,
                    "provider": p.name,
                    "model": res.model,
                    "ok": True,
                    "elapsed_s": round(res.elapsed_s, 1),
                    "attempts": res.attempts,
                    "usage": res.usage,
                }
            )
            rec_dir = REC / p.name
            rec_dir.mkdir(parents=True, exist_ok=True)
            safe = t.source.replace("#", "__").replace(" ", "_")
            (rec_dir / f"{safe}.json").write_text(
                json.dumps(
                    {
                        "provider": res.provider,
                        "model": res.model,
                        "table": t.source,
                        "response": res.value.model_dump(),
                    },
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
            ai_cols = {c.column_index: c for c in res.value.columns}
            for s in rules:
                a = ai_cols.get(s.column_index)
                raw = {"quantity": a.quantity if a else None, "unit": a.unit if a else None}
                auto = bool(a) and a.confidence >= 0.8 and not a.ambiguities
                per[f"ai_raw:{p.name}"].append(
                    {"table": t.source, "header": s.header} | outcome(raw, truth[s.header], auto)
                )
            for m in merge(rules, AIMapping.model_validate(res.value.model_dump()), p.name):
                per[f"merged:{p.name}"].append(
                    {"table": t.source, "header": m.header} | outcome(m, truth[m.header])
                )
            print(f"  {p.name:6s} {t.source}: {res.elapsed_s:.1f}s", flush=True)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": "fixtures/import (SYNTHETIC, 14 tables incl. 1 adversarial header)",
        "providers": {p.name: p.status().__dict__ for p in chosen},
        "summary": {k: summarize(v) for k, v in per.items() if v},
        "calls": calls,
        "columns": per,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"mapping_eval_{datetime.now().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
    print("written", path.relative_to(ROOT))


if __name__ == "__main__":
    main(sys.argv[1:])
