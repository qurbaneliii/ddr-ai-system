from __future__ import annotations

from ddr_ai.chat.grounding import (
    analyze_question,
    detect_language,
    deterministic_retrieval_query,
    grounded_verbalize,
    unsupported_claim_reason,
)
from ddr_ai.config import Settings
from ddr_ai.nlp.providers import ChatResult, OllamaProvider


class ScriptedOllamaProvider(OllamaProvider):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(Settings(ollama_max_retries=0, _env_file=None))
        self.responses = responses
        self.calls = 0

    def chat(self, messages, *, json_schema=None):
        del messages, json_schema
        response = self.responses[self.calls]
        self.calls += 1
        return ChatResult(response, self.model, prompt_eval_count=10, eval_count=5)


def test_azerbaijani_english_and_mixed_language_detection() -> None:
    assert detect_language("Hansı quyularda avadanlıq nasazlığı baş verib?") == "az"
    assert detect_language("Which wellbores had equipment failure?") == "en"
    assert detect_language("Hansı wellbore had equipment nasazlığı?") == "mixed"


def test_azerbaijani_query_rewriting_uses_english_ddr_terms() -> None:
    rewritten = deterministic_retrieval_query(
        "Hansı quyularda avadanlıq nasazlığı baş verib və hansı əməliyyat aparılırdı?"
    )
    assert "equipment failure" in rewritten
    assert "operations" in rewritten
    assert "wellbore" in rewritten


def test_ollama_structured_query_analysis_preserves_azerbaijani_target() -> None:
    provider = ScriptedOllamaProvider([
        '{"detected_language":"az","route":"structured",'
        '"english_retrieval_query":"equipment failure operation temporal match",'
        '"intent":"equipment_failure_activity","slots":{}}'
    ])
    analysis = analyze_question(
        "Hansı quyularda avadanlıq nasazlığı baş verib?", "Auto", provider
    )
    assert analysis.llm_used is True
    assert analysis.target_language == "az"
    assert analysis.retrieval_query == "equipment failure operation temporal match"


def test_ollama_azerbaijani_english_and_mixed_response_targets() -> None:
    for target, generated in [
        ("az", "Nasazlıq qeydi report.pdf, səhifə 2 mənbəsi ilə təsdiqlənir."),
        ("en", "The failure record is supported by report.pdf, page 2."),
    ]:
        provider = ScriptedOllamaProvider([generated])
        text, result, reason = grounded_verbalize(
            provider,
            original_question="Hansı wellbore had equipment nasazlığı?",
            target_language=target,
            deterministic_answer="One supported failure record.",
            route="structured_failure_activity",
            rows=[{"match_status": "exact", "source_file": "report.pdf"}],
            evidence=[{"file_name": "report.pdf", "page_number": 2}],
            limitations=[],
        )
        assert text == generated
        assert result is not None
        assert reason is None


def test_unsupported_claim_rejection_for_unresolved_mapping() -> None:
    reason = unsupported_claim_reason(
        "Well_15 and pressure_time_plot_15 are the same well.",
        "hybrid_mapping",
        [],
        [],
        ["All cross-namespace mappings remain unresolved."],
    )
    assert reason and "mapping" in reason


def test_unknown_pressure_unit_rejects_psi_claim() -> None:
    reason = unsupported_claim_reason(
        "Pressure increased to 1200 PSI.",
        "plot_analytics",
        [{"value": 1200}],
        [{"plot": "pressure_time_plot_01"}],
        ["Pressure unit is unknown; trend is descriptive and sparse."],
    )
    assert reason and "unit is unknown" in reason


def test_ambiguous_failure_match_rejects_blanket_concurrency_claim() -> None:
    reason = unsupported_claim_reason(
        "All failures occurred during drilling.",
        "structured_failure_activity",
        [{"match_status": "ambiguous", "concurrent_main_activity": None}],
        [{"failure": {"evidence_id": "equipment_failure:1"}}],
        [],
    )
    assert reason and "unresolved" in reason


def test_unsupported_numeric_claim_is_rejected() -> None:
    reason = unsupported_claim_reason(
        "The supported downtime was 999 minutes.",
        "structured_failure_activity",
        [{"match_status": "exact", "downtime_minutes": 15}],
        [{"file_name": "report.pdf", "page_number": 2}],
        [],
    )
    assert reason and "numeric" in reason
