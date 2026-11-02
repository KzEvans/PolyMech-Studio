"""Static figure export with Matplotlib (PNG / SVG / PDF). No animation, no transparency
effects; closed frame with ticks on all four sides (SPEC §5.1; default style per DECISIONS
2026-10-27)."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any, Literal

import matplotlib
import matplotlib.font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import AutoMinorLocator
from numpy.typing import NDArray

from polymech_plotting.spec import AxisSpec, PlotSpec, SeriesSource

Arrays = tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64] | None]
Resolver = Callable[[SeriesSource], Arrays]
Format = Literal["png", "svg", "pdf"]

# Per-glyph fallback so Chinese axis labels render next to Latin text; only installed fonts
# are listed (macOS: PingFang/Hiragino/Heiti; Windows: Microsoft YaHei; Linux: Noto CJK).
_CJK_CANDIDATES = [
    "PingFang SC",
    "Heiti SC",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Arial Unicode MS",
]
_INSTALLED = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
CJK_FALLBACK = [f for f in _CJK_CANDIDATES if f in _INSTALLED] + ["DejaVu Sans"]
_MARKERS = {"circle": "o", "square": "s", "triangle": "^", "diamond": "D", "cross": "x", "none": ""}
_LINES = {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-."}


def inline_resolver(src: SeriesSource) -> Arrays:
    if src.x is None or src.y is None:
        raise ValueError("series has no inline data; a resolver for stored runs is required")
    err = np.asarray(src.y_err, dtype=float) if src.y_err is not None else None
    return np.asarray(src.x, dtype=float), np.asarray(src.y, dtype=float), err


def to_display(values: NDArray[np.float64], axis: AxisSpec) -> NDArray[np.float64]:
    f, o = axis.factor_offset
    return values * f + o


def _mirror_axis(ax: Any, which: Literal["x", "y"], direction: str) -> None:
    """Top/right ticks pointing the other way than bottom/left: an unlabelled twin axis with the
    same scale, ticks and limits (Matplotlib sets one direction per axis)."""
    twin = ax.twiny() if which == "x" else ax.twinx()
    lim = getattr(ax, f"get_{which}lim")()
    getattr(twin, f"set_{which}scale")(getattr(ax, f"get_{which}scale")())
    getattr(twin, f"set_{which}ticks")(getattr(ax, f"get_{which}ticks")())
    getattr(twin, f"set_{which}ticks")(getattr(ax, f"get_{which}ticks")(minor=True), minor=True)
    getattr(twin, f"set_{which}lim")(lim)
    twin.tick_params(
        axis=which,
        which="both",
        direction=direction,
        labelleft=False,
        labelright=False,
        labeltop=False,
        labelbottom=False,
    )


def render(spec: PlotSpec, fmt: Format = "png", resolver: Resolver = inline_resolver) -> bytes:
    st, lay = spec.style, spec.layout
    same_dir = st.mirror_tick_direction == st.tick_direction
    rc: dict[Any, Any] = {
        "font.family": [
            f for f in (st.font_family, *CJK_FALLBACK) if f in _INSTALLED or f == "DejaVu Sans"
        ],
        "font.size": st.font_size_pt,
        "font.weight": st.font_weight,
        "axes.labelsize": st.axis_title_size_pt,
        "axes.labelweight": st.font_weight,
        "axes.titleweight": st.font_weight,
        "legend.fontsize": st.legend_size_pt,
        "axes.linewidth": st.axis_line_width,
        "axes.unicode_minus": False,
        "xtick.direction": st.tick_direction,
        "ytick.direction": st.tick_direction,
        "xtick.top": st.mirror_ticks and same_dir,
        "ytick.right": st.mirror_ticks and same_dir,
        "xtick.major.width": st.axis_line_width,
        "ytick.major.width": st.axis_line_width,
        "xtick.minor.width": st.axis_line_width,
        "ytick.minor.width": st.axis_line_width,
        "xtick.major.size": st.major_tick_length_pt,
        "ytick.major.size": st.major_tick_length_pt,
        "xtick.minor.size": st.minor_tick_length_pt,
        "ytick.minor.size": st.minor_tick_length_pt,
        "xtick.minor.visible": st.minor_ticks,
        "ytick.minor.visible": st.minor_ticks,
        "svg.fonttype": "none",  # keep text editable in SVG
        "pdf.fonttype": 42,  # TrueType: editable in Illustrator
    }
    with plt.rc_context(rc):
        fig, axes = plt.subplots(
            lay.rows, lay.cols, figsize=(lay.width_mm / 25.4, lay.height_mm / 25.4), squeeze=False
        )
        for k, panel in enumerate(spec.panels):
            ax = axes[k // lay.cols][k % lay.cols]
            ax2 = ax.twinx() if panel.y2 is not None else None
            if ax2 is not None:
                ax2.tick_params(direction=st.tick_direction)
                ax.tick_params(right=False)
            n_series = sum(s.visible for s in panel.series)
            for i, s in enumerate(panel.series):
                if not s.visible:
                    continue
                x, y, err = resolver(s.source)
                target, yaxis = (
                    (ax2, panel.y2)
                    if (s.y_axis == "y2" and ax2 is not None and panel.y2)
                    else (ax, panel.y)
                )
                xd, yd = to_display(x, panel.x), to_display(y, yaxis)
                color = spec.color_of(i, s, n_series)
                ls = _LINES[s.line_style] if s.kind != "scatter" else ""
                mk = _MARKERS[s.marker] if s.kind != "line" else ""
                face = color if s.marker_filled else "none"
                if s.error_bars and err is not None:
                    ed = err * yaxis.factor_offset[0]
                    target.errorbar(
                        xd,
                        yd,
                        yerr=ed,
                        color=color,
                        ls=ls or "none",
                        marker=mk or None,
                        ms=s.marker_size,
                        mfc=face,
                        lw=s.line_width,
                        capsize=2,
                        label=s.name,
                    )
                else:
                    target.plot(
                        xd,
                        yd,
                        color=color,
                        ls=ls or "none",
                        marker=mk or None,
                        ms=s.marker_size,
                        mfc=face,
                        lw=s.line_width,
                        label=s.name,
                    )
            for axis_spec, a, setter in (
                (panel.x, ax, "x"),
                (panel.y, ax, "y"),
                (panel.y2, ax2, "y"),
            ):
                if axis_spec is None or a is None:
                    continue
                getattr(a, f"set_{setter}label")(axis_spec.title)
                getattr(a, f"set_{setter}scale")(axis_spec.scale)
                if st.minor_ticks and axis_spec.scale == "linear":  # one minor between majors
                    getattr(a, f"{setter}axis").set_minor_locator(AutoMinorLocator(2))
                if axis_spec.min is not None or axis_spec.max is not None:
                    getattr(a, f"set_{setter}lim")(axis_spec.min, axis_spec.max)
            if st.mirror_ticks and not same_dir:
                _mirror_axis(ax, "x", st.mirror_tick_direction)
                if ax2 is None:
                    _mirror_axis(ax, "y", st.mirror_tick_direction)
            for ann in panel.annotations:
                if ann.kind == "vline":
                    ax.axvline(ann.x, color="0.4", lw=0.6, ls="--")
                elif ann.kind == "hline":
                    ax.axhline(ann.y, color="0.4", lw=0.6, ls="--")
                elif ann.kind == "span" and ann.x2 is not None:
                    ax.axvspan(ann.x, ann.x2, color="0.85", lw=0)
                if ann.text:
                    ax.annotate(ann.text, (ann.x, ann.y), fontsize=st.font_size_pt - 1)
            if panel.legend.show and any(s.visible for s in panel.series):
                handles, labels = ax.get_legend_handles_labels()
                if ax2 is not None:
                    h2, l2 = ax2.get_legend_handles_labels()
                    handles, labels = handles + h2, labels + l2
                loc = "upper left" if panel.legend.position == "outside" else panel.legend.position
                kw = {"bbox_to_anchor": (1.02, 1)} if panel.legend.position == "outside" else {}
                ax.legend(handles, labels, loc=loc, frameon=panel.legend.frame, **kw)
            if panel.title:
                ax.set_title(panel.title)
            if lay.panel_labels and len(spec.panels) > 1:
                ax.text(
                    -0.18, 1.02, f"({chr(ord('a') + k)})", transform=ax.transAxes, fontweight="bold"
                )
        for k in range(len(spec.panels), lay.rows * lay.cols):
            axes[k // lay.cols][k % lay.cols].set_visible(False)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=lay.dpi if fmt == "png" else None)
        plt.close(fig)
    return buf.getvalue()
