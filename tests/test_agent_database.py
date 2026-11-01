"""Database-layer containment tests. Need the local evaluation database; skipped otherwise."""
import os

import psycopg
import pytest

from agent.database import QueryError, ReadOnlyDB

RO_URL = os.environ.get("EVAL_DATABASE_URL", "postgresql://app_readonly@localhost:5433/uniprot")
PRIV_URL = os.environ.get("EVAL_PRIV_URL", "postgresql://ingest@localhost:5433/uniprot")


def _up(url):
    try:
        psycopg.connect(url, connect_timeout=2).close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(RO_URL), reason="evaluation database not available")


@pytest.fixture(scope="module")
def db():
    return ReadOnlyDB(RO_URL)


def test_catalog_has_20_tables_with_comments(db):
    assert len(db.catalog) == 20
    assert "NbExp" in db.catalog["interactions"].columns[3]["comment"]


def test_describe_reports_non_null_counts_and_samples(db):
    d = db.describe("mutagenesis")
    by = {c["name"]: c for c in d["columns"]}
    assert by["effect"]["non_null"] == 0 and by["description"]["non_null"] > 0
    assert len(d["sample_rows"]) == 3
    assert any("proteins" in fk for fk in d["foreign_keys"])


def test_describe_unknown_table_lists_alternatives(db):
    with pytest.raises(QueryError) as e:
        db.describe("protein")
    assert "proteins" in e.value.message


def test_search_values_finds_exact_spelling(db):
    hits = dict(db.search_values("proteins", "organism", "sapiens"))
    assert hits == {"Homo sapiens (Human)": 12000}


def test_search_values_escapes_wildcards(db):
    assert db.search_values("proteins", "organism", "%") == []


def test_run_returns_rows_and_columns(db):
    r = db.run("SELECT entry, entry_name FROM proteins WHERE entry = 'P04637'")
    assert r.columns == ["entry", "entry_name"] and r.rows == [("P04637", "P53_HUMAN")] and not r.truncated


def test_row_cap_holds_however_the_query_is_written(db):
    # The legacy LIMIT-regex let all three of these return tens of thousands of rows.
    for sql in ["SELECT * FROM interactions",
                "SELECT * FROM interactions -- note",
                "SELECT * FROM interactions WHERE protein_id IN (SELECT protein_id FROM proteins LIMIT 5000)"]:
        r = db.run(sql)
        assert len(r.rows) == 200 and r.truncated, sql


def test_runaway_query_is_cancelled_by_server_timeout():
    slow = ReadOnlyDB(RO_URL, timeout_ms=500)
    with pytest.raises(QueryError) as e:
        slow.run("SELECT count(*) FROM generate_series(1,100000) a, generate_series(1,100000) b")
    assert e.value.kind == "timeout"


def test_guard_rejection_surfaces_as_query_error(db):
    with pytest.raises(QueryError) as e:
        db.run("WITH d AS (DELETE FROM genes RETURNING *) SELECT count(*) FROM d")
    assert e.value.kind == "guard"


def test_sql_error_message_is_actionable(db):
    with pytest.raises(QueryError) as e:
        db.run("SELECT entri FROM proteins")
    assert e.value.kind == "sql" and "entri" in e.value.message


@pytest.mark.skipif(not _up(PRIV_URL), reason="privileged role not available")
def test_read_only_transaction_stops_writes_even_for_a_privileged_role():
    """Layer 2 on its own: bypass the guard and the least-privilege role entirely."""
    db = ReadOnlyDB(PRIV_URL)
    for write in ("DELETE FROM genes WHERE false", "CREATE TABLE should_not_exist (x int)"):
        with db._connect() as conn:  # a failed statement aborts the transaction: one per connection
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                conn.execute(write)


def test_privilege_warnings():
    assert ReadOnlyDB(RO_URL).privilege_warnings() == []
    if _up(PRIV_URL):
        assert ReadOnlyDB(PRIV_URL).privilege_warnings()
