from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True, slots=True)
class TimedOperation:
    key: Hashable
    start: datetime | None
    end: datetime | None
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class MatchDecision:
    operation_key: Hashable | None
    status: str
    confidence: float
    rule: str
    time_difference_minutes: float | None = None


def _clock(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        return None


def normalize_operation_interval(
    start_raw: str | None,
    end_raw: str | None,
    period_start: datetime | None,
) -> tuple[datetime | None, datetime | None, str, str | None]:
    """Normalize a report-local operation interval without crossing report boundaries."""
    if period_start is None:
        return None, None, "missing_report_period", "Report period start is unavailable."
    start_clock = _clock(start_raw)
    end_clock = _clock(end_raw)
    if start_clock is None or end_clock is None:
        status = "missing_operation_time" if not start_raw or not end_raw else "invalid_operation_time"
        return None, None, status, "Both operation clock values are required."

    start = datetime.combine(period_start.date(), start_clock)
    end = datetime.combine(period_start.date(), end_clock)
    if end < start:
        return start, end + timedelta(days=1), "midnight_rollover", None
    if end == start:
        return start, None, "equal_time_ambiguous", (
            "Equal start and end times cannot distinguish a zero-duration row from a 24-hour row."
        )
    return start, end, "valid", None


def normalize_failure_time(
    start_raw: str | None,
    period_start: datetime | None,
) -> tuple[datetime | None, str, str | None]:
    if period_start is None:
        return None, "missing_report_period", "Report period start is unavailable."
    start_clock = _clock(start_raw)
    if start_clock is None:
        status = "missing_failure_time" if not start_raw else "invalid_failure_time"
        return None, status, "A valid failure start clock is required for temporal matching."
    return datetime.combine(period_start.date(), start_clock), "valid", None


def match_failure_to_operations(
    failure_start: datetime | None,
    failure_end: datetime | None,
    operations: Iterable[TimedOperation],
    *,
    nearest_tolerance_minutes: float = 0.0,
) -> list[MatchDecision]:
    """Apply exact, overlap, optional-nearest, or explicit unmatched rules."""
    if failure_start is None:
        return [MatchDecision(None, "missing_failure_time", 1.0, "failure_start_unavailable")]

    timed: list[tuple[TimedOperation, datetime, datetime]] = []
    for item in operations:
        if item.start is not None and item.end is not None:
            timed.append((item, item.start, item.end))
    if not timed:
        return [MatchDecision(None, "missing_operation_time", 1.0, "no_valid_operation_intervals")]

    exact = [item for item, start, end in timed if start <= failure_start < end]
    if len(exact) > 1:
        return [MatchDecision(item.key, "ambiguous", min(0.6, item.confidence),
                              "multiple_exact_interval_candidates", 0.0) for item in exact]

    if failure_end is not None and failure_end > failure_start:
        overlaps = [
            item for item, start, end in timed
            if start < failure_end and end > failure_start
        ]
        if len(overlaps) == 1 and not exact:
            return [MatchDecision(overlaps[0].key, "overlap", min(0.9, overlaps[0].confidence),
                                  "failure_interval_overlaps_operation")]
        if len(overlaps) > 1:
            return [MatchDecision(item.key, "ambiguous", min(0.55, item.confidence),
                                  "multiple_overlap_candidates") for item in overlaps]
    if len(exact) == 1:
        return [MatchDecision(exact[0].key, "exact", min(0.98, exact[0].confidence),
                              "failure_start_inside_operation_interval", 0.0)]

    if nearest_tolerance_minutes > 0:
        distances = [
            (
                min(abs((failure_start - start).total_seconds()),
                    abs((failure_start - end).total_seconds())) / 60,
                item,
            )
            for item, start, end in timed
        ]
        minimum = min(distance for distance, _item in distances)
        nearest = [item for distance, item in distances if distance == minimum]
        if minimum <= nearest_tolerance_minutes and len(nearest) == 1:
            return [MatchDecision(nearest[0].key, "inferred_nearest", min(0.5, nearest[0].confidence),
                                  "unique_operation_within_configured_tolerance", round(minimum, 3))]
        if minimum <= nearest_tolerance_minutes and len(nearest) > 1:
            return [MatchDecision(item.key, "ambiguous", min(0.4, item.confidence),
                                  "multiple_equidistant_nearest_candidates", round(minimum, 3))
                    for item in nearest]

    return [MatchDecision(None, "unmatched", 0.95, "no_supported_temporal_match")]
