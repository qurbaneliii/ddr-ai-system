from __future__ import annotations

import hashlib
import time

from sqlalchemy.orm import Session

from ddr_ai.chat.contracts import ChatAnswer, PlotImageContext
from ddr_ai.chat.grounding import (
    grounded_verbalize,
    localize_deterministic_answer,
    unsupported_claim_reason,
)
from ddr_ai.chat.handlers import HANDLER_REGISTRY
from ddr_ai.chat.multimodal import deterministic_plot_description, vlm_prompt
from ddr_ai.chat.query import QueryAnalyzer, QueryPlan
from ddr_ai.db.models import QueryAudit
from ddr_ai.nlp.providers import BaseLLMProvider, LexicalFallbackProvider, LLMProviderError
from ddr_ai.retrieval.corpus import (
    CorpusRetriever,
    EvidencePack,
    RetrievalDiagnostics,
    RetrievalHit,
)


def _audit(session: Session, question: str, answer: ChatAnswer, started: float) -> None:
    session.add(
        QueryAudit(
            route=answer.route,
            question_hash=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            generated_sql=answer.sql,
            status="complete",
            row_count=len(answer.rows),
            duration_seconds=round(time.perf_counter() - started, 4),
        )
    )


def _citation(item: RetrievalHit) -> str:
    parts = [item.file_name]
    if item.page_number is not None:
        parts.append(f"page {item.page_number}")
    if item.section_type:
        parts.append(item.section_type)
    return ", ".join(parts)


def _corpus_answer(
    plan: QueryPlan,
    hits: list[RetrievalHit],
    diagnostics: RetrievalDiagnostics,
) -> ChatAnswer:
    evidence = [item.evidence() for item in hits]
    if not hits:
        if plan.target_language == "az":
            text = (
                "Bu sualın cavabı emal edilmiş DDR korpusunda tapılmadı. Xarici və ya ümumi "
                "neft-qaz biliyindən cavab yaradılmadı. Məsələn, qazma fəaliyyətləri, avadanlıq "
                "nasazlıqları və ya drilling-fluid parametrləri barədə soruşa bilərsiniz."
            )
        else:
            text = (
                "The answer was not found in the processed DDR corpus. No external or general "
                "oil-industry knowledge was used. Try asking about drilling activities, equipment "
                "failures, or drilling-fluid properties present in the reports."
            )
        return ChatAnswer(
            text,
            "not_found_corpus",
            limitations=[
                "Two-stage corpus retrieval found no useful source-backed evidence for the supplied filters."
            ],
            confidence=1.0,
            corpus_status=diagnostics.corpus_status,
            retrieval_diagnostics=diagnostics.to_dict(),
        )

    if plan.target_language == "az":
        lead = f"Emal edilmiş DDR korpusunda {len(hits)} uyğun sübut parçası tapıldı:"
    else:
        lead = f"Found {len(hits)} ranked evidence excerpts in the processed DDR corpus:"
    lines = [lead]
    for index, item in enumerate(hits[:6], start=1):
        excerpt = " ".join(item.text[:500].split())
        lines.append(f"{index}. {excerpt} [{_citation(item)}]")
    pack = EvidencePack(
        plan=plan,
        deterministic_summary="\n\n".join(lines),
        evidence=evidence,
        limitations=[
            "Results are ranked corpus evidence, not general drilling knowledge.",
            "Retrieved excerpts can be incomplete; citations identify the stored source records.",
        ],
        confidence=min(0.95, 0.55 + hits[0].score),
        diagnostics=diagnostics,
    )
    bounded = pack.bounded_evidence()
    return ChatAnswer(
        pack.deterministic_summary,
        "corpus_retrieval",
        evidence=bounded,
        rows=bounded,
        limitations=pack.limitations,
        confidence=pack.confidence,
        evidence_hit_count=len(bounded),
        retrieval_source_types=diagnostics.source_types,
        corpus_status=diagnostics.corpus_status,
        retrieval_diagnostics=diagnostics.to_dict(),
        export_filename="ddr-corpus-evidence.csv",
    )


def _deterministic_answer(session: Session, plan: QueryPlan) -> ChatAnswer:
    if plan.intent == "unsupported_out_of_corpus":
        empty = RetrievalDiagnostics("ready", "not_applicable", 0, 0.0, 2, 0, 0, [])
        return _corpus_answer(plan, [], empty)
    handler = HANDLER_REGISTRY.get(plan.intent)
    if handler is not None:
        answer = handler(session, plan)
        if answer is not None:
            return answer
    hits, diagnostics = CorpusRetriever().search(session, plan)
    return _corpus_answer(plan, hits, diagnostics)


def _apply_diagnostics(answer: ChatAnswer, plan: QueryPlan) -> None:
    answer.detected_language = plan.detected_language
    answer.selected_language = plan.target_language
    answer.retrieval_query = plan.retrieval_query
    answer.rewritten_query = plan.follow_up_rewrite
    answer.query_plan = plan.to_dict()
    if answer.evidence_hit_count == 0:
        answer.evidence_hit_count = len(answer.evidence)
    if not answer.retrieval_source_types:
        answer.retrieval_source_types = sorted(
            {
                str(item.get("source_type"))
                for item in answer.evidence
                if isinstance(item, dict) and item.get("source_type")
            }
        )


def _apply_plot_context(
    answer: ChatAnswer,
    provider: BaseLLMProvider,
    context: PlotImageContext,
    *,
    question: str,
    language: str,
) -> None:
    facts = context.deterministic_facts()
    deterministic = deterministic_plot_description(context, language=language)
    citation = context.allowed_citation
    limitations = [
        "Visual description is limited to the explicitly selected stored plot image.",
        "Deterministic CV/SQL facts remain authoritative over qualitative visual wording.",
    ]
    if context.unit_status == "unknown" or not context.y_unit:
        limitations.append("Pressure unit is unknown and must not be inferred from the image.")
    answer.selected_plot_identifier = context.plot_identifier
    answer.visual_validation_status = "deterministic_fallback"
    answer.evidence.append(citation)
    answer.rows.append({"selected_plot_facts": facts})
    answer.evidence_hit_count = max(answer.evidence_hit_count, len(answer.evidence))
    answer.limitations.extend(item for item in limitations if item not in answer.limitations)
    if not provider.supports_images:
        answer.answer = f"{answer.answer}\n\n{deterministic}"
        answer.answer_type = "deterministic selected-plot facts"
        reason = provider.health_check().reason or "The active provider does not support images."
        answer.fallback_reason = answer.fallback_reason or reason
        return
    try:
        result = provider.describe_image(
            context.image_bytes,
            mime_type=context.mime_type,
            prompt=vlm_prompt(context, question=question),
        )
    except LLMProviderError as exc:
        answer.answer = f"{answer.answer}\n\n{deterministic}"
        answer.answer_type = "deterministic selected-plot facts"
        answer.visual_provider = provider.mode_label
        answer.visual_model = provider.model
        answer.visual_validation_status = "provider_error_fallback"
        answer.fallback_reason = str(exc)
        return
    rejection = unsupported_claim_reason(
        result.content,
        "plot_visual",
        [facts],
        [citation],
        limitations,
        deterministic_answer=deterministic,
    )
    answer.visual_provider = provider.mode_label
    answer.visual_model = result.model
    if rejection:
        answer.answer = f"{answer.answer}\n\n{deterministic}"
        answer.answer_type = "deterministic selected-plot facts"
        answer.visual_validation_status = "rejected"
        answer.fallback_reason = rejection
        return
    label = "Visual description" if language != "az" else "Vizual təsvir"
    answer.answer = f"{answer.answer}\n\n{label}: {result.content}\n\n{deterministic}"
    answer.answer_type = "deterministic facts + grounded VLM"
    answer.visual_analysis_used = True
    answer.visual_validation_status = "accepted"
    answer.provider = provider.mode_label
    answer.model = result.model


def answer_question(
    session: Session,
    question: str,
    *,
    provider: BaseLLMProvider | None = None,
    language: str = "Auto",
    history: list[dict[str, str]] | None = None,
    plot_context: PlotImageContext | None = None,
) -> ChatAnswer:
    """Plan safely, run a trusted handler or bounded corpus search, then verbalize facts."""

    started = time.perf_counter()
    active_provider = provider or LexicalFallbackProvider("No reachable LLM provider was supplied.")
    planning_provider = (
        LexicalFallbackProvider("Selected plots use deterministic query planning.")
        if plot_context is not None
        else active_provider
    )
    plan = QueryAnalyzer().analyze(
        question,
        language,
        planning_provider,
        history=(history or [])[-4:],
    )
    answer = _deterministic_answer(session, plan)
    _apply_diagnostics(answer, plan)
    deterministic_text = localize_deterministic_answer(
        answer.answer,
        answer.route,
        plan.target_language,
        rows=answer.rows,
    )

    if plot_context is not None or answer.route == "not_found_corpus":
        generated_text, result, fallback_reason = deterministic_text, None, None
    else:
        generated_text, result, fallback_reason = grounded_verbalize(
            active_provider,
            original_question=plan.standalone_question,
            target_language=plan.target_language,
            deterministic_answer=deterministic_text,
            route=answer.route,
            rows=answer.rows[:40],
            evidence=answer.evidence[:40],
            limitations=answer.limitations,
        )
    answer.answer = generated_text
    if result is not None and fallback_reason is None:
        answer.provider = active_provider.mode_label
        answer.model = result.model
        answer.answer_type = "OpenAI-verbalized"
        answer.model_metrics = {
            "total_duration_ns": result.total_duration_ns,
            "prompt_eval_count": result.prompt_eval_count,
            "eval_count": result.eval_count,
        }
    else:
        answer.provider = "Lexical fallback"
        answer.model = None
        if answer.route == "not_found_corpus":
            answer.answer_type = "not found in corpus"
        elif answer.route == "corpus_retrieval":
            answer.answer_type = "lexical corpus retrieval"
        else:
            answer.answer_type = "deterministic structured"
        answer.fallback_reason = fallback_reason or plan.fallback_reason
        if not isinstance(active_provider, LexicalFallbackProvider) and fallback_reason:
            answer.limitations.append("OpenAI failed safely; deterministic evidence was returned.")
        elif isinstance(active_provider, LexicalFallbackProvider):
            limitation = "This answer is deterministic/lexical and was not LLM-generated."
            if limitation not in answer.limitations:
                answer.limitations.append(limitation)
    if plot_context is not None:
        _apply_plot_context(
            answer,
            active_provider,
            plot_context,
            question=plan.standalone_question,
            language=plan.target_language,
        )
    _audit(session, question, answer, started)
    return answer


__all__ = ["ChatAnswer", "answer_question"]
