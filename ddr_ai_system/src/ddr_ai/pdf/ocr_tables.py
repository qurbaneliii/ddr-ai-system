from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean

from ddr_ai.models.schemas import (
    EquipmentFailureExtraction,
    ExtractedField,
    OperationExtraction,
    Provenance,
)
from ddr_ai.pdf.ocr_contracts import OCRToken
from ddr_ai.pdf.parser import equipment_failure_from_cells, operation_from_cells

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
KEY_VALUE_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9 /()_-]{2,80}):\s*(?P<value>.+)$")


@dataclass(slots=True)
class OCRStructuredResult:
    operations: list[OperationExtraction] = field(default_factory=list)
    equipment_failures: list[EquipmentFailureExtraction] = field(default_factory=list)
    fields: list[ExtractedField] = field(default_factory=list)
    warnings: list[dict[str, object]] = field(default_factory=list)
    table_count: int = 0


def _rows(tokens: tuple[OCRToken, ...]) -> list[list[OCRToken]]:
    grouped: dict[tuple[int, int, int], list[OCRToken]] = {}
    for token in tokens:
        grouped.setdefault((token.block, token.paragraph, token.line), []).append(token)
    return sorted(
        (sorted(items, key=lambda item: item.x0) for items in grouped.values()),
        key=lambda items: (mean((item.y0 + item.y1) / 2 for item in items), items[0].x0),
    )


def _line_text(tokens: list[OCRToken]) -> str:
    return " ".join(item.text for item in tokens if item.text.strip()).strip()


def _bbox(tokens: list[OCRToken]) -> tuple[float, float, float, float] | None:
    if not tokens:
        return None
    return (
        min(item.x0 for item in tokens),
        min(item.y0 for item in tokens),
        max(item.x1 for item in tokens),
        max(item.y1 for item in tokens),
    )


def _confidence(tokens: list[OCRToken]) -> float:
    values = [item.confidence for item in tokens if item.text.strip()]
    return round(sum(values) / len(values), 4) if values else 0.0


def _token_x(tokens: list[OCRToken], terms: tuple[str, ...], *, occurrence: int = 0) -> float | None:
    matches = [
        item.x0
        for item in tokens
        if any(term in re.sub(r"[^a-z0-9]+", "", item.text.casefold()) for term in terms)
    ]
    return matches[occurrence] if len(matches) > occurrence else None


def _starts(header: list[OCRToken], kind: str) -> list[float]:
    left = min(item.x0 for item in header)
    right = max(item.x1 for item in header)
    width = max(right - left, 1.0)
    if kind == "operations":
        end_values = sorted(
            item.x0
            for item in header
            if re.sub(r"[^a-z0-9]+", "", item.text.casefold()) == "end"
        )
        values = [
            _token_x(header, ("start",)),
            end_values[0] if end_values else None,
            _token_x(header, ("depth",)) or (end_values[1] if len(end_values) > 1 else None),
            _token_x(header, ("activity", "main")),
            _token_x(header, ("state",)),
            _token_x(header, ("remark",)),
        ]
        fractions: tuple[float, ...] = (0.0, 0.11, 0.22, 0.38, 0.72, 0.82)
    else:
        values = [
            _token_x(header, ("start",)),
            _token_x(header, ("mmd", "depth")),
            _token_x(header, ("mtvd",), occurrence=0),
            _token_x(header, ("equip", "system")),
            _token_x(header, ("downtime", "operation")),
            _token_x(header, ("repaired",)),
            _token_x(header, ("remark",)),
        ]
        fractions = (0.0, 0.11, 0.22, 0.34, 0.62, 0.76, 0.86)
    starts = [value if value is not None else left + width * fraction for value, fraction in zip(values, fractions, strict=True)]
    for index in range(1, len(starts)):
        if starts[index] <= starts[index - 1]:
            starts[index] = starts[index - 1] + max(2.0, width * 0.04)
    return starts


def _cells(tokens: list[OCRToken], starts: list[float]) -> list[str | None]:
    boundaries = starts[1:]
    values: list[list[str]] = [[] for _ in starts]
    for token in tokens:
        column = sum(token.x0 >= boundary for boundary in boundaries)
        values[min(column, len(values) - 1)].append(token.text)
    return [" ".join(value).strip() or None for value in values]


def reconstruct_ddr_tables(
    tokens: tuple[OCRToken, ...],
    text: str,
    *,
    page_number: int,
    source_path: str,
) -> OCRStructuredResult:
    result = OCRStructuredResult()
    rows = _rows(tokens)
    operation_index = next(
        (
            index
            for index, row in enumerate(rows)
            if all(term in _line_text(row).casefold() for term in ("start", "state", "remark"))
            and "end" in _line_text(row).casefold()
        ),
        None,
    )
    if operation_index is not None:
        starts = _starts(rows[operation_index], "operations")
        row_index = 0
        for row in rows[operation_index + 1 :]:
            values = _cells(row, starts)
            if values[0] and TIME_RE.fullmatch(values[0].replace(" ", "")):
                operation = operation_from_cells(
                    values,
                    row_index=row_index,
                    page_number=page_number,
                    table_index=operation_index,
                    table_row_index=row_index + 1,
                    bbox=_bbox(row),
                    confidence=_confidence(row),
                )
                if operation is not None:
                    operation.raw_values["extraction_method"] = "ocr_layout"
                    result.operations.append(operation)
                    row_index += 1
            elif result.operations and values[-1]:
                previous = result.operations[-1]
                previous.remark = " ".join(filter(None, (previous.remark, values[-1])))
        if result.operations:
            result.table_count += 1

    failure_index = next(
        (
            index
            for index, row in enumerate(rows)
            if "start" in _line_text(row).casefold()
            and "downtime" in _line_text(row).casefold().replace(" ", "")
            and "remark" in _line_text(row).casefold()
        ),
        None,
    )
    if failure_index is not None:
        starts = _starts(rows[failure_index], "failure")
        headers: list[str | None] = [
            "Start time",
            "Depth mMD",
            "Depth mTVD",
            "Sub Equip - Syst Class",
            "Operation Downtime (min)",
            "Equipment Repaired",
            "Remark",
        ]
        for row_index, row in enumerate(rows[failure_index + 1 :], start=1):
            values = _cells(row, starts)
            if not values[0] or not TIME_RE.fullmatch(values[0].replace(" ", "")):
                continue
            failure = equipment_failure_from_cells(
                headers,
                values,
                table_index=failure_index,
                row_index=row_index,
                page_number=page_number,
                bbox=_bbox(row),
            )
            if failure is not None:
                failure.confidence = _confidence(row)
                failure.raw_values["extraction_method"] = "ocr_layout"
                result.equipment_failures.append(failure)
        if result.equipment_failures:
            result.table_count += 1

    for line in text.splitlines():
        match = KEY_VALUE_RE.match(" ".join(line.split()))
        if not match:
            continue
        label = match.group("label").strip()
        value = match.group("value").strip()
        if label.casefold() in {"wellbore", "period", "status", "report number", "spud date"}:
            continue
        result.fields.append(
            ExtractedField(
                field_name=label,
                raw_value=value,
                normalized_text=value,
                provenance=Provenance(
                    source_path=source_path,
                    page_number=page_number,
                    section="ocr_key_value",
                    extraction_method="ocr",
                ),
                confidence=_confidence(list(tokens)),
            )
        )

    uncertain = sum(item.confidence < 0.6 for item in result.operations)
    uncertain += sum(item.confidence < 0.6 for item in result.equipment_failures)
    if uncertain:
        result.warnings.append(
            {
                "code": "ocr_uncertain_structured_rows",
                "severity": "medium",
                "page_number": page_number,
                "row_count": uncertain,
            }
        )
    return result
