"""Rule-based column mapping (SPEC §3.2, §8.1 fallback when AI is off or fails).

Each suggestion carries a confidence, the evidence used and open ambiguities. Anything that
could change a scientific conclusion (unknown unit, strain vs stretch, nominal vs true stress)
is marked `needs_confirmation`; nothing here silently assumes a unit.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from polymech_dataio.reader import RawColumn, RawTable
from polymech_dataio.units_text import unit_for_pint
from polymech_mechanics.errors import UnitDimensionError
from polymech_mechanics.units import kind_of, parse_unit

AUTO_ACCEPT_CONFIDENCE = 0.8


class Quantity(StrEnum):
    TIME = "time"
    FORCE = "force"
    DISPLACEMENT = "displacement"
    NOMINAL_STRESS = "nominal_stress"
    TRUE_STRESS = "true_stress"
    ENGINEERING_STRAIN = "engineering_strain"
    STRETCH = "stretch"
    CYCLE = "cycle_number"
    TEMPERATURE = "temperature"
    FREQUENCY = "frequency"
    STORAGE_MODULUS = "storage_modulus"
    LOSS_MODULUS = "loss_modulus"
    LOSS_FACTOR = "loss_factor"
    CRACK_LENGTH = "crack_length"
    CRACK_EXTENSION = "crack_extension"
    ENERGY_RELEASE_RATE = "energy_release_rate"
    PEEL_FORCE = "peel_force"


@dataclass(frozen=True)
class QuantityInfo:
    label: str  # Chinese display label
    kind: str  # unit kind in polymech_mechanics.units.SI_UNITS
    patterns: tuple[str, ...]  # regexes on the normalised column name (most specific first)


Q = Quantity
# Patterns per quantity, tiered: [exact name, specific phrase, generic fragment].
QUANTITIES: dict[Quantity, QuantityInfo] = {
    Q.TIME: QuantityInfo(
        "时间",
        "time",
        (r"^(test |elapsed |total )?time$|^t$|^(试验|测试|实验)?时间$", r"elapsed|\btime\b|时间"),
    ),
    Q.PEEL_FORCE: QuantityInfo(
        "剥离力", "force", (r"^peel(ing)? (force|load)$|^剥离力$", r"peel|剥离")
    ),
    Q.FORCE: QuantityInfo(
        "力",
        "force",
        (
            r"^(force|load|standard force|tensile force)$|^f$|^(力|力值|载荷|荷载|负荷|拉力|试验力)$",
            r"\b(force|load)\b|力值|载荷|荷载|负荷|拉力|试验力",
            r"力$",
        ),
    ),
    Q.DISPLACEMENT: QuantityInfo(
        "位移",
        "length",
        (
            r"^(displacement|extension|position|crosshead( displacement)?)$|^(位移|伸长量|变形量|横梁位移)$",
            r"crosshead|displacement|extension|位移|伸长量|变形量|横梁",
        ),
    ),
    Q.TRUE_STRESS: QuantityInfo(
        "真实应力", "stress", (r"^(true stress|真实应力|真应力)$", r"true stress|真实?应力")
    ),
    Q.NOMINAL_STRESS: QuantityInfo(
        "名义应力",
        "stress",
        (
            r"^((nominal|engineering) stress|名义应力|工程应力)$|^σ[ _]?nom",
            r"(nominal|engineering) stress|名义应力|工程应力",
            r"^(tensile )?stress$|^应力$|^σ$|^sigma$|stress|应力",
        ),
    ),
    Q.STRETCH: QuantityInfo(
        "拉伸比",
        "dimensionless",
        (r"^(stretch|stretch ratio|λ|lambda)$|^(拉伸比|伸长比)$", r"stretch|拉伸比|伸长比"),
    ),
    Q.ENGINEERING_STRAIN: QuantityInfo(
        "工程应变",
        "dimensionless",
        (
            r"^((engineering|tensile|nominal) strain|工程应变)$",
            r"(engineering|tensile|nominal) strain|工程应变|^strain$|^应变$|^ε$|^epsilon$",
            r"strain|应变",
        ),
    ),
    Q.CYCLE: QuantityInfo(
        "循环编号",
        "dimensionless",
        (
            r"^(cycle|cycles|cycle number|cycle no\.?|cycle count|n)$|^(循环|循环次数|循环数|圈数|循环编号)$",
            r"cycle|循环|圈数",
        ),
    ),
    Q.TEMPERATURE: QuantityInfo(
        "温度", "temperature", (r"^(temp|temperature|t)$|^温度$", r"temperature|温度")
    ),
    Q.FREQUENCY: QuantityInfo(
        "频率", "frequency", (r"^(freq|frequency|f)$|^频率$", r"frequency|频率")
    ),
    Q.STORAGE_MODULUS: QuantityInfo(
        "储能模量",
        "stress",
        (r"^(storage modulus|[eg]'|[eg]′)$|^储能模量$", r"storage modulus|储能模量"),
    ),
    Q.LOSS_MODULUS: QuantityInfo(
        "损耗模量",
        "stress",
        (r"^(loss modulus|[eg]''|[eg]″)$|^损耗模量$", r"loss modulus|损耗模量"),
    ),
    Q.LOSS_FACTOR: QuantityInfo(
        "损耗因子",
        "dimensionless",
        (
            r"^(tan ?(δ|delta|d)|loss factor|loss tangent)$|^(损耗因子|损耗角正切)$",
            r"tan ?(δ|delta)|loss factor|损耗因子|损耗角正切",
        ),
    ),
    Q.CRACK_EXTENSION: QuantityInfo(
        "裂纹扩展距离",
        "length",
        (
            r"^(crack (extension|growth|advance)|δc|delta c|dc)$|^(裂纹扩展|裂纹增长|裂纹扩展长度)$",
            r"crack (extension|growth|advance)|裂纹(扩展|增长)",
        ),
    ),
    Q.CRACK_LENGTH: QuantityInfo(
        "裂纹长度", "length", (r"^(crack length|c)$|^裂纹长度$", r"crack length|裂纹长度")
    ),
    Q.ENERGY_RELEASE_RATE: QuantityInfo(
        "能量释放率",
        "energy_per_area",
        (r"^(energy release rate|g)$|^能量释放率$", r"energy release rate|能量释放率"),
    ),
}

# patterns ordered "exact/specific" → "generic": earlier index ⇒ higher name score
_PATTERN_SCORES = (0.9, 0.75, 0.6)


@dataclass(frozen=True)
class ColumnSuggestion:
    column_index: int
    header: str
    quantity: Quantity | None
    unit: str | None  # Pint-parsable unit text, None when unknown
    confidence: float
    rationale: tuple[str, ...]
    ambiguities: tuple[str, ...]
    needs_confirmation: bool
    alternatives: tuple[tuple[Quantity, float], ...] = ()
    source: str = "rules"  # "rules" | "profile:<name>" | "ai:<provider>"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["quantity"] = self.quantity.value if self.quantity else None
        d["alternatives"] = [(q.value, c) for q, c in self.alternatives]
        return d


def _norm(name: str) -> str:
    s = name.strip().lower().replace("（", "(").replace("）", ")")
    s = re.sub(r"[_\s]+", " ", s)
    return s.strip(" .:")


def _unit_kind(unit_text: str | None) -> tuple[str | None, str | None]:
    """(pint unit text, kind) for a unit as written; kind None if unknown/unparsable."""
    u = unit_for_pint(unit_text)
    if u is None:
        return None, None
    if u.strip() in {"%", "percent"}:
        return "%", "dimensionless"
    try:
        return u, kind_of(parse_unit(u))
    except UnitDimensionError:
        return u, None


def _name_scores(col: RawColumn) -> dict[Quantity, tuple[float, str]]:
    texts = {_norm(col.name), _norm(col.header), _norm(col.name.split(" / ")[-1])}
    # instruments number channels per specimen (“力4”, “应变 2”): match on the bare name too
    texts |= {re.sub(r"\s*\d+$", "", t) for t in texts}
    out: dict[Quantity, tuple[float, str]] = {}
    for q, info in QUANTITIES.items():
        for i, pat in enumerate(info.patterns):
            if any(re.search(pat, t) for t in texts):
                score = _PATTERN_SCORES[min(i, len(_PATTERN_SCORES) - 1)]
                out[q] = (score, f"列名“{col.name}”匹配{info.label}的命名规则")
                break
    # a specific match suppresses the generic one it contains
    if Q.PEEL_FORCE in out:
        out.pop(Q.FORCE, None)
    if Q.TRUE_STRESS in out:
        out.pop(Q.NOMINAL_STRESS, None)
    if Q.TRUE_STRESS in out or Q.NOMINAL_STRESS in out:
        out.pop(Q.FORCE, None)  # “应力” ends in “力”
    if Q.STORAGE_MODULUS in out or Q.LOSS_MODULUS in out:
        out.pop(Q.NOMINAL_STRESS, None)
    if Q.CRACK_EXTENSION in out:
        out.pop(Q.CRACK_LENGTH, None)
    if Q.STRETCH in out:
        out.pop(Q.ENGINEERING_STRAIN, None)
    return out


def _value_evidence(q: Quantity, v: np.ndarray) -> tuple[float, list[str], list[str]]:
    """Adjust the score from the numbers themselves; returns (delta, reasons, ambiguities)."""
    v = v[np.isfinite(v)]
    if len(v) < 3:
        return -0.2, ["有效数值太少"], ["数值不足以核验"]
    reasons: list[str] = []
    amb: list[str] = []
    delta = 0.0
    d = np.diff(v)
    if q is Q.TIME:
        if np.all(d >= 0):
            delta += 0.05
            reasons.append("数值单调递增，符合时间")
        else:
            delta -= 0.2
            amb.append("数值并非单调递增，不像时间")
    if q is Q.CYCLE:
        if np.allclose(v, np.round(v)) and np.all(d >= 0):
            delta += 0.05
            reasons.append("整数且不减，符合循环编号")
        else:
            delta -= 0.2
            amb.append("数值不是不减的整数")
    if q in (Q.STRETCH, Q.ENGINEERING_STRAIN):
        start = float(v[0])
        if abs(start - 1.0) < 0.05:
            reasons.append(f"起始值 {start:.3g} ≈ 1，符合拉伸比")
            if q is Q.ENGINEERING_STRAIN:
                delta -= 0.3
                amb.append("列名像应变，但起始值约为 1：可能是拉伸比，请确认")
            else:
                delta += 0.05
        elif abs(start) < 0.05 * max(1.0, float(np.abs(v).max())):
            reasons.append(f"起始值 {start:.3g} ≈ 0，符合工程应变")
            if q is Q.STRETCH:
                delta -= 0.3
                amb.append("列名像拉伸比，但起始值约为 0：可能是工程应变，请确认")
            else:
                delta += 0.05
    if q is Q.LOSS_FACTOR and (v.min() < 0 or v.max() > 10):
        delta -= 0.2
        amb.append("数值超出损耗因子的常见范围")
    return delta, reasons, amb


def suggest_column(col: RawColumn) -> ColumnSuggestion:
    unit, ukind = _unit_kind(col.unit_text)
    names = _name_scores(col)
    candidates: dict[Quantity, tuple[float, list[str], list[str]]] = {}
    for q, (score, why) in names.items():
        info = QUANTITIES[q]
        reasons, amb = [why], []
        if ukind is not None:
            if ukind == info.kind:
                score += 0.1
                reasons.append(f"单位 {col.unit_text} 的量纲与{info.label}一致")
            else:
                score -= 0.6
                amb.append(f"单位 {col.unit_text} 的量纲与{info.label}（{info.kind}）不一致")
        elif col.unit_text is not None:
            amb.append(f"无法识别的单位“{col.unit_text}”")
        dv, r2, a2 = _value_evidence(q, col.values)
        candidates[q] = (min(score + dv, 0.99), reasons + r2, amb + a2)

    if not candidates:
        return ColumnSuggestion(
            col.index,
            col.header,
            None,
            unit,
            0.0,
            ("列名无法匹配任何已知物理量",),
            ("需要人工指定或忽略该列",),
            True,
        )
    ranked = sorted(candidates.items(), key=lambda kv: kv[1][0], reverse=True)
    best_q, (conf, reasons, amb) = ranked[0]
    amb = list(amb)
    info = QUANTITIES[best_q]
    if len(ranked) > 1 and ranked[1][1][0] > conf - 0.1:
        amb.append(f"也可能是{QUANTITIES[ranked[1][0]].label}")
    if best_q is Q.NOMINAL_STRESS and not re.search(
        r"nominal|engineering|名义|工程", _norm(col.header)
    ):
        amb.append("列名未说明是名义应力还是真实应力，请确认")
        conf = min(conf, 0.7)
    if unit is None:
        if info.kind == "dimensionless":
            if best_q is Q.ENGINEERING_STRAIN:
                finite = col.values[np.isfinite(col.values)]
                pct = finite.size > 0 and float(np.abs(finite).max()) > 5
                unit = "%" if pct else "dimensionless"
                amb.append(
                    "未给出单位：按数值范围推测为百分数应变，请确认"
                    if pct
                    else "未给出单位：按小数应变处理，请确认是否为百分数"
                )
            else:
                unit = "dimensionless"
        else:
            amb.append(f"未给出单位，{info.label}必须指定单位后才能计算")
    elif best_q is Q.STRETCH and unit == "%":
        amb.append("拉伸比不应使用百分数单位，可能是百分数应变")
    needs = conf < AUTO_ACCEPT_CONFIDENCE or bool(amb)
    return ColumnSuggestion(
        col.index,
        col.header,
        best_q,
        unit,
        round(conf, 3),
        tuple(reasons),
        tuple(amb),
        needs,
        tuple((q, round(c[0], 3)) for q, c in ranked[1:4]),
    )


def suggest_mapping(table: RawTable) -> list[ColumnSuggestion]:
    out = [suggest_column(c) for c in table.columns]
    # one column per quantity: keep the most confident, flag the others
    by_q: dict[Quantity, list[int]] = {}
    for i, s in enumerate(out):
        if s.quantity is not None:
            by_q.setdefault(s.quantity, []).append(i)
    for q, idxs in by_q.items():
        if len(idxs) < 2:
            continue
        keep = max(idxs, key=lambda i: out[i].confidence)
        for i in idxs:
            s = out[i]
            note = f"多个列都被识别为{QUANTITIES[q].label}"
            out[i] = ColumnSuggestion(
                s.column_index,
                s.header,
                s.quantity,
                s.unit,
                s.confidence if i == keep else round(s.confidence * 0.5, 3),
                s.rationale,
                (*s.ambiguities, note),
                True,
                s.alternatives,
                s.source,
            )
    return out


# --------------------------------------------------------------------------- profiles
@dataclass(frozen=True)
class ProfileRule:
    header: str  # exact header text (case/space-insensitive match)
    quantity: Quantity | None  # None = ignore this column
    unit: str | None


@dataclass(frozen=True)
class ImportProfile:
    """Reusable per-instrument mapping (SPEC §3.2: save rules for a given instrument)."""

    name: str
    instrument: str = ""
    rules: tuple[ProfileRule, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "instrument": self.instrument,
            "rules": [
                {
                    "header": r.header,
                    "quantity": r.quantity.value if r.quantity else None,
                    "unit": r.unit,
                }
                for r in self.rules
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ImportProfile:
        return cls(
            d["name"],
            d.get("instrument", ""),
            tuple(
                ProfileRule(
                    r["header"], Quantity(r["quantity"]) if r["quantity"] else None, r.get("unit")
                )
                for r in d.get("rules", [])
            ),
        )

    def matches(self, table: RawTable) -> bool:
        headers = {_norm(c.header) for c in table.columns}
        return bool(self.rules) and all(_norm(r.header) in headers for r in self.rules)


def apply_profile(table: RawTable, profile: ImportProfile) -> list[ColumnSuggestion]:
    """Profile rules win where they apply; other columns fall back to the rule engine."""
    rules = {_norm(r.header): r for r in profile.rules}
    out: list[ColumnSuggestion] = []
    for col, auto in zip(table.columns, suggest_mapping(table), strict=True):
        r = rules.get(_norm(col.header))
        if r is None:
            out.append(auto)
            continue
        out.append(
            ColumnSuggestion(
                col.index,
                col.header,
                r.quantity,
                r.unit,
                1.0,
                (f"来自已保存的仪器导入规则“{profile.name}”",),
                (),
                False,
                (),
                f"profile:{profile.name}",
            )
        )
    return out


def profile_from_mapping(
    name: str, instrument: str, table: RawTable, mapping: Sequence[MappedColumn]
) -> ImportProfile:
    by_index = {m.column_index: m for m in mapping}
    rules = []
    for c in table.columns:
        m = by_index.get(c.index)
        rules.append(ProfileRule(c.header, m.quantity if m else None, m.unit if m else None))
    return ImportProfile(name, instrument, tuple(rules))


@dataclass(frozen=True)
class MappedColumn:
    """A user-confirmed mapping of one column."""

    column_index: int
    quantity: Quantity
    unit: str
