"""AST-based SQL guard.

Built on pglast (the PostgreSQL server's own parser) instead of keyword matching, so a
statement is judged by what it *is*, not by which words appear in it. It is the first of
several independent layers (see agent/database.py): the guard gives early, explainable
rejections; the read-only transaction, statement timeout, row cap and least-privilege
role are what actually contain a mistake.

A query is accepted only if:
  * it is exactly one statement and that statement is a SELECT (CTEs allowed),
  * no INSERT/UPDATE/DELETE/MERGE appears anywhere in it (data-modifying CTEs),
  * it has no SELECT INTO and no locking clause (FOR UPDATE/SHARE),
  * it calls no administrative / file / network / session-changing function,
  * it reads only the application's own tables (or CTEs it defines itself) - never
    pg_catalog, information_schema, or another schema.
"""
import re
from dataclasses import dataclass

from pglast import ast, parse_sql
from pglast.visitors import Visitor

MAX_SQL_CHARS = 6000

_FENCE_RE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

BLOCKED_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink")
BLOCKED_FUNCTIONS = {"set_config", "current_setting", "query_to_xml", "table_to_xml", "xpath"}


def clean_sql(text: str) -> str:
    """Strip markdown code fences and a trailing semicolon."""
    return _FENCE_RE.sub("", text or "").strip().rstrip(";").strip()


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = ""
    sql: str = ""


class _Scan(Visitor):
    def __init__(self, allowed_tables: set[str]):
        super().__init__()
        self.allowed = allowed_tables
        self.ctes: set[str] = set()
        self.relations: list[ast.RangeVar] = []
        self.problems: list[str] = []

    def visit_CommonTableExpr(self, ancestors, node):  # noqa: N802
        self.ctes.add(node.ctename.lower())

    def visit_RangeVar(self, ancestors, node):  # noqa: N802
        self.relations.append(node)

    def visit_FuncCall(self, ancestors, node):  # noqa: N802
        name = node.funcname[-1].sval.lower()
        if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_FUNCTION_PREFIXES):
            self.problems.append(f"function {name}() is not allowed")

    def visit_SelectStmt(self, ancestors, node):  # noqa: N802
        if node.intoClause is not None:
            self.problems.append("SELECT ... INTO is not allowed")
        if node.lockingClause:
            self.problems.append("row locking (FOR UPDATE/SHARE) is not allowed")

    def _write(self, kind):
        self.problems.append(f"{kind} is not allowed (read-only access)")

    def visit_InsertStmt(self, ancestors, node):  # noqa: N802
        self._write("INSERT")

    def visit_UpdateStmt(self, ancestors, node):  # noqa: N802
        self._write("UPDATE")

    def visit_DeleteStmt(self, ancestors, node):  # noqa: N802
        self._write("DELETE")

    def visit_MergeStmt(self, ancestors, node):  # noqa: N802
        self._write("MERGE")


def check_sql(text: str, allowed_tables: set[str]) -> GuardResult:
    """Validate model-written SQL. `allowed_tables` = the application's table names."""
    sql = clean_sql(text)
    if not sql:
        return GuardResult(False, "empty query")
    if len(sql) > MAX_SQL_CHARS:
        return GuardResult(False, f"query longer than {MAX_SQL_CHARS} characters")
    try:
        stmts = parse_sql(sql)
    except Exception as e:  # noqa: BLE001 - pglast raises its own ParseError
        return GuardResult(False, f"not valid PostgreSQL: {str(e).splitlines()[0]}")
    if len(stmts) != 1:
        return GuardResult(False, "exactly one statement is allowed")
    root = stmts[0].stmt
    if not isinstance(root, ast.SelectStmt):
        return GuardResult(False, f"only SELECT is allowed, got {type(root).__name__}")

    scan = _Scan({t.lower() for t in allowed_tables})
    scan(root)
    problems = list(scan.problems)
    for rel in scan.relations:
        name = rel.relname.lower()
        if rel.schemaname and rel.schemaname.lower() != "public":
            problems.append(f"schema {rel.schemaname} is not allowed")
        elif name in scan.ctes and not rel.schemaname:
            continue
        elif name not in scan.allowed:
            known = ", ".join(sorted(scan.allowed))
            problems.append(f"unknown table {rel.relname!r}; available tables: {known}")
    if problems:
        return GuardResult(False, "; ".join(dict.fromkeys(problems)))
    return GuardResult(True, sql=sql)
