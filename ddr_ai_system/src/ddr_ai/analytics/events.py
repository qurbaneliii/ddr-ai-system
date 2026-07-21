from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

NormalizationMethod = Literal["canonical", "alias", "unknown"]

CANONICAL_MAIN_ACTIVITIES = frozenset(
    {
        "completion",
        "drilling",
        "formation_evaluation",
        "interruption",
        "moving",
        "plug_abandon",
        "workover",
    }
)

CANONICAL_SUBACTIVITIES = frozenset(
    {
        "anchor",
        "bop_activities",
        "bop_wellhead_equipment",
        "casing",
        "cement_plug",
        "circulating_conditioning",
        "circulation_samples",
        "completion_string",
        "core",
        "cut",
        "drill",
        "drill_stem_test",
        "equipment_recovery",
        "fish",
        "hole_open",
        "log",
        "lost_circulation",
        "maintain",
        "mechanical_plug",
        "mill",
        "other",
        "perforate",
        "position",
        "pressure_detection",
        "ream",
        "repair",
        "rft_fit",
        "rig_up_down",
        "sidetrack",
        "skid",
        "squeeze",
        "survey",
        "test_scsssv",
        "transit",
        "trip",
        "wait",
        "waiting_on_weather",
        "well_control",
        "wireline",
    }
)


@dataclass(frozen=True, slots=True)
class ActivityNormalizationResult:
    raw_label: str | None
    canonical_label: str
    method: NormalizationMethod
    confidence: float
    matched_alias: str | None = None


def _key(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    text = value.replace("\n", "")
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    return " ".join(text.split()) or None


def _canonical_keys(vocabulary: frozenset[str]) -> dict[str, str]:
    return {_key(value) or value: value for value in vocabulary}


MAIN_ACTIVITY_ALIASES = {
    "formationevaluation": "formation_evaluation",
    "plug abandon": "plug_abandon",
    "plug and abandon": "plug_abandon",
    "plugabandon": "plug_abandon",
}

SUB_ACTIVITY_ALIASES = {
    "bop activities": "bop_activities",
    "bopactivities": "bop_activities",
    "bop wellhead equipment": "bop_wellhead_equipment",
    "bop wellheadequipment": "bop_wellhead_equipment",
    "cement plug": "cement_plug",
    "cementplug": "cement_plug",
    "circulating conditioning": "circulating_conditioning",
    "circulatingconditioning": "circulating_conditioning",
    "circulation samples": "circulation_samples",
    "completion string": "completion_string",
    "drill stem test": "drill_stem_test",
    "drill stemtest": "drill_stem_test",
    "drillstem test": "drill_stem_test",
    "equipment recovery": "equipment_recovery",
    "hole open": "hole_open",
    "lost circulation": "lost_circulation",
    "lostcirculation": "lost_circulation",
    "mechanical plug": "mechanical_plug",
    "mechanicalplug": "mechanical_plug",
    "pressure detection": "pressure_detection",
    "pressuredetection": "pressure_detection",
    "rft fit": "rft_fit",
    "rig up down": "rig_up_down",
    "rigup down": "rig_up_down",
    "surv ey": "survey",
    "test scsssv": "test_scsssv",
    "testscsssv": "test_scsssv",
    "waiting on weather": "waiting_on_weather",
    "waiting onweather": "waiting_on_weather",
    "waitingon weather": "waiting_on_weather",
    "well control": "well_control",
    "wellcontrol": "well_control",
    "wire line": "wireline",
}


def normalize_label(
    raw_label: str | None,
    *,
    vocabulary: frozenset[str],
    aliases: dict[str, str],
) -> ActivityNormalizationResult:
    key = _key(raw_label)
    if key is None:
        return ActivityNormalizationResult(raw_label, "unknown", "unknown", 0.0)
    canonical = _canonical_keys(vocabulary).get(key)
    if canonical is not None:
        return ActivityNormalizationResult(raw_label, canonical, "canonical", 1.0, key)
    alias = aliases.get(key)
    if alias is not None:
        return ActivityNormalizationResult(raw_label, alias, "alias", 0.99, key)
    return ActivityNormalizationResult(raw_label, "unknown", "unknown", 0.0)


def normalize_activity_result(
    main: str | None, sub: str | None
) -> tuple[ActivityNormalizationResult, ActivityNormalizationResult]:
    return (
        normalize_label(
            main,
            vocabulary=CANONICAL_MAIN_ACTIVITIES,
            aliases=MAIN_ACTIVITY_ALIASES,
        ),
        normalize_label(
            sub,
            vocabulary=CANONICAL_SUBACTIVITIES,
            aliases=SUB_ACTIVITY_ALIASES,
        ),
    )


def normalize_activity(main: str | None, sub: str | None) -> tuple[str, str]:
    """Compatibility tuple API backed by the explicit canonical taxonomy."""

    main_result, sub_result = normalize_activity_result(main, sub)
    return main_result.canonical_label, sub_result.canonical_label

