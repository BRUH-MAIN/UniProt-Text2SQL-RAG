"""Agent-loop behaviour with scripted model replies against the real evaluation database."""
import json
import os

import psycopg
import pytest

from agent.database import ReadOnlyDB
from agent.llm import ScriptedLLM
from agent.loop import parse_action, run_agent

RO_URL = os.environ.get("EVAL_DATABASE_URL", "postgresql://app_readonly@localhost:5433/uniprot")


def _up():
    try:
        psycopg.connect(RO_URL, connect_timeout=2).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def act(action, thought="t", **args):
    return json.dumps({"thought": thought, "action": action, "args": args})


@pytest.fixture(scope="module")
def db():
    if not _up():
        pytest.skip("evaluation database not available")
    return ReadOnlyDB(RO_URL)


# ---------------------------------------------------------------- parsing (no DB needed)
@pytest.mark.parametrize("text", [
    '{"thought": "x", "action": "list_tables", "args": {}}',
    '```json\n{"thought": "x", "action": "list_tables", "args": {}}\n```',
    'Sure! Here is my step:\n{"thought": "x", "action": "list_tables", "args": {}}\nHope that helps.',
])
def test_parse_tolerates_fences_and_prose(text):
    assert parse_action(text)[0] == "list_tables"


def test_parse_handles_braces_inside_strings():
    out = parse_action('{"thought": "a } b", "action": "run_sql", "args": {"sql": "SELECT \'{\' AS x"}}')
    assert out[0] == "run_sql" and out[1]["sql"] == "SELECT '{' AS x"


@pytest.mark.parametrize("text", ["", "no json here", '{"action": "rm -rf"}', '{"thought": "no action"}', "[1,2]"])
def test_parse_rejects_garbage(text):
    assert parse_action(text) is None


# ---------------------------------------------------------------- loop
def test_happy_path_explores_then_answers_with_grounded_numbers(db):
    llm = ScriptedLLM([
        act("describe_table", table="proteins"),
        act("search_values", table="proteins", column="organism", pattern="sapiens"),
        act("run_sql", sql="SELECT count(*) FROM proteins WHERE organism = 'Homo sapiens (Human)'"),
        act("answer", text="There are 12000 human proteins.", query="Q1"),
    ])
    r = run_agent("How many human proteins are there?", llm, db)
    assert r.outcome == "answered" and r.rows == [(12000,)] and r.grounding.ok
    assert [s.action for s in r.steps] == ["describe_table", "search_values", "run_sql", "answer"]
    assert "'Homo sapiens (Human)': 12000" in r.steps[1].observation
    assert "[ALWAYS NULL]" not in r.steps[0].observation  # proteins has no always-null columns
    assert r.sql.startswith("SELECT count(*)")


def test_sql_error_is_fed_back_and_repaired(db):
    llm = ScriptedLLM([
        act("run_sql", sql="SELECT entri FROM proteins LIMIT 1"),
        act("run_sql", sql="SELECT entry FROM proteins ORDER BY entry LIMIT 1"),
        act("answer", text="The first accession is A0A087X1C5."),
    ])
    r = run_agent("First accession?", llm, db)
    assert not r.steps[0].ok and "ERROR (sql)" in r.steps[0].observation and "entri" in r.steps[0].observation
    assert r.outcome == "answered" and r.rows == [("A0A087X1C5",)]


def test_guard_rejection_is_reported_and_agent_can_decline(db):
    llm = ScriptedLLM([act("run_sql", sql="DELETE FROM proteins"), act("decline", reason="Read-only database.")])
    r = run_agent("Delete everything", llm, db)
    assert "ERROR (guard)" in r.steps[0].observation
    assert r.outcome == "declined" and r.sql is None and r.rows == []


def test_cannot_answer_before_running_a_query(db):
    llm = ScriptedLLM([act("answer", text="42"), act("run_sql", sql="SELECT count(*) FROM genes"),
                       act("answer", text="26619 genes.")])
    r = run_agent("How many genes?", llm, db)
    assert not r.steps[0].ok and "not run a successful query" in r.steps[0].observation
    assert r.outcome == "answered" and r.rows == [(26619,)]


def test_malformed_reply_gets_one_more_chance(db):
    llm = ScriptedLLM(["I think the answer is 12000.", act("run_sql", sql="SELECT 1"), act("answer", text="1")])
    r = run_agent("?", llm, db)
    assert r.steps[0].action == "invalid" and not r.steps[0].ok
    assert r.outcome == "answered"


def test_budget_exhaustion_claims_no_answer_and_no_sql(db):
    llm = ScriptedLLM([act("run_sql", sql="SELECT count(*) FROM proteins")] * 5)
    r = run_agent("loop forever", llm, db, max_steps=3)
    assert r.outcome == "budget_exhausted" and len(r.steps) == 3
    assert r.answer is None and r.sql is None and r.last_sql == "SELECT count(*) FROM proteins"
    assert len(llm.calls) == 3


def test_last_step_nudge_is_sent(db):
    llm = ScriptedLLM([act("list_tables")] * 4)
    run_agent("?", llm, db, max_steps=3)
    assert "last step" in llm.calls[2][-1]["content"]
    assert "last step" not in llm.calls[1][-1]["content"]


def test_answer_can_cite_an_earlier_query(db):
    llm = ScriptedLLM([
        act("run_sql", sql="SELECT count(*) FROM genes"),
        act("run_sql", sql="SELECT count(*) FROM proteins"),
        act("answer", text="26619 genes.", query="Q1"),
    ])
    r = run_agent("How many genes?", llm, db)
    assert r.chosen_query == "Q1" and r.rows == [(26619,)] and r.grounding.ok


def test_unknown_query_reference_is_rejected(db):
    llm = ScriptedLLM([act("run_sql", sql="SELECT 1"), act("answer", text="1", query="Q9"), act("answer", text="1")])
    r = run_agent("?", llm, db)
    assert not r.steps[1].ok and "Unknown query" in r.steps[1].observation and r.outcome == "answered"


def test_invented_number_is_flagged_on_the_result(db):
    llm = ScriptedLLM([act("run_sql", sql="SELECT count(*) FROM proteins"), act("answer", text="There are 99999 proteins.")])
    r = run_agent("How many proteins?", llm, db)
    assert r.outcome == "answered" and not r.grounding.ok and r.grounding.ungrounded_numbers == ["99999"]


def test_empty_result_answer_must_say_so(db):
    llm = ScriptedLLM([act("run_sql", sql="SELECT dose_description FROM toxic_doses"),
                       act("answer", text="The toxic dose is 5 mg/kg.")])
    r = run_agent("Toxic doses?", llm, db)
    assert r.rows == [] and r.grounding.empty_result_not_acknowledged


def test_system_prompt_carries_overview_and_step_budget(db):
    llm = ScriptedLLM([act("decline", reason="x")])
    run_agent("?", llm, db, max_steps=5)
    system = llm.calls[0][0]["content"]
    assert "at most 5 steps" in system and "- proteins (12000 rows)" in system and "interactions" in system


def test_usage_is_accumulated(db):
    llm = ScriptedLLM([act("list_tables"), act("decline", reason="x")])
    r = run_agent("?", llm, db)
    assert r.input_tokens > 0 and r.output_tokens > 0


# ---------------------------------------------------------------- reply formats seen from real models
def test_parse_python_style_dict():
    out = parse_action("{'thought': 'x', 'action': 'run_sql', 'args': {'sql': \"SELECT 1 WHERE 'a' = 'a'\"}}")
    assert out[0] == "run_sql" and out[1]["sql"] == "SELECT 1 WHERE 'a' = 'a'"


def test_parse_raw_newlines_inside_the_sql_string():
    out = parse_action('{"thought": "x", "action": "run_sql", "args": {"sql": "SELECT a\nFROM proteins\nWHERE b = 1"}}')
    assert out[0] == "run_sql" and out[1]["sql"].count("\n") == 2


def test_parse_stray_trailing_brace():
    assert parse_action('{"thought": "x", "action": "describe_table", "args": {"table": "genes"}}}')[1] == {"table": "genes"}


def test_parse_args_given_as_bare_string():
    assert parse_action('{"thought": "x", "action": "run_sql", "args": "SELECT 1"}')[1] == {"sql": "SELECT 1"}
    assert parse_action('{"action": "decline", "args": "not in the schema"}')[1] == {"reason": "not in the schema"}


def test_parse_args_at_top_level_and_aliases():
    assert parse_action('{"action": "run_sql", "sql": "SELECT 1"}')[1]["sql"] == "SELECT 1"
    assert parse_action('{"action": "run_sql", "args": {"query": "SELECT 2"}}')[1]["sql"] == "SELECT 2"
    assert parse_action('{"action": "answer", "args": {"answer": "42"}}')[1]["text"] == "42"
    assert parse_action('{"action": "search_values", "args": {"table": "genes", "column": "gene_name", "value": "TP"}}')[1]["pattern"] == "TP"


def test_parse_action_name_is_case_insensitive():
    assert parse_action('{"action": "Run_SQL", "args": {"sql": "SELECT 1"}}')[0] == "run_sql"


def test_unknown_action_is_still_rejected():
    assert parse_action('{"action": "drop_everything", "args": {}}') is None


def test_raw_reply_is_recorded_on_every_step(db):
    llm = ScriptedLLM(["not json", act("decline", reason="x")])
    r = run_agent("?", llm, db)
    assert [s.raw for s in r.steps][0] == "not json" and "decline" in r.steps[1].raw


def test_answer_combining_two_queries_is_grounded_against_all_evidence(db):
    llm = ScriptedLLM([
        act("run_sql", sql="SELECT entry FROM proteins WHERE entry_name = 'P53_HUMAN'"),
        act("run_sql", sql="SELECT entry FROM proteins WHERE entry_name = 'EGFR_HUMAN'"),
        act("answer", text="P53 is P04637 and EGFR is P00533.", query="Q2"),
    ])
    r = run_agent("Accessions of P53_HUMAN and EGFR_HUMAN?", llm, db)
    assert r.chosen_query == "Q2" and r.grounding.ok
