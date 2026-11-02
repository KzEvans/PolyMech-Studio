"""Experiment metadata and per-test-type requirements (SPEC §3.4).

Dimensions are stored in SI (m). A missing dimension is None — never a default — and every
analysis checks what it needs before running.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, fields
from enum import StrEnum

from polymech_dataio.mapping import Quantity


class TestType(StrEnum):
    __test__ = False  # not a pytest class

    UNIAXIAL = "uniaxial"
    CYCLIC = "cyclic"
    PURE_SHEAR_UNNOTCHED = "pure_shear_unnotched"
    PURE_SHEAR_NOTCHED = "pure_shear_notched"
    FATIGUE_UNNOTCHED_CYCLIC = "fatigue_unnotched_cyclic"
    FATIGUE_CRACK_GROWTH = "fatigue_crack_growth"
    DMA = "dma"
    PEEL_T = "peel_t"
    PEEL_TROUSER = "peel_trouser"


TEST_TYPE_LABELS: dict[TestType, str] = {
    TestType.UNIAXIAL: "单轴拉伸",
    TestType.CYCLIC: "循环拉伸",
    TestType.PURE_SHEAR_UNNOTCHED: "纯剪切（无预切裂纹）",
    TestType.PURE_SHEAR_NOTCHED: "纯剪切（有预切裂纹）",
    TestType.FATIGUE_UNNOTCHED_CYCLIC: "疲劳：无裂纹样品循环（稳态 W）",
    TestType.FATIGUE_CRACK_GROWTH: "疲劳：裂纹长度–循环次数",
    TestType.DMA: "动态力学分析（DMA）",
    TestType.PEEL_T: "T 型剥离",
    TestType.PEEL_TROUSER: "裤型剥离",
}

FIELD_LABELS: dict[str, str] = {
    "material_name": "材料名称",
    "batch": "批次",
    "specimen_id": "样品编号",
    "instrument": "仪器名称",
    "test_date": "测试日期",
    "temperature_k": "温度",
    "thickness_m": "样品厚度",
    "width_m": "样品宽度",
    "gauge_length_m": "初始标距",
    "height_m": "纯剪切可拉伸高度 H0",
    "notch_length_m": "预切裂纹长度",
    "fixture": "夹具类型",
    "stretch_rate_per_s": "拉伸速率",
    "cycle_frequency_hz": "循环频率",
    "precycles": "预循环次数",
    "crack_resolution_m": "裂纹位置测量分辨率",
    "notes": "实验备注",
}


@dataclass
class ExperimentMetadata:
    material_name: str = ""
    test_type: TestType = TestType.UNIAXIAL
    batch: str = ""
    specimen_id: str = ""
    instrument: str = ""
    test_date: str = ""  # ISO date
    temperature_k: float | None = None
    thickness_m: float | None = None
    width_m: float | None = None
    gauge_length_m: float | None = None
    height_m: float | None = None
    notch_length_m: float | None = None
    fixture: str = ""
    stretch_rate_per_s: float | None = None
    cycle_frequency_hz: float | None = None
    precycles: int | None = None
    crack_resolution_m: float | None = None
    raw_file: str = ""
    notes: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def required_fields(test_type: TestType, available: Collection[Quantity]) -> list[str]:
    """Metadata needed before the analysis of `test_type` can run with these columns."""
    q = set(available)
    has_stress = Quantity.NOMINAL_STRESS in q
    has_stretch = Quantity.STRETCH in q or Quantity.ENGINEERING_STRAIN in q
    need: list[str] = ["material_name"]
    if test_type in (TestType.UNIAXIAL, TestType.CYCLIC):
        if not has_stress:
            need += ["width_m", "thickness_m"]
        if not has_stretch:
            need += ["gauge_length_m"]
    elif test_type in (
        TestType.PURE_SHEAR_UNNOTCHED,
        TestType.PURE_SHEAR_NOTCHED,
        TestType.FATIGUE_UNNOTCHED_CYCLIC,
    ):
        need += ["height_m"]  # H0 enters G = H0·W even when stress/stretch are given
        if not has_stress:
            need += ["width_m", "thickness_m"]
        if test_type is TestType.PURE_SHEAR_NOTCHED:
            need += ["notch_length_m"]
    elif test_type is TestType.FATIGUE_CRACK_GROWTH:
        need += ["crack_resolution_m"]
    elif test_type is TestType.PEEL_T:
        need += ["width_m"]
    elif test_type is TestType.PEEL_TROUSER:
        need += ["thickness_m"]
    return need


def missing_fields(meta: ExperimentMetadata, available: Collection[Quantity]) -> list[str]:
    out = []
    for name in required_fields(meta.test_type, available):
        v = getattr(meta, name)
        if v is None or v == "" or (isinstance(v, (int, float)) and not v > 0):
            out.append(name)
    return out
