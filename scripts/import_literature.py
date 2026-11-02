"""Import curated literature records into a PolyMech data directory.

    uv run python scripts/import_literature.py [FILE ...] [--data-dir DIR]

Default file: literature/theses_chen2024_liu2026.json. The import is validated as a whole
and idempotent (records already present are skipped).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymech_api.settings import Settings
from polymech_database.db import Database
from polymech_database.literature import import_literature

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--data-dir", type=Path, default=Settings.from_env().data_dir)
    a = ap.parse_args()
    files = a.files or [ROOT / "literature" / "theses_chen2024_liu2026.json"]
    db = Database(a.data_dir)
    for f in files:
        with db.session() as s:
            out = import_literature(s, json.loads(f.read_text(encoding="utf-8")))
        print(
            f"{f.name}: 新增 {out.records_added} 条，更正 {out.records_updated} 条，"
            f"未变化 {out.records_skipped} 条，"
            f"新建材料 {out.materials_created} 个"
        )


if __name__ == "__main__":
    main()
