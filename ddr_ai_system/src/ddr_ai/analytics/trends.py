from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import spearmanr, theilslopes


def robust_sparse_trend(x: list[float], y: list[float]) -> dict[str, Any]:
    if len(x) != len(y) or len(x) < 4:
        return {"applicable": False, "reason": "At least four paired observations are required."}
    x_array = np.asarray(x, dtype=float)
    y_array = np.asarray(y, dtype=float)
    valid = np.isfinite(x_array) & np.isfinite(y_array)
    x_array, y_array = x_array[valid], y_array[valid]
    if len(x_array) < 4 or np.ptp(x_array) == 0:
        return {"applicable": False, "reason": "Insufficient distinct finite observations."}
    slope, intercept, low, high = theilslopes(y_array, x_array, 0.95)
    rho, p_value = spearmanr(x_array, y_array)
    residuals = y_array - (slope * x_array + intercept)
    median = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - median)))
    return {
        "applicable": True,
        "method": "Theil-Sen slope plus Spearman rank correlation",
        "observation_count": int(len(x_array)),
        "slope": float(slope),
        "slope_ci_low": float(low),
        "slope_ci_high": float(high),
        "intercept": float(intercept),
        "spearman_rho": float(rho),
        "spearman_p_value": float(p_value),
        "residual_mad": mad,
        "interpretation_scope": "descriptive_candidate_level",
    }
