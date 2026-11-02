"""Evaluate AI literature benchmarking (SPEC §8.3) with real provider calls.

Scenario: SYNTHETIC uniaxial and DMA experiments in a temporary data directory, plus the
curated thesis records. Sends material descriptors, indicator names/conditions and published
literature records (and, in the second case, the synthetic experiment values) to the model.
Checks the guard rails mechanically:
  - every cited record is a candidate (schema) and its material matches (post-check);
  - no AI-written values (number + unit) in the explanatory text;
  - a recommendation never claims "可直接比较" when the rule verdict is weaker.
Writes reports/data/ai_eval/benchmark_eval_<date>.json.

Run:  uv run python scripts/eval_ai_benchmark.py [codex] [claude]
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from polymech_api.main import create_app
from polymech_api.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "import"
OUT = ROOT / "reports" / "data" / "ai_eval"
MANIFEST = {
    (e["file"], e["sheet"]): e
    for e in json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
}


def ok(r: Any) -> Any:
    assert r.status_code == 200, r.text
    return r.json()


def experiment(c: TestClient, name: str, test_type: str, label: str) -> int:
    f = ok(c.post("/api/imports", files=[("files", (name, (FIX / name).read_bytes()))]))["files"][0]
    t = f["tables"][0]
    entry = MANIFEST[(name, None)]
    maps = [
        {"column_index": col["index"], **entry["columns"][col["header"]]} for col in t["columns"]
    ]
    body = {
        "raw_file_id": f["raw_file_id"],
        "mappings": maps,
        "material_name": f"SYN-{label}",
        "specimen_label": label,
        "test_type": test_type,
        **entry["metadata"],
    }
    return int(ok(c.post("/api/experiments", json=body))["id"])


def check(out: dict[str, Any]) -> dict[str, Any]:
    verdicts = {c["record_id"]: c["best_verdict"] for c in out["candidates"]}
    recs = out.get("recommendations") or []
    overclaim = [
        r["material"]
        for r in recs
        if "可直接比较" in r["comparability_note"]
        and "不" not in r["comparability_note"].split("可直接比较")[0][-4:]
        and any(verdicts[c["record_id"]] != "direct" for c in r["records"])
    ]
    return {
        "n_candidates": len(verdicts),
        "n_recommendations": len(recs),
        "n_rejected": sum(r["rejected"] for r in recs),
        "n_with_ai_values": sum(r["contains_values"] for r in recs),
        "possible_overclaims": overclaim,
        "cited_records": sorted({c["record_id"] for r in recs for c in r["records"]}),
    }


def main() -> None:
    providers = sys.argv[1:] or ["codex"]
    os.environ["POLYMECH_NO_KEYCHAIN"] = "1"
    lit = json.loads(
        (ROOT / "literature" / "theses_chen2024_liu2026.json").read_text(encoding="utf-8")
    )
    report: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs": [],
    }
    with (
        tempfile.TemporaryDirectory() as tmp,
        TestClient(create_app(Settings(data_dir=Path(tmp)))) as c,
    ):
        ok(c.post("/api/literature/import", json=lit))
        uni = experiment(c, "SYNTH_uniaxial_gbk_chinese.csv", "uniaxial", "U1")
        dma = experiment(c, "SYNTH_dma.csv", "dma", "D1")
        runs = {
            "uniaxial": ok(c.post(f"/api/experiments/{uni}/analyses/uniaxial", json={}))["id"],
            "dma": ok(c.post(f"/api/experiments/{dma}/analyses/dma", json={}))["id"],
        }
        for prov in providers:
            ok(c.put("/api/settings", json={"ai_enabled": True, "ai_provider": prov}))
            for case, run_id in runs.items():
                for include_values in (False, True):
                    out = ok(
                        c.post(
                            "/api/ai/benchmark",
                            json={"run_id": run_id, "include_values": include_values},
                        )
                    )
                    entry = {
                        "provider": prov,
                        "case": case,
                        "include_values": include_values,
                        "fallback": out.get("fallback"),
                        "error": out.get("error"),
                        "model": out.get("model"),
                        "elapsed_s": out.get("elapsed_s"),
                        "checks": check(out),
                        "summary": out.get("summary"),
                        "recommendations": [
                            {
                                k: r[k]
                                for k in (
                                    "material",
                                    "key_metrics",
                                    "reason",
                                    "condition_differences",
                                    "comparability_note",
                                    "rejected",
                                    "problems",
                                    "contains_values",
                                )
                            }
                            | {"record_ids": [x["record_id"] for x in r["records"]]}
                            for r in out.get("recommendations") or []
                        ],
                        "limitations": out.get("limitations"),
                    }
                    report["runs"].append(entry)
                    print(
                        prov,
                        case,
                        include_values,
                        json.dumps(entry["checks"], ensure_ascii=False),
                        entry["elapsed_s"],
                    )
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"benchmark_eval_{datetime.now().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
