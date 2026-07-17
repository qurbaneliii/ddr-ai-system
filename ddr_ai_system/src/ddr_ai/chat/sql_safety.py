from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp, parse


class UnsafeSQLError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedSQL:
    sql: str
    tables: tuple[str, ...]
    limit: int


PROHIBITED = (
    exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter,
    exp.Command, exp.Merge, exp.Transaction,
)


def validate_select_sql(
    sql: str,
    *,
    allowed_tables: set[str],
    default_limit: int = 200,
    max_limit: int = 1000,
    dialect: str = "sqlite",
) -> ValidatedSQL:
    try:
        statements = parse(sql, read=dialect)
    except Exception as exc:
        raise UnsafeSQLError("SQL could not be parsed") from exc
    if len(statements) != 1:
        raise UnsafeSQLError("Exactly one SQL statement is allowed")
    statement = statements[0]
    if statement is None:
        raise UnsafeSQLError("SQL did not contain a statement")
    if any(statement.find(kind) is not None for kind in PROHIBITED):
        raise UnsafeSQLError("Only read-only SELECT queries are allowed")
    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)) and not isinstance(
        statement, exp.Query
    ):
        raise UnsafeSQLError("Only SELECT queries are allowed")
    tables = {table.name.casefold() for table in statement.find_all(exp.Table)}
    disallowed = tables - {table.casefold() for table in allowed_tables}
    if disallowed:
        raise UnsafeSQLError(f"Table access is not allowed: {', '.join(sorted(disallowed))}")
    limit_node = statement.args.get("limit")
    requested = default_limit
    if limit_node is not None:
        expression = limit_node.expression
        if not isinstance(expression, exp.Literal) or not expression.is_int:
            raise UnsafeSQLError("LIMIT must be a literal integer")
        requested = int(expression.this)
    applied = max(1, min(requested, max_limit))
    statement.set("limit", exp.Limit(expression=exp.Literal.number(applied)))
    return ValidatedSQL(statement.sql(dialect=dialect), tuple(sorted(tables)), applied)
