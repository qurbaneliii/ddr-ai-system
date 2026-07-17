from __future__ import annotations

import re

MAIN_ACTIVITY_ALIASES = {
    "drilling": "drilling",
    "interruption": "interruption",
    "plug abandon": "plug_abandon",
    "plug and abandon": "plug_abandon",
    "workover": "workover",
    "completion": "completion",
    "formation evaluation": "formation_evaluation",
    "moving": "moving",
}

SUB_ACTIVITY_ALIASES = {
    "surv ey": "survey",
    "survey": "survey",
    "drill": "drill",
    "trip": "trip",
    "casing": "casing",
    "ream": "ream",
    "circulating conditioning": "circulating_conditioning",
    "circulating/conditioning": "circulating_conditioning",
    "bop wellhead equipment": "bop_wellhead_equipment",
    "repair": "repair",
    "waiting on weather": "waiting_on_weather",
    "lost circulation": "lost_circulation",
    "well control": "well_control",
    "wireline": "wireline",
    "perforate": "perforate",
    "cement mechanical plug": "cement_mechanical_plug",
}


def _key(value: str | None) -> str | None:
    if not value:
        return None
    text = value.replace("\n", "")
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    return " ".join(text.split())


def normalize_activity(main: str | None, sub: str | None) -> tuple[str | None, str | None]:
    main_key = _key(main)
    sub_key = _key(sub)
    return (
        MAIN_ACTIVITY_ALIASES.get(main_key or "", main_key or "unknown"),
        SUB_ACTIVITY_ALIASES.get(sub_key or "", sub_key or "unknown"),
    )

