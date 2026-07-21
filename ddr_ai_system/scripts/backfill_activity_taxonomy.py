from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from sqlalchemy import func, select

from ddr_ai.analytics.events import normalize_activity_result
from ddr_ai.config import get_settings
from ddr_ai.db.models import Operation, Report
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.retrieval.corpus import replace_document_chunks


def _distribution(values: list[str | None]) -> dict[str, int]:
    return dict(sorted(Counter(value or "null" for value in values).items()))


def backfill(*, database_url: str, apply: bool) -> dict[str, Any]:
    with session_scope(database_url) as session:
        before_total = int(session.scalar(select(func.count(Operation.id))) or 0)
        rows = list(
            session.execute(
                select(Operation, Report.source_document_id)
                .join(Report, Report.id == Operation.report_id)
                .order_by(Operation.id)
            )
        )
        before_main = _distribution([operation.main_activity_normalized for operation, _ in rows])
        before_sub = _distribution([operation.sub_activity_normalized for operation, _ in rows])
        changed = 0
        affected_documents: set[int] = set()
        unknown_main: Counter[str] = Counter()
        unknown_sub: Counter[str] = Counter()
        mapping_audit: dict[str, dict[str, dict[str, Any]]] = {"main": {}, "sub": {}}

        for operation, source_document_id in rows:
            main, sub = normalize_activity_result(
                operation.main_activity_raw, operation.sub_activity_raw
            )
            for bucket, result in (("main", main), ("sub", sub)):
                key = result.raw_label or "<missing>"
                mapping_audit[bucket][key] = {
                    "canonical": result.canonical_label,
                    "method": result.method,
                    "confidence": result.confidence,
                    "matched_alias": result.matched_alias,
                }
            if main.method == "unknown":
                unknown_main[operation.main_activity_raw or "<missing>"] += 1
            if sub.method == "unknown":
                unknown_sub[operation.sub_activity_raw or "<missing>"] += 1

            next_main = (
                main.canonical_label
                if main.method != "unknown"
                else operation.main_activity_normalized
            )
            next_sub = (
                sub.canonical_label
                if sub.method != "unknown"
                else operation.sub_activity_normalized
            )
            method = (
                "source_rule"
                if main.method != "unknown" and sub.method != "unknown"
                else "unknown"
            )
            confidence = min(main.confidence, sub.confidence) if method == "source_rule" else 0.0
            evidence = {
                "main": {
                    "raw": main.raw_label,
                    "canonical": main.canonical_label,
                    "method": main.method,
                    "matched_alias": main.matched_alias,
                },
                "sub": {
                    "raw": sub.raw_label,
                    "canonical": sub.canonical_label,
                    "method": sub.method,
                    "matched_alias": sub.matched_alias,
                },
            }
            row_changed = any(
                (
                    operation.main_activity_normalized != next_main,
                    operation.sub_activity_normalized != next_sub,
                    operation.classification_method != method,
                    operation.classification_confidence != confidence,
                    operation.classification_model_version is not None,
                    operation.classification_evidence_json != evidence,
                )
            )
            if not row_changed:
                continue
            changed += 1
            affected_documents.add(source_document_id)
            if apply:
                operation.main_activity_normalized = next_main
                operation.sub_activity_normalized = next_sub
                operation.classification_method = method
                operation.classification_confidence = confidence
                operation.classification_model_version = None
                operation.classification_evidence_json = evidence

        if apply:
            session.flush()
            rebuilt = sum(
                replace_document_chunks(session, source_document_id)
                for source_document_id in sorted(affected_documents)
            )
        else:
            rebuilt = 0
        after_total = int(session.scalar(select(func.count(Operation.id))) or 0)
        if after_total != before_total:
            raise RuntimeError("Operation count changed during taxonomy backfill.")
        after_main = _distribution(
            [
                (
                    normalize_activity_result(item.main_activity_raw, item.sub_activity_raw)[
                        0
                    ].canonical_label
                    if normalize_activity_result(item.main_activity_raw, item.sub_activity_raw)[
                        0
                    ].method
                    != "unknown"
                    else item.main_activity_normalized
                )
                for item, _ in rows
            ]
        )
        after_sub = _distribution(
            [
                (
                    normalize_activity_result(item.main_activity_raw, item.sub_activity_raw)[
                        1
                    ].canonical_label
                    if normalize_activity_result(item.main_activity_raw, item.sub_activity_raw)[
                        1
                    ].method
                    != "unknown"
                    else item.sub_activity_normalized
                )
                for item, _ in rows
            ]
        )
        return {
            "mode": "apply" if apply else "dry_run",
            "operation_count": before_total,
            "changed_rows": changed,
            "affected_documents": len(affected_documents),
            "retrieval_chunks_rebuilt": rebuilt,
            "before": {"main": before_main, "sub": before_sub},
            "after": {"main": after_main, "sub": after_sub},
            "unknown": {"main": dict(unknown_main), "sub": dict(unknown_sub)},
            "distinct_label_mapping": mapping_audit,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Canonicalize source-labelled operations without modifying raw labels."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Persist canonical labels and provenance.")
    mode.add_argument("--dry-run", action="store_true", help="Audit only (default).")
    args = parser.parse_args()
    settings = get_settings()
    upgrade_schema(settings.database_url)
    print(json.dumps(backfill(database_url=settings.database_url, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
