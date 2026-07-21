from __future__ import annotations

import pytest

from ddr_ai.analytics.events import normalize_activity, normalize_activity_result


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("formationevaluation", "formation_evaluation"),
        ("plugabandon", "plug_abandon"),
        ("Plug / Abandon", "plug_abandon"),
    ],
)
def test_main_activity_variants_are_canonical(raw: str, expected: str) -> None:
    result, _ = normalize_activity_result(raw, "other")
    assert result.canonical_label == expected
    assert result.method in {"canonical", "alias"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("wire line", "wireline"),
        ("bop/wellheadequipment", "bop_wellhead_equipment"),
        ("circulatingconditioning", "circulating_conditioning"),
        ("rigup/down", "rig_up_down"),
        ("waitingon weather", "waiting_on_weather"),
        ("lostcirculation", "lost_circulation"),
        ("drill stemtest", "drill_stem_test"),
        ("wellcontrol", "well_control"),
    ],
)
def test_subactivity_spacing_slash_and_concatenation_variants(
    raw: str, expected: str
) -> None:
    _, result = normalize_activity_result("drilling", raw)
    assert result.canonical_label == expected
    assert result.confidence >= 0.99


def test_unknown_labels_are_not_silently_mapped() -> None:
    main, sub = normalize_activity_result("novel operation", "mystery task")
    assert main.canonical_label == sub.canonical_label == "unknown"
    assert main.method == sub.method == "unknown"
    assert normalize_activity("novel operation", "mystery task") == ("unknown", "unknown")
