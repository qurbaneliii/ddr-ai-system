from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
from scipy.stats import spearmanr, theilslopes


@dataclass(frozen=True, slots=True)
class TrendObservation:
    observed_at: date | datetime | None
    value: float | None
    unit: str | None
    included: bool = True
    exclusion_reason: str | None = None


def robust_sparse_trend(x: list[float], y: list[float]) -> dict[str, Any]:
    if len(x) != len(y) or len(x) < 4:
        return {"applicable": False, "reason": "At least four paired observations are required."}
    x_array = np.asarray(x, dtype=float)
    y_array = np.asarray(y, dtype=float)
    valid = np.isfinite(x_array) & np.isfinite(y_array)
    x_array, y_array = x_array[valid], y_array[valid]
    if len(x_array) < 4 or np.ptp(x_array) == 0:
        return {"applicable": False, "reason": "Insufficient distinct finite observations."}
    if np.ptp(y_array) == 0:
        return {
            "applicable": True,
            "method": "Theil-Sen slope plus Spearman rank correlation",
            "observation_count": int(len(x_array)),
            "slope": 0.0,
            "slope_ci_low": 0.0,
            "slope_ci_high": 0.0,
            "intercept": float(y_array[0]),
            "spearman_rho": 0.0,
            "spearman_p_value": 1.0,
            "residual_mad": 0.0,
            "interpretation_scope": "descriptive_candidate_level",
        }
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


def compatible_parameter_trend(observations: list[TrendObservation]) -> dict[str, Any]:
    """Analyze one parameter only when dates and units are comparable."""

    excluded_reasons: dict[str, int] = {}
    usable: list[TrendObservation] = []
    for item in observations:
        reason = item.exclusion_reason
        if not item.included:
            reason = reason or "data_quality_exclusion"
        elif item.observed_at is None:
            reason = "invalid_or_missing_date"
        elif item.value is None or not np.isfinite(item.value):
            reason = "invalid_or_missing_value"
        elif not item.unit or item.unit.casefold().strip() in {"unknown", "n/a", "none"}:
            reason = "unknown_unit"
        if reason:
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
        else:
            usable.append(item)

    units = sorted({str(item.unit).casefold().strip() for item in usable})
    base = {
        "input_count": len(observations),
        "included_record_count": len(usable),
        "excluded_record_count": len(observations) - len(usable),
        "excluded_reasons": excluded_reasons,
        "compatible_units": units,
    }
    if len(units) != 1:
        reason = "Known units are mixed and cannot be combined." if units else "No known-unit observations."
        return {**base, "applicable": False, "reason": reason}

    values_by_date: dict[date, list[float]] = {}
    for item in usable:
        observed_date = (
            item.observed_at.date() if isinstance(item.observed_at, datetime) else item.observed_at
        )
        assert observed_date is not None and item.value is not None
        values_by_date.setdefault(observed_date, []).append(float(item.value))
    dates = sorted(values_by_date)
    x = [float(item.toordinal()) for item in dates]
    y = [float(np.median(values_by_date[item])) for item in dates]
    result = robust_sparse_trend(x, y)
    result.update(
        {
            **base,
            "observation_count": len(dates),
            "duplicate_date_count": len(usable) - len(dates),
            "unit": units[0],
            "date_start": dates[0].isoformat() if dates else None,
            "date_end": dates[-1].isoformat() if dates else None,
        }
    )
    if result.get("applicable"):
        low = float(result["slope_ci_low"])
        high = float(result["slope_ci_high"])
        result["direction"] = (
            "increasing" if low > 0 else "decreasing" if high < 0 else "stable_or_uncertain"
        )
    return result
