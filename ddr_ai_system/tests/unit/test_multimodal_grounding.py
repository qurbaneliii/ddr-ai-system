from __future__ import annotations

import hashlib
import io
from datetime import date

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ddr_ai.chat.multimodal import load_plot_image_context
from ddr_ai.chat.service import answer_question
from ddr_ai.db.models import Base, Plot, PlotPoint, SourceDocument, StoredAsset
from ddr_ai.nlp.providers import (
    BaseLLMProvider,
    ChatResult,
    LexicalFallbackProvider,
    LLMProviderError,
    ProviderHealth,
)


class VisualProvider(BaseLLMProvider):
    name = "visual-test"
    mode_label = "Visual test provider"
    model = "visual-test-model"
    supports_images = True

    def __init__(self, response: str | None = None, *, fail: bool = False) -> None:
        self.response = response or "The chart shows multiple colored series and a rising shape."
        self.fail = fail
        self.image_calls = 0

    def health_check(self, *, force: bool = False) -> ProviderHealth:
        del force
        return ProviderHealth(True, "test", self.model, not self.fail)

    def chat(self, messages, *, json_schema=None, max_output_tokens=None) -> ChatResult:
        del messages, json_schema, max_output_tokens
        raise AssertionError("Selected-plot flow must not make a second paid text call.")

    def describe_image(self, image_bytes: bytes, *, mime_type: str, prompt: str) -> ChatResult:
        self.image_calls += 1
        assert image_bytes and mime_type == "image/jpeg"
        assert "unknown" in prompt
        if self.fail:
            raise LLMProviderError("Sanitized visual provider failure.")
        return ChatResult(self.response, self.model)


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (120, 80), color=(240, 245, 250)).save(output, format="PNG")
    return output.getvalue()


def _context() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    content = _png()
    digest = hashlib.sha256(content).hexdigest()
    document = SourceDocument(
        sha256=digest,
        file_name="pressure_time_plot_99.png",
        source_path="unsafe/outside/path.png",
        media_type="image/png",
        asset_kind="pressure_time",
        byte_size=len(content),
        parser_version="test",
        processing_status="complete",
    )
    session.add(document)
    session.flush()
    plot = Plot(
        source_document_id=document.id,
        plot_type="pressure_time",
        plot_identifier="pressure_time_plot_99",
        width=120,
        height=80,
        plot_bbox_json={"left": 0, "top": 0, "right": 120, "bottom": 80},
        x_axis_label="DATE",
        y_axis_label="Pressure",
        x_unit="date",
        y_unit=None,
        unit_status="unknown",
        calibration_json={"method": "test"},
        confidence=0.9,
        warnings_json=[{"code": "pressure_unit_unresolved"}],
    )
    session.add(plot)
    session.flush()
    for index, value in enumerate((100.0, 110.0, 120.0)):
        session.add(
            PlotPoint(
                plot_id=plot.id,
                point_index=index,
                series_identifier="Well_01",
                pixel_x=float(index),
                pixel_y=float(index),
                y_value=value,
                observed_date=date(2026, 1, index + 1),
                confidence=0.9,
                source_bbox_json={"x0": 0, "y0": 0, "x1": 1, "y1": 1},
            )
        )
    session.add(
        StoredAsset(
            source_document_id=document.id,
            sha256=digest,
            file_name=document.file_name,
            media_type="image/png",
            byte_size=len(content),
            storage_backend="database",
            storage_key=f"sha256/{digest[:2]}/{digest}",
            storage_status="stored",
            content_bytes=content,
        )
    )
    session.commit()
    return session, load_plot_image_context(session, plot.id)


def test_selected_plot_uses_one_grounded_visual_call() -> None:
    session, context = _context()
    provider = VisualProvider()
    answer = answer_question(
        session,
        "Describe the selected pressure-time plot without assuming its pressure unit.",
        provider=provider,
        plot_context=context,
    )
    assert provider.image_calls == 1
    assert answer.visual_analysis_used is True
    assert answer.visual_validation_status == "accepted"
    assert answer.selected_plot_identifier == "pressure_time_plot_99"
    assert "Visual description" in answer.answer
    assert answer.visual_model == "visual-test-model"


def test_hallucinated_unit_and_number_are_rejected() -> None:
    session, context = _context()
    provider = VisualProvider("The pressure reaches 500 PSI and confirms an anomaly.")
    answer = answer_question(
        session,
        "Describe the selected plot.",
        provider=provider,
        plot_context=context,
    )
    assert answer.visual_analysis_used is False
    assert answer.visual_validation_status == "rejected"
    assert "500 PSI" not in answer.answer
    assert answer.fallback_reason and "unit is unknown" in answer.fallback_reason


def test_disabled_or_failed_visual_provider_returns_deterministic_facts() -> None:
    session, context = _context()
    lexical = answer_question(
        session,
        "Describe the selected plot.",
        provider=LexicalFallbackProvider("Images disabled for test."),
        plot_context=context,
    )
    assert lexical.visual_validation_status == "deterministic_fallback"
    assert lexical.visual_analysis_used is False
    assert "y unit is unknown" in lexical.answer

    failed = answer_question(
        session,
        "Describe the selected plot.",
        provider=VisualProvider(fail=True),
        plot_context=context,
    )
    assert failed.visual_validation_status == "provider_error_fallback"
    assert "Sanitized visual provider failure" in (failed.fallback_reason or "")
