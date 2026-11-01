"""The Gradio handler end to end, with a scripted model and the real database."""
import importlib
import json
import os

import psycopg
import pytest

from agent.llm import ScriptedLLM
from agent.ratelimit import RateLimiter

RO_URL = os.environ.get("EVAL_DATABASE_URL", "postgresql://app_readonly@localhost:5433/uniprot")


def _up():
    try:
        psycopg.connect(RO_URL, connect_timeout=2).close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytest.importorskip("gradio")
pytestmark = pytest.mark.skipif(not _up(), reason="evaluation database not available")


def act(action, **args):
    return json.dumps({"thought": "t", "action": action, "args": args})


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model-1")
    monkeypatch.setenv("DATABASE_URL", RO_URL)
    mod = importlib.import_module("app")
    mod = importlib.reload(mod)
    mod.LIMITER = RateLimiter(per_client=3, global_limit=100)
    return mod


def test_answers_and_shows_sql_trace_and_rows(app):
    app.LLM = ScriptedLLM([act("run_sql", sql="SELECT count(*) AS n FROM proteins"), act("answer", text="There are 12000 proteins.")])
    answer, sql, trace, table = app.ask("How many proteins?")
    assert answer == "There are 12000 proteins."
    assert sql.startswith("SELECT count(*)") and "run_sql" in trace
    assert table.to_dict("records") == [{"n": 12000}]


def test_ungrounded_answer_carries_a_warning(app):
    app.LLM = ScriptedLLM([act("run_sql", sql="SELECT count(*) FROM proteins"), act("answer", text="There are 99999 proteins.")])
    answer, *_ = app.ask("How many proteins?")
    assert "⚠️" in answer and "99999" in answer


def test_decline_is_explained(app):
    app.LLM = ScriptedLLM([act("decline", reason="Data cannot be modified.")])
    answer, sql, _trace, table = app.ask("Delete all proteins.")
    assert answer.startswith("I can't answer") and "cannot be modified" in answer and sql == "" and table.empty


def test_truncated_result_is_flagged(app):
    app.LLM = ScriptedLLM([act("run_sql", sql="SELECT * FROM interactions"), act("answer", text="Here are the interactions.")])
    answer, _sql, _trace, table = app.ask("Show all interactions")
    assert "only the first 200" in answer and len(table) == 200


def test_rate_limit_and_input_limits(app):
    app.LLM = ScriptedLLM([act("decline", reason="x")])
    assert "Please enter" in app.ask("   ")[0]
    assert "under 500" in app.ask("x" * 501)[0]
    for _ in range(3):
        app.ask("q")
    assert "per hour" in app.ask("q")[0]


def test_llm_failure_is_a_message_not_a_stack_trace(app):
    class Boom:
        name = "boom"

        def complete(self, messages):
            raise RuntimeError("provider down")

    app.LLM = Boom()
    answer, *_ = app.ask("anything")
    assert "agent failed" in answer and "provider down" in answer


def test_missing_config_is_reported(monkeypatch):
    for v in ("GEMINI_API_KEY", "GEMINI_MODEL", "DATABASE_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    mod = importlib.reload(importlib.import_module("app"))
    assert mod.CONFIG_ERROR and "GEMINI_MODEL" in mod.CONFIG_ERROR
    assert "Missing configuration" in mod.ask("hi")[0]
