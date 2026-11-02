"""Turn a PlotJob into a real Origin project with originpro. Runs only in the worker thread."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from polymech_bridge import templates
from polymech_bridge.schema import Axis, PlotJob, safe_text

_KIND = {"line": "l", "scatter": "s", "linesymbol": "y"}
# LabTalk symbol shape codes (set %C -k): 1 square, 2 circle, 3 up-triangle, 5 diamond
_SYMBOL = {"square": 1, "circle": 2, "triangle": 3, "diamond": 5}
# LabTalk dash codes (set %C -d): 0 solid, 1 dash, 2 dot, 3 dash-dot
_DASH = {"solid": 0, "dash": 1, "dot": 2, "dashdot": 3}


def _col_values(values: list[Any]) -> list[Any]:
    return [math.nan if v is None else v for v in values]


def build_project(
    op: Any, job: PlotJob, job_dir: Path, template_dir: Path = templates.DEFAULT_DIR
) -> dict[str, Any]:
    """Create books + graphs, save OPJU, export images. Returns a manifest of what was made."""
    op.new()
    for page in list(op.pages()):  # the default new-project template adds an empty Book1
        page.destroy()
    made: dict[str, Any] = {"books": [], "graphs": [], "exports": {}, "export_errors": {}}
    sheets: dict[tuple[str, int], Any] = {}
    for b in job.books:
        wb = op.new_book("w", lname=safe_text(b.long_name))
        wb.name = b.name
        for i, sh in enumerate(b.sheets):
            wks = wb[0] if i == 0 else wb.add_sheet(safe_text(sh.name, 31))
            wks.name = safe_text(sh.name, 31)
            wks.cols = len(sh.columns)
            for j, c in enumerate(sh.columns):
                wks.from_list(
                    j,
                    _col_values(list(c.values)),
                    lname=safe_text(c.long_name),
                    units=safe_text(c.units, 60),
                    comments=safe_text(c.comments, 500),
                    axis=c.designation,
                )
            sheets[(b.name, i)] = wks
        made["books"].append(
            {"name": wb.name, "long_name": b.long_name, "sheets": [s.name for s in b.sheets]}
        )

    for g in job.graphs:
        tpl = templates.resolve(g.template, template_dir)
        if tpl.warning:
            made.setdefault("template_warnings", []).append(tpl.warning)
        gp = op.new_graph(template=tpl.template, lname=safe_text(g.long_name))
        gp.name = g.name
        layers = {"y": gp[0]}
        if g.y2 is not None:
            layers["y2"] = gp[1] if tpl.base == "doubley" else gp.add_layer(1)
        for p in g.plots:
            layer = layers[p.axis]
            plot = layer.add_plot(
                sheets[(p.book, p.sheet)],
                coly=p.y,
                colx=p.x,
                type=_KIND[p.kind],
                colyerr=p.yerr if p.yerr is not None else -1,
            )
            if plot is None:
                raise RuntimeError(f"Origin 未能为 {p.book} 添加曲线")
            plot.color = p.color
            plot.set_cmd(f"-w {round(p.line_width_pt * 500)}")  # LabTalk: 1/500 pt units
            if p.kind != "scatter":
                plot.set_cmd(f"-d {_DASH[p.line_style]}")
            if p.kind != "line" and p.symbol != "none":
                plot.symbol_kind = _SYMBOL[p.symbol]
                plot.symbol_size = p.symbol_size
                plot.symbol_interior = 1 if p.symbol_filled else 2
        bold = templates.STYLES[tpl.style].bold_text
        for key, layer in layers.items():
            layer.rescale()
            _axis(layer, "x", g.x, bold)
            _axis(layer, "y", g.y if key == "y" else g.y2, bold)  # type: ignore[arg-type]
            layer.lt_exec("legend -r" if g.legend else "label -r legend")
        if tpl.mode == "programmatic":
            templates.apply_style(op, gp, tpl.style)
        if g.legend:
            templates.apply_text_style(op, gp, tpl.style)
        made["graphs"].append(
            {
                "name": gp.name,
                "long_name": g.long_name,
                "template": g.template,
                "template_mode": tpl.mode,
                "style": tpl.style,
                "n_plots": len(g.plots),
            }
        )
        for fmt in job.exports:
            target = job_dir / f"{job.file_stem}_{g.name}.{fmt}"
            try:
                out = gp.save_fig(
                    str(target), type=fmt, width=job.image_width_px if fmt == "png" else 0
                )
                if out and target.exists() and target.stat().st_size > 0:
                    made["exports"].setdefault(fmt, []).append(target.name)
                else:
                    made["export_errors"][f"{g.name}.{fmt}"] = (
                        "Origin 未生成文件（该版本可能不支持此格式）"
                    )
            except Exception as e:  # recorded, not swallowed: shown in the job result
                made["export_errors"][f"{g.name}.{fmt}"] = str(e)

    # the first graph is the active window when the project is opened (the figure in front;
    # workbooks stay open behind it)
    first = next((p for p in op.pages("g") if job.graphs and p.name == job.graphs[0].name), None)
    if first is not None:
        first.activate()
    opju = job_dir / f"{job.file_stem}.opju"
    if not op.save(str(opju)) or not opju.exists():
        raise RuntimeError("Origin 保存工程失败")
    made["opju"] = opju.name
    return made


def _axis(layer: Any, which: str, spec: Axis, bold: bool = False) -> None:
    ax = layer.axis(which)
    title = safe_text(spec.title)
    ax.title = f"\\b({title})" if bold and title else title
    ax.scale = spec.scale
    if spec.min is not None or spec.max is not None:
        (layer.set_xlim if which == "x" else layer.set_ylim)(spec.min, spec.max)


def verify_project(op: Any, job: PlotJob, opju: Path) -> dict[str, Any]:
    """Reopen the saved OPJU (read-only) and check books, row counts and graphs."""
    op.new()
    report: dict[str, Any] = {"opened": bool(op.open(file=str(opju), readonly=True))}
    if not report["opened"]:
        report["passed"] = False
        return report
    books = {p.name: p for p in op.pages("w")}
    graphs = {p.name: p for p in op.pages("g")}
    checks = []
    for b in job.books:
        wb = books.get(b.name)
        for i, sh in enumerate(b.sheets):
            ok = False
            rows = None
            if wb is not None and i < len(list(wb)):
                wks = wb[i]
                first = wks.to_list(0)
                rows = len(first)
                ok = rows == len(sh.columns[0].values) and wks.cols == len(sh.columns)
            checks.append(
                {
                    "book": b.name,
                    "sheet": sh.name,
                    "rows": rows,
                    "expected_rows": len(sh.columns[0].values),
                    "ok": ok,
                }
            )
    for g in job.graphs:
        gp = graphs.get(g.name)
        n = sum(len(layer.plot_list()) for layer in gp) if gp is not None else 0
        checks.append(
            {"graph": g.name, "plots": n, "expected_plots": len(g.plots), "ok": n == len(g.plots)}
        )
    report["checks"] = checks
    report["passed"] = all(c["ok"] for c in checks)
    op.new()
    return report


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
