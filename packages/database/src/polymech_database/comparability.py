"""Comparability of two stored property values (SPEC §7.5).

Equal units are never enough. Each aspect (indicator type, test type, temperature, frequency,
loading rate, stress definition, geometry, pre-cycling, energy/threshold method, value form)
gives a level; the overall verdict is the worst level found:

    not_recommended > insufficient > conditional > direct

Rules are deterministic and every finding carries a Chinese explanation for the user.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Level = Literal["direct", "conditional", "insufficient", "not_recommended"]
RANK: dict[Level, int] = {"direct": 0, "conditional": 1, "insufficient": 2, "not_recommended": 3}
VERDICT_LABELS: dict[Level, str] = {
    "direct": "可直接比较",
    "conditional": "有条件比较",
    "insufficient": "信息不足",
    "not_recommended": "不建议直接比较",
}

DMA_STATE = {"storage_modulus", "loss_modulus", "loss_factor"}
UNIAXIAL = {
    "elastic_modulus",
    "tensile_strength",
    "break_stress",
    "true_break_stress",
    "ultimate_stretch",
    "elongation_at_break",
    "work_of_fracture",
}
CYCLIC = {"hysteresis_energy", "residual_strain"}
METHOD_TEST_TYPE = {
    "uniaxial": "uniaxial",
    "cyclic": "cyclic",
    "pure_shear": "pure_shear",
    "fatigue_threshold": "fatigue",
    "crack_growth": "fatigue",
    "fatigue_steady": "fatigue",
    "dma": "dma",
}


@dataclass(frozen=True)
class Record:
    """A property value with everything needed to judge comparability."""

    id: int
    label: str
    quantity: str
    value: float | None
    lower_bound: float | None
    upper_bound: float | None
    test_type: str  # uniaxial | cyclic | pure_shear | fatigue | dma | peel_t | peel_trouser | ""
    source_kind: Literal["analysis", "literature"]
    conditions: Mapping[str, Any] = field(default_factory=dict)

    @property
    def approximate(self) -> bool:
        return bool(self.conditions.get("approximate"))

    def get(self, key: str) -> Any:
        v = self.conditions.get(key)
        return None if v in (None, "") else v


@dataclass(frozen=True)
class Finding:
    aspect: str
    level: Level
    message: str


@dataclass(frozen=True)
class Comparison:
    a: int
    b: int
    verdict: Level
    verdict_label: str
    findings: tuple[Finding, ...]


def _worst(findings: Sequence[Finding]) -> Level:
    return max((f.level for f in findings), key=RANK.__getitem__, default="direct")


def _close(x: float, y: float, rel: float) -> bool:
    return abs(x - y) <= rel * max(abs(x), abs(y), 1e-300)


def _stress_basis(r: Record) -> str:
    if r.quantity == "true_break_stress":
        return "true"
    if r.source_kind == "analysis":
        return "nominal"  # the engine fits and reports nominal stress
    return str(r.get("stress_basis") or "unspecified")


def _toughness_method(r: Record) -> Any:
    return r.get("method") or ("pure_shear" if r.source_kind == "analysis" else None)


def _both(a: Record, b: Record, key: str) -> tuple[Any, Any]:
    return a.get(key), b.get(key)


def compare(a: Record, b: Record) -> Comparison:
    out: list[Finding] = []
    add = out.append

    # 1. indicator type
    pair = {a.quantity, b.quantity}
    if a.quantity != b.quantity:
        if pair == {"ultimate_stretch", "elongation_at_break"}:
            add(
                Finding(
                    "指标类型",
                    "conditional",
                    "断裂拉伸比与断裂伸长率可按 λ = 1 + ε 换算（仅当伸长率按夹具间距的工程应变计）",
                )
            )
        elif pair & {"true_break_stress"} and pair & {"break_stress", "tensile_strength"}:
            add(Finding("应力定义", "not_recommended", "真实应力与名义应力定义不同，不能直接比较"))
        else:
            add(Finding("指标类型", "not_recommended", "不是同一类指标"))
            return _done(a, b, out)

    # 2. test type
    ta, tb = a.test_type, b.test_type
    if not ta or not tb:
        add(Finding("实验类型", "insufficient", "至少一方未记录实验类型"))
    elif ta != tb:
        add(Finding("实验类型", "not_recommended", f"实验类型不同（{ta} / {tb}）"))

    # 3. value form
    for r in (a, b):
        if r.value is None:
            add(
                Finding(
                    "数值形式",
                    "conditional",
                    f"{r.label} 只有区间（下界/上界），只能判断大小关系，不能计算差值",
                )
            )
        elif r.approximate:
            add(Finding("数值形式", "conditional", f"{r.label} 为原文约值（~/约）"))

    q = a.quantity
    # 4. temperature
    t1, t2 = _both(a, b, "temperature_k")
    if q in DMA_STATE:
        if t1 is None or t2 is None:
            add(Finding("温度", "insufficient", "DMA 状态量必须注明温度"))
        elif abs(t1 - t2) > 1.0:
            add(
                Finding(
                    "温度",
                    "not_recommended",
                    f"温度不同（{t1 - 273.15:.1f} / {t2 - 273.15:.1f} °C）",
                )
            )
    elif q != "glass_transition_temperature":
        if t1 is None or t2 is None:
            add(Finding("温度", "conditional", "测试温度未记录：按同为室温试验比较，需人工确认"))
        elif abs(t1 - t2) > 20:
            add(Finding("温度", "not_recommended", f"测试温度相差 {abs(t1 - t2):.0f} K"))
        elif abs(t1 - t2) > 5:
            add(Finding("温度", "conditional", f"测试温度相差 {abs(t1 - t2):.0f} K"))

    # 5. frequency (DMA and fatigue)
    if q in DMA_STATE or q == "glass_transition_temperature":
        f1, f2 = _both(a, b, "frequency_hz")
        if f1 is None or f2 is None:
            add(Finding("频率", "insufficient", "DMA 结果必须注明频率"))
        elif not _close(f1, f2, 0.01):
            level: Level = (
                "conditional" if q == "glass_transition_temperature" else "not_recommended"
            )
            add(Finding("频率", level, f"频率不同（{f1:g} / {f2:g} Hz）：Tg 与模量随频率变化"))
        m1, m2 = _both(a, b, "deformation_mode")
        if m1 and m2 and m1 != m2:
            add(
                Finding(
                    "加载模式",
                    "not_recommended",
                    f"形变模式不同（{m1} / {m2}）：E 与 G 不能直接比较",
                )
            )
    if q == "glass_transition_temperature":
        d1, d2 = _both(a, b, "tg_definition")
        if d1 is None or d2 is None:
            add(Finding("Tg 定义", "insufficient", "至少一方未注明 Tg 定义"))
        elif d1 != d2:
            add(Finding("Tg 定义", "not_recommended", f"Tg 定义不同（{d1} / {d2}）"))

    # 6. loading rate
    if q in UNIAXIAL | {"fracture_toughness"}:
        r1, r2 = _both(a, b, "stretch_rate_per_s")
        if r1 is None or r2 is None:
            add(Finding("加载速度", "conditional", "拉伸速率未记录：粘弹性材料的结果与速率有关"))
        else:
            ratio = max(r1, r2) / max(min(r1, r2), 1e-300)
            if ratio > 30:
                add(Finding("加载速度", "not_recommended", f"拉伸速率相差 {ratio:.0f} 倍"))
            elif ratio > 3:
                add(Finding("加载速度", "conditional", f"拉伸速率相差 {ratio:.0f} 倍"))

    # 7. stress definition
    if q in {"elastic_modulus", "tensile_strength", "break_stress"}:
        s1, s2 = _stress_basis(a), _stress_basis(b)
        if "unspecified" in (s1, s2):
            add(Finding("应力定义", "conditional", "至少一方未说明名义应力或真实应力"))
        elif s1 != s2:
            level = "conditional" if q == "elastic_modulus" else "not_recommended"
            note = "（小应变下两者初始斜率接近）" if q == "elastic_modulus" else ""
            add(Finding("应力定义", level, f"应力定义不同（{s1} / {s2}）{note}"))

    # 8. fracture: method, λc definition, geometry
    if q == "fracture_toughness":
        m1, m2 = _toughness_method(a), _toughness_method(b)
        if m1 is None or m2 is None:
            add(Finding("应变能计算方法", "insufficient", "至少一方未说明韧性测试方法"))
        elif m1 != m2:
            add(Finding("应变能计算方法", "not_recommended", f"韧性测试方法不同（{m1} / {m2}）"))
        c1, c2 = _both(a, b, "lambda_c_definition")
        if c1 and c2 and c1 != c2:
            add(
                Finding(
                    "临界拉伸比定义",
                    "conditional",
                    f"λc 定义不同（{c1} / {c2}）：对稳定扩展的韧性材料两者可相差很大",
                )
            )
        _geometry(a, b, "height_m", "可拉伸高度 H0", out, size_effect=True)

    # 9. fatigue threshold: decision method, pre-cycling, resolution
    if q == "fatigue_threshold":
        m1, m2 = _both(a, b, "method")
        if m1 is None or m2 is None:
            add(Finding("疲劳阈值判定方法", "insufficient", "至少一方未说明阈值判定方法"))
        elif m1 != m2:
            add(Finding("疲劳阈值判定方法", "not_recommended", f"判定方法不同（{m1} / {m2}）"))
        g1 = a.get("G_definition") or a.get("G_note")
        g2 = b.get("G_definition") or b.get("G_note")
        if g1 and g2 and g1 != g2:
            add(Finding("G 定义", "conditional", f"G 的定义表述不同，请确认一致：{g1} / {g2}"))
        p1, p2 = _both(a, b, "steady_state_cycles")
        if p1 and p2 and p1 != p2:
            add(Finding("预循环次数", "conditional", f"稳态 W 的预循环次数不同（{p1} / {p2}）"))
        d1, d2 = _both(a, b, "detection_limit_m_per_cycle")
        if d1 and d2 and not _close(d1, d2, 0.2):
            add(Finding("检测限", "conditional", "dc/dN 检测限不同，阈值附近的判定灵敏度不同"))
        _geometry(a, b, "height_m", "可拉伸高度 H0", out, size_effect=False)

    # 10. cyclic: amplitude and recovery
    if q in CYCLIC:
        s1, s2 = _both(a, b, "stretch_max")
        if s1 is None or s2 is None:
            add(Finding("加载幅度", "insufficient", "至少一方未注明最大拉伸比"))
        elif not _close(s1, s2, 0.02):
            add(Finding("加载幅度", "not_recommended", f"最大拉伸比不同（{s1:g} / {s2:g}）"))
        r1, r2 = _both(a, b, "recovery_time_s")
        if r1 and r2 and not _close(r1, r2, 0.1):
            add(Finding("恢复时间", "conditional", f"卸载后恢复时间不同（{r1:g} / {r2:g} s）"))

    # 11. interfacial toughness method
    if q == "interfacial_toughness":
        m1, m2 = _both(a, b, "method")
        if m1 and m2 and m1 != m2:
            add(Finding("加载模式", "not_recommended", f"剥离/撕裂方式不同（{m1} / {m2}）"))

    return _done(a, b, out)


def _geometry(
    a: Record, b: Record, key: str, label: str, out: list[Finding], *, size_effect: bool
) -> None:
    h1, h2 = _both(a, b, key)
    if h1 is None or h2 is None:
        out.append(Finding("样品几何", "conditional", f"{label} 未记录"))
    elif not _close(h1, h2, 0.05):
        why = "：过程区较大时纯剪切韧性与样品高度有关" if size_effect else ""
        out.append(
            Finding(
                "样品几何", "conditional", f"{label} 不同（{h1 * 1e3:g} / {h2 * 1e3:g} mm）{why}"
            )
        )


def _done(a: Record, b: Record, findings: list[Finding]) -> Comparison:
    v = _worst(findings)
    if not findings:
        findings = [Finding("全部检查项", "direct", "实验类型、条件与定义一致")]
    return Comparison(a.id, b.id, v, VERDICT_LABELS[v], tuple(findings))


def compare_to_reference(reference: Record, others: Sequence[Record]) -> list[Comparison]:
    return [compare(reference, r) for r in others]
