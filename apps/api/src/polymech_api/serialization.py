"""JSON conversion of engine results: arrays are excluded (they go to Parquet curves),
NaN/inf become null, enums become their values."""

from __future__ import annotations

import dataclasses
import math
from enum import Enum
from typing import Any

import numpy as np


def to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {}
        for fld in dataclasses.fields(obj):
            v = getattr(obj, fld.name)
            if isinstance(v, np.ndarray):
                continue
            out[fld.name] = to_jsonable(v)
        return out
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def lttb(x: np.ndarray, y: np.ndarray, n_out: int) -> np.ndarray:
    """Largest-Triangle-Three-Buckets: indices of a shape-preserving subsample (preview only;
    calculations always use the full data)."""
    n = len(x)
    if n_out >= n or n_out < 3:
        return np.arange(n)
    every = (n - 2) / (n_out - 2)
    idx = [0]
    a = 0
    for i in range(n_out - 2):
        lo = int(i * every) + 1
        hi = int((i + 1) * every) + 1
        nlo, nhi = hi, min(int((i + 2) * every) + 1, n)
        cx, cy = (x[nlo:nhi].mean(), y[nlo:nhi].mean()) if nhi > nlo else (x[-1], y[-1])
        xs, ys = x[lo:hi], y[lo:hi]
        area = np.abs((x[a] - cx) * (ys - y[a]) - (x[a] - xs) * (cy - y[a]))
        a = lo + int(np.argmax(area))
        idx.append(a)
    idx.append(n - 1)
    return np.asarray(idx)


def downsample_curves(
    curves: dict[str, np.ndarray], x_key: str, y_key: str, n_out: int = 2000
) -> dict[str, list[Any]]:
    """Subsample all equal-length columns with indices chosen on (x_key, y_key)."""
    n = len(curves[x_key])
    x, y = curves[x_key], curves[y_key]
    ok = np.isfinite(x) & np.isfinite(y)
    base = np.nonzero(ok)[0]
    keep = base[lttb(x[ok], y[ok], n_out)] if len(base) else np.arange(0)
    return {k: to_jsonable(v[keep]) if len(v) == n else to_jsonable(v) for k, v in curves.items()}
