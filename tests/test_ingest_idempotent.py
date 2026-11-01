"""Loading the same input twice must not change the database. Uses a throwaway database."""
import os
from pathlib import Path

import psycopg
import pytest

from ingest.parse_and_load import run

ADMIN = os.environ.get("EVAL_ADMIN_URL", "postgresql://postgres@localhost:5433/postgres")
SCRATCH = "uniprot_ingest_test"
FIXTURE = Path(__file__).parent / "fixtures" / "sample.dat"
DB_DIR = Path(__file__).parent.parent / "db"


def _up():
    try:
        psycopg.connect(ADMIN, connect_timeout=2).close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="local Postgres not available")


@pytest.fixture()
def url(monkeypatch):
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {SCRATCH}")
    scratch_url = ADMIN.rsplit("/", 1)[0] + "/" + SCRATCH
    with psycopg.connect(scratch_url) as c:
        c.execute((DB_DIR / "schema.sql").read_text() + (DB_DIR / "annotations.sql").read_text())
    monkeypatch.setenv("INGEST_DATABASE_URL", scratch_url)
    yield scratch_url
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)")


def _counts(url):
    with psycopg.connect(url) as c:
        tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")]
        return {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def test_second_run_without_truncate_changes_nothing(url):
    run(FIXTURE, 10, truncate=False)
    first = _counts(url)
    assert first["proteins"] == 3 and sum(first.values()) > 30
    run(FIXTURE, 10, truncate=False)
    assert _counts(url) == first


def test_truncate_discards_reference_rows_from_the_previous_load(url):
    """A truncating reload of a smaller input must equal a clean load of that input - including the
    genes/pathways/families tables, which are not FK-children of proteins and used to survive."""
    run(FIXTURE, 1, truncate=False)
    clean_one = _counts(url)
    run(FIXTURE, 10, truncate=False)      # now holds all 3 proteins and their genes/families
    assert _counts(url)["genes"] > clean_one["genes"]
    run(FIXTURE, 1, truncate=True)
    assert _counts(url) == clean_one
