from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ddr_ai.chat.sql_safety import (
    UnsafeSQLError,
    execute_validated_select,
    validate_select_sql,
)

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


def test_validated_sql_executes_in_read_only_mode_with_limit() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE reports(id INTEGER, wellbore TEXT)")
        connection.exec_driver_sql("INSERT INTO reports VALUES (1, '15/9-F-14'), (2, '15/9-F-15')")
    validated = validate_select_sql(
        "SELECT id, wellbore FROM reports ORDER BY id",
        allowed_tables={"reports"},
        allowed_columns={"reports": {"id", "wellbore"}},
        default_limit=1,
    )
    with Session(engine) as session:
        rows = execute_validated_select(session, validated, timeout_seconds=1)
    assert rows == [{"id": 1, "wellbore": "15/9-F-14"}]
