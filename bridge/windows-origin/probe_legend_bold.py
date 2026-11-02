"""Probe how to make legend entries bold without freezing them: LabTalk may substitute %(1)
when the string is assigned. Tries several escapes, reads legend.text$ back, exports PNGs.

Run:  scripts/vm/run_user.sh -t 600 '%BRIDGE%\\venv\\Scripts\\python.exe' '%BRIDGE%\\app\\probe_legend_bold.py'
Output: %BRIDGE%\\stage\\probe_legend\\*.png, printed report
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from polymech_bridge.worker import kill_pid, origin_pids

OUT = Path(__file__).resolve().parents[1] / "stage" / "probe_legend"

VARIANTS = {
    "plain": "\\b(\\l(1) %(1))\\n\\b(\\l(2) %(2))",  # freezes the entries
    "double_pct": "\\b(\\l(1) %%(1))\\n\\b(\\l(2) %%(2))",  # live, but \\n is literal
    "crlf": "\\b(\\l(1) %%(1))%(CRLF)\\b(\\l(2) %%(2))",
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()
    rep: dict[str, object] = {}
    before = origin_pids()
    import originpro as op

    op.set_show(False)
    owned = origin_pids() - before
    try:
        op.new()
        wks = op.new_sheet()
        xs = [1.0, 2.0, 3.0, 4.0]
        wks.from_list(0, xs, lname="X", axis="X")
        wks.from_list(1, [1.0, 2.0, 3.0, 4.0], lname="Series A")
        wks.from_list(2, [1.0, 1.5, 2.0, 2.5], lname="Series B")
        for name, text in VARIANTS.items():
            gp = op.new_graph(template="line")
            gp.name = f"L{name.replace('_', '')}"
            gp[0].add_plot(wks, coly=1, colx=0)
            gp[0].add_plot(wks, coly=2, colx=0)
            gp[0].rescale()
            gp.activate()
            op.lt_exec("legend -r;")
            op.lt_exec(f'legend.text$="{text}";')
            r: dict[str, object] = {"sent": text, "read": str(op.get_lt_str("legend.text$"))}
            # rename a column: a live legend follows, a frozen one does not
            wks.set_label(2, "Renamed B")
            op.lt_exec("doc -uw;")
            gp.activate()
            r["after_rename"] = str(op.get_lt_str("legend.text$"))
            wks.set_label(2, "Series B")
            png = OUT / f"{name}.png"
            gp.save_fig(str(png), type="png", width=800)
            r["png"] = png.exists()
            rep[name] = r
    finally:
        with contextlib.suppress(Exception):
            op.exit()
        time.sleep(3)
        for pid in owned & origin_pids():
            kill_pid(pid)
        rep["owned_left"] = sorted(owned & origin_pids())
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
