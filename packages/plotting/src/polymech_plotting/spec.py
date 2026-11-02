"""Serializable PlotSpec (SPEC §5.2): one description drives Plotly preview, Matplotlib export
and Origin plotting. Series values are SI; axes carry the display unit and the SI→display
conversion so every renderer shows the same numbers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SPEC_VERSION = "1.0"

# Okabe–Ito palette: colour-blind safe, journal friendly.
OKABE_ITO = ["#000000", "#E69F00", "#56B4E9", "#009E73", "#0072B2", "#D55E00", "#CC79A7", "#F0E442"]

# Default style measured from the user's thesis figures (Origin, 300 dpi; DECISIONS 2026-10-27):
# a red–blue diverging set whose choice depends on how many series a panel has.
THESIS_BLUE, THESIS_RED = "#317CB7", "#DC6D57"
THESIS_NAVY, THESIS_LIGHT_BLUE, THESIS_PEACH, THESIS_DARK_RED = (
    "#104680",
    "#6DADD1",
    "#F6B293",
    "#B72230",
)
THESIS_PALETTE = [
    THESIS_NAVY,
    THESIS_LIGHT_BLUE,
    THESIS_PEACH,
    THESIS_DARK_RED,
    THESIS_BLUE,
    THESIS_RED,
]
THESIS_PALETTE_BY_COUNT = {
    1: [THESIS_BLUE],
    2: [THESIS_BLUE, THESIS_RED],
    3: [THESIS_NAVY, THESIS_LIGHT_BLUE, THESIS_RED],
    4: [THESIS_NAVY, THESIS_LIGHT_BLUE, THESIS_PEACH, THESIS_DARK_RED],
}

# SI unit → {display unit: (factor, offset)}: display = value * factor + offset
DISPLAY_UNITS: dict[str, dict[str, tuple[float, float]]] = {
    "Pa": {"Pa": (1, 0), "kPa": (1e-3, 0), "MPa": (1e-6, 0), "GPa": (1e-9, 0)},
    "J/m^3": {"J/m³": (1, 0), "kJ/m³": (1e-3, 0), "MJ/m³": (1e-6, 0)},
    "J/m^2": {"J/m²": (1, 0), "kJ/m²": (1e-3, 0)},
    "m": {"m": (1, 0), "mm": (1e3, 0), "μm": (1e6, 0)},
    "m/cycle": {"m/cycle": (1, 0), "nm/cycle": (1e9, 0), "μm/cycle": (1e6, 0)},
    "N": {"N": (1, 0), "mN": (1e3, 0), "kN": (1e-3, 0)},
    "N/m": {"N/m": (1, 0), "kN/m": (1e-3, 0)},
    "K": {"K": (1, 0), "°C": (1, -273.15)},
    "s": {"s": (1, 0), "min": (1 / 60, 0), "h": (1 / 3600, 0)},
    "Hz": {"Hz": (1, 0)},
    "1": {"": (1, 0), "%": (100, 0)},
    "cycle": {"": (1, 0)},
}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AxisSpec(Model):
    label: str
    si_unit: str = "1"
    unit: str = ""  # display unit; must be listed in DISPLAY_UNITS[si_unit]
    scale: Literal["linear", "log"] = "linear"
    min: float | None = None  # in display units
    max: float | None = None

    @model_validator(mode="after")
    def _known_unit(self) -> AxisSpec:
        units = DISPLAY_UNITS.get(self.si_unit)
        if units is None or self.unit not in units:
            raise ValueError(f"unsupported display unit {self.unit!r} for {self.si_unit!r}")
        return self

    @property
    def factor_offset(self) -> tuple[float, float]:
        return DISPLAY_UNITS[self.si_unit][self.unit]

    @property
    def title(self) -> str:
        return f"{self.label} ({self.unit})" if self.unit else self.label


class SeriesSource(Model):
    """Where series values come from: a stored analysis run's curve columns, or inline values."""

    run_id: int | None = None
    x_key: str | None = None
    y_key: str | None = None
    y_err_key: str | None = None
    x: list[float] | None = None
    y: list[float] | None = None
    y_err: list[float] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> SeriesSource:
        inline = self.x is not None and self.y is not None
        stored = self.run_id is not None and self.x_key is not None and self.y_key is not None
        if inline == stored:
            raise ValueError("series needs either inline x/y or run_id + x_key + y_key")
        if inline and self.x is not None and self.y is not None and len(self.x) != len(self.y):
            raise ValueError("x and y must have the same length")
        return self


class SeriesSpec(Model):
    name: str
    source: SeriesSource
    kind: Literal["line", "scatter", "line+markers"] = "line"
    color: str | None = None  # None → palette by position
    line_width: float = 3.0  # pt
    line_style: Literal["solid", "dash", "dot", "dashdot"] = "solid"
    marker: Literal["circle", "square", "triangle", "diamond", "cross", "none"] = "none"
    marker_size: float = 4.0  # pt
    marker_filled: bool = True
    y_axis: Literal["y", "y2"] = "y"
    error_bars: bool = False
    visible: bool = True
    note: str = ""  # e.g. "below detection limit (upper bound)"


class LegendSpec(Model):
    show: bool = True
    position: Literal[
        "best", "upper left", "upper right", "lower left", "lower right", "outside"
    ] = "best"
    frame: bool = False


class AnnotationSpec(Model):
    text: str
    x: float  # display units
    y: float
    kind: Literal["text", "vline", "hline", "span"] = "text"
    x2: float | None = None  # for span


class PanelSpec(Model):
    id: str = "a"
    template_id: str = ""  # template the panel was built from ("restore defaults" per panel)
    title: str = ""
    x: AxisSpec
    y: AxisSpec
    y2: AxisSpec | None = None
    series: list[SeriesSpec] = Field(default_factory=list)
    legend: LegendSpec = Field(default_factory=LegendSpec)
    annotations: list[AnnotationSpec] = Field(default_factory=list)


class LayoutSpec(Model):
    rows: int = 1
    cols: int = 1
    width_mm: float = 272.288  # Origin page of the thesis figures (3216 × 2280 px at 300 dpi)
    height_mm: float = 193.04
    dpi: int = 300
    panel_labels: bool = True  # (a), (b)… for multi-panel figures


class StyleSpec(Model):
    font_family: str = "Times New Roman"
    font_weight: Literal["normal", "bold"] = "bold"
    font_size_pt: float = 20.0  # tick labels and annotations
    axis_title_size_pt: float = 28.0
    legend_size_pt: float = 22.0
    tick_direction: Literal["in", "out"] = "out"
    mirror_ticks: bool = True  # ticks on all four sides, closed frame
    mirror_tick_direction: Literal["in", "out"] = "in"  # top/right ticks (Origin: into the frame)
    axis_line_width: float = 2.2
    major_tick_length_pt: float = 9.0
    minor_tick_length_pt: float = 4.0
    minor_ticks: bool = True
    palette: list[str] = Field(default_factory=lambda: list(THESIS_PALETTE))
    palette_by_count: dict[int, list[str]] = Field(
        default_factory=lambda: {k: list(v) for k, v in THESIS_PALETTE_BY_COUNT.items()}
    )
    """Colours by number of series in the panel; falls back to `palette` when absent."""

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: object) -> object:
        """Styles saved before these fields existed keep their look (single font size, regular
        weight, Matplotlib tick lengths, no minor ticks, palette by position)."""
        if isinstance(data, dict) and "font_size_pt" in data and "axis_title_size_pt" not in data:
            size = data["font_size_pt"]
            return {
                "font_weight": "normal",
                "mirror_tick_direction": data.get("tick_direction", "in"),
                "axis_title_size_pt": size,
                "legend_size_pt": size,
                "major_tick_length_pt": 3.5,
                "minor_tick_length_pt": 2.0,
                "minor_ticks": False,
                "palette_by_count": {},
                **data,
            }
        return data


class PlotSpec(Model):
    spec_version: str = SPEC_VERSION
    template_id: str
    template_version: str
    title: str = ""
    panels: list[PanelSpec]
    layout: LayoutSpec = Field(default_factory=LayoutSpec)
    style: StyleSpec = Field(default_factory=StyleSpec)

    @model_validator(mode="after")
    def _fits_layout(self) -> PlotSpec:
        if len(self.panels) > self.layout.rows * self.layout.cols:
            raise ValueError("more panels than layout cells")
        return self

    def color_of(self, index: int, series: SeriesSpec, n_series: int = 0) -> str:
        palette = self.style.palette_by_count.get(n_series) or self.style.palette
        return series.color or palette[index % len(palette)]
