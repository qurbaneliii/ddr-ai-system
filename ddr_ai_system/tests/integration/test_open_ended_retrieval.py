from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ddr_ai.chat.grounding import unsupported_claim_reason
from ddr_ai.chat.query import QUERY_PLAN_SCHEMA, QueryAnalyzer
from ddr_ai.chat.service import answer_question
from ddr_ai.db.models import (
    Base,
    EquipmentFailure,
    ExtractedValue,
    Operation,
    Report,
    ReportSection,
    RetrievalChunk,
    SectionTableRow,
    SourceDocument,
)
from ddr_ai.nlp.providers import BaseLLMProvider, ChatResult, ProviderHealth
from ddr_ai.retrieval.corpus import backfill_retrieval_chunks


def corpus_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    document = SourceDocument(
        sha256="c" * 64,
        file_name="15_9-F-14_2008-06-14.pdf",
        source_path="fixture.pdf",
        media_type="application/pdf",
        asset_kind="digital_pdf",
        byte_size=100,
        parser_version="test",
        processing_status="complete",
    )
    session.add(document)
    session.flush()
    report = Report(
        source_document_id=document.id,
        wellbore="15/9-F-14",
        period_start=datetime(2008, 6, 13),
        period_end=datetime(2008, 6, 14),
        summary_activities="Drilled ahead, reamed and circulated before cementing.",
        summary_planned="Run casing and continue cementing operations.",
        filename_identity_match=True,
        filename_date_match=True,
        data_quality_status="passed_automated_checks",
    )
    session.add(report)
    session.flush()
    session.add_all(
        [
            ReportSection(
                report_id=report.id,
                section_type="operations",
                heading_raw="Operations",
                page_number=2,
                text="Lost circulation was observed; the stuck pipe was freed after circulation.",
            ),
            ReportSection(
                report_id=report.id,
                section_type="drilling_fluid",
                heading_raw="Drilling Fluid",
                page_number=3,
                text="Mud weight and fluid density were recorded with rheology properties.",
            ),
            Operation(
                report_id=report.id,
                row_index=0,
                page_number=2,
                start_time_raw="08:00",
                end_time_raw="12:00",
                duration_hours=4.0,
                main_activity_raw="Drilling",
                main_activity_normalized="drilling",
                sub_activity_raw="Circulate and ream",
                sub_activity_normalized="circulation",
                state_normalized="normal",
                remark="Circulation losses followed by cementing preparation",
                confidence=1.0,
            ),
            ExtractedValue(
                source_document_id=document.id,
                page_number=3,
                section_type="drilling_fluid",
                field_name="Mud weight",
                raw_value="1.20",
                normalized_number=1.2,
                unit_raw="sg",
                unit_normalized="sg",
                value_origin="source_fact",
            ),
        ]
    )
    session.flush()
    fluid_section = session.scalar(
        select(ReportSection).where(ReportSection.section_type == "drilling_fluid")
    )
    session.add(
        SectionTableRow(
            source_document_id=document.id,
            report_id=report.id,
            report_section_id=fluid_section.id if fluid_section else None,
            page_number=3,
            section_type="drilling_fluid",
            table_index=1,
            row_index=1,
            header_cells_json=["Property", "Value", "Unit"],
            raw_cells_json=["Fluid density", "1.20", "sg"],
            normalized_cells_json=[{"field": "fluid density", "value": 1.2, "unit": "sg"}],
            table_bbox_json={"x0": 0.0, "top": 0.0, "x1": 1.0, "bottom": 1.0},
        )
    )
    session.add(
        EquipmentFailure(
            report_id=report.id,
            source_document_id=document.id,
            page_number=4,
            table_index=2,
            row_index=1,
            failed_equipment_raw="top drive",
            failed_equipment_normalized="top drive",
            system_class_raw="hoisting equipment",
            system_class_normalized="hoisting equipment",
            operational_downtime_raw="30",
            operational_downtime_minutes=30,
            failure_remark="Top drive breakdown caused downtime; mud pump inspected.",
            temporal_status="valid",
            raw_values_json={},
            normalized_values_json={},
        )
    )
    session.commit()
    result = backfill_retrieval_chunks(session)
    session.commit()
    assert result["chunks"] >= 7
    return session


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("What drilling problems were reported across the corpus?", "en"),
        ("Which reports mention cementing operations?", "en"),
        ("What drilling-fluid properties are available?", "en"),
        ("Which reports mention circulation losses?", "en"),
        ("Bu DDR-lərdə əsas qazma fəaliyyətləri hansılardır?", "az"),
        ("Cementing əməliyyatı hansı hesabatlarda qeyd olunub?", "az"),
        ("Lost circulation və stuck pipe haqqında hansı qeydlər var?", "az"),
    ],
)
def test_broad_questions_return_source_backed_evidence(question: str, language: str) -> None:
    session = corpus_session()
    answer = answer_question(session, question)
    assert answer.route == "corpus_retrieval"
    assert answer.detected_language == language
    assert answer.evidence_hit_count > 0
    assert answer.evidence
    assert answer.evidence[0]["file_name"] == "15_9-F-14_2008-06-14.pdf"
    assert answer.evidence[0]["page_number"] is not None
    assert answer.evidence[0]["section"]
    assert "Try a supported structured question or process the source corpus" not in answer.answer


def test_unified_chunks_cover_every_report_source_type_and_are_idempotent() -> None:
    session = corpus_session()
    first = backfill_retrieval_chunks(session)
    session.commit()
    first_count = session.scalar(select(func.count(RetrievalChunk.id)))
    second = backfill_retrieval_chunks(session)
    session.commit()
    assert second["chunks"] == first["chunks"]
    assert session.scalar(select(func.count(RetrievalChunk.id))) == first_count
    assert set(second["source_types"]) == {
        "equipment_failure",
        "extracted_value",
        "operation",
        "report_section",
        "report_summary",
        "section_table_row",
    }


def test_follow_up_is_rewritten_but_history_is_not_evidence() -> None:
    session = corpus_session()
    previous = "15/9-F-14 üçün tamamlanan və planlaşdırılan fəaliyyətlər nə idi?"
    answer = answer_question(
        session,
        "Bunlardan ən sonuncusu hansı tarixdə olub?",
        history=[
            {"role": "user", "content": previous},
            {"role": "assistant", "content": "Untrusted prior wording."},
        ],
    )
    assert answer.route == "structured_report_lookup"
    assert answer.rewritten_query and previous in answer.rewritten_query
    assert answer.rows[0]["wellbore"] == "15/9-F-14"
    assert "mənbə-dəstəkli hesabat xülasəsi" in answer.answer
    assert "Untrusted prior wording" not in str(answer.evidence)


@pytest.mark.parametrize(
    "question",
    [
        "What is the current oil price?",
        "Summarize completed activities for 99/99-Z-99.",
        "What happened on 2099-01-01?",
    ],
)
def test_out_of_corpus_questions_are_truthful(question: str) -> None:
    answer = answer_question(corpus_session(), question)
    assert answer.route == "not_found_corpus"
    assert answer.evidence_hit_count == 0
    assert "not found in the processed DDR corpus" in answer.answer
    assert "process the source corpus" not in answer.answer


def test_citation_and_numeric_validator_rejects_unsupplied_claims() -> None:
    reason = unsupported_claim_reason(
        "The value was 9.9 according to invented.pdf.",
        "corpus_retrieval",
        [],
        [{"file_name": "fixture.pdf", "excerpt": "value 1.2"}],
        [],
        deterministic_answer="value 1.2",
    )
    assert reason and ("citation" in reason or "numeric" in reason)


class RecordingProvider(BaseLLMProvider):
    name = "recording"
    mode_label = "recording"
    model = "test"

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def health_check(self, *, force: bool = False) -> ProviderHealth:
        del force
        return ProviderHealth(True, "test", self.model, True)

    def chat(
        self,
        messages: Any,
        *,
        json_schema: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> ChatResult:
        self.requests.append(
            {"messages": messages, "json_schema": json_schema, "max_output_tokens": max_output_tokens}
        )
        payload = {
            "detected_language": "en",
            "intent": "narrative_corpus_search",
            "search_terms": ["cementing", "operations"],
            "wellbore": None,
            "date_from": None,
            "date_to": None,
            "report_id": None,
            "section_types": [],
            "activity_names": ["cementing"],
            "equipment_names": [],
            "metric": None,
            "aggregation": None,
            "sort_direction": None,
            "limit": 10,
            "standalone_question": "Which reports discuss cementing operations?",
            "confidence": 0.9,
        }
        return ChatResult(json.dumps(payload), self.model)


def test_unclear_question_uses_bounded_structured_query_analysis() -> None:
    provider = RecordingProvider()
    plan = QueryAnalyzer().analyze("Tell me about those items", "Auto", provider, history=[])
    assert plan.llm_used is True
    assert plan.intent == "narrative_corpus_search"
    assert provider.requests[0]["json_schema"] == QUERY_PLAN_SCHEMA
    assert provider.requests[0]["max_output_tokens"] == 400
