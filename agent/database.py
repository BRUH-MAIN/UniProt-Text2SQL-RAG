"""Read-only database access for the SQL agent.

Containment is layered, and no single layer is trusted on its own:

  1. agent.guard      - AST allowlist: one SELECT, no writes/functions/catalogs (early, explainable)
  2. READ ONLY txn    - Postgres itself refuses any write, even from a privileged role
  3. statement_timeout- a runaway query (cartesian join, pg_sleep) is cancelled by the server
  4. row cap          - at most MAX_ROWS rows are ever pulled over the wire (server-side cursor),
                        regardless of how the query is written; truncation is reported
  5. least privilege  - the deployed DATABASE_URL should be a SELECT-only role; `privilege_warnings`
                        reports it loudly if it is not

The introspection helpers (tables / describe / search_values) never interpolate model output
into SQL: identifiers are validated against the catalog and quoted, values are bound parameters.
"""
import os
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import sql as psql

from agent.guard import check_sql

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 10_000
CELL_CHARS = 160


class QueryError(Exception):
    """A query was rejected or failed. `kind` is guard | timeout | sql | internal."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    elapsed_ms: float
    sql: str = ""


@dataclass
class TableInfo:
    name: str
    comment: str
    n_rows: int
    columns: list[dict] = field(default_factory=list)
    foreign_keys: list[str] = field(default_factory=list)


def _clip(v: Any, n: int = CELL_CHARS) -> Any:
    return v[: n - 1] + "…" if isinstance(v, str) and len(v) > n else v


class ReadOnlyDB:
    def __init__(self, url: str | None = None, *, timeout_ms: int = STATEMENT_TIMEOUT_MS,
                 max_rows: int = MAX_ROWS):
        self.url = url or os.environ["DATABASE_URL"]
        self.timeout_ms, self.max_rows = timeout_ms, max_rows
        self._catalog: dict[str, TableInfo] | None = None

    # ------------------------------------------------------------------ connection
    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.url)
        conn.read_only = True  # BEGIN READ ONLY
        return conn

    # ------------------------------------------------------------------ catalog
    @property
    def catalog(self) -> dict[str, TableInfo]:
        if self._catalog is None:
            self._catalog = self._load_catalog()
        return self._catalog

    def table_names(self) -> set[str]:
        return set(self.catalog)

    def _load_catalog(self) -> dict[str, TableInfo]:
        with self._connect() as conn:
            tables = conn.execute(
                "SELECT c.relname, coalesce(obj_description(c.oid, 'pg_class'), '') "
                "FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' ORDER BY 1"
            ).fetchall()
            out: dict[str, TableInfo] = {}
            for name, comment in tables:
                n = conn.execute(psql.SQL("SELECT count(*) FROM {}").format(psql.Identifier(name))).fetchone()[0]
                cols = conn.execute(
                    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull, "
                    "coalesce(col_description(a.attrelid, a.attnum), '') "
                    "FROM pg_attribute a WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped "
                    "ORDER BY a.attnum", (f"public.{name}",)).fetchall()
                out[name] = TableInfo(name, comment, n, [
                    {"name": c[0], "type": c[1], "nullable": c[2], "comment": c[3]} for c in cols])
            fks = conn.execute(
                "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE contype = 'f' AND connamespace = 'public'::regnamespace").fetchall()
        for table, definition in fks:
            out[table].foreign_keys.append(definition)
        return out

    # ------------------------------------------------------------------ introspection tools
    def describe(self, table: str, sample_rows: int = 3) -> dict:
        info = self._table(table)
        with self._connect() as conn:
            nn = conn.execute(psql.SQL("SELECT {} FROM {}").format(
                psql.SQL(", ").join(psql.SQL("count({})").format(psql.Identifier(c["name"])) for c in info.columns),
                psql.Identifier(info.name))).fetchone()
            cur = conn.execute(psql.SQL("SELECT * FROM {} LIMIT %s").format(psql.Identifier(info.name)), (sample_rows,))
            samples = [tuple(_clip(v, 80) for v in r) for r in cur.fetchall()]
        cols = [{**c, "non_null": non_null} for c, non_null in zip(info.columns, nn)]
        return {"table": info.name, "comment": info.comment, "n_rows": info.n_rows,
                "columns": cols, "foreign_keys": info.foreign_keys, "sample_rows": samples}

    def search_values(self, table: str, column: str, pattern: str, limit: int = 10) -> list[tuple[str, int]]:
        info = self._table(table)
        if column not in {c["name"] for c in info.columns}:
            raise QueryError("sql", f"unknown column {column!r} in {table}; columns: "
                             + ", ".join(c["name"] for c in info.columns))
        like = "%" + pattern.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        q = psql.SQL("SELECT {c}::text, count(*) FROM {t} WHERE {c}::text ILIKE %s "
                     "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %s").format(
            c=psql.Identifier(column), t=psql.Identifier(info.name))
        with self._connect() as conn:
            conn.execute(f"SET LOCAL statement_timeout = {int(self.timeout_ms)}")
            return [(_clip(v), n) for v, n in conn.execute(q, (like, min(int(limit), 25))).fetchall()]

    def _table(self, table: str) -> TableInfo:
        info = self.catalog.get(table.strip().lower())
        if info is None:
            raise QueryError("sql", f"unknown table {table!r}; available tables: " + ", ".join(sorted(self.catalog)))
        return info

    # ------------------------------------------------------------------ model-written SQL
    def run(self, text: str) -> QueryResult:
        verdict = check_sql(text, self.table_names())
        if not verdict.ok:
            raise QueryError("guard", verdict.reason)
        import time
        t0 = time.perf_counter()
        try:
            with self._connect() as conn:
                conn.execute(f"SET LOCAL statement_timeout = {int(self.timeout_ms)}")
                conn.execute("SET LOCAL lock_timeout = 2000")
                with conn.cursor(name="agent_cur") as cur:  # server-side: only max_rows+1 rows travel
                    cur.execute(verdict.sql)
                    fetched = cur.fetchmany(self.max_rows + 1)
                    cols = [d.name for d in cur.description] if cur.description else []
        except psycopg.errors.QueryCanceled:
            raise QueryError("timeout", f"query exceeded {self.timeout_ms / 1000:.0f}s and was cancelled; "
                             "make it cheaper (filter earlier, avoid cross joins)") from None
        except psycopg.Error as e:
            diag = e.diag
            msg = diag.message_primary or str(e).splitlines()[0]
            if diag.message_hint:
                msg += f" (hint: {diag.message_hint})"
            raise QueryError("sql", msg) from None
        truncated = len(fetched) > self.max_rows
        return QueryResult(cols, fetched[: self.max_rows], truncated, (time.perf_counter() - t0) * 1000, verdict.sql)

    # ------------------------------------------------------------------ deployment hygiene
    def privilege_warnings(self) -> list[str]:
        """Problems with the role this connection uses (empty list = least-privilege)."""
        warnings = []
        with self._connect() as conn:
            row = conn.execute("SELECT current_user, rolsuper, rolcreatedb, rolcreaterole "
                               "FROM pg_roles WHERE rolname = current_user").fetchone()
            user, sup, cdb, crole = row
            if sup or cdb or crole:
                warnings.append(f"role {user!r} has elevated attributes (superuser={sup}, createdb={cdb}, createrole={crole})")
            writable = [t for t in self.catalog if conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'INSERT,UPDATE,DELETE,TRUNCATE')",
                (f"public.{t}",)).fetchone()[0]]
            if writable:
                warnings.append(f"role {user!r} can write to {len(writable)} table(s), e.g. {writable[0]}; use a SELECT-only role")
        return warnings
