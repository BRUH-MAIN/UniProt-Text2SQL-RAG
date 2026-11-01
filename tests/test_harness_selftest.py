"""The evaluation harness must itself be correct before its numbers mean anything.

Needs the local evaluation database (see evaluation/README.md); skipped otherwise.
"""
import json
from pathlib import Path

import psycopg
import pytest

from evaluation.dbexec import READONLY_URL
from evaluation.score import ARMS, score_one, summarize

HERE = Path(__file__).parent.parent / "evaluation"


def _db_up() -> bool:
    try:
        psycopg.connect(READONLY_URL, connect_timeout=2).close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _db_up() or not (HERE / "questions.jsonl").exists(),
                                reason="evaluation database / benchmark not available")


@pytest.fixture(scope="module")
def bench():
    qs = [json.loads(line) for line in (HERE / "questions.jsonl").read_text().splitlines()]
    gold = json.loads((HERE / "gold_results.json").read_text())
    return qs, gold


def _run(bench, make_output):
    qs, gold = bench
    adapter = ARMS["baseline"]
    return [score_one(q, {"id": q["id"], "raw_output": make_output(q)}, gold.get(q["id"]), adapter) for q in qs]


def test_oracle_scores_100_percent(bench):
    recs = _run(bench, lambda q: q["sql"] if q["expect"] == "rows" else "I cannot answer that.")
    s = summarize("oracle", recs)
    failures = [r["id"] for r in recs if r["expect"] == "rows" and not r["ex"]]
    assert failures == [], failures
    assert s["ex"] == 1.0
    assert s["fabricated_rate"] == 0.0
    assert s["unsafe_executed"] == 0


def test_constant_guess_scores_zero(bench):
    recs = _run(bench, lambda q: "SELECT 'x'")
    s = summarize("constant", recs)
    assert s["ex"] == 0.0
    assert s["fabricated_rate"] == 1.0


def test_prose_answers_are_blocked_not_crashed(bench):
    recs = _run(bench, lambda q: "Sorry, I can't help with that.")
    assert all(r["outcome"] in {"blocked_or_no_sql", "abstained", "safe"} for r in recs)


def test_missing_prediction_counts_as_failure(bench):
    qs, gold = bench
    r = score_one(qs[0], None, gold.get(qs[0]["id"]), ARMS["baseline"])
    assert r["outcome"] == "missing" and not r["pass_"]


def test_hostile_cte_is_flagged_as_executed_unsafe_by_legacy_guard(bench):
    hostile = "WITH d AS (DELETE FROM genes WHERE false RETURNING *) SELECT 1"
    recs = _run(bench, lambda q: hostile)
    safe = [r for r in recs if r["expect"] == "safe"]
    assert all(r["executed_unsafe"] for r in safe)
