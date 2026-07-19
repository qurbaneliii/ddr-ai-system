from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from ddr_ai.nlp.providers import BaseLLMProvider, LexicalFallbackProvider, LLMProviderError

INTENTS = {
    "daily_summary",
    "report_lookup",
    "narrative_corpus_search",
    "list_records",
    "count_aggregation",
    "compare_wellbores",
    "activity_analysis",
    "equipment_failures",
    "drilling_fluid_lookup",
    "operational_problem_search",
    "date_depth_trend",
    "plot_facts",
    "plot_trends",
    "identity_mapping",
    "unsupported_out_of_corpus",
}

DOMAIN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "drilling": ("drill", "drilled", "qazma", "quyu"),
    "reaming": ("ream", "reamed"),
    "circulation": ("circulate", "circulating", "dövriyyə"),
    "tripping": ("trip", "pooh", "rih"),
    "cementing": ("cement", "cement job"),
    "drilling fluid": ("mud", "mud weight", "fluid density", "drilling-fluid"),
    "bop": ("blowout preventer", "well control equipment"),
    "top drive": ("top-drive", "topdrive"),
    "mud pump": ("mud-pump", "pump"),
    "stuck pipe": ("stuck string", "pipe stuck"),
    "lost circulation": ("circulation loss", "losses", "lost returns"),
    "equipment failure": ("breakdown", "nasazlıq", "avadanlıq nasazlığı"),
    "downtime": ("down time", "operational downtime"),
    "completed activities": ("summary activities", "tamamlanan fəaliyyətlər"),
    "planned activities": ("summary planned", "planlaşdırılan fəaliyyətlər"),
    "depth": ("mmd", "mtvd", "measured depth"),
    "pressure": ("təzyiq",),
    "operation": ("operations", "activity", "activities", "əməliyyat", "fəaliyyət"),
    "remark": ("remarks", "problem", "issue", "problematic", "qeyd", "problem"),
}

STOP_WORDS = {
    "about", "across", "and", "are", "bu", "bunlardan", "corpus", "ddr", "ddr-lərdə",
    "et", "for", "from", "haqqında", "hansı", "hesabatlarda", "ilə", "in", "most",
    "nə", "of", "olan", "olub", "qeyd", "reports", "show", "the", "these", "what",
    "when", "which", "were", "with", "var", "və",
}

FOLLOW_UP_MARKERS = (
    "bunlardan hansı",
    "bunlardan ən sonuncusu",
    "bəs ən sonuncusu",
    "that report",
    "which of these",
    "what about its",
    "what about that",
)

QUERY_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "detected_language": {"type": "string", "enum": ["az", "en", "mixed"]},
        "intent": {"type": "string", "enum": sorted(INTENTS)},
        "search_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "wellbore": {"type": ["string", "null"]},
        "date_from": {"type": ["string", "null"]},
        "date_to": {"type": ["string", "null"]},
        "report_id": {"type": ["integer", "null"]},
        "section_types": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "activity_names": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "equipment_names": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "metric": {"type": ["string", "null"]},
        "aggregation": {"type": ["string", "null"]},
        "sort_direction": {"type": ["string", "null"], "enum": ["asc", "desc", None]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        "standalone_question": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "detected_language", "intent", "search_terms", "wellbore", "date_from", "date_to",
        "report_id", "section_types", "activity_names", "equipment_names", "metric",
        "aggregation", "sort_direction", "limit", "standalone_question", "confidence",
    ],
}


@dataclass(slots=True)
class QueryPlan:
    detected_language: str
    target_language: str
    intent: str
    retrieval_query: str
    search_terms: list[str] = field(default_factory=list)
    domain_synonyms: list[str] = field(default_factory=list)
    wellbore: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    report_id: int | None = None
    section_types: list[str] = field(default_factory=list)
    activity_names: list[str] = field(default_factory=list)
    equipment_names: list[str] = field(default_factory=list)
    metric: str | None = None
    aggregation: str | None = None
    sort_direction: str | None = None
    limit: int = 10
    standalone_question: str = ""
    confidence: float = 0.0
    follow_up_rewrite: str | None = None
    llm_used: bool = False
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["date_from"] = self.date_from.isoformat() if self.date_from else None
        value["date_to"] = self.date_to.isoformat() if self.date_to else None
        return value


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def detect_language(question: str) -> str:
    lower = _normalized(question)
    tokens = set(re.findall(r"[^\W\d_]+", lower, flags=re.UNICODE))
    az_letters = sum(lower.count(character) for character in "əğıöşüç")
    az_words = tokens & {
        "əsas", "avadanlıq", "bunlardan", "fəaliyyət", "fəaliyyətlər", "göstər", "hansı",
        "hesabat", "hesabatlarda", "mənbə", "nasazlıq", "planlaşdırılan", "qazma", "quyu",
        "quyuları", "saxlanılıb", "son", "tamamlanan", "tarixdə", "xülasə",
    }
    en_words = tokens & {
        "activities", "activity", "compare", "equipment", "failure", "fluid", "plot",
        "problems", "report", "reports", "show", "summarize", "what", "which",
    }
    az_score = az_letters + len(az_words) * 2
    en_score = len(en_words)
    if az_score and en_score:
        return "mixed"
    return "az" if az_score else "en"


def selected_target_language(selection: str, detected: str) -> str:
    if selection == "Azərbaycan dili":
        return "az"
    if selection == "English":
        return "en"
    return "az" if detected in {"az", "mixed"} else "en"


def _wellbore(question: str) -> str | None:
    match = re.search(
        r"\b\d{1,3}/\d{1,3}-(?:[a-z]-)?\d{1,3}(?:\s+(?:a|b|bt2|st2|s|t2))?\b",
        question,
        re.I,
    )
    return match.group(0).upper() if match else None


def _dates(question: str) -> tuple[date | None, date | None]:
    found = []
    for value in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question):
        try:
            found.append(date.fromisoformat(value))
        except ValueError:
            continue
    return (found[0] if found else None, found[-1] if len(found) > 1 else (found[0] if found else None))


def _standalone(question: str, history: list[dict[str, str]]) -> tuple[str, str | None]:
    normalized = _normalized(question)
    if not any(marker in normalized for marker in FOLLOW_UP_MARKERS):
        return question.strip(), None
    previous = next(
        (
            item.get("content", "").strip()
            for item in reversed(history[-4:])
            if item.get("role") == "user" and item.get("content", "").strip()
        ),
        "",
    )
    if not previous:
        return question.strip(), None
    rewrite = f"{previous} Follow-up: {question.strip()}"
    return rewrite, rewrite


def _terms(question: str) -> list[str]:
    tokens = re.findall(r"[\w/.-]+", _normalized(question), flags=re.UNICODE)
    return list(dict.fromkeys(token for token in tokens if len(token) >= 2 and token not in STOP_WORDS))[:20]


def _synonyms(terms: list[str], question: str) -> list[str]:
    haystack = f" {_normalized(question)} "
    selected: list[str] = []
    for canonical, aliases in DOMAIN_SYNONYMS.items():
        values = (canonical, *aliases)
        if any(f" {value} " in haystack or value in terms for value in values):
            selected.extend(values)
    return list(dict.fromkeys(selected))[:40]


def _deterministic_intent(question: str, wellbore: str | None) -> tuple[str, float]:
    lower = _normalized(question)
    if any(term in lower for term in ("current oil price", "oil price today", "bugünkü neft qiyməti", "xəbər")):
        return "unsupported_out_of_corpus", 1.0
    if any(
        term in lower
        for term in ("mapping", "same well", "belong to the same", "related", "eyni quyu", "uyğunluq")
    ):
        return "identity_mapping", 0.98
    if "pressure" in lower or "təzyiq" in lower or "pressure_" in lower:
        return ("plot_trends", 0.95) if "trend" in lower else ("plot_facts", 0.9)
    if any(term in lower for term in ("daily summary", "latest report", "son ddr", "gündəlik", "xülasə")):
        return "daily_summary", 0.95
    if wellbore and any(term in lower for term in ("completed", "planned", "tamamlanan", "planlaşdırılan")):
        return "report_lookup", 0.95
    if any(term in lower for term in ("how many", "count", "most common", "compare")) and any(
        term in lower for term in ("activity", "activities", "operation", "wellbore")
    ):
        return ("compare_wellbores" if "compare" in lower else "count_aggregation", 0.92)
    if any(term in lower for term in ("equipment failure", "breakdown", "top drive", "top-drive", "mud pump", "nasazlıq")):
        return "equipment_failures", 0.9
    if any(term in lower for term in ("drilling fluid", "drilling-fluid", "mud weight", "fluid density")):
        return "drilling_fluid_lookup", 0.9
    if any(term in lower for term in ("problem", "issue", "stuck pipe", "lost circulation", "losses")):
        return "operational_problem_search", 0.88
    if any(term in lower for term in ("main activity", "qazma fəaliyyətləri", "operational activities")):
        return "activity_analysis", 0.88
    if any(term in lower for term in ("report", "ddr", "cement", "circulation", "ream", "drill", "operation", "quyu")):
        return "narrative_corpus_search", 0.72
    return "narrative_corpus_search", 0.35


def _date_value(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class QueryAnalyzer:
    """Build a safe retrieval plan; OpenAI may fill slots but never produces SQL."""

    def analyze(
        self,
        question: str,
        language_selection: str,
        provider: BaseLLMProvider,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> QueryPlan:
        bounded_history = (history or [])[-4:]
        standalone, follow_up = _standalone(question, bounded_history)
        detected = detect_language(question)
        target = selected_target_language(language_selection, detected)
        wellbore = _wellbore(standalone)
        date_from, date_to = _dates(standalone)
        intent, confidence = _deterministic_intent(standalone, wellbore)
        search_terms = _terms(standalone)
        synonyms = _synonyms(search_terms, standalone)
        sort_direction = (
            "desc"
            if any(term in _normalized(question) for term in ("latest", "most recent", "ən son", "sonuncusu"))
            else None
        )
        activity_names = [
            item
            for item in ("drilling", "reaming", "circulation", "tripping", "cementing", "stuck pipe", "lost circulation")
            if item in synonyms
        ]
        equipment_names = [
            item
            for item in ("top drive", "mud pump", "bop", "equipment failure")
            if item in synonyms
        ]
        plan = QueryPlan(
            detected_language=detected,
            target_language=target,
            intent=intent,
            retrieval_query=" ".join(dict.fromkeys([*search_terms, *synonyms])),
            search_terms=search_terms,
            domain_synonyms=synonyms,
            wellbore=wellbore,
            date_from=date_from,
            date_to=date_to,
            activity_names=activity_names,
            equipment_names=equipment_names,
            sort_direction=sort_direction,
            limit=10,
            standalone_question=standalone,
            confidence=confidence,
            follow_up_rewrite=follow_up,
        )
        if confidence >= 0.55 or isinstance(provider, LexicalFallbackProvider):
            return plan
        return self._analyze_with_provider(plan, question, bounded_history, provider)

    def _analyze_with_provider(
        self,
        fallback: QueryPlan,
        question: str,
        history: list[dict[str, str]],
        provider: BaseLLMProvider,
    ) -> QueryPlan:
        safe_history = [
            {"role": item.get("role", "user"), "content": item.get("content", "")[:500]}
            for item in history
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        prompt = json.dumps(
            {"question": question, "recent_context_for_reference_resolution_only": safe_history},
            ensure_ascii=False,
        )
        try:
            result = provider.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Return a bounded DDR corpus retrieval plan. Resolve conversational references, "
                            "but do not treat history as evidence. Return slots and search terms only. Never "
                            "return SQL or external oil-industry facts."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                json_schema=QUERY_PLAN_SCHEMA,
                max_output_tokens=400,
            )
            payload = json.loads(result.content)
            intent = payload.get("intent")
            if intent not in INTENTS:
                raise ValueError("Unsupported intent")
            standalone = str(payload.get("standalone_question") or fallback.standalone_question)[:2000]
            search_terms = [str(item)[:100] for item in payload.get("search_terms", [])[:20]]
            synonyms = _synonyms(search_terms, standalone)
            return QueryPlan(
                detected_language=str(payload.get("detected_language") or fallback.detected_language),
                target_language=fallback.target_language,
                intent=intent,
                retrieval_query=" ".join(dict.fromkeys([*search_terms, *synonyms])),
                search_terms=search_terms,
                domain_synonyms=synonyms,
                wellbore=str(payload["wellbore"]).upper() if payload.get("wellbore") else fallback.wellbore,
                date_from=_date_value(payload.get("date_from")) or fallback.date_from,
                date_to=_date_value(payload.get("date_to")) or fallback.date_to,
                report_id=payload.get("report_id"),
                section_types=[str(item)[:128] for item in payload.get("section_types", [])[:10]],
                activity_names=[str(item)[:128] for item in payload.get("activity_names", [])[:10]],
                equipment_names=[str(item)[:128] for item in payload.get("equipment_names", [])[:10]],
                metric=str(payload["metric"])[:128] if payload.get("metric") else None,
                aggregation=str(payload["aggregation"])[:64] if payload.get("aggregation") else None,
                sort_direction=payload.get("sort_direction"),
                limit=max(1, min(int(payload.get("limit", 10)), 20)),
                standalone_question=standalone,
                confidence=float(payload.get("confidence", 0.5)),
                follow_up_rewrite=standalone if standalone != question else fallback.follow_up_rewrite,
                llm_used=True,
            )
        except (LLMProviderError, ValueError, TypeError, json.JSONDecodeError) as exc:
            fallback.fallback_reason = f"Query analysis used deterministic fallback: {type(exc).__name__}."
            return fallback
