"""Read a stored plot series at full resolution in SI units."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from numpy.typing import NDArray

from polymech_mechanics.errors import InvalidInputError
from polymech_plotting.spec import SeriesSource


def stored_series(
    src: SeriesSource, curves: Mapping[str, NDArray[np.float64]]
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64] | None]:
    assert src.x_key is not None and src.y_key is not None
    if src.x_key not in curves or src.y_key not in curves:
        raise InvalidInputError(f"分析 #{src.run_id} 中没有 {src.x_key}/{src.y_key} 数据")
    x, y = curves[src.x_key], curves[src.y_key]
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    keep = np.isfinite(x) & np.isfinite(y)
    err = curves[src.y_err_key][:n][keep] if src.y_err_key and src.y_err_key in curves else None
    return x[keep], y[keep], err
