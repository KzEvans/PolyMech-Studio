"""Data quality checks (SPEC §3.5). Checks only *flag* — data are never removed or edited."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from polymech_dataio.mapping import QUANTITIES, Quantity
from polymech_dataio.metadata import TestType
from polymech_dataio.normalize import NormalizedData
from polymech_dataio.reader import RawTable
from polymech_mechanics.cyclic import CyclicParams, segment_cycles
from polymech_mechanics.errors import CycleSegmentationError
from polymech_mechanics.flags import Severity
from polymech_mechanics.uniaxial import UniaxialParams, detect_break

MIN_POINTS = 20
# Plausible SI ranges; values outside suggest a wrong unit (e.g. MPa data labelled Pa).
_PLAUSIBLE: dict[Quantity, tuple[float, float]] = {
    Quantity.FORCE: (1e-4, 1e5),
    Quantity.PEEL_FORCE: (1e-4, 1e4),
    Quantity.DISPLACEMENT: (1e-7, 10.0),
    Quantity.NOMINAL_STRESS: (10.0, 1e10),
    Quantity.TRUE_STRESS: (10.0, 1e11),
    Quantity.STORAGE_MODULUS: (1e2, 1e11),
    Quantity.LOSS_MODULUS: (1e1, 1e11),
    Quantity.STRETCH: (0.5, 100.0),
    Quantity.ENGINEERING_STRAIN: (1e-5, 100.0),
    Quantity.TEMPERATURE: (1.0, 800.0),
    Quantity.CRACK_LENGTH: (1e-7, 1.0),
}


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: Severity
    message: str
    quantity: Quantity | None = None
    indices: tuple[int, ...] = ()  # first few affected rows (0-based, data rows)


def _first(idx: NDArray[np.intp], n: int = 10) -> tuple[int, ...]:
    return tuple(int(i) for i in idx[:n])


def _mad(x: NDArray[np.float64]) -> float:
    return float(np.median(np.abs(x - np.median(x)))) * 1.4826


def check_quality(
    data: NormalizedData, test_type: TestType, raw: RawTable | None = None
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    n = data.n_rows
    label = {q: QUANTITIES[q].label for q in data.columns}

    if n < MIN_POINTS:
        issues.append(QualityIssue("too_few_points", "warning", f"只有 {n} 行数据，结果可能不可靠"))

    if raw is not None:
        mapped = {c.column_index: c.quantity for c in data.conversions}
        for col in raw.columns:
            if col.index not in mapped:
                continue
            if col.n_non_numeric:
                issues.append(
                    QualityIssue(
                        "non_numeric",
                        "warning",
                        f"“{col.header}”有 {col.n_non_numeric} 个非数值单元格"
                        f"（如 {', '.join(col.non_numeric_examples)}），已作为缺失值处理",
                        mapped[col.index],
                    )
                )

    for q, v in data.columns.items():
        nan = np.nonzero(~np.isfinite(v))[0]
        if len(nan):
            issues.append(
                QualityIssue(
                    "missing_values", "warning", f"{label[q]}有 {len(nan)} 个缺失值", q, _first(nan)
                )
            )
        finite = v[np.isfinite(v)]
        if len(finite) < 3:
            continue
        if q in _PLAUSIBLE:
            lo, hi = _PLAUSIBLE[q]
            peak = float(np.max(np.abs(finite)))
            if peak > 0 and not lo <= peak <= hi:
                issues.append(
                    QualityIssue(
                        "unit_suspect",
                        "warning",
                        f"{label[q]}的最大值 {peak:.3g}（SI）超出常见范围 [{lo:g}, {hi:g}]，请核对单位",
                        q,
                    )
                )
        # sudden jumps: step much larger than the typical step
        d = np.diff(finite)
        if len(d) >= 10:
            scale = _mad(d) or float(np.median(np.abs(d)))  # MAD is 0 for perfectly regular steps
            rng = float(finite.max() - finite.min())
            if scale > 0 and rng > 0:
                big = np.nonzero((np.abs(d) > 20 * scale) & (np.abs(d) > 0.05 * rng))[0]
                # a single large final drop is a fracture, not a jump
                if q in (Quantity.FORCE, Quantity.NOMINAL_STRESS) and len(big):
                    big = big[big < len(d) - 5]
                if len(big):
                    issues.append(
                        QualityIssue(
                            "signal_jump",
                            "warning",
                            f"{label[q]}出现 {len(big)} 处突然跳变",
                            q,
                            _first(big + 1),
                        )
                    )
        # flat top: the maximum repeated many times → possible range truncation / sensor saturation.
        # Noisy clipped signals dip below the cap between hits, so require ≥ 5 hits that make up at
        # least half of the span between the first and last hit (not strictly consecutive).
        if q in (Quantity.FORCE, Quantity.NOMINAL_STRESS, Quantity.PEEL_FORCE):
            top = finite.max()
            at_top = np.nonzero(finite == top)[0]
            span = int(at_top[-1] - at_top[0] + 1) if len(at_top) else 0
            if top > 0 and len(at_top) >= 5 and len(at_top) >= 0.5 * span:
                issues.append(
                    QualityIssue(
                        "saturation",
                        "warning",
                        f"{label[q]}在最大值 {top:.4g} 处出现 {len(at_top)} 次，疑似量程截断或传感器饱和",
                        q,
                        _first(at_top),
                    )
                )

    t = data.get(Quantity.TIME)
    if t is not None:
        tf = t[np.isfinite(t)]
        dt = np.diff(tf)
        back = np.nonzero(dt < 0)[0]
        if len(back):
            issues.append(
                QualityIssue(
                    "time_not_monotonic",
                    "warning",
                    f"时间有 {len(back)} 处倒退",
                    Quantity.TIME,
                    _first(back + 1),
                )
            )
        dup = np.nonzero(dt == 0)[0]
        if len(dup):
            issues.append(
                QualityIssue(
                    "time_duplicate",
                    "info",
                    f"有 {len(dup)} 个重复时间戳",
                    Quantity.TIME,
                    _first(dup + 1),
                )
            )
        pos = dt[dt > 0]
        if len(pos) >= 10:
            med = float(np.median(pos))
            gaps = np.nonzero(dt > 10 * med)[0]
            if len(gaps):
                issues.append(
                    QualityIssue(
                        "time_gap",
                        "info",
                        f"采样间隔有 {len(gaps)} 处超过中位间隔的 10 倍（不规则采样或数据中断）",
                        Quantity.TIME,
                        _first(gaps + 1),
                    )
                )

    # duplicated consecutive records across all mapped columns
    stacked = np.column_stack(list(data.columns.values()))
    same = np.all(np.isclose(stacked[1:], stacked[:-1], equal_nan=True), axis=1)
    dup_rows = np.nonzero(same)[0]
    if len(dup_rows):
        issues.append(
            QualityIssue(
                "duplicate_rows",
                "info",
                f"有 {len(dup_rows)} 行与上一行完全相同",
                None,
                _first(dup_rows + 1),
            )
        )

    load_q = next((q for q in (Quantity.NOMINAL_STRESS, Quantity.FORCE) if q in data.columns), None)
    load = data.get(load_q) if load_q else None
    if load is not None and load_q is not None and np.isfinite(load).sum() >= MIN_POINTS:
        lf = load[np.isfinite(load)]
        peak = float(lf.max())
        k = max(3, len(lf) // 100)
        start = float(np.mean(lf[:k]))
        if peak > 0 and abs(start) > 0.05 * peak:
            issues.append(
                QualityIssue(
                    "baseline_offset",
                    "warning",
                    f"{label[load_q]}起始值约为峰值的 {abs(start) / peak:.0%}，可能存在预载或零点漂移，可选择零点校正",
                    load_q,
                )
            )
        if test_type in (
            TestType.UNIAXIAL,
            TestType.PURE_SHEAR_UNNOTCHED,
            TestType.PURE_SHEAR_NOTCHED,
        ):
            imax = int(np.argmax(lf))
            pre = lf[: imax + 1]
            if len(pre) > 1:
                drops = (pre[:-1] - pre[1:]) / np.maximum(np.abs(pre[:-1]), 1e-300)
                slip = np.nonzero((drops > 0.1) & (pre[:-1] > 0.05 * peak))[0]
                if len(slip):
                    issues.append(
                        QualityIssue(
                            "possible_slip",
                            "warning",
                            f"加载段有 {len(slip)} 处超过 10% 的突降，疑似夹具打滑",
                            load_q,
                            _first(slip + 1),
                        )
                    )
            if (
                test_type is not TestType.PURE_SHEAR_NOTCHED
                and detect_break(lf, UniaxialParams()) is None
            ):
                issues.append(
                    QualityIssue(
                        "break_not_found",
                        "warning",
                        "无法确定断裂位置（未发现明显的断裂下降），请人工指定",
                        load_q,
                    )
                )

    if test_type in (TestType.CYCLIC, TestType.FATIGUE_UNNOTCHED_CYCLIC):
        strain_q = next(
            (
                q
                for q in (Quantity.STRETCH, Quantity.ENGINEERING_STRAIN, Quantity.DISPLACEMENT)
                if q in data.columns
            ),
            None,
        )
        if strain_q is None:
            issues.append(
                QualityIssue(
                    "cycle_no_strain", "error", "循环数据缺少拉伸比、应变或位移列，无法分割循环"
                )
            )
        else:
            s = data.columns[strain_q]
            try:
                segs = segment_cycles(s[np.isfinite(s)], CyclicParams())
                if len(segs) < 2:
                    issues.append(
                        QualityIssue(
                            "few_cycles", "warning", f"只识别到 {len(segs)} 个循环", strain_q
                        )
                    )
            except CycleSegmentationError as e:
                issues.append(
                    QualityIssue(
                        "cycle_segmentation_failed", "error", f"循环分割失败：{e}", strain_q
                    )
                )

    return issues


def summarize_issues(issues: Sequence[QualityIssue]) -> dict[str, int]:
    out = {"info": 0, "warning": 0, "error": 0}
    for i in issues:
        out[i.severity] += 1
    return out
