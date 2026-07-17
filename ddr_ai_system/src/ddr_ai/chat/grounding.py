from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ddr_ai.nlp.providers import BaseLLMProvider, ChatResult, LLMProviderError, OllamaProvider

GROUNDED_SYSTEM_INSTRUCTION = """You are a grounded assistant for Daily Drilling Reports. Answer in the language of the user's latest question unless the UI explicitly selects another language. Preserve wellbore names, filenames, dates, units and technical identifiers. Use only the supplied SQL results, retrieved report sections and verified plot data. Never invent missing values, mappings, activities, failures, pressure units, anomalies or engineering thresholds. Cite the supporting source records. Clearly distinguish facts, inferences, candidates and unresolved information."""

QUERY_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "detected_language": {"type": "string", "enum": ["az", "en", "mixed"]},
        "route": {
            "type": "string",
            "enum": ["structured", "narrative", "plot", "hybrid"],
        },
        "english_retrieval_query": {"type": "string"},
        "intent": {"type": "string"},
        "slots": {"type": "object"},
    },
    "required": ["detected_language", "route", "english_retrieval_query", "intent", "slots"],
}

AZERBAIJANI_MARKERS = {
    "hansı",
    "quyu",
    "quyularda",
    "avadanlıq",
    "nasazlıq",
    "baş",
    "verib",
    "zamanı",
    "əməliyyat",
    "aparılırdı",
    "tarixləri",
    "mənbələri",
    "göstər",
    "hesabat",
}


@dataclass(frozen=True, slots=True)
class QueryAnalysis:
    detected_language: str
    target_language: str
    route: str
    retrieval_query: str
    intent: str
    slots: dict[str, Any]
    llm_used: bool
    fallback_reason: str | None = None


def detect_language(question: str) -> str:
    lower = question.casefold()
    tokens = set(re.findall(r"[\wəğıöşüç]+", lower, flags=re.UNICODE))
    az_score = len(tokens & AZERBAIJANI_MARKERS) + sum(
        lower.count(character) for character in "əğıöşüç"
    )
    en_score = len(tokens & {"which", "what", "report", "failure", "equipment", "plot", "trend"})
    if az_score and en_score:
        return "mixed"
    return "az" if az_score else "en"


def selected_target_language(selection: str, detected: str) -> str:
    if selection == "Azərbaycan dili":
        return "az"
    if selection == "English":
        return "en"
    return "az" if detected in {"az", "mixed"} else "en"


def deterministic_retrieval_query(question: str) -> str:
    lower = question.casefold()
    if "nasaz" in lower and ("avadan" in lower or "equipment" in lower):
        return "equipment failure operations activity start end time downtime wellbore report date"
    replacements = {
        "quyu": "wellbore",
        "quyularda": "wellbores",
        "hesabat": "report",
        "tarix": "date",
        "əməliyyat": "operation",
        "fəaliyyət": "activity",
        "təzyiq": "pressure",
        "nasazlıq": "failure",
        "avadanlıq": "equipment",
        "mənbə": "source",
    }
    result = lower
    for source, target in replacements.items():
        result = result.replace(source, target)
    return " ".join(result.split())


def analyze_question(
    question: str,
    language_selection: str,
    provider: BaseLLMProvider,
) -> QueryAnalysis:
    detected = detect_language(question)
    target = selected_target_language(language_selection, detected)
    fallback_query = deterministic_retrieval_query(question)
    fallback_route = _deterministic_route(question)
    if not isinstance(provider, OllamaProvider):
        return QueryAnalysis(
            detected,
            target,
            fallback_route,
            fallback_query,
            fallback_route,
            {},
            False,
            provider.health_check().reason,
        )
    prompt = (
        "Analyze the latest DDR question. Preserve the original question. Produce English DDR "
        "retrieval terminology even when the question is Azerbaijani. Classify only; do not answer.\n\n"
        f"Question: {question}"
    )
    try:
        result = provider.chat(
            [
                {"role": "system", "content": GROUNDED_SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            json_schema=QUERY_ANALYSIS_SCHEMA,
        )
        parsed = json.loads(result.content)
        retrieval_query = str(parsed.get("english_retrieval_query") or fallback_query).strip()
        route = str(parsed.get("route") or fallback_route)
        if route not in {"structured", "narrative", "plot", "hybrid"}:
            route = fallback_route
        llm_detected = str(parsed.get("detected_language") or detected)
        if llm_detected not in {"az", "en", "mixed"}:
            llm_detected = detected
        return QueryAnalysis(
            llm_detected,
            selected_target_language(language_selection, llm_detected),
            route,
            retrieval_query,
            str(parsed.get("intent") or route),
            parsed.get("slots") if isinstance(parsed.get("slots"), dict) else {},
            True,
        )
    except (LLMProviderError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return QueryAnalysis(
            detected,
            target,
            fallback_route,
            fallback_query,
            fallback_route,
            {},
            False,
            f"Query analysis fell back to deterministic routing ({type(exc).__name__}).",
        )


def _deterministic_route(question: str) -> str:
    lower = question.casefold()
    if "plot" in lower or "pressure" in lower or "təzyiq" in lower or "min" in lower:
        return "plot"
    if "failure" in lower or "nasaz" in lower or "activity" in lower or "əməliyyat" in lower:
        return "structured"
    if "mapping" in lower or "related" in lower or "uyğun" in lower:
        return "hybrid"
    return "narrative"


def grounded_verbalize(
    provider: BaseLLMProvider,
    *,
    original_question: str,
    target_language: str,
    deterministic_answer: str,
    route: str,
    rows: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    limitations: list[str],
) -> tuple[str, ChatResult | None, str | None]:
    if not isinstance(provider, OllamaProvider):
        return deterministic_answer, None, provider.health_check().reason
    facts = {
        "deterministic_summary": deterministic_answer,
        "route": route,
        "rows": rows[:12],
        "evidence": evidence[:12],
        "limitations": limitations,
    }
    target = "Azerbaijani" if target_language == "az" else "English"
    prompt = (
        f"Answer the original question in {target}. Use only FACTS_JSON. Keep citations and "
        "technical identifiers unchanged. For ambiguous or unmatched temporal records, explicitly "
        "say that the activity is unresolved. Do not convert unknown pressure units to PSI. "
        "Do not claim that unresolved plot identities match.\n\n"
        f"ORIGINAL_QUESTION:\n{original_question}\n\n"
        f"FACTS_JSON:\n{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    try:
        result = provider.chat(
            [
                {"role": "system", "content": GROUNDED_SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ]
        )
    except LLMProviderError as exc:
        return deterministic_answer, None, str(exc)
    rejection = unsupported_claim_reason(
        result.content,
        route,
        rows,
        evidence,
        limitations,
        grounding_text=deterministic_answer,
    )
    if rejection:
        return deterministic_answer, result, rejection
    return result.content, result, None


def unsupported_claim_reason(
    text: str,
    route: str,
    rows: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    limitations: list[str],
    *,
    grounding_text: str = "",
) -> str | None:
    lower = text.casefold()
    if not evidence and any(token in lower for token in ("occurred", "baş verib", "confirmed")):
        return "LLM answer rejected because it asserted a fact without evidence."
    if route == "hybrid_mapping" and not rows and any(
        token in lower for token in ("are the same", "corresponds to", "eynidir", "uyğundur")
    ):
        return "LLM answer rejected because the plot/wellbore mapping is unresolved."
    unknown_pressure = any("pressure unit is unknown" in item.casefold() for item in limitations)
    if unknown_pressure and re.search(r"\b(?:psi|kpa|mpa|bar)\b", lower):
        return "LLM answer rejected because the pressure unit is unknown."
    if route == "structured_failure_activity":
        unresolved = [row for row in rows if row.get("match_status") not in {"exact", "overlap"}]
        if unresolved and ("all failures occurred during" in lower or "bütün nasazlıqlar" in lower):
            return "LLM answer rejected because some failure/activity matches are unresolved."
    supplied = json.dumps(
        {"rows": rows, "evidence": evidence, "limitations": limitations},
        ensure_ascii=False,
        default=str,
    ) + grounding_text
    unsupported_numbers = _number_tokens(text) - _number_tokens(supplied)
    if unsupported_numbers:
        return "LLM answer rejected because it introduced unsupported numeric values."
    return None


def _number_tokens(text: str) -> set[str]:
    return set(re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", text))


def localize_deterministic_answer(answer: str, route: str, target_language: str) -> str:
    if target_language != "az":
        return answer
    if route == "structured_failure_activity":
        numbers = re.findall(r"\d+", answer)
        if len(numbers) >= 7:
            return (
                f"{numbers[0]} doldurulmuş avadanlıq nasazlığı qeydi, bölməni ehtiva edən "
                f"{numbers[2]} hesabatdan {numbers[1]}-də aşkarlandı. {numbers[3]} qeyd üçün "
                f"əməliyyat vaxt uyğunluğu təsdiqləndi; {numbers[4]} qeyddə uyğunluq qeyri-müəyyəndir, "
                f"{numbers[5]} qeyd uyğunlaşdırılmayıb və {numbers[6]} qeyddə etibarlı Operations "
                "intervalı yoxdur. Cədvəldə tarixlər, mənbə səhifələri və uyğunluq statusları göstərilir."
            )
        return "Avadanlıq nasazlığı qeydləri mənbə və vaxt uyğunluğu ilə cədvəldə göstərilir."
    if "unavailable" in answer.casefold() or "no " in answer.casefold():
        return "Mövcud emal edilmiş məlumat bu faktı müəyyən etmir."
    return answer
