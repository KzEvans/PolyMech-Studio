"""Independent check of an OPJU in a FRESH Origin instance (launched and closed by this
script; only its own -Embedding PID is ever terminated). Prints one JSON line.

Usage (VM, user session):  python verify_opju.py <file.opju>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from polymech_bridge.worker import kill_pid, origin_pids


def main(path: str) -> int:
    before = origin_pids()
    import originpro as op

    report: dict = {"file": Path(path).name, "size": Path(path).stat().st_size}
    try:
        op.set_show(False)
        report["origin_version"] = op.lt_float("@V")
        report["opened"] = bool(op.open(file=path, readonly=True))
        books = []
        for b in op.pages("w"):
            sheets = []
            for wks in b:
                cols = wks.cols
                sheets.append(
                    {
                        "name": wks.name,
                        "cols": cols,
                        "rows": len(wks.to_list(0)) if cols else 0,
                        "long_names": [wks.get_label(i, "L") for i in range(cols)],
                    }
                )
            books.append({"name": b.name, "long_name": b.lname, "sheets": sheets})
        graphs = [
            {"name": g.name, "long_name": g.lname, "plots": sum(len(lay.plot_list()) for lay in g)}
            for g in op.pages("g")
        ]
        report |= {"books": books, "graphs": graphs}
    finally:
        try:
            op.lt_exec("doc -s;")
            op.exit()
        except Exception:
            pass
        time.sleep(5)
        for pid in origin_pids() - before:
            kill_pid(pid)
        time.sleep(1)
        report["leftover_pids"] = sorted(origin_pids() - before)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("opened") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
