from __future__ import annotations

from datetime import datetime, timedelta

from ddr_ai.analytics.failure_matching import (
    TimedOperation,
    match_failure_to_operations,
    normalize_operation_interval,
)


def test_one_failure_has_one_exact_operation_match() -> None:
    start = datetime(2024, 1, 1, 2)
    decisions = match_failure_to_operations(
        start,
        None,
        [TimedOperation(7, start - timedelta(hours=1), start + timedelta(hours=1))],
    )
    assert [(item.operation_key, item.status) for item in decisions] == [(7, "exact")]


def test_failure_overlapping_multiple_operations_is_ambiguous() -> None:
    failure_start = datetime(2024, 1, 1, 1)
    failure_end = datetime(2024, 1, 1, 4)
    operations = [
        TimedOperation(1, datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 2)),
        TimedOperation(2, datetime(2024, 1, 1, 3), datetime(2024, 1, 1, 5)),
    ]
    decisions = match_failure_to_operations(failure_start, failure_end, operations)
    assert {item.operation_key for item in decisions} == {1, 2}
    assert {item.status for item in decisions} == {"ambiguous"}


def test_failure_without_start_time_is_explicit() -> None:
    decisions = match_failure_to_operations(None, None, [])
    assert decisions[0].status == "missing_failure_time"


def test_operations_without_valid_times_are_explicit() -> None:
    decisions = match_failure_to_operations(
        datetime(2024, 1, 1), None, [TimedOperation(1, None, None)]
    )
    assert decisions[0].status == "missing_operation_time"


def test_midnight_rollover_is_normalized_to_next_day() -> None:
    start, end, status, ambiguity = normalize_operation_interval(
        "23:30", "00:15", datetime(2024, 1, 1)
    )
    assert start == datetime(2024, 1, 1, 23, 30)
    assert end == datetime(2024, 1, 2, 0, 15)
    assert status == "midnight_rollover"
    assert ambiguity is None


def test_missing_activity_match_does_not_use_nearest_by_default() -> None:
    failure = datetime(2024, 1, 1)
    decisions = match_failure_to_operations(
        failure,
        None,
        [TimedOperation(1, failure + timedelta(hours=6), failure + timedelta(hours=7))],
    )
    assert decisions[0].status == "unmatched"
    assert decisions[0].operation_key is None
