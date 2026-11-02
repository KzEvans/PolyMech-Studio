"""Ordinary least-squares line fit with the diagnostics the UI must show (SPEC §4.1)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from polymech_mechanics._numeric import FloatArray, require_points


@dataclass(frozen=True)
class LinearFit:
    """y = intercept + slope * x over the points actually used."""

    slope: float
    intercept: float
    slope_stderr: float
    intercept_stderr: float
    r_squared: float
    n_points: int
    x_min: float
    x_max: float
    residuals: tuple[float, ...]
    cov_slope_intercept: float  # needed for uncertainty of derived quantities (e.g. x-intercept)

    def predict(self, x: FloatArray) -> FloatArray:
        return self.intercept + self.slope * x


def linear_fit(x: FloatArray, y: FloatArray, what: str = "线性拟合") -> LinearFit:
    require_points(len(x), 3, what)
    res = stats.linregress(x, y)
    n = len(x)
    resid = y - (res.intercept + res.slope * x)
    sxx = float(np.sum((x - x.mean()) ** 2))
    s2 = float(np.sum(resid**2) / (n - 2))
    cov = -x.mean() * s2 / sxx if sxx > 0 else float("nan")
    return LinearFit(
        slope=float(res.slope),
        intercept=float(res.intercept),
        slope_stderr=float(res.stderr),
        intercept_stderr=float(res.intercept_stderr),
        r_squared=float(res.rvalue**2),
        n_points=n,
        x_min=float(x.min()),
        x_max=float(x.max()),
        residuals=tuple(float(r) for r in resid),
        cov_slope_intercept=cov,
    )
