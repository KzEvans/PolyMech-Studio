"""Probe, in real Origin, the LabTalk properties needed for the thesis-style template and for
visible graph windows: set each property, read it back, save/reopen an OPJU, export a PNG.

Property names are from the OriginLab LabTalk reference (Layer.Axis, Layer.Axis.Label, Page,
Graphic Objects, Window command); this script checks what Origin 2025b actually accepts.
Starts its own hidden Origin and closes only that instance.

Run:  scripts/vm/run_user.sh -t 600 '%BRIDGE%\\venv\\Scripts\\python.exe' '%BRIDGE%\\app\\probe_thesis_style.py'
Output: %BRIDGE%\\stage\\probe_thesis\\report.json, probe.png, probe.opju
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from polymech_bridge.worker import kill_pid, origin_pids

OUT = Path(__file__).resolve().parents[1] / "stage" / "probe_thesis"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()
    rep: dict[str, object] = {}
    before = origin_pids()
    import originpro as op

    op.set_show(False)
    owned = origin_pids() - before

    def rd(prop: str) -> float | None:
        try:
            return float(op.lt_float(prop))
        except Exception:
            return None

    def rs(expr: str) -> str | None:
        try:
            return str(op.get_lt_str(expr))
        except Exception:
            return None

    def setp(cmd: str, prop: str) -> dict[str, object]:
        ok = op.lt_exec(cmd + ";")
        return {"cmd": cmd, "ok": bool(ok), "read": rd(prop)}

    try:
        rep["origin_version"] = op.lt_float("@V")
        op.new()
        wks = op.new_sheet()
        xs = [1.0 + 0.1 * i for i in range(40)]
        wks.from_list(0, xs, lname="拉伸比 λ (SYNTHETIC)", axis="X")
        wks.from_list(1, [0.3 * (x - 1) for x in xs], lname="A")
        wks.from_list(2, [0.2 * (x - 1) ** 1.3 for x in xs], lname="B")
        gp = op.new_graph(template="line")
        gp.name = "Probe"
        p1 = gp[0].add_plot(wks, coly=1, colx=0, type="l")
        p2 = gp[0].add_plot(wks, coly=2, colx=0, type="l")
        gp[0].rescale()
        gp.activate()
        rep["page_attrs"] = sorted(a for a in dir(gp) if not a.startswith("_"))
        rep["page_before"] = {k: rd(f"page.{k}") for k in ("width", "height", "resx", "resy", "unit", "win")}

        s: dict[str, object] = {}
        # ticks: bottom/left out (major 2 + minor 8 = 10), top/right in (major 1 + minor 4 = 5)
        for ax, v in (("x", 10), ("y", 10), ("x2", 5), ("y2", 5)):
            s[f"{ax}.ticks"] = setp(f"layer.{ax}.ticks={v}", f"layer.{ax}.ticks")
        for ax in ("x", "y"):
            s[f"{ax}.showAxes"] = setp(f"layer.{ax}.showAxes=3", f"layer.{ax}.showAxes")
            s[f"{ax}.showLabels"] = setp(f"layer.{ax}.showLabels=1", f"layer.{ax}.showLabels")
            s[f"{ax}.thickness"] = setp(f"layer.{ax}.thickness=2.2", f"layer.{ax}.thickness")
            s[f"{ax}.tickthickness"] = setp(f"layer.{ax}.tickthickness=2.2", f"layer.{ax}.tickthickness")
            s[f"{ax}.mtickthickness"] = setp(f"layer.{ax}.mtickthickness=2.2", f"layer.{ax}.mtickthickness")
            s[f"{ax}.ticklength"] = setp(f"layer.{ax}.ticklength=9", f"layer.{ax}.ticklength")
            s[f"{ax}.mticklength"] = setp(f"layer.{ax}.mticklength=4", f"layer.{ax}.mticklength")
            s[f"{ax}.minorTicks"] = setp(f"layer.{ax}.minorTicks=1", f"layer.{ax}.minorTicks")
            s[f"{ax}.label.font"] = setp(f"layer.{ax}.label.font=font(Times New Roman)", f"layer.{ax}.label.font")
            s[f"{ax}.label.pt"] = setp(f"layer.{ax}.label.pt=20", f"layer.{ax}.label.pt")
            s[f"{ax}.label.bold"] = setp(f"layer.{ax}.label.bold=1", f"layer.{ax}.label.bold")
        s["font_id_tnr"] = rd("font(Times New Roman)")
        # axis titles and legend (graphic objects)
        op.lt_exec("legend -r;")
        for obj in ("xb", "yl", "legend"):
            size = 22 if obj == "legend" else 28
            s[f"{obj}.font"] = setp(f"{obj}.font=font(Times New Roman)", f"{obj}.font")
            s[f"{obj}.fsize"] = setp(f"{obj}.fsize={size}", f"{obj}.fsize")
            s[f"{obj}.bold"] = setp(f"{obj}.bold=1", f"{obj}.bold")
        s["legend.background"] = setp("legend.background=0", "legend.background")
        s["xb.text_before"] = rs("xb.text$")
        op.lt_exec('xb.text$="\\b(拉伸比 λ)";')
        s["xb.text_after"] = rs("xb.text$")
        s["legend.text"] = rs("legend.text$")
        # page size: 272.288 × 193.04 mm = 10.72 × 7.6 in
        resx, resy = rd("page.resx") or 0, rd("page.resy") or 0
        if resx and resy:
            s["page.width"] = setp(f"page.width={round(10.72 * resx)}", "page.width")
            s["page.height"] = setp(f"page.height={round(7.6 * resy)}", "page.height")
        # plots: line width (1/500 pt) and dash style
        p1.set_cmd("-w 1500")
        p2.set_cmd("-w 1500")
        s["dash_ok"] = bool(p2.set_cmd("-d 1"))
        rep["style"] = s

        # window visibility in the hidden instance, and ways to change it
        vis: dict[str, object] = {"win_initial": rd("page.win")}
        for cmd in ("win -a Probe", "win -h 0", "win -r", "win -b Probe"):
            ok = op.lt_exec(cmd + ";")
            vis[cmd] = {"ok": bool(ok), "page.win": rd("page.win")}
        if hasattr(gp, "show"):
            with contextlib.suppress(Exception):
                vis["gp.show_before"] = gp.show
                gp.show = True
                vis["gp.show_after"] = gp.show
                vis["win_after_gp_show"] = rd("page.win")
        rep["visibility"] = vis

        png = OUT / "probe.png"
        gp.save_fig(str(png), type="png", width=3216)
        rep["png"] = png.exists()
        opju = OUT / "probe.opju"
        rep["saved"] = bool(op.save(str(opju))) and opju.exists()

        # reopen: style and window state as saved
        op.new()
        rep["reopened"] = bool(op.open(file=str(opju), readonly=True))
        g2 = next((p for p in op.pages("g") if p.name == "Probe"), None)
        if g2 is not None:
            g2.activate()
            rep["reopen"] = {
                "page.win": rd("page.win"),
                "show": getattr(g2, "show", None),
                **{
                    k: rd(k)
                    for k in (
                        "layer.x.ticks", "layer.x2.ticks", "layer.y.ticks", "layer.y2.ticks",
                        "layer.x.thickness", "layer.x.label.pt", "layer.x.label.bold",
                        "xb.fsize", "legend.fsize", "page.width", "page.height",
                    )
                },
            }
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
