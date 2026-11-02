"""Replicate statistics (SPEC §4.1 item 13–14, §4.3 item 6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

from polymech_mechanics._numeric import require_points


@dataclass(frozen=True)
class ReplicateSummary:
    n: int
    mean: float
    std: float  # sample standard deviation (ddof=1); nan when n == 1
    sem: float
    ci95_low: float  # Student-t 95% confidence interval of the mean
    ci95_high: float
    cv: float  # coefficient of variation std/|mean|
    values: tuple[float, ...]


def summarize(values: Sequence[float]) -> ReplicateSummary:
    arr = np.asarray(values, dtype=float)
    require_points(len(arr), 1, "重复样品统计")
    n = len(arr)
    mean = float(arr.mean())
    if n == 1:
        nan = float("nan")
        return ReplicateSummary(1, mean, nan, nan, nan, nan, nan, (mean,))
    std = float(arr.std(ddof=1))
    sem = std / np.sqrt(n)
    half = float(stats.t.ppf(0.975, n - 1)) * sem
    cv = std / abs(mean) if mean != 0 else float("nan")
    return ReplicateSummary(
        n, mean, std, sem, mean - half, mean + half, cv, tuple(float(v) for v in arr)
    )
