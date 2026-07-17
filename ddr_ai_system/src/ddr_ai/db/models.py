from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("sha256", name="uq_source_document_sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)

    pages: Mapped[list[Page]] = relationship(back_populates="document", cascade="all, delete-orphan")
    report: Mapped[Report | None] = relationship(back_populates="document", uselist=False,
                                                  cascade="all, delete-orphan")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("source_document_id", "page_number", name="uq_document_page"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    native_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deduplicated_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extraction_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    document: Mapped[SourceDocument] = relationship(back_populates="pages")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("source_document_id", name="uq_report_document"),
        Index("ix_reports_wellbore_period_end", "wellbore", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    wellbore: Mapped[str | None] = mapped_column(String(128), index=True)
    filename_wellbore: Mapped[str | None] = mapped_column(String(128))
    period_start: Mapped[datetime | None] = mapped_column(DateTime)
    period_end: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    filename_date: Mapped[date | None] = mapped_column(Date)
    spud_date: Mapped[datetime | None] = mapped_column(DateTime)
    report_number: Mapped[int | None] = mapped_column(Integer)
    status_raw: Mapped[str | None] = mapped_column(String(64))
    summary_activities: Mapped[str | None] = mapped_column(Text)
    summary_planned: Mapped[str | None] = mapped_column(Text)
    filename_identity_match: Mapped[bool | None] = mapped_column(Boolean)
    filename_date_match: Mapped[bool | None] = mapped_column(Boolean)
    excluded_from_default_trends: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data_quality_status: Mapped[str] = mapped_column(String(32), default="unreviewed", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    document: Mapped[SourceDocument] = relationship(back_populates="report")
    sections: Mapped[list[ReportSection]] = relationship(back_populates="report", cascade="all, delete-orphan")
    operations: Mapped[list[Operation]] = relationship(back_populates="report", cascade="all, delete-orphan")
    equipment_failures: Mapped[list[EquipmentFailure]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class ReportSection(Base):
    __tablename__ = "report_sections"
    __table_args__ = (Index("ix_sections_report_type", "report_id", "section_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    section_type: Mapped[str] = mapped_column(String(128), nullable=False)
    heading_raw: Mapped[str] = mapped_column(String(256), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    row_count: Mapped[int | None] = mapped_column(Integer)
    bbox_json: Mapped[dict[str, float] | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")

    report: Mapped[Report] = relationship(back_populates="sections")


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (Index("ix_operations_report_state", "report_id", "state_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_raw: Mapped[str | None] = mapped_column(String(32))
    end_time_raw: Mapped[str | None] = mapped_column(String(32))
    duration_hours: Mapped[float | None] = mapped_column(Float)
    end_depth_mmd_raw: Mapped[str | None] = mapped_column(String(64))
    end_depth_mmd: Mapped[float | None] = mapped_column(Float)
    end_depth_missing_reason: Mapped[str | None] = mapped_column(String(64))
    main_activity_raw: Mapped[str | None] = mapped_column(String(256))
    sub_activity_raw: Mapped[str | None] = mapped_column(String(256))
    main_activity_normalized: Mapped[str | None] = mapped_column(String(128), index=True)
    sub_activity_normalized: Mapped[str | None] = mapped_column(String(128))
    state_raw: Mapped[str | None] = mapped_column(String(64))
    state_normalized: Mapped[str | None] = mapped_column(String(64), index=True)
    remark: Mapped[str | None] = mapped_column(Text)
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    temporal_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unprocessed")
    temporal_ambiguity: Mapped[str | None] = mapped_column(Text)
    raw_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    normalized_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    bbox_json: Mapped[dict[str, float] | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")

    report: Mapped[Report] = relationship(back_populates="operations")


class ExtractedValue(Base):
    __tablename__ = "extracted_values"
    __table_args__ = (Index("ix_values_document_field", "source_document_id", "field_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_type: Mapped[str | None] = mapped_column(String(128))
    field_name: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    normalized_number: Mapped[float | None] = mapped_column(Float)
    unit_raw: Mapped[str | None] = mapped_column(String(64))
    unit_normalized: Mapped[str | None] = mapped_column(String(64))
    missing_reason: Mapped[str | None] = mapped_column(String(64))
    value_origin: Mapped[str] = mapped_column(String(32), nullable=False, default="source_fact")
    bbox_json: Mapped[dict[str, float] | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")


class SectionTableRow(Base):
    __tablename__ = "section_table_rows"
    __table_args__ = (
        UniqueConstraint(
            "source_document_id", "page_number", "table_index", "row_index",
            name="uq_section_table_source_row",
        ),
        Index("ix_section_table_report_type", "report_id", "section_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    report_section_id: Mapped[int | None] = mapped_column(ForeignKey("report_sections.id"))
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_type: Mapped[str] = mapped_column(String(128), nullable=False)
    table_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    header_cells_json: Mapped[list[str | None]] = mapped_column(JSON, nullable=False, default=list)
    raw_cells_json: Mapped[list[str | None]] = mapped_column(JSON, nullable=False, default=list)
    normalized_cells_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    table_bbox_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.9)
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unreviewed"
    )


class EquipmentFailure(Base):
    __tablename__ = "equipment_failures"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "page_number", "table_index", "row_index",
            name="uq_equipment_failure_source_row",
        ),
        Index("ix_equipment_failures_report_start", "report_id", "start_datetime"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    report_section_id: Mapped[int | None] = mapped_column(ForeignKey("report_sections.id"))
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_type: Mapped[str] = mapped_column(
        String(128), nullable=False, default="equipment_failure_information"
    )
    table_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_raw: Mapped[str | None] = mapped_column(String(32))
    end_time_raw: Mapped[str | None] = mapped_column(String(32))
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    depth_mmd_raw: Mapped[str | None] = mapped_column(String(64))
    depth_mmd: Mapped[float | None] = mapped_column(Float)
    depth_mtvd_raw: Mapped[str | None] = mapped_column(String(64))
    depth_mtvd: Mapped[float | None] = mapped_column(Float)
    failed_equipment_raw: Mapped[str | None] = mapped_column(String(256))
    failed_equipment_normalized: Mapped[str | None] = mapped_column(String(256), index=True)
    system_class_raw: Mapped[str | None] = mapped_column(String(256))
    system_class_normalized: Mapped[str | None] = mapped_column(String(256), index=True)
    operational_downtime_raw: Mapped[str | None] = mapped_column(String(64))
    operational_downtime_minutes: Mapped[float | None] = mapped_column(Float)
    equipment_repaired_raw: Mapped[str | None] = mapped_column(String(128))
    failure_remark: Mapped[str | None] = mapped_column(Text)
    temporal_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unprocessed")
    temporal_ambiguity: Mapped[str | None] = mapped_column(Text)
    raw_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    normalized_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    bbox_json: Mapped[dict[str, float] | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.9)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")

    report: Mapped[Report] = relationship(back_populates="equipment_failures")
    matches: Mapped[list[FailureOperationMatch]] = relationship(
        back_populates="failure", cascade="all, delete-orphan"
    )


class FailureOperationMatch(Base):
    __tablename__ = "failure_operation_matches"
    __table_args__ = (
        UniqueConstraint("equipment_failure_id", "operation_id", name="uq_failure_operation_match"),
        Index("ix_failure_matches_status", "match_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_failure_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_failures.id", ondelete="CASCADE"), nullable=False
    )
    operation_id: Mapped[int | None] = mapped_column(ForeignKey("operations.id"))
    match_status: Mapped[str] = mapped_column(String(64), nullable=False)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    matching_rule: Mapped[str] = mapped_column(String(256), nullable=False)
    time_difference_minutes: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    human_validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unreviewed"
    )

    failure: Mapped[EquipmentFailure] = relationship(back_populates="matches")


class Plot(Base):
    __tablename__ = "plots"
    __table_args__ = (UniqueConstraint("source_document_id", name="uq_plot_document"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    plot_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plot_identifier: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    plot_bbox_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    x_axis_label: Mapped[str | None] = mapped_column(String(256))
    y_axis_label: Mapped[str | None] = mapped_column(String(256))
    x_unit: Mapped[str | None] = mapped_column(String(64))
    y_unit: Mapped[str | None] = mapped_column(String(64))
    unit_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    calibration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    overlay_path: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)


class PlotPoint(Base):
    __tablename__ = "plot_points"
    __table_args__ = (Index("ix_plot_points_plot_series", "plot_id", "series_identifier"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int] = mapped_column(ForeignKey("plots.id"), nullable=False)
    point_index: Mapped[int] = mapped_column(Integer, nullable=False)
    series_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    pixel_x: Mapped[float] = mapped_column(Float, nullable=False)
    pixel_y: Mapped[float] = mapped_column(Float, nullable=False)
    x_value: Mapped[float | None] = mapped_column(Float)
    y_value: Mapped[float | None] = mapped_column(Float)
    observed_date: Mapped[date | None] = mapped_column(Date)
    reference_values_json: Mapped[dict[str, float | None]] = mapped_column(JSON, nullable=False, default=dict)
    band_classification: Mapped[str | None] = mapped_column(String(64), index=True)
    anomaly_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source_bbox_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)


class IdentityMapping(Base):
    __tablename__ = "identity_mappings"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_identifier", "target_namespace",
                         "target_identifier", name="uq_identity_mapping"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(256), nullable=False)
    target_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    target_identifier: Mapped[str] = mapped_column(String(256), nullable=False, default="unresolved")
    mapping_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unresolved")
    mapping_source: Mapped[str] = mapped_column(String(256), nullable=False, default="no_metadata")
    evidence: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    notes: Mapped[str | None] = mapped_column(Text)
    validated_by: Mapped[str | None] = mapped_column(String(256))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (Index("ix_anomalies_category_validation", "category", "validation_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    source_record_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_record_id: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_or_model: Mapped[str] = mapped_column(String(256), nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    severity_heuristic: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    domain_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class QueryAudit(Base):
    __tablename__ = "query_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    route: Mapped[str] = mapped_column(String(64), nullable=False)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(128))
