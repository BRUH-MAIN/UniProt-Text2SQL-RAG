"""Query execution used by the evaluation harness.

Mirrors `db.connection.run_select` (including its LIMIT-appending behaviour, which is
part of the system under test) but adds what the harness needs to be safe and
reproducible: a read-only transaction and a statement timeout.
"""
import os
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg

from db.connection import _ensure_limit

READONLY_URL = os.environ.get("EVAL_DATABASE_URL", "postgresql://app_readonly@localhost:5433/uniprot")


@dataclass
class ExecResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: str = ""
    error_type: str = ""
    ms: float = 0.0


def execute(sql: str, *, url: str = READONLY_URL, timeout_ms: int = 15000,
            pipeline_limit: bool = True) -> ExecResult:
    """Run `sql` read-only. `pipeline_limit=True` reproduces run_select's LIMIT handling."""
    text = _ensure_limit(sql) if pipeline_limit else sql.strip().rstrip(";")
    t0 = time.perf_counter()
    try:
        with psycopg.connect(url) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                cur.execute(text)
                cols = [d.name for d in cur.description] if cur.description else []
                rows = cur.fetchall() if cur.description else []
        return ExecResult(True, cols, rows, ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:  # noqa: BLE001 - every failure is a scored outcome
        return ExecResult(False, error=str(e).strip().splitlines()[0][:300],
                          error_type=type(e).__name__, ms=(time.perf_counter() - t0) * 1000)


def json_safe(v: Any) -> Any:
    from decimal import Decimal
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    return str(v)
