from __future__ import annotations

from datetime import date

import pytest

from ddr_ai.analytics.trends import TrendObservation, compatible_parameter_trend


def _series(values: list[float], *, unit: str = "sg") -> list[TrendObservation]:
    return [
        TrendObservation(date(2026, 1, index + 1), value, unit)
        for index, value in enumerate(values)
    ]


@pytest.mark.parametrize(
    ("values", "direction"),
    [
        ([1.0, 2.0, 3.0, 4.0, 5.0], "increasing"),
        ([5.0, 4.0, 3.0, 2.0, 1.0], "decreasing"),
        ([2.0, 2.0, 2.0, 2.0, 2.0], "stable_or_uncertain"),
    ],
)
def test_compatible_parameter_trend_directions(values: list[float], direction: str) -> None:
    result = compatible_parameter_trend(_series(values))
    assert result["applicable"] is True
    assert result["direction"] == direction
    assert result["unit"] == "sg"


def test_parameter_trend_rejects_mixed_and_unknown_units() -> None:
    mixed = _series([1, 2, 3, 4])
    mixed[-1] = TrendObservation(date(2026, 1, 4), 4.0, "ppg")
    assert compatible_parameter_trend(mixed)["reason"] == "Known units are mixed and cannot be combined."
    unknown = _series([1, 2, 3, 4], unit="unknown")
    result = compatible_parameter_trend(unknown)
    assert result["applicable"] is False
    assert result["excluded_reasons"] == {"unknown_unit": 4}


def test_parameter_trend_collapses_duplicates_and_reports_exclusions() -> None:
    observations = [
        *_series([1.0, 2.0, 3.0, 4.0]),
        TrendObservation(date(2026, 1, 2), 2.2, "sg"),
        TrendObservation(None, 9.0, "sg"),
        TrendObservation(date(2026, 1, 5), 5.0, "sg", included=False),
    ]
    result = compatible_parameter_trend(observations)
    assert result["applicable"] is True
    assert result["duplicate_date_count"] == 1
    assert result["included_record_count"] == 5
    assert result["excluded_reasons"] == {
        "invalid_or_missing_date": 1,
        "data_quality_exclusion": 1,
    }


def test_parameter_trend_requires_four_distinct_dates() -> None:
    result = compatible_parameter_trend(_series([1.0, 2.0, 3.0]))
    assert result["applicable"] is False
    assert "four paired" in result["reason"]
