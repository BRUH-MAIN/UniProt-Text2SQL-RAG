"""Read-only database access for the Streamlit app.

Deliberately dependency-light: no SQLAlchemy/ORM. The schema is static after
ingestion, so it's read straight from schema.sql rather than introspected at
runtime.
"""
import os
import re
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_LIMIT_RE = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)
DEFAULT_ROW_LIMIT = 200


def get_schema() -> str:
    """Return the DDL as a schema description to feed into LLM prompts."""
    return SCHEMA_PATH.read_text(encoding="utf-8")


def _ensure_limit(sql: str, limit: int = DEFAULT_ROW_LIMIT) -> str:
    """Append a LIMIT clause if the query doesn't already have one."""
    trimmed = sql.strip().rstrip(";").strip()
    if _LIMIT_RE.search(trimmed):
        return trimmed
    return f"{trimmed} LIMIT {limit}"


def run_select(sql: str) -> list[dict[str, Any]]:
    """Execute a read-only SELECT against DATABASE_URL and return rows as dicts.

    Callers must have already validated `sql` with baseline.sql_guard.is_safe_select
    before calling this - this function does not itself restrict statement type.
    """
    database_url = os.environ["DATABASE_URL"]
    bounded_sql = _ensure_limit(sql)

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(bounded_sql)
            return cur.fetchall()
