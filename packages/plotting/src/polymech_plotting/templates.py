"""Built-in plot templates (SPEC §5.2). A template is data, not a picture: it fixes axes,
units and series styling, and turns bound data sources into a PlotSpec."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import KW_ONLY, dataclass
from typing import Literal

from polymech_plotting.spec import (
    AxisSpec,
    LayoutSpec,
    PanelSpec,
    PlotSpec,
    SeriesSource,
    SeriesSpec,
)

SeriesKind = Literal["line", "scatter", "line+markers"]


@dataclass(frozen=True)
class Template:
    id: str
    name: str  # Chinese display name
    version: str
    x: AxisSpec
    y: AxisSpec
    y2: AxisSpec | None = None
    _: KW_ONLY
    kind: SeriesKind = "line"
    marker: Literal["circle", "square", "triangle", "diamond", "cross", "none"] = "none"
    x_key: str | None = None  # default curve keys when binding analysis runs
    y_key: str | None = None
    y2_key: str | None = None
    x_property: str | None = None  # material-property comparison templates (materials DB)
    y_property: str | None = None
    origin_template: str = "pm_line"
    """Registered Origin template id (templates/origin/registry.json, .otpu); the bridge falls
    back to the built-in base plus programmatic style if the file is missing."""
    description: str = ""


def _ax(
    label: str, si: str = "1", unit: str = "", scale: Literal["linear", "log"] = "linear"
) -> AxisSpec:
    return AxisSpec(label=label, si_unit=si, unit=unit, scale=scale)


STRETCH = _ax("Stretch ratio λ")
CYCLE = _ax("Cycle number N", "cycle")

TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in [
        Template(
            "nominal_stress_stretch",
            "名义应力–拉伸比",
            "1.0",
            STRETCH,
            _ax("Nominal stress σ", "Pa", "MPa"),
            x_key="stretch",
            y_key="nominal_stress_pa",
        ),
        Template(
            "true_stress_stretch",
            "真实应力–拉伸比",
            "1.0",
            STRETCH,
            _ax("True stress σ", "Pa", "MPa"),
            x_key="stretch",
            y_key="true_stress_pa",
        ),
        Template(
            "differential_modulus_stretch",
            "微分模量–拉伸比",
            "1.0",
            STRETCH,
            _ax("Differential modulus dσ/dλ", "Pa", "MPa"),
            x_key="stretch",
            y_key="differential_modulus_pa",
        ),
        Template(
            "cyclic_hysteresis",
            "循环滞后曲线",
            "1.0",
            STRETCH,
            _ax("Nominal stress σ", "Pa", "MPa"),
            x_key="stretch",
            y_key="nominal_stress_pa",
        ),
        Template(
            "hysteresis_vs_cycle",
            "滞后能–循环次数",
            "1.0",
            CYCLE,
            _ax("Hysteresis energy", "J/m^3", "kJ/m³"),
            kind="line+markers",
            marker="circle",
            x_key="cycle_index",
            y_key="hysteresis_j_m3",
            origin_template="pm_linesymb",
        ),
        Template(
            "residual_strain_vs_cycle",
            "残余应变–循环次数",
            "1.0",
            CYCLE,
            _ax("Residual strain", "1", "%"),
            kind="line+markers",
            marker="square",
            x_key="cycle_index",
            y_key="residual_strain",
            origin_template="pm_linesymb",
        ),
        Template(
            "dma_storage_tan_delta",
            "储能模量与损耗因子–温度",
            "1.0",
            _ax("Temperature T", "K", "°C"),
            _ax("Storage modulus E′", "Pa", "MPa", "log"),
            _ax("Loss factor tan δ"),
            x_key="temperature_k",
            y_key="storage_modulus_pa",
            y2_key="loss_factor",
            origin_template="pm_doubley",
        ),
        Template(
            "dma_loss_modulus",
            "损耗模量–温度",
            "1.0",
            _ax("Temperature T", "K", "°C"),
            _ax("Loss modulus E″", "Pa", "MPa", "log"),
            x_key="temperature_k",
            y_key="loss_modulus_pa",
        ),
        Template(
            "dma_tan_delta",
            "损耗因子–温度",
            "1.0",
            _ax("Temperature T", "K", "°C"),
            _ax("Loss factor tan δ"),
            x_key="temperature_k",
            y_key="loss_factor",
            description="Tg 标注须写明定义（tan δ 峰 / E″ 峰 / E′ 起始）",
        ),
        Template(
            "dma_storage_frequency",
            "储能模量–频率",
            "1.0",
            _ax("Frequency f", "Hz", "Hz", "log"),
            _ax("Storage modulus E′", "Pa", "MPa", "log"),
            kind="line+markers",
            marker="circle",
            x_key="frequency_hz",
            y_key="storage_modulus_pa",
            origin_template="pm_linesymb",
        ),
        Template(
            "fatigue_dcdn_g",
            "dc/dN–G 疲劳曲线",
            "1.0",
            _ax("Energy release rate G", "J/m^2", "J/m²"),
            _ax("Crack growth rate dc/dN", "m/cycle", "nm/cycle"),
            kind="scatter",
            marker="circle",
            x_key="g_j_m2",
            y_key="dc_dn_m_per_cycle",
            origin_template="pm_scatter",
            description="低于检测限的点以空心标记显示为上界，不作为 0",
        ),
        Template(
            "crack_growth_vs_cycles",
            "裂纹增长量–循环次数",
            "1.0",
            CYCLE,
            _ax("Crack extension Δc", "m", "μm"),
            kind="line+markers",
            marker="circle",
            x_key="crack_cycles",
            y_key="crack_extension_m",
            origin_template="pm_linesymb",
        ),
        Template(
            "crack_resistance_curve",
            "裂纹扩展阻力曲线",
            "1.0",
            _ax("Crack extension Δc", "m", "mm"),
            _ax("Energy release rate G", "J/m^2", "kJ/m²"),
            kind="line+markers",
            marker="circle",
            x_key="crack_extension_m",
            y_key="g_j_m2",
            origin_template="pm_linesymb",
        ),
        Template(
            "peel_force_displacement",
            "剥离力–位移",
            "1.0",
            _ax("Displacement", "m", "mm"),
            _ax("Peel force F", "N", "N"),
            x_key="displacement_m",
            y_key="force_n",
        ),
        Template(
            "modulus_vs_toughness",
            "模量–断裂韧性对比",
            "1.0",
            _ax("Elastic modulus E", "Pa", "MPa", "log"),
            _ax("Fracture toughness Gc", "J/m^2", "kJ/m²", "log"),
            kind="scatter",
            marker="circle",
            x_property="elastic_modulus",
            y_property="fracture_toughness",
            origin_template="pm_scatter",
        ),
        Template(
            "modulus_vs_threshold",
            "模量–疲劳阈值对比",
            "1.0",
            _ax("Elastic modulus E", "Pa", "MPa", "log"),
            _ax("Fatigue threshold Gth", "J/m^2", "J/m²", "log"),
            kind="scatter",
            marker="circle",
            x_property="elastic_modulus",
            y_property="fatigue_threshold",
            origin_template="pm_scatter",
        ),
        Template(
            "toughness_vs_threshold",
            "断裂韧性–疲劳阈值对比",
            "1.0",
            _ax("Fracture toughness Gc", "J/m^2", "kJ/m²", "log"),
            _ax("Fatigue threshold Gth", "J/m^2", "J/m²", "log"),
            kind="scatter",
            marker="circle",
            x_property="fracture_toughness",
            y_property="fatigue_threshold",
            origin_template="pm_scatter",
        ),
    ]
}


def make_spec(
    template_id: str,
    series: Sequence[tuple[str, SeriesSource]],
    title: str = "",
    y2_series: Sequence[tuple[str, SeriesSource]] = (),
) -> PlotSpec:
    """Bind named data sources to a template; styling follows the template defaults."""
    t = TEMPLATES[template_id]
    specs = [
        SeriesSpec(name=name, source=src, kind=t.kind, marker=t.marker) for name, src in series
    ]
    specs += [
        SeriesSpec(name=name, source=src, kind="line", line_style="dash", y_axis="y2")
        for name, src in y2_series
    ]
    panel = PanelSpec(template_id=t.id, x=t.x, y=t.y, y2=t.y2, series=specs)
    return PlotSpec(
        template_id=t.id,
        template_version=t.version,
        title=title,
        panels=[panel],
        layout=LayoutSpec(),
    )


def run_series(template_id: str, run_id: int, name: str) -> SeriesSource:
    t = TEMPLATES[template_id]
    if t.x_key is None or t.y_key is None:
        raise ValueError(f"template {template_id} has no default curve keys")
    return SeriesSource(run_id=run_id, x_key=t.x_key, y_key=t.y_key)
