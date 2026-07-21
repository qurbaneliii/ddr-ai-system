from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from sqlalchemy import func, select

from ddr_ai.chat.contracts import ChatAnswer
from ddr_ai.chat.service import answer_question
from ddr_ai.config import PROJECT_ROOT, Settings
from ddr_ai.db.models import RetrievalChunk, SourceDocument
from ddr_ai.db.session import dispose_engine, session_scope
from ddr_ai.nlp.providers import LexicalFallbackProvider

COMMITTED_DATABASE = PROJECT_ROOT / "data/processed/ddr_ai.db"


@dataclass(frozen=True, slots=True)
class ChatCase:
    case_id: str
    question: str
    expected_routes: tuple[str, ...]
    require_evidence: bool = False
    require_rows: bool = False
    expected_language: str | None = None
    answer_terms: tuple[str, ...] = ()
    history: tuple[dict[str, str], ...] = field(default_factory=tuple)
    require_rewrite: bool = False


CASES = (
    ChatCase(
        "activity",
        "Which reports mention lost circulation during drilling operations?",
        ("corpus_retrieval",),
        require_evidence=True,
    ),
    ChatCase(
        "equipment_failures",
        "Which wellbores had equipment failures and what activities occurred at the same time?",
        ("structured_failure_activity",),
        require_evidence=True,
        require_rows=True,
    ),
    ChatCase(
        "drilling_fluid",
        "Which drilling-fluid values and units are available in the reports?",
        ("corpus_retrieval",),
        require_evidence=True,
    ),
    ChatCase(
        "daily_summary",
        "Give the latest daily summary for wellbore 15/9-F-14.",
        ("hybrid_summary",),
        require_evidence=True,
        require_rows=True,
    ),
    ChatCase(
        "multi_day_plot_trend",
        "Show the pressure trend for Well_01 in pressure_time_plot_01.",
        ("plot_analytics",),
        require_evidence=True,
        require_rows=True,
        answer_terms=("unknown pressure-units/day",),
    ),
    ChatCase(
        "azerbaijani",
        "Qazma zamanı baş verən avadanlıq nasazlıqlarını mənbələrlə göstər.",
        ("structured_failure_activity",),
        require_evidence=True,
        expected_language="az",
    ),
    ChatCase(
        "follow_up",
        "Bunlardan ən sonuncusu hansı tarixdə olub?",
        ("structured_report_lookup",),
        require_evidence=True,
        require_rows=True,
        expected_language="az",
        history=(
            {
                "role": "user",
                "content": "15/9-F-14 üçün tamamlanan və planlaşdırılan fəaliyyətlər nə idi?",
            },
            {"role": "assistant", "content": "Prior wording is not evidence."},
        ),
        require_rewrite=True,
    ),
    ChatCase(
        "missing_well",
        "Summarize completed activities for 99/99-Z-99.",
        ("not_found_corpus",),
        answer_terms=("not found in the processed DDR corpus",),
    ),
    ChatCase(
        "missing_date",
        "What was the main activity for wellbore 15/9-F-14 on 2099-01-01?",
        ("not_found_corpus",),
    ),
    ChatCase(
        "current_oil_price_refusal",
        "What is the current market price of oil?",
        ("not_found_corpus",),
        answer_terms=("not found in the processed DDR corpus",),
    ),
    ChatCase(
        "plot_facts",
        "Which pressure profile points are below the MIN curve?",
        ("plot_sql",),
        require_evidence=True,
        require_rows=True,
    ),
    ChatCase(
        "rule_vs_ml_candidates",
        "Show unusual operation-duration candidates and distinguish rule vs ML evidence.",
        ("anomaly_candidates",),
        require_rows=True,
        answer_terms=("candidates, not confirmed incidents",),
    ),
    ChatCase(
        "validated_anomaly_wording",
        "Show confirmed validated anomaly candidates.",
        ("anomaly_candidates",),
        answer_terms=("No human-confirmed anomaly",),
    ),
)


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _fingerprint(database_url: str) -> tuple[str, dict[str, int]]:
    with session_scope(database_url) as session:
        document_count = int(session.scalar(select(func.count(SourceDocument.id))) or 0)
        chunk_count = int(session.scalar(select(func.count(RetrievalChunk.id))) or 0)
        hashes = session.scalars(
            select(RetrievalChunk.content_hash).order_by(RetrievalChunk.id)
        ).all()
    digest = hashlib.sha256("".join(hashes).encode()).hexdigest()
    return digest, {"source_documents": document_count, "retrieval_chunks": chunk_count}


def _check_case(case: ChatCase, answer: ChatAnswer, valid_files: set[str]) -> dict[str, Any]:
    checks = {
        "route": answer.route in case.expected_routes,
        "evidence": not case.require_evidence or bool(answer.evidence),
        "rows": not case.require_rows or bool(answer.rows),
        "language": case.expected_language is None
        or answer.detected_language == case.expected_language,
        "answer_terms": all(term.casefold() in answer.answer.casefold() for term in case.answer_terms),
        "follow_up_rewrite": not case.require_rewrite or bool(answer.rewritten_query),
        "corpus_boundary": not (
            case.case_id == "current_oil_price_refusal" and answer.route != "not_found_corpus"
        ),
    }
    cited_files = {
        str(item["file_name"])
        for item in answer.evidence
        if isinstance(item, dict) and item.get("file_name")
    }
    checks["citation_files"] = not cited_files or cited_files <= valid_files
    return {
        "case_id": case.case_id,
        "passed": all(checks.values()),
        "route": answer.route,
        "detected_language": answer.detected_language,
        "answer_type": answer.answer_type,
        "evidence_count": len(answer.evidence),
        "row_count": len(answer.rows),
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic DDR chat acceptance evaluation.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data/processed/evaluations/chat.json",
    )
    args = parser.parse_args()
    if not COMMITTED_DATABASE.is_file():
        raise SystemExit("Committed DDR database is unavailable.")

    with tempfile.TemporaryDirectory(prefix="ddr-chat-eval-") as temporary:
        database_path = Path(temporary) / "chat-eval.db"
        shutil.copy2(COMMITTED_DATABASE, database_path)
        database_url = f"sqlite:///{database_path.as_posix()}"
        fingerprint, corpus_counts = _fingerprint(database_url)
        with session_scope(database_url) as session:
            valid_files = set(session.scalars(select(SourceDocument.file_name)))
        provider = LexicalFallbackProvider("Evaluation forbids external model calls.")
        results: list[dict[str, Any]] = []
        latencies: list[float] = []
        for case in CASES:
            started = time.perf_counter()
            with session_scope(database_url) as session:
                answer = answer_question(
                    session,
                    case.question,
                    provider=provider,
                    history=list(case.history),
                )
            latency = time.perf_counter() - started
            latencies.append(latency)
            result = _check_case(case, answer, valid_files)
            result["latency_seconds"] = round(latency, 4)
            results.append(result)
        dispose_engine(database_url)

    passed = sum(bool(item["passed"]) for item in results)
    routes = Counter(str(item["route"]) for item in results)
    evidence_cases = [item for item in results if int(item["evidence_count"]) > 0]
    settings = Settings(_env_file=None)
    evaluation = {
        "evaluation_name": "ddr_deterministic_chat_acceptance",
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "parser_version": settings.parser_version,
        "model_version": "deterministic-query-planner-and-lexical-retriever",
        "data_fingerprint": fingerprint,
        "sample_count": len(results),
        "parameters": {
            "provider": "Lexical fallback",
            "external_model_calls": 0,
            "corpus_counts": corpus_counts,
            "fixed_case_ids": [item.case_id for item in CASES],
        },
        "actual_metrics": {
            "passed_cases": passed,
            "failed_cases": len(results) - passed,
            "pass_rate": passed / len(results),
            "cases_with_evidence": len(evidence_cases),
            "citation_file_validity_rate": mean(
                float(item["checks"]["citation_files"]) for item in results
            ),
            "mean_latency_seconds": mean(latencies),
            "median_latency_seconds": median(latencies),
            "max_latency_seconds": max(latencies),
            "routes": dict(sorted(routes.items())),
        },
        "cases": results,
        "limitations": [
            "This evaluation exercises deterministic planning, structured handlers, and lexical retrieval.",
            "No OpenAI request is made; LLM verbalization quality is outside this CI-safe evaluation.",
            "Candidate wording checks do not constitute domain validation.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "passed": passed,
                "failed": len(results) - passed,
                "failed_cases": [item["case_id"] for item in results if not item["passed"]],
            },
            indent=2,
        )
    )
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
