"""Safety checks applied to LLM-generated SQL before execution.

This is defense-in-depth on top of, not instead of, a database-level
read-only role (see docs/SETUP.md) - the app's DATABASE_URL should already
only have SELECT privileges.
"""
import re

import sqlparse
from sqlparse.sql import Statement

_FENCE_RE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def clean_sql(text: str) -> str:
    """Strip markdown code fences the LLM commonly wraps SQL in."""
    return _FENCE_RE.sub("", text).strip()


def is_safe_select(sql: str) -> bool:
    """True only if `sql` is exactly one SELECT (or WITH ... SELECT) statement."""
    statements = [s for s in sqlparse.parse(sql) if not _is_empty(s)]
    if len(statements) != 1:
        return False

    statement = statements[0]
    stmt_type = statement.get_type()
    if stmt_type == "SELECT":
        return True
    # sqlparse reports CTEs (WITH ...) as UNKNOWN; confirm it resolves to a SELECT.
    if stmt_type == "UNKNOWN":
        first_keyword = statement.token_first(skip_cm=True)
        if first_keyword and first_keyword.normalized.upper() == "WITH":
            return "SELECT" in sql.upper()
    return False


def _is_empty(statement: Statement) -> bool:
    return not statement.tokens or statement.token_first(skip_cm=True) is None
