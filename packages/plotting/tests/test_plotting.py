import io
import json

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from polymech_plotting.render import render, to_display
from polymech_plotting.spec import (
    OKABE_ITO,
    THESIS_PALETTE,
    AxisSpec,
    PlotSpec,
    SeriesSource,
    StyleSpec,
)
from polymech_plotting.templates import TEMPLATES, make_spec, run_series

LAM = np.linspace(1, 4, 50)
SIG = 0.4e6 * (LAM - LAM**-2)


def inline(x, y, err=None):
    return SeriesSource(x=list(x), y=list(y), y_err=None if err is None else list(err))


def test_all_templates_exist_and_build() -> None:
    assert len(TEMPLATES) == 17  # 14 from SPEC §5.2 + 3 DMA (SPEC §4.5)
    for tid in TEMPLATES:
        spec = make_spec(tid, [("A", inline(LAM, SIG))])
        assert spec.template_id == tid
        assert spec.panels[0].series[0].name == "A"


def test_spec_json_roundtrip() -> None:
    spec = make_spec(
        "dma_storage_tan_delta", [("E'", inline(LAM, SIG))], y2_series=[("tan", inline(LAM, LAM))]
    )
    again = PlotSpec.model_validate(json.loads(spec.model_dump_json()))
    assert again == spec
    assert again.panels[0].series[1].y_axis == "y2"


def test_display_conversion() -> None:
    mpa = AxisSpec(label="σ", si_unit="Pa", unit="MPa")
    np.testing.assert_allclose(to_display(np.array([2e6]), mpa), [2.0])
    c = AxisSpec(label="T", si_unit="K", unit="°C")
    np.testing.assert_allclose(to_display(np.array([273.15]), c), [0.0], atol=1e-12)
    assert mpa.title == "σ (MPa)"


@pytest.mark.parametrize(
    "bad",
    [
        lambda: AxisSpec(label="σ", si_unit="Pa", unit="kJ/m²"),
        lambda: SeriesSource(x=[1.0], y=[1.0, 2.0]),
        lambda: SeriesSource(),
        lambda: SeriesSource(run_id=1, x_key="a", y_key="b", x=[1.0], y=[1.0]),
    ],
)
def test_invalid_specs_rejected(bad) -> None:
    with pytest.raises(ValidationError):
        bad()


def test_run_series_uses_template_keys() -> None:
    src = run_series("nominal_stress_stretch", 7, "S1")
    assert (src.run_id, src.x_key, src.y_key) == (7, "stretch", "nominal_stress_pa")


@pytest.mark.parametrize("fmt", ["png", "svg", "pdf"])
def test_render_formats(fmt: str) -> None:
    spec = make_spec(
        "nominal_stress_stretch", [("样品 A", inline(LAM, SIG)), ("样品 B", inline(LAM, 1.2 * SIG))]
    )
    out = render(spec, fmt)  # type: ignore[arg-type]
    magic = {"png": b"\x89PNG", "svg": b"<?xml", "pdf": b"%PDF"}[fmt]
    assert out.startswith(magic)
    if fmt == "svg":
        assert "样品 A".encode() in out  # text stays editable


def test_render_error_bars_log_axes_and_multipanel() -> None:
    spec = make_spec("modulus_vs_toughness", [("lit", inline([1e6, 3e6], [1e3, 5e3], [1e2, 4e2]))])
    spec.panels[0].series[0].error_bars = True
    p2 = spec.panels[0].model_copy(update={"id": "b"})
    spec = spec.model_copy(
        update={
            "panels": [spec.panels[0], p2],
            "layout": spec.layout.model_copy(update={"cols": 2, "width_mm": 170}),
        }
    )
    assert render(spec, "png").startswith(b"\x89PNG")


def test_default_colours_follow_series_count() -> None:
    """Default style is the thesis figures' palette, chosen by how many series a panel has."""
    expected = {
        1: ["#317CB7"],
        2: ["#317CB7", "#DC6D57"],
        3: ["#104680", "#6DADD1", "#DC6D57"],
        4: ["#104680", "#6DADD1", "#F6B293", "#B72230"],
        6: THESIS_PALETTE,
    }
    for n, colours in expected.items():
        spec = make_spec("nominal_stress_stretch", [(str(i), inline(LAM, SIG)) for i in range(n)])
        series = spec.panels[0].series
        assert [spec.color_of(i, s, n) for i, s in enumerate(series)] == colours
    series[0].color = "#123456"
    assert spec.color_of(0, series[0], 6) == "#123456"


def test_default_figure_matches_thesis_page() -> None:
    spec = make_spec("nominal_stress_stretch", [("A", inline(LAM, SIG)), ("B", inline(LAM, SIG))])
    st = spec.style
    assert (st.font_family, st.font_weight, st.tick_direction) == ("Times New Roman", "bold", "out")
    assert (st.font_size_pt, st.axis_title_size_pt, st.axis_line_width) == (20, 28, 2.2)
    assert spec.panels[0].series[0].line_width == 3.0
    img = Image.open(io.BytesIO(render(spec, "png")))
    assert img.size == (3216, 2280)  # same page as the Origin exports at 300 dpi


def test_style_saved_before_new_fields_keeps_its_look() -> None:
    old = {
        "font_family": "Arial",
        "font_size_pt": 7.0,
        "tick_direction": "in",
        "mirror_ticks": True,
        "axis_line_width": 0.75,
        "palette": OKABE_ITO,
    }
    st = StyleSpec.model_validate(old)
    assert (st.font_weight, st.axis_title_size_pt, st.legend_size_pt) == ("normal", 7.0, 7.0)
    assert not st.minor_ticks
    assert st.mirror_tick_direction == "in"
    assert st.palette_by_count == {}
    spec = make_spec("nominal_stress_stretch", [("A", inline(LAM, SIG)), ("B", inline(LAM, SIG))])
    spec.style = st
    assert spec.color_of(1, spec.panels[0].series[1], 2) == OKABE_ITO[1]


def test_template_axis_titles_default_to_english() -> None:
    """Figures are for English-language papers/theses (user request 2026-10-28); the in-app
    interface stays Chinese (template names)."""
    import re

    cjk = re.compile(r"[一-鿿]")
    for t in TEMPLATES.values():
        for ax in (t.x, t.y, t.y2):
            if ax is not None:
                assert not cjk.search(ax.title), (t.id, ax.title)
    assert TEMPLATES["nominal_stress_stretch"].y.title == "Nominal stress σ (MPa)"
