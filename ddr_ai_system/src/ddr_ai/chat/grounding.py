from __future__ import annotations

import json
import re
from typing import Any

from ddr_ai.nlp.providers import (
    BaseLLMProvider,
    ChatResult,
    LexicalFallbackProvider,
    LLMProviderError,
)

GROUNDED_SYSTEM_INSTRUCTION = """You are a grounded assistant for Daily Drilling Reports. Answer in the language of the user's latest question unless the UI explicitly selects another language. Preserve wellbore names, filenames, dates, units and technical identifiers. Use only the supplied SQL results, retrieved report sections and verified plot data. Never invent missing values, mappings, activities, failures, pressure units, anomalies or engineering thresholds. Cite the supporting source records. Clearly distinguish facts, inferences, candidates and unresolved information."""

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
    if isinstance(provider, LexicalFallbackProvider):
        return deterministic_answer, None, provider.health_check().reason
    facts = {
        "deterministic_summary": deterministic_answer,
        "route": route,
        "rows": rows[:40],
        "evidence": evidence[:40],
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
        deterministic_answer=deterministic_answer,
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
    deterministic_answer: str = "",
) -> str | None:
    lower = text.casefold()
    if not evidence and any(token in lower for token in ("occurred", "baş verib", "confirmed")):
        return "LLM answer rejected because it asserted a fact without evidence."
    if (
        route in {"hybrid_mapping", "structured_mapping"}
        and not rows
        and any(
            token in lower for token in ("are the same", "corresponds to", "eynidir", "uyğundur")
        )
    ):
        return "LLM answer rejected because the plot/wellbore mapping is unresolved."
    unknown_pressure = any(
        "pressure unit is unknown" in item.casefold()
        or "pressure unit is unknown" in str(item).casefold()
        or "unit is unknown" in item.casefold()
        for item in limitations
    )
    if unknown_pressure and re.search(r"\b(?:psi|kpa|mpa|bar)\b", lower):
        return "LLM answer rejected because the pressure unit is unknown."
    if route in {"structured_failure_activity", "structured_equipment_failures"}:
        unresolved = [row for row in rows if row.get("match_status") not in {"exact", "overlap"}]
        if unresolved and ("all failures occurred during" in lower or "bütün nasazlıqlar" in lower):
            return "LLM answer rejected because some failure/activity matches are unresolved."

    def citation_files(value: Any) -> set[str]:
        if isinstance(value, dict):
            dictionary_files = {
                str(item)
                for key, item in value.items()
                if key in {"file_name", "source_file"} and isinstance(item, str)
            }
            for item in value.values():
                dictionary_files.update(citation_files(item))
            return dictionary_files
        if isinstance(value, list):
            list_files: set[str] = set()
            for item in value:
                list_files.update(citation_files(item))
            return list_files
        return set()

    allowed_files = citation_files(evidence) | citation_files(rows)
    generated_files = set(
        re.findall(
            r"[\w.-]+\.(?:pdf|png|jpe?g|tiff?)",
            text,
            flags=re.IGNORECASE,
        )
    )
    if generated_files - allowed_files:
        return "LLM answer rejected because it introduced a citation outside the supplied evidence."
    fact_text = json.dumps(
        {
            "answer": deterministic_answer,
            "rows": rows,
            "evidence": evidence,
            "limitations": limitations,
        },
        ensure_ascii=False,
        default=str,
    )

    def normalize(value: str) -> str:
        return value.replace(",", "").lstrip("+")

    allowed_numbers = {
        normalize(value) for value in re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?", fact_text)
    }
    generated_numbers = {
        normalize(value) for value in re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?", text)
    }
    unsupported_numbers = generated_numbers - allowed_numbers
    if unsupported_numbers:
        return "LLM answer rejected because it introduced unsupported numeric claims."
    return None


def localize_deterministic_answer(
    answer: str,
    route: str,
    target_language: str,
    *,
    rows: list[dict[str, Any]] | None = None,
) -> str:
    if target_language != "az":
        return answer
    facts = rows[0] if rows else {}
    if route == "hybrid_summary" and facts:
        wellbore = facts.get("wellbore") or "Naməlum quyu"
        period = facts.get("period_end") or "tarixi məlum olmayan dövr"
        operation_count = facts.get("operation_count", 0)
        fail_count = facts.get("fail_operation_count", 0)
        text = (
            f"{wellbore} üçün {period} tarixli DDR-də {operation_count} əməliyyat sətri "
            f"çıxarılıb; {fail_count} əməliyyat sətri nasaz vəziyyət kimi işarələnib."
        )
        if facts.get("summary_activities"):
            text += f" Mənbə fəaliyyət xülasəsi: {facts['summary_activities']}"
        if facts.get("summary_planned"):
            text += f" Planlaşdırılan fəaliyyət: {facts['summary_planned']}"
        return text
    if route == "structured_report_lookup" and facts:
        wellbore = facts.get("wellbore") or "naməlum quyu"
        report_date = facts.get("report_date") or "tarixi məlum olmayan"
        text = (
            f"{wellbore} üçün {len(rows or [])} mənbə-dəstəkli hesabat xülasəsi tapıldı. "
            f"Ən son hesabatın tarixi {report_date}-dir."
        )
        if facts.get("completed_activities"):
            text += f" Tamamlanan fəaliyyətlər: {facts['completed_activities']}"
        if facts.get("planned_activities"):
            text += f" Planlaşdırılan fəaliyyətlər: {facts['planned_activities']}"
        return text
    if route == "plot_analytics" and facts:
        identifiers = facts.get("plot_identifiers") or ["seçilmiş qrafik"]
        plot_label = ", ".join(str(item) for item in identifiers)
        return (
            f"{plot_label} daxilində "
            f"{facts.get('series_identifier') or 'seçilmiş sıra'} üçün "
            f"{facts.get('point_count', 0)} saxlanmış nöqtə əsasında Theil-Sen meyli "
            f"{facts.get('slope')} naməlum təzyiq vahidi/gün, Spearman rho isə "
            f"{facts.get('spearman_rho')} kimi hesablanıb. Təzyiq vahidi məlum deyil."
        )
    if route == "plot_sql":
        return f"MIN əyrisindən aşağı təsnif edilmiş {len(rows or [])} ölçülmüş profil nöqtəsi tapıldı."
    if route == "hybrid_mapping" and not rows:
        return (
            "Mövcud metadata bu uyğunluğu təsdiqləmir. Eyni rəqəmli indekslər təzyiq "
            "profilinin, təzyiq-zaman faylının, göstərilən sıranın və ya DDR quyusunun eyni "
            "obyekt olduğunu sübut etmir."
        )
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
