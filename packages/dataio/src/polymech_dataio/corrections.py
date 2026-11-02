"""User-selected corrections (SPEC §3.5): zero offset, baseline, smoothing.

Every function returns a NEW array plus a CorrectionRecord (algorithm, parameters, operator,
time); callers keep the original curve alongside the corrected one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import signal

from polymech_dataio.errors import DataIOError

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class CorrectionRecord:
    algorithm: str
    params: dict[str, Any]
    operator: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


def zero_offset(
    values: FloatArray, n_points: int, operator: str
) -> tuple[FloatArray, CorrectionRecord]:
    """Subtract the mean of the first `n_points` finite values."""
    finite = values[np.isfinite(values)]
    if n_points < 1 or len(finite) < n_points:
        raise DataIOError("零点校正所用点数无效")
    offset = float(np.mean(finite[:n_points]))
    return values - offset, CorrectionRecord(
        "zero_offset", {"n_points": n_points, "offset": offset}, operator
    )


def shift_to_contact(
    displacement: FloatArray, force: FloatArray, threshold: float, operator: str
) -> tuple[FloatArray, CorrectionRecord]:
    """Re-zero displacement where force first exceeds `threshold` (removes slack / pre-contact)."""
    idx = np.nonzero(force >= threshold)[0]
    if len(idx) == 0:
        raise DataIOError("力始终未超过接触阈值，无法确定接触点")
    i = int(idx[0])
    d0 = float(displacement[i])
    return displacement - d0, CorrectionRecord(
        "shift_to_contact",
        {"threshold": threshold, "contact_index": i, "displacement_offset": d0},
        operator,
    )


def linear_baseline(
    x: FloatArray, y: FloatArray, start: int, stop: int, operator: str
) -> tuple[FloatArray, CorrectionRecord]:
    """Subtract a straight line fitted to y[start:stop] versus x[start:stop]."""
    if stop - start < 2:
        raise DataIOError("基线拟合区间至少需要 2 个点")
    xs, ys = x[start:stop], y[start:stop]
    ok = np.isfinite(xs) & np.isfinite(ys)
    slope, intercept = np.polyfit(xs[ok], ys[ok], 1)
    return y - (slope * x + intercept), CorrectionRecord(
        "linear_baseline",
        {"start": start, "stop": stop, "slope": float(slope), "intercept": float(intercept)},
        operator,
    )


def smooth(
    values: FloatArray, method: str, window: int, operator: str, polyorder: int = 3
) -> tuple[FloatArray, CorrectionRecord]:
    """Savitzky–Golay ('savgol') or centred moving average ('moving_average')."""
    if window < 3 or window % 2 == 0 or window > len(values):
        raise DataIOError("平滑窗口必须是奇数，且不小于 3、不大于数据长度")
    if not np.all(np.isfinite(values)):
        raise DataIOError("含缺失值的列不能直接平滑，请先处理缺失值")
    if method == "savgol":
        if polyorder >= window:
            raise DataIOError("多项式阶数必须小于窗口长度")
        out = signal.savgol_filter(values, window, polyorder)
        params: dict[str, Any] = {"window": window, "polyorder": polyorder}
    elif method == "moving_average":
        pad = window // 2
        padded = np.pad(values, pad, mode="edge")
        out = np.convolve(padded, np.ones(window) / window, mode="valid")
        params = {"window": window}
    else:
        raise DataIOError(f"未知的平滑方法：{method}")
    return out, CorrectionRecord(method, params, operator)
