from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str
    page_number: int
    section: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    extraction_method: str = "native_pdf"


class PageExtraction(BaseModel):
    page_number: int
    width: float
    height: float
    native_character_count: int
    deduplicated_character_count: int
    text: str
    table_count: int


class SectionExtraction(BaseModel):
    section_type: str
    heading_raw: str
    page_number: int
    text: str
    row_count: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 1.0


class OperationExtraction(BaseModel):
    row_index: int
    page_number: int
    start_time_raw: str | None = None
    end_time_raw: str | None = None
    duration_hours: float | None = None
    end_depth_raw: str | None = None
    end_depth_mmd: float | None = None
    end_depth_missing_reason: str | None = None
    main_activity_raw: str | None = None
    sub_activity_raw: str | None = None
    main_activity_normalized: str | None = None
    sub_activity_normalized: str | None = None
    state_raw: str | None = None
    state_normalized: str | None = None
    remark: str | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    temporal_status: str = "unprocessed"
    temporal_ambiguity: str | None = None
    raw_values: dict[str, Any] = Field(default_factory=dict)
    normalized_values: dict[str, Any] = Field(default_factory=dict)
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 1.0


class EquipmentFailureExtraction(BaseModel):
    table_index: int
    row_index: int
    page_number: int
    start_time_raw: str | None = None
    end_time_raw: str | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    depth_mmd_raw: str | None = None
    depth_mmd: float | None = None
    depth_mtvd_raw: str | None = None
    depth_mtvd: float | None = None
    failed_equipment_raw: str | None = None
    failed_equipment_normalized: str | None = None
    system_class_raw: str | None = None
    system_class_normalized: str | None = None
    operational_downtime_raw: str | None = None
    operational_downtime_minutes: float | None = None
    equipment_repaired_raw: str | None = None
    failure_remark: str | None = None
    temporal_status: str = "unprocessed"
    temporal_ambiguity: str | None = None
    raw_values: dict[str, Any] = Field(default_factory=dict)
    normalized_values: dict[str, Any] = Field(default_factory=dict)
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 1.0


class ExtractedField(BaseModel):
    field_name: str
    raw_value: str | None
    normalized_text: str | None = None
    normalized_number: float | None = None
    unit_raw: str | None = None
    unit_normalized: str | None = None
    missing_reason: str | None = None
    provenance: Provenance
    confidence: float = 1.0


class ParsedReport(BaseModel):
    source_path: str
    file_name: str
    sha256: str
    pdf_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[PageExtraction]
    wellbore: str | None = None
    filename_wellbore: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    filename_date: date | None = None
    spud_date: datetime | None = None
    report_number: int | None = None
    status_raw: str | None = None
    summary_activities: str | None = None
    summary_planned: str | None = None
    filename_identity_match: bool | None = None
    filename_date_match: bool | None = None
    excluded_from_default_trends: bool = False
    sections: list[SectionExtraction] = Field(default_factory=list)
    operations: list[OperationExtraction] = Field(default_factory=list)
    equipment_failures: list[EquipmentFailureExtraction] = Field(default_factory=list)
    fields: list[ExtractedField] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    sentinel_count: int = 0
