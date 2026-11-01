"""Red-team the SQL safety layer with hostile statements.

For every case we record, per executor:
  guard     - did `is_safe_select(clean_sql(sql))` let it through?
  readonly  - outcome when run as the SELECT-only `app_readonly` role
  privileged- outcome when run as a superuser on a THROWAWAY copy of the DB
              (what happens if DATABASE_URL is mis-set - the docs' only real
              protection is that it "should" be the read-only role)

Each execution runs in a subprocess with a watchdog so a query that never
returns is reported as such instead of hanging the harness.

Usage:  python -m evaluation.redteam --executor legacy  --out evaluation/results/redteam_legacy.json
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import psycopg

ADMIN_URL = "postgresql://postgres@localhost:5433/postgres"
MAIN_DB, SCRATCH_DB = "uniprot", "uniprot_scratch"
RO_URL = f"postgresql://app_readonly@localhost:5433/{MAIN_DB}"
PRIV_URL = f"postgresql://ingest@localhost:5433/{SCRATCH_DB}"
WATCHDOG_S = 4

# (id, class, description, sql, what a correct system must do)
CASES = [
    ("ctl_select", "control", "plain SELECT", "SELECT entry FROM proteins LIMIT 3", "allow"),
    ("ctl_cte", "control", "read-only CTE", "WITH t AS (SELECT entry FROM proteins LIMIT 3) SELECT * FROM t", "allow"),
    ("ctl_semicolon_in_literal", "control", "';' inside a string literal", "SELECT 'a;b' AS x", "allow"),
    ("w_cte_delete", "write", "data-modifying CTE (DELETE)",
     "WITH d AS (DELETE FROM genes WHERE gene_id < 0 RETURNING *) SELECT count(*) FROM d", "block"),
    ("w_cte_insert", "write", "data-modifying CTE (INSERT)",
     "WITH i AS (INSERT INTO genes(gene_name) VALUES ('REDTEAM_X') RETURNING *) SELECT * FROM i", "block"),
    ("w_cte_update", "write", "data-modifying CTE (UPDATE)",
     "WITH u AS (UPDATE genes SET gene_name = gene_name WHERE gene_id < 0 RETURNING *) SELECT count(*) FROM u", "block"),
    ("w_with_delete_tail", "write", "WITH ... DELETE (SELECT only inside the CTE)",
     "WITH x AS (SELECT 1) DELETE FROM genes WHERE gene_id < 0", "block"),
    ("w_select_into", "write", "SELECT ... INTO creates a table",
     "SELECT * INTO redteam_copy FROM genes LIMIT 1", "block"),
    ("w_for_update", "write", "SELECT ... FOR UPDATE takes row locks",
     "SELECT * FROM genes LIMIT 1 FOR UPDATE", "block"),
    ("w_stacked", "write", "stacked statements", "SELECT 1; DROP TABLE genes", "block"),
    ("w_leading_comment", "write", "comment before DELETE", "/* hi */ DELETE FROM genes WHERE gene_id < 0", "block"),
    ("w_explain_analyze", "write", "EXPLAIN ANALYZE of a write", "EXPLAIN ANALYZE DELETE FROM genes WHERE gene_id < 0", "block"),
    ("w_copy_program", "write", "COPY ... TO PROGRAM", "COPY (SELECT 1) TO PROGRAM 'id'", "block"),
    ("d_pg_sleep", "dos", "pg_sleep ties up a connection", "SELECT pg_sleep(30)", "block or time-limit"),
    ("d_cartesian", "dos", "cartesian product, never returns",
     "SELECT count(*) FROM generate_series(1,100000) a, generate_series(1,100000) b", "block or time-limit"),
    ("d_unbounded_comment", "dos", "trailing comment swallows the appended LIMIT",
     "SELECT * FROM interactions -- note", "cap at 200 rows"),
    ("d_unbounded_subquery_limit", "dos", "LIMIT in a subquery defeats the LIMIT regex",
     "SELECT * FROM interactions WHERE protein_id IN (SELECT protein_id FROM proteins LIMIT 5000)", "cap at 200 rows"),
    ("x_pg_read_file", "exfil", "server-side file read", "SELECT pg_read_file('PG_VERSION')", "block"),
    ("x_lo_import", "exfil", "server-side large-object import", "SELECT lo_import('PG_VERSION')", "block"),
    ("x_set_config", "exfil", "change a session setting", "SELECT set_config('statement_timeout','0',false)", "block"),
    ("x_pg_user", "exfil", "enumerate DB roles", "SELECT usename FROM pg_user", "block"),
]


def _scratch(create: bool) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
        if create:
            c.execute(f"CREATE DATABASE {SCRATCH_DB} TEMPLATE {MAIN_DB}")


def _kill_stragglers() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname IN (%s,%s) AND pid <> pg_backend_pid() "
            "AND usename IN ('app_readonly','ingest')",
            (MAIN_DB, SCRATCH_DB),
        )


LEGACY_RUNNER = """
import json, sys, time
from baseline.sql_guard import clean_sql, is_safe_select
from db.connection import run_select
sql = clean_sql(sys.argv[1])
if not is_safe_select(sql):
    print(json.dumps({"guard": False})); sys.exit(0)
t = time.time()
try:
    rows = run_select(sql)
    out = {"guard": True, "ok": True, "rows": len(rows)}
except Exception as e:
    out = {"guard": True, "ok": False, "error": type(e).__name__ + ": " + str(e).splitlines()[0][:160]}
out["secs"] = round(time.time() - t, 2)
print(json.dumps(out))
"""


HARDENED_RUNNER = """
import json, os, sys, time
from agent.database import ReadOnlyDB, QueryError
db = ReadOnlyDB(os.environ["DATABASE_URL"], timeout_ms=2000)
t = time.time()
try:
    r = db.run(sys.argv[1])
    out = {"guard": True, "ok": True, "rows": len(r.rows), "truncated": r.truncated}
except QueryError as e:
    out = {"guard": e.kind != "guard", "ok": False, "error": e.kind + ": " + e.message[:160], "kind": e.kind}
except Exception as e:
    out = {"guard": True, "ok": False, "error": type(e).__name__ + ": " + str(e).splitlines()[0][:160], "kind": "internal"}
out["secs"] = round(time.time() - t, 2)
print(json.dumps(out))
"""


def _run(runner: str, sql: str, url: str) -> dict:
    env = {"DATABASE_URL": url, "PATH": "/usr/bin:/bin"}
    try:
        p = subprocess.run(
            [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.')\n" + runner, sql],
            capture_output=True, text=True, timeout=WATCHDOG_S, env=env,
        )
    except subprocess.TimeoutExpired:
        _kill_stragglers()
        return {"guard": True, "ok": None, "hung": True, "secs": WATCHDOG_S}
    if p.returncode != 0:
        return {"guard": None, "error": p.stderr.strip().splitlines()[-1][:200] if p.stderr else "crash"}
    return json.loads(p.stdout.strip().splitlines()[-1])


def summarize(r: dict) -> str:
    if r.get("guard") is False:
        return "BLOCKED by guard"
    if r.get("hung"):
        return f"RAN >{WATCHDOG_S}s (no timeout)"
    if r.get("kind") == "timeout":
        return "CANCELLED by server timeout"
    if r.get("error", "").startswith("sql: cannot execute") or "read-only transaction" in r.get("error", ""):
        return "REFUSED by read-only transaction"
    if r.get("ok"):
        cap = " (capped)" if r.get("truncated") else ""
        return f"ran, {r['rows']} rows{cap}"
    if "didn't produce records" in r.get("error", ""):
        return "EXECUTED (a write; no rows to fetch)"
    return "db error: " + r.get("error", "?")[:90]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--executor", default="legacy", choices=["legacy", "hardened"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    runner = LEGACY_RUNNER if args.executor == "legacy" else HARDENED_RUNNER

    _scratch(create=True)
    results = []
    try:
        for cid, klass, desc, sql, expect in CASES:
            ro = _run(runner, sql, RO_URL)
            priv = _run(runner, sql, PRIV_URL)
            row = {"id": cid, "class": klass, "desc": desc, "sql": sql, "expect": expect,
                   "guard_passed": ro.get("guard"), "readonly": ro, "privileged": priv,
                   "readonly_summary": summarize(ro), "privileged_summary": summarize(priv)}
            results.append(row)
            print(f"{cid:28} guard={'pass' if row['guard_passed'] else 'BLOCK':5} | ro: {row['readonly_summary']:40} | priv: {row['privileged_summary']}")
    finally:
        _kill_stragglers()
        _scratch(create=False)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
