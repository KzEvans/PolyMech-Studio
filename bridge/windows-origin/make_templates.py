"""Build the PolyMech Origin graph templates (.otpu) in real Origin and verify them.

For each entry: new graph from the Origin built-in base template, SYNTHETIC placeholder plots,
the template's style via LabTalk (journal: closed frame, inward ticks, Arial; thesis: Times New
Roman bold, ticks out on bottom/left and in on top/right, 2.2 pt axes — see
polymech_bridge.templates.STYLES), every style property read back, saved with
`template_saveas`, reloaded with op.new_graph(template=path), style read back again from the
reloaded graph, and a PNG exported for visual review.
Starts its own hidden Origin and closes only that instance.

Run:  scripts/vm/run_user.sh -t 600 '%BRIDGE%\\venv\\Scripts\\python.exe' '%BRIDGE%\\app\\make_templates.py' [id ...]
      (no ids = all templates)
Output: %BRIDGE%\\stage\\templates\\*.otpu, *_check.png, report.json
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from polymech_bridge.templates import STYLES, apply_text_style, set_text_font
from polymech_bridge.worker import kill_pid, origin_pids

OUT = Path(__file__).resolve().parents[1] / "stage" / "templates"

# id → (built-in base, n placeholder plots on the left axis, plot type, right axis, style)
TEMPLATES = {
    "pm_line": ("line", 2, "l", False, "journal"),
    "pm_scatter": ("scatter", 2, "s", False, "journal"),
    "pm_linesymb": ("linesymb", 2, "y", False, "journal"),
    "pm_doubley": ("doubley", 1, "l", True, "journal"),
    "pm_thesis_line": ("line", 2, "l", False, "thesis"),
    "pm_thesis_scatter": ("scatter", 2, "s", False, "thesis"),
    "pm_thesis_linesymb": ("linesymb", 2, "y", False, "thesis"),
    "pm_thesis_doubley": ("doubley", 1, "l", True, "thesis"),
}


def read(op, prop: str) -> float | None:  # type: ignore[no-untyped-def]
    try:
        return float(op.lt_float(prop))
    except Exception:
        return None


def style_layer(op, gp, layer_index: int, style: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    st = STYLES[style]
    gp.activate()
    op.lt_exec(f"page.active={layer_index + 1};")
    out = {}
    for cmd, prop, want in st.primary if layer_index == 0 else st.secondary:
        ok = op.lt_exec(cmd + ";")
        got = read(op, prop)
        out[prop] = {"set_ok": bool(ok), "read": got, "expected": want}
    if st.text:
        for obj, size in st.text:
            set_text_font(op, obj, size)
            out[f"{obj}.fsize"] = {"read": read(op, f"{obj}.fsize"), "expected": size}
    else:
        for txt in ("xb", "yl", "yr"):
            op.lt_exec(f"if(exist({txt})) {{{txt}.font=font(Arial);}};")
    if layer_index == 0:
        op.lt_exec("legend.background=0;")
        out["legend.background"] = {"read": read(op, "legend.background"), "expected": 0}
    return out


def main() -> int:
    wanted = sys.argv[1:] or list(TEMPLATES)
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()
    report: dict[str, object] = {"templates": {}}
    before = origin_pids()
    import originpro as op

    op.set_show(False)
    owned = origin_pids() - before
    report["origin_version"] = op.lt_float("@V")
    try:
        op.new()
        wks = op.new_sheet()
        xs = [1.0 + 0.25 * i for i in range(13)]
        wks.from_list(0, xs, lname="X (SYNTHETIC)", axis="X")
        wks.from_list(1, [0.3 * (x - 1) for x in xs], lname="Y1")
        wks.from_list(2, [0.2 * (x - 1) ** 1.3 for x in xs], lname="Y2")
        wks.from_list(3, [0.05 + 0.01 * x for x in xs], lname="Y3")
        for tid in wanted:
            base, n, kind, right, style = TEMPLATES[tid]
            st = STYLES[style]
            gp = op.new_graph(template=base)
            gp.name = tid.replace("_", "")
            for k in range(n):
                gp[0].add_plot(wks, coly=1 + k, colx=0, type=kind)
            if right:
                gp[1].add_plot(wks, coly=3, colx=0, type=kind)
            entry: dict[str, object] = {"base": base, "style": style, "layers": {}}
            gp[0].lt_exec("legend -r;")  # before styling, so the legend's frame setting is saved
            for li in range(len(gp)):
                gp[li].rescale()
                entry["layers"][li] = style_layer(op, gp, li, style)  # type: ignore[index]
            ok = op.lt_exec(f'template_saveas pg:=[{gp.name}] template:="{tid}" filepath:="{OUT}";')
            path = OUT / f"{tid}.otpu"
            entry["saved"] = bool(ok) and path.exists()
            # reload from the saved file, read the style back, export a check image
            g2 = op.new_graph(template=str(path))
            entry["reloaded_layers"] = len(g2)
            back = {}
            for li in range(len(g2)):
                g2.activate()
                op.lt_exec(f"page.active={li + 1};")
                back[li] = {
                    prop: read(op, prop) for _, prop, _ in (st.primary if li == 0 else st.secondary)
                }
            back["legend_background"] = read(op, "legend.background")  # type: ignore[index]
            entry["reloaded_style"] = back
            for k in range(n):
                g2[0].add_plot(wks, coly=1 + k, colx=0, type=kind)
            if right and len(g2) > 1:
                g2[1].add_plot(wks, coly=3, colx=0, type=kind)
            for li in range(len(g2)):
                g2[li].rescale()
            g2[0].lt_exec("legend -r;")
            if st.bold_text:  # as the bridge does for real jobs: bold axis titles and legend
                g2[0].axis("x").title = "\\b(拉伸比 λ (SYNTHETIC))"
                g2[0].axis("y").title = "\\b(名义应力 σ (MPa))"
            entry["reloaded_label_font"] = read(op, "layer.x.label.font")  # 1 = preference default
            apply_text_style(op, g2, style)
            entry["reloaded_page_in"] = [
                read(op, "page.width/page.resx"),
                read(op, "page.height/page.resy"),
            ]
            png = OUT / f"{tid}_check.png"
            g2.save_fig(str(png), type="png", width=1200 if style == "journal" else 3216)
            entry["check_png"] = png.exists()
            report["templates"][tid] = entry  # type: ignore[index]
    finally:
        with contextlib.suppress(Exception):
            op.exit()
        time.sleep(3)
        for pid in owned & origin_pids():
            kill_pid(pid)
        report["owned_left"] = sorted(owned & origin_pids())
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
