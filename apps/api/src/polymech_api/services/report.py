"""Per-analysis report (SPEC §10): deterministic content only — no AI text, no mechanism claims."""

from __future__ import annotations

import base64
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from polymech_api.services.analysis import EXPERIMENT_METADATA_FIELDS, run_curves
from polymech_database.models import AnalysisRun, Material, RawDataFile
from polymech_plotting.render import render
from polymech_plotting.spec import SeriesSource
from polymech_plotting.templates import TEMPLATES, make_spec

METHOD_NAMES = {
    "uniaxial": "单轴拉伸",
    "cyclic": "循环拉伸",
    "pure_shear": "纯剪切断裂韧性",
    "fatigue_steady": "循环纯剪切疲劳：稳态能量",
    "crack_growth": "循环纯剪切疲劳：裂纹扩展速率",
    "fatigue_threshold": "循环纯剪切疲劳：疲劳阈值",
    "dma": "动态力学分析（DMA）",
}
FORMULAS = {
    "uniaxial": [
        "λ = L/L0 = 1 + Δl/L0；ε = λ − 1",
        "σ_nom = F/A0（A0 = 初始宽度 × 厚度）；σ_true ≈ λ·σ_nom（近似不可压缩、均匀变形）",
        "W(λ) = ∫₁^λ σ_nom dλ（梯形积分）；W_f = W(λ_b)",
        "初始模量 E = 指定拉伸比区间内 σ_nom–λ 线性拟合斜率；微分模量 = dσ_nom/dλ",
    ],
    "cyclic": [
        "W_load = ∫ σ_nom dλ（加载段），W_unload = ∫ σ_nom dλ（卸载段，取正值）",
        "W_hys = W_load − W_unload；仅当循环闭合时等于 ∮σ dλ（耗散能密度）",
        "残余应变 = 卸载应力降至阈值时的 λ − 1",
    ],
    "pure_shear": [
        "G_c = H0 · W(λc)，W(λ) = ∫₁^λ σ_nom dλ 取自无裂纹样品，λc 取自有裂纹样品（陈 式 2-71）"
    ],
    "fatigue_steady": ["G = H0 · W(λ)，W 取无裂纹样品循环至稳态后的加载段积分（陈 p.78；刘 p.77）"],
    "crack_growth": [
        "dc/dN ≈ Δc/ΔN；检测限 = 位置分辨率 / ΔN；Δc 小于分辨率时记为删失观测（不记为 0）"
    ],
    "fatigue_threshold": [
        "线性外推：dc/dN = b·(G − G0)，只使用可测点；G0 标准误差用 delta 法，置信区间为固定种子成对 bootstrap",
        "实验区间：未检出扩展的最高 G（下界）与检出扩展的最低 G（上界）",
    ],
    "dma": [
        "tan δ = E″/E′（陈 p.70）；只给出其中两列时由此式求第三列",
        "Tg 候选按定义分别给出：tan δ 峰、E″ 峰（抛物线插值峰位）、E′ 下降起始（玻璃态基线与最陡下降切线交点，log E′）",
        "峰只在测量范围内识别，不外推；存在多个显著峰时不自动选定；不同定义、不同频率的 Tg 不合并比较",
    ],
}


def figure(data_dir: Path, run: AnalysisRun) -> str | None:
    tid = {
        "uniaxial": "nominal_stress_stretch",
        "cyclic": "cyclic_hysteresis",
        "pure_shear": "nominal_stress_stretch",
        "fatigue_steady": "nominal_stress_stretch",
        "crack_growth": "crack_growth_vs_cycles",
        "fatigue_threshold": "fatigue_dcdn_g",
        "dma": "dma_storage_tan_delta",
    }.get(run.method)
    if run.method == "dma" and run.result.get("mode") == "frequency_sweep":
        tid = "dma_storage_frequency"
    curves = run_curves(data_dir, run)
    t = TEMPLATES.get(tid or "")
    if t is None or t.x_key not in curves or t.y_key not in curves:
        return None

    x_key = t.x_key

    def source(y_key: str) -> SeriesSource:
        x, y = curves[x_key], curves[y_key]
        n = min(len(x), len(y))
        ok = [i for i in range(n) if x[i] == x[i] and y[i] == y[i]]
        return SeriesSource(x=[float(x[i]) for i in ok], y=[float(y[i]) for i in ok])

    y2: list[tuple[str, SeriesSource]] = []
    if t.y2_key and t.y2_key in curves and np.isfinite(curves[t.y2_key]).any():
        y2 = [(t.y2.label if t.y2 else t.y2_key, source(t.y2_key))]
    png = render(make_spec(t.id, [(f"v{run.version}", source(t.y_key))], y2_series=y2), "png")
    return base64.b64encode(png).decode()


def build_report(s: Any, data_dir: Path, run: AnalysisRun) -> dict[str, Any]:
    exp = run.experiment
    sp = exp.specimen
    material = s.get(Material, sp.material_id)
    raw = (
        s.get(RawDataFile, run.inputs.get("raw_file_id")) if run.inputs.get("raw_file_id") else None
    )
    experiment = run.inputs.get("experiment")
    flags = list(run.flags)
    if experiment is None:
        experiment = {k: None for k in EXPERIMENT_METADATA_FIELDS}
        experiment.update(id=exp.id, test_type=exp.test_type)
        # Legacy runs kept these test conditions in their properties; DMA property
        # temperatures are interpolation targets, not the experiment's temperature.
        keys = ["stretch_rate_per_s", "cycle_frequency_hz"]
        if run.method != "dma":
            keys.append("temperature_k")
        for k in keys:
            values = {p.conditions[k] for p in run.properties if p.conditions.get(k) is not None}
            if len(values) == 1:
                experiment[k] = values.pop()
        flags.append(
            {
                "code": "legacy_experiment_metadata",
                "severity": "info",
                "message": "此历史版本未保存完整实验条件；仅显示当时记录的条件，未记录的字段留空",
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "material": {
            "name": material.name if material else "",
            "polymer_type": material.polymer_type if material else "",
        },
        "specimen": {"label": sp.label, **run.inputs.get("geometry", {})},
        "experiment": experiment,
        "method": {
            "id": run.method,
            "name": METHOD_NAMES.get(run.method, run.method),
            "formulas": FORMULAS.get(run.method, []),
        },
        "analysis": {
            "run_id": run.id,
            "version": run.version,
            "status": run.status,
            "parent_run_id": run.parent_run_id,
            "created_at": run.created_at.isoformat(),
            "operator": run.operator,
            "params": run.params,
        },
        "results": run.result,
        "properties": [
            {
                "quantity": p.quantity,
                "value": p.value,
                "unit": p.unit,
                "uncertainty": p.uncertainty,
                "uncertainty_kind": p.uncertainty_kind,
                "lower_bound": p.lower_bound,
                "upper_bound": p.upper_bound,
                "conditions": p.conditions,
            }
            for p in run.properties
        ],
        "quality_flags": flags,
        "provenance": {
            "raw_file": raw.original_name if raw else None,
            "raw_file_sha256": run.inputs.get("raw_file_sha256"),
            "input_sha256": run.input_sha256,
            "result_sha256": run.result_sha256,
            "software_version": run.software_version,
            "inputs": run.inputs,
        },
        "ai_content": None,  # this report contains only deterministic calculations
    }


LABELS = {
    "label": "样品编号",
    "thickness_m": "厚度",
    "width_m": "宽度",
    "gauge_length_m": "初始标距 L0",
    "height_m": "可拉伸高度 H0",
    "notch_length_m": "预切裂纹长度 c0",
    "id": "实验编号",
    "test_type": "测试类型",
    "instrument": "仪器",
    "test_date": "测试日期",
    "temperature_k": "温度",
    "stretch_rate_per_s": "拉伸速率 (s⁻¹)",
    "cycle_frequency_hz": "循环频率 (Hz)",
    "fixture": "夹具",
    "notes": "备注",
    "raw_file": "原始文件",
    "raw_file_sha256": "原始文件 SHA-256",
    "input_sha256": "输入哈希",
    "result_sha256": "结果哈希",
    "software_version": "软件版本",
}


def _display(key: str, v: Any) -> Any:
    """Lengths in mm and temperatures in °C for readers; JSON export keeps SI."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if key.endswith("_m") and key not in {"resolution_m"}:
            return f"{v * 1e3:.6g} mm"
        if key.endswith("_k"):
            return f"{v - 273.15:.4g} °C"
    return v


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, (dict, list)):
        return html.escape(json.dumps(v, ensure_ascii=False)[:400])
    return html.escape("—" if v is None else str(v))


def render_html(rep: dict[str, Any], figure_b64: str | None) -> str:
    def table(d: dict[str, Any]) -> str:
        return (
            "<table>"
            + "".join(
                f"<tr><th>{html.escape(str(k))}</th><td>{_fmt(v)}</td></tr>" for k, v in d.items()
            )
            + "</table>"
        )

    props = "".join(
        f"<tr><td>{html.escape(p['quantity'])}</td><td>{_fmt(p['value'])}</td><td>{html.escape(p['unit'])}</td>"
        f"<td>{_fmt(p['uncertainty'])} {html.escape(p['uncertainty_kind'] or '')}</td>"
        f"<td>{_fmt(p['lower_bound'])} – {_fmt(p['upper_bound'])}</td><td>{_fmt(p['conditions'])}</td></tr>"
        for p in rep["properties"]
    )
    flags = (
        "".join(
            f"<li class='{html.escape(f['severity'])}'>{html.escape(f['message'])}</li>"
            for f in rep["quality_flags"]
        )
        or "<li>无</li>"
    )
    scalars = {k: v for k, v in rep["results"].items() if not isinstance(v, (dict, list))}
    m = rep["method"]
    fig = (
        f"<figure><img alt='{html.escape(m['name'])}结果图' src='data:image/png;base64,{figure_b64}'/></figure>"
        if figure_b64
        else ""
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(m["name"])}分析报告</title>
<style>
body{{font:13px/1.5 -apple-system,"PingFang SC",sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#1d1d1f}}
h1{{font-size:22px}}h2{{font-size:15px;border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:24px}}
table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid #eee;padding:3px 6px;text-align:left;vertical-align:top;font-variant-numeric:tabular-nums}}
th{{color:#5e5e63;font-weight:500;width:32%}}figure{{margin:12px 0}}img{{max-width:100%}}li.warning{{color:#9a5b00}}li.error{{color:#c4241b}}
code{{font-size:11px}}@media print{{body{{margin:0}}}}
</style></head><body>
<h1>{html.escape(m["name"])}分析报告</h1>
<p>{html.escape(rep["material"]["name"])} · 样品 {html.escape(str(rep["specimen"].get("label", "")))} · 分析版本 v{rep["analysis"]["version"]}（{"正式" if rep["analysis"]["status"] == "ok" else "临时"}）· 生成于 {html.escape(rep["generated_at"])}</p>
<p><small>本报告只包含确定性计算结果；不包含 AI 生成的解释，也不包含材料机理结论。</small></p>
<h2>1. 材料与样品</h2>{table({"材料": rep["material"]["name"], **rep["specimen"]})}
<h2>2–3. 实验方法、仪器与测试条件</h2>{table(rep["experiment"])}
<h2>4–5. 数据处理方法与关键公式</h2><ul>{"".join(f"<li>{html.escape(f)}</li>" for f in m["formulas"])}</ul>
<h2>6. 计算参数</h2>{table(rep["analysis"]["params"])}
<h2>7. 结果与不确定度</h2><table><tr><th>性能</th><th>数值</th><th>SI 单位</th><th>不确定度</th><th>区间</th><th>条件</th></tr>{props}</table>
{table(scalars)}
<h2>8. 图表</h2>{fig or "<p>无</p>"}
<h2>9. 质量警告</h2><ul>{flags}</ul>
<h2>10–12. 原始数据来源、软件版本与哈希</h2>{table(rep["provenance"] | {"inputs": None})}
</body></html>"""
