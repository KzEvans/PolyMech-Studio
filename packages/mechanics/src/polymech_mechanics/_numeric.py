"""Small numeric helpers shared by the analysis modules."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from polymech_mechanics.errors import InsufficientDataError, InvalidInputError

FloatArray = NDArray[np.float64]


def as_1d(name: str, values: ArrayLike) -> FloatArray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise InvalidInputError(f"{name} 必须是一维数组")
    if not np.all(np.isfinite(arr)):
        raise InvalidInputError(f"{name} 含有缺失值或非数值（NaN/Inf），请先在质量检查中处理")
    return arr


def same_length(**arrays: FloatArray) -> None:
    lengths = {k: len(v) for k, v in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise InvalidInputError(f"数组长度不一致：{lengths}")


def require_points(n: int, minimum: int, what: str) -> None:
    if n < minimum:
        raise InsufficientDataError(f"{what}只有 {n} 个有效数据点，至少需要 {minimum} 个")


def cumulative_trapezoid(y: FloatArray, x: FloatArray) -> FloatArray:
    """∫ y dx from x[0] to each x[i] (trapezoidal rule), starting at 0."""
    out = np.zeros_like(y)
    out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(x))
    return out


def trapezoid(y: FloatArray, x: FloatArray) -> float:
    return float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(x)))
