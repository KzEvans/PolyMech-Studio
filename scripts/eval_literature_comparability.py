"""Comparability verdicts for every same-indicator pair of the curated literature records.

Writes reports/data/eval/literature_comparability_<date>.json.
Run:  uv run python scripts/eval_literature_comparability.py
"""

from __future__ import annotations

import collections
import itertools
import json
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from polymech_api.services.compare import record_of
from polymech_database.comparability import compare
from polymech_database.db import Database
from polymech_database.literature import import_literature
from polymech_database.models import MechanicalProperty

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    payload = json.loads((ROOT / "literature" / "theses_chen2024_liu2026.json").read_text("utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp))
        with db.session() as s:
            import_literature(s, payload)
        with db.session() as s:
            recs = [record_of(s, p) for p in s.scalars(select(MechanicalProperty))]
            by = collections.defaultdict(list)
            for r in recs:
                by[r.quantity].append(r)
            totals: collections.Counter[str] = collections.Counter()
            deciding: collections.Counter[str] = collections.Counter()
            pairs = []
            for q, rs in sorted(by.items()):
                for a, b in itertools.combinations(rs, 2):
                    c = compare(a, b)
                    totals[c.verdict] += 1
                    for f in c.findings:
                        if f.level == c.verdict and c.verdict != "direct":
                            deciding[f"{c.verdict} / {f.aspect}"] += 1
                    pairs.append({"quantity": q, "a": a.label, "b": b.label, "verdict": c.verdict})
    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "n_records": len(recs),
        "n_pairs": len(pairs),
        "verdicts": dict(totals),
        "deciding_aspects": dict(deciding.most_common()),
        "note": "pairs are formed within the same quantity; a pair's verdict is its worst aspect",
        "pairs": pairs,
    }
    dest = (
        ROOT
        / "reports"
        / "data"
        / "eval"
        / f"literature_comparability_{datetime.now():%Y%m%d}.json"
    )
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out["n_pairs"], out["verdicts"])


if __name__ == "__main__":
    main()
