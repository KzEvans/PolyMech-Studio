"""Origin graph template registry (SPEC §6.5).

Mode A: a registered `.otpu` whose file exists and whose SHA-256 matches the registry.
Mode B: when the file is missing or altered, the built-in base template plus the same journal
style applied programmatically — and the job manifest says so ("Origin 模板丢失").
Requests name templates by id only; file paths never come from a request.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUILTIN = ("line", "scatter", "linesymb", "doubley")
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "templates"

# A style is a list of (LabTalk assignment, property, expected) per layer; expected None =
# applied but not compared (font ids differ between machines). Property names are from the
# LabTalk reference (Layer.Axis, Layer.Axis.Label, graphic objects) and were checked in
# Origin 2025b (bridge/windows-origin/probe_thesis_style.py).
Check = tuple[str, str, float | None]

# Journal style (first layer); secondary layers (right axis of a double-Y graph) only get
# inward ticks so Origin keeps them right.
STYLE_PRIMARY: list[Check] = [
    ("layer.x.showAxes=3", "layer.x.showAxes", 3),
    ("layer.y.showAxes=3", "layer.y.showAxes", 3),
    ("layer.x.showLabels=1", "layer.x.showLabels", 1),
    ("layer.y.showLabels=1", "layer.y.showLabels", 1),
    ("layer.x.ticks=5", "layer.x.ticks", 5),
    ("layer.y.ticks=5", "layer.y.ticks", 5),
]
STYLE_SECONDARY: list[Check] = [("layer.y.ticks=5", "layer.y.ticks", 5)]


def _axis_lines(axes: tuple[str, ...]) -> list[Check]:
    out: list[Check] = []
    for a in axes:
        out += [
            (f"layer.{a}.thickness=2.2", f"layer.{a}.thickness", 2.2),
            (f"layer.{a}.tickthickness=2.2", f"layer.{a}.tickthickness", 2.2),
            (f"layer.{a}.mtickthickness=2.2", f"layer.{a}.mtickthickness", 2.2),
            (f"layer.{a}.ticklength=9", f"layer.{a}.ticklength", 9),
            (f"layer.{a}.mticklength=4", f"layer.{a}.mticklength", 4),
        ]
    return out


def _tick_labels(axes: tuple[str, ...]) -> list[Check]:
    out: list[Check] = []
    for a in axes:
        out += [
            (f"layer.{a}.minorTicks=1", f"layer.{a}.minorTicks", 1),
            (f"layer.{a}.label.font=font(Times New Roman)", f"layer.{a}.label.font", None),
            (f"layer.{a}.label.pt=20", f"layer.{a}.label.pt", 20),
            (f"layer.{a}.label.bold=1", f"layer.{a}.label.bold", 1),
        ]
    return out


# Thesis style, measured from the user's Origin figures (DECISIONS 2026-10-27): Times New Roman
# bold, tick labels 20 pt, axis titles 28 pt, legend 22 pt, axes 2.2 pt, ticks out on
# bottom/left (major 2 + minor 8) and in on top/right (1 + 4), major 9 pt, minor 4 pt, one
# minor tick between majors. Page: Origin's default 10.72 × 7.6 in, as in those figures.
THESIS_PRIMARY: list[Check] = [
    ("layer.x.showAxes=3", "layer.x.showAxes", 3),
    ("layer.y.showAxes=3", "layer.y.showAxes", 3),
    ("layer.x.showLabels=1", "layer.x.showLabels", 1),
    ("layer.y.showLabels=1", "layer.y.showLabels", 1),
    ("layer.x.ticks=10", "layer.x.ticks", 10),
    ("layer.y.ticks=10", "layer.y.ticks", 10),
    ("layer.x2.ticks=5", "layer.x2.ticks", 5),
    ("layer.y2.ticks=5", "layer.y2.ticks", 5),
    *_axis_lines(("x", "y", "x2", "y2")),
    *_tick_labels(("x", "y")),
    # black axes and labels (Origin colours a double-Y graph's axes like their plots)
    *[(f"layer.{a}.color=1", f"layer.{a}.color", 1) for a in ("x", "y", "x2", "y2")],
    *[(f"layer.{a}.label.color=1", f"layer.{a}.label.color", 1) for a in ("x", "y")],
]
# right axis of a double-Y graph: a real labelled axis, so ticks out like the left one, and
# black like the rest (Origin colours it like its plot). On the right side it is addressed
# as y2 ("right/top"); y is set as well so either placement gets the style.
THESIS_SECONDARY: list[Check] = [
    ("layer.y.ticks=10", "layer.y.ticks", 10),
    ("layer.y2.ticks=10", "layer.y2.ticks", 10),
    *_axis_lines(("y", "y2")),
    *_tick_labels(("y", "y2")),
    ("layer.y.color=1", "layer.y.color", 1),
    ("layer.y2.color=1", "layer.y2.color", 1),
    ("layer.y.label.color=1", "layer.y.label.color", 1),
    ("layer.y2.label.color=1", "layer.y2.label.color", 1),
]
# text objects (axis titles, legend) and their size in pt; set without a guard — LabTalk's
# exist() does not see graph text objects, so a guarded assignment is silently skipped. A
# layer without the object (no yr on a single-axis graph) just reports an error.
THESIS_TEXT = [
    ("xb", 28), ("yl", 28), ("yr", 28), ("legend", 22),
]  # fmt: skip


@dataclass(frozen=True)
class Style:
    primary: list[Check]
    secondary: list[Check]
    text: list[tuple[str, float]]
    bold_text: bool  # axis titles and legend entries wrapped in \b(...)


STYLES = {
    "journal": Style(STYLE_PRIMARY, STYLE_SECONDARY, [], False),
    "thesis": Style(THESIS_PRIMARY, THESIS_SECONDARY, THESIS_TEXT, True),
}


@dataclass(frozen=True)
class Resolved:
    requested: str
    mode: str  # native | programmatic | builtin
    template: str  # path for native, built-in name otherwise
    base: str
    warning: str = ""
    style: str = "journal"  # key of STYLES


def load_registry(directory: Path = DEFAULT_DIR) -> dict[str, dict[str, Any]]:
    f = directory / "registry.json"
    if not f.exists():
        return {}
    data = json.loads(f.read_text(encoding="utf-8"))
    return {t["id"]: t for t in data.get("templates", [])}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(template_id: str, directory: Path = DEFAULT_DIR) -> Resolved:
    reg = load_registry(directory)
    entry = reg.get(template_id)
    if entry is not None:
        path = directory / entry["file"]
        base = entry["base_builtin"]
        style = entry.get("style_id", "journal")
        if not path.is_file():
            return Resolved(
                template_id,
                "programmatic",
                base,
                base,
                f"模板文件 {entry['file']} 缺失，已改用内置模板 {base} 并以程序设置样式",
                style,
            )
        if _sha256(path) != entry["sha256"]:
            return Resolved(
                template_id,
                "programmatic",
                base,
                base,
                f"模板文件 {entry['file']} 与注册表哈希不一致（可能被修改），已改用内置模板 {base} 并以程序设置样式",
                style,
            )
        return Resolved(template_id, "native", str(path), base, "", style)
    if template_id in BUILTIN:
        return Resolved(template_id, "builtin", template_id, template_id)
    return Resolved(
        template_id,
        "programmatic",
        "line",
        "line",
        f"未注册的模板 {template_id}，已改用内置 line 模板并以程序设置样式",
    )


def available(directory: Path = DEFAULT_DIR) -> list[dict[str, Any]]:
    out = []
    for tid, e in load_registry(directory).items():
        r = resolve(tid, directory)
        out.append(
            {
                "id": tid,
                "kind": "otpu",
                "name": e["name"],
                "version": e["version"],
                "chart_types": e["chart_types"],
                "required_columns": e["required_columns"],
                "min_origin_version": e["min_origin_version"],
                "available": r.mode == "native",
                "problem": r.warning,
            }
        )
    out += [{"id": b, "kind": "builtin", "available": True} for b in BUILTIN]
    return out


def _read(op: Any, prop: str) -> float | None:
    try:
        return float(op.lt_float(prop))
    except Exception:
        return None


def set_text_font(op: Any, obj: str, size: float) -> None:
    op.lt_exec(f"{obj}.font=font(Times New Roman);")
    op.lt_exec(f"{obj}.fsize={size};")


def apply_style(op: Any, gp: Any, style: str = "journal") -> dict[str, float | None]:
    """Apply a style to every layer of a graph page (template generation, and mode B when a
    template file is missing); returns the read-back values."""
    st = STYLES[style]
    got: dict[str, float | None] = {}
    for li in range(len(gp)):
        gp.activate()
        op.lt_exec(f"page.active={li + 1};")
        for cmd, prop, _ in st.primary if li == 0 else st.secondary:
            op.lt_exec(cmd + ";")
            got[f"L{li}.{prop}"] = _read(op, prop)
        for obj, size in st.text:
            set_text_font(op, obj, size)
    op.lt_exec("page.active=1;")
    op.lt_exec("legend.background=0;")  # frameless legend, as in the .otpu templates
    got["legend.background"] = _read(op, "legend.background")
    return got


def apply_journal_style(op: Any, gp: Any) -> dict[str, float | None]:
    return apply_style(op, gp, "journal")


def apply_text_style(op: Any, gp: Any, style: str) -> None:
    """After the plots exist: font faces and sizes of tick labels, axis titles and legend on
    every layer, and bold legend entries for styles with bold text. Needed even with a native
    .otpu: Origin 2025b reloads template tick-label fonts as the preference default
    (label.font = 1, checked in make_templates.py), and `legend -r` rebuilds the legend."""
    st = STYLES[style]
    if not st.text:
        return
    for li in range(len(gp)):
        gp.activate()
        op.lt_exec(f"page.active={li + 1};")
        for cmd, _, _ in st.primary if li == 0 else st.secondary:
            if ".label.font=" in cmd:
                op.lt_exec(cmd + ";")
        for obj, size in st.text:
            set_text_font(op, obj, size)
    op.lt_exec("page.active=1;")
    op.lt_exec("legend.background=0;")
    if st.bold_text:
        try:
            text = str(op.get_lt_str("legend.text$"))
        except Exception:
            return
        lines = [ln for ln in text.replace("\r", "").split("\n") if ln.strip()]
        if lines and not all(ln.startswith("\\b(") for ln in lines):
            # %% keeps %(n) live (a single % is substituted on assignment and freezes the
            # entry); %(CRLF) is LabTalk's line break — both checked in probe_legend_bold.py
            bold = "%(CRLF)".join(f"\\b({ln.replace('%', '%%')})" for ln in lines)
            op.lt_exec(f'legend.text$="{bold}";')
