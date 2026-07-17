from __future__ import annotations

from pathlib import Path

from conftest import find_raw

from ddr_ai.plots import digitize_pressure_profile, digitize_pressure_time


def test_profile_plot_calibration_ten_markers_and_below_min(raw_dir: Path, tmp_path: Path) -> None:
    path = find_raw(raw_dir, "pressure_profiles", "Well_04_pressure_profile.png")
    result = digitize_pressure_profile(path, tmp_path / "profile_overlay.png")
    assert result["marker_count"] == 10
    assert result["calibration"]["x"] is not None
    assert result["calibration"]["y"] is not None
    assert result["calibration"]["x"]["rmse"] < 2
    assert sum(point["band_classification"] == "below_min" for point in result["points"]) == 1
    assert (tmp_path / "profile_overlay.png").exists()


def test_well_21_high_side_candidate_is_recomputed(raw_dir: Path) -> None:
    path = find_raw(raw_dir, "pressure_profiles", "Well_21_pressure_profile.png")
    result = digitize_pressure_profile(path)
    high = [point for point in result["points"] if point["band_classification"] in {"above_max", "above_virgin"}]
    assert len(result["points"]) == 10
    assert len(high) >= 1


def test_time_plot_dynamic_legend_date_calibration_and_colors(raw_dir: Path, tmp_path: Path) -> None:
    path = find_raw(raw_dir, "pressure_time_plots", "pressure_time_plot_01.png")
    result = digitize_pressure_time(path, tmp_path / "time_overlay.png")
    assert result["legend_markers_excluded"] == 4
    assert result["point_count"] == 23
    assert result["series_counts"] == {"Well_01": 4, "Well_02": 6, "Well_03": 5, "Well_04": 8}
    assert result["calibration"]["x"] is not None
    assert result["calibration"]["y"] is not None
    assert result["unit_status"] == "unknown"

