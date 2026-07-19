from __future__ import annotations

import pytest

from ddr_ai.chat.grounding import unsupported_claim_reason
from ddr_ai.chat.sql_safety import UnsafeSQLError, validate_select_sql

ALLOWED = {"reports", "operations"}


def test_select_only_query_gets_limit() -> None:
    result = validate_select_sql("SELECT wellbore FROM reports", allowed_tables=ALLOWED, default_limit=25)
    assert result.limit == 25
    assert "LIMIT 25" in result.sql


def test_limit_is_clamped() -> None:
    result = validate_select_sql("SELECT * FROM operations LIMIT 99999", allowed_tables=ALLOWED, max_limit=100)
    assert result.limit == 100


@pytest.mark.parametrize("sql", [
    "DELETE FROM reports", "UPDATE reports SET wellbore='x'", "DROP TABLE reports",
    "CREATE TABLE bad(x INT)", "SELECT * FROM reports; SELECT * FROM operations",
])
def test_ddl_dml_and_multiple_statements_rejected(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        validate_select_sql(sql, allowed_tables=ALLOWED)


def test_disallowed_table_rejected() -> None:
    with pytest.raises(UnsafeSQLError, match="not allowed"):
        validate_select_sql("SELECT * FROM sqlite_master", allowed_tables=ALLOWED)


def test_generated_sql_restricts_columns_and_wildcards() -> None:
    with pytest.raises(UnsafeSQLError, match="Wildcard"):
        validate_select_sql(
            "SELECT * FROM reports",
            allowed_tables={"reports"},
            allowed_columns={"reports": {"id", "wellbore"}},
        )
    with pytest.raises(UnsafeSQLError, match="secret_note"):
        validate_select_sql(
            "SELECT secret_note FROM reports",
            allowed_tables={"reports"},
            allowed_columns={"reports": {"id", "wellbore"}},
        )


def test_grounding_rejects_unsupported_numeric_claim() -> None:
    reason = unsupported_claim_reason(
        "There were 999 failures.",
        "structured_failure_activity",
        [{"failure_count": 2}],
        [{"source_file": "report.pdf", "page_number": 1}],
        [],
        deterministic_answer="There were 2 source-backed failures.",
    )
    assert reason == "LLM answer rejected because it introduced unsupported numeric claims."
