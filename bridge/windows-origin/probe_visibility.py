"""Probe how graph windows created by the bridge (hidden Origin instance) are saved: hidden or
visible when the project is opened. Several candidate ways to show a page are tried, the
project is saved, reopened, and each page's state is read back (page.win, is_open()).

Run:  scripts/vm/run_user.sh -t 600 '%BRIDGE%\\venv\\Scripts\\python.exe' '%BRIDGE%\\app\\probe_visibility.py'
Output: %BRIDGE%\\stage\\probe_visibility\\report.json, probe.opju
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from polymech_bridge.worker import kill_pid, origin_pids

OUT = Path(__file__).resolve().parents[1] / "stage" / "probe_visibility"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()
    rep: dict[str, object] = {}
    before = origin_pids()
    import originpro as op

    op.set_show(False)
    owned = origin_pids() - before

    def state(p) -> dict[str, object]:  # type: ignore[no-untyped-def]
        p.activate()
        out: dict[str, object] = {}
        with contextlib.suppress(Exception):
            out["page.win"] = float(op.lt_float("page.win"))
        with contextlib.suppress(Exception):
            out["is_open"] = p.is_open()
        with contextlib.suppress(Exception):
            out["show"] = p.show
        return out

    try:
        op.new()
        wks = op.new_sheet()
        wks.from_list(0, [1.0, 2.0, 3.0], axis="X")
        wks.from_list(1, [1.0, 4.0, 9.0])
        rep["book_initial"] = state(wks.get_book())
        graphs = {}
        for name in ("Ctrl", "ShowTrue", "WinCh0", "ObjSetShow"):
            gp = op.new_graph(template="line")
            gp.name = name
            gp[0].add_plot(wks, coly=1, colx=0)
            graphs[name] = gp
        rep["obj_methods"] = sorted(a for a in dir(graphs["Ctrl"].obj) if "show" in a.lower() or "win" in a.lower())
        tried: dict[str, object] = {}
        g = graphs["ShowTrue"]
        with contextlib.suppress(Exception):
            g.show = False
            g.show = True
            tried["ShowTrue"] = "show False→True"
        graphs["WinCh0"].activate()
        tried["WinCh0"] = bool(op.lt_exec("win -ch 0;"))
        g = graphs["ObjSetShow"]
        for meth in ("SetShow", "Show"):
            fn = getattr(g.obj, meth, None)
            if callable(fn):
                with contextlib.suppress(Exception):
                    tried["ObjSetShow"] = {meth: str(fn(3))}
                    break
        rep["tried"] = tried
        rep["runtime"] = {n: state(g) for n, g in graphs.items()}
        opju = OUT / "probe.opju"
        rep["saved"] = bool(op.save(str(opju))) and opju.exists()
        op.new()
        rep["reopened"] = bool(op.open(file=str(opju), readonly=True))
        rep["after_reopen"] = {p.name: state(p) for p in op.pages("g")}
        rep["book_after_reopen"] = {p.name: state(p) for p in op.pages("w")}
    finally:
        with contextlib.suppress(Exception):
            op.exit()
        time.sleep(3)
        for pid in owned & origin_pids():
            kill_pid(pid)
        rep["owned_left"] = sorted(owned & origin_pids())
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
