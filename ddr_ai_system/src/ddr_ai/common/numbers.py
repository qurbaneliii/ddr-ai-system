from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

SENTINELS = {Decimal("-999.99"), Decimal("-999.9")}


@dataclass(frozen=True, slots=True)
class NormalizedNumber:
    raw_value: str | None
    value: float | None
    missing_reason: str | None = None


def normalize_number(raw: object) -> NormalizedNumber:
    if raw is None:
        return NormalizedNumber(None, None, "source_blank")
    text = str(raw).strip()
    if not text:
        return NormalizedNumber(text, None, "source_blank")
    normalized = text.replace(" ", "")
    if "," in normalized and "." not in normalized:
        normalized = normalized.replace(",", ".")
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return NormalizedNumber(text, None, "not_numeric")
    if number in SENTINELS:
        return NormalizedNumber(text, None, "source_sentinel")
    return NormalizedNumber(text, float(number), None)

