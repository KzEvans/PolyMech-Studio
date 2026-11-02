"""Plot-job schema. Jobs carry data and whitelisted style options only — never code,
shell commands or LabTalk (SPEC §6.8)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,119}$")
_SHORT = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,24}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
# Characters with meaning in LabTalk command lines / text escapes are removed from any text
# that ends up in a LabTalk statement (axis titles are set via `label -xb <text>`).
_LABTALK_UNSAFE = re.compile(r'[;"$%{}\\\r\n`]')


def safe_text(s: str, max_len: int = 200) -> str:
    return _LABTALK_UNSAFE.sub("", s)[:max_len].strip()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Column(Model):
    long_name: str = Field(max_length=200)
    units: str = Field(default="", max_length=60)
    comments: str = Field(default="", max_length=500)
    designation: Literal["X", "Y", "E", "L"] = "Y"
    values: list[float | None] | list[str]


class Sheet(Model):
    name: str = Field(min_length=1, max_length=31)
    columns: list[Column] = Field(min_length=1, max_length=200)


class Book(Model):
    name: str  # Origin short name: letter + alphanumerics
    long_name: str = Field(max_length=200)
    sheets: list[Sheet] = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def _short(cls, v: str) -> str:
        if not _SHORT.match(v):
            raise ValueError("book short name must be a letter followed by letters/digits (≤25)")
        return v


class PlotRef(Model):
    book: str
    sheet: int = 0
    x: int
    y: int
    yerr: int | None = None
    kind: Literal["line", "scatter", "linesymbol"] = "line"
    color: str = "#000000"
    line_width_pt: float = Field(default=1.0, gt=0, le=10)
    line_style: Literal["solid", "dash", "dot", "dashdot"] = "solid"
    symbol: Literal["square", "circle", "triangle", "diamond", "none"] = "none"
    symbol_size: float = Field(default=6, gt=0, le=50)
    symbol_filled: bool = True
    axis: Literal["y", "y2"] = "y"

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not _COLOR.match(v):
            raise ValueError("color must be #rrggbb")
        return v


class Axis(Model):
    title: str = Field(max_length=200)
    scale: Literal["linear", "log10"] = "linear"
    min: float | None = None
    max: float | None = None


class Graph(Model):
    name: str
    long_name: str = Field(max_length=200)
    template: str = Field(default="line", pattern=r"^[a-z][a-z0-9_]{0,39}$")
    """Built-in Origin template or a registered .otpu id — never a path."""
    x: Axis
    y: Axis
    y2: Axis | None = None
    plots: list[PlotRef] = Field(min_length=1, max_length=50)
    legend: bool = True

    @field_validator("name")
    @classmethod
    def _short(cls, v: str) -> str:
        if not _SHORT.match(v):
            raise ValueError("graph short name must be a letter followed by letters/digits (≤25)")
        return v


class PlotJob(Model):
    file_stem: str
    books: list[Book] = Field(min_length=1, max_length=20)
    graphs: list[Graph] = Field(default_factory=list, max_length=10)
    exports: list[Literal["png", "pdf", "svg"]] = Field(default_factory=lambda: ["png"])
    image_width_px: int = Field(default=1600, ge=200, le=8000)
    verify: bool = True

    @field_validator("file_stem")
    @classmethod
    def _stem(cls, v: str) -> str:
        if not _STEM.match(v) or ".." in v:
            raise ValueError("file_stem may contain only letters, digits, '_', '-', '.'")
        return v

    @model_validator(mode="after")
    def _refs(self) -> PlotJob:
        books = {b.name: b for b in self.books}
        if len(books) != len(self.books):
            raise ValueError("duplicate book names")
        for g in self.graphs:
            for p in g.plots:
                b = books.get(p.book)
                if b is None or p.sheet >= len(b.sheets):
                    raise ValueError(f"plot refers to unknown book/sheet {p.book}[{p.sheet}]")
                n = len(b.sheets[p.sheet].columns)
                for c in (p.x, p.y, p.yerr):
                    if c is not None and not 0 <= c < n:
                        raise ValueError(f"column index {c} out of range in {p.book}")
                if p.axis == "y2" and g.y2 is None:
                    raise ValueError("plot on y2 needs a y2 axis")
        return self
