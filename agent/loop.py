"""The SQL agent: a bounded tool-use loop over a read-only database.

At each step the model chooses one action (inspect the schema, look up stored values, run SQL,
answer, decline). Tool results - including SQL errors and guard rejections - are fed back so
it can correct itself. The loop is bounded (max_steps), every step is recorded in a trace, and
the final answer is checked against the rows it claims to be based on.
"""
import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent.database import QueryError, QueryResult, ReadOnlyDB
from agent.grounding import Grounding, check_grounding
from agent.llm import LLM
from agent.prompts import BAD_REPLY, LAST_STEP_NUDGE, NO_QUERY_YET, SYSTEM

ACTIONS = {"list_tables", "describe_table", "search_values", "run_sql", "answer", "decline"}
SHOWN_ROWS = 25  # rows echoed back to the model; the full result is kept for the user


@dataclass
class Step:
    n: int
    thought: str
    action: str
    args: dict
    observation: str
    ok: bool = True
    raw: str = ""  # the model's reply exactly as received (format problems are visible, not inferred)


@dataclass
class AgentResult:
    question: str
    outcome: str  # answered | declined | budget_exhausted
    answer: str | None = None
    sql: str | None = None  # the query the answer is based on; None unless answered
    chosen_query: str | None = None  # its id (Q1, Q2, ...)
    last_sql: str | None = None  # last successful query, kept for diagnostics even when unanswered
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    steps: list[Step] = field(default_factory=list)
    grounding: Grounding | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0


# ---------------------------------------------------------------- parsing
# Models do not all emit clean JSON. Observed in practice: fenced blocks, a stray extra brace, raw newlines
# inside the SQL string, Python-style dicts with single quotes, and arguments given as a bare string or at
# the top level instead of under "args". All of those are accepted; anything else is a wasted step.
_PRIMARY_ARG = {"run_sql": "sql", "answer": "text", "decline": "reason", "describe_table": "table"}
_ARG_ALIASES = {
    "run_sql": {"sql": ("sql", "query", "sql_query", "statement")},
    "answer": {"text": ("text", "answer", "response", "final_answer"), "query": ("query", "from_query", "based_on")},
    "decline": {"reason": ("reason", "text", "message")},
    "describe_table": {"table": ("table", "table_name", "name")},
    "search_values": {"table": ("table", "table_name"), "column": ("column", "column_name"),
                      "pattern": ("pattern", "value", "search", "text")},
}


def _loads(text: str):
    for load in (lambda t: json.loads(t, strict=False), ast.literal_eval):
        try:
            return load(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
    return None


def _balanced_objects(text: str):
    """Yield the first balanced {...} span, once aware of double-quoted strings and once not."""
    start = text.find("{")
    if start == -1:
        return
    for string_aware in (True, False):
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if string_aware and in_str:
                esc = (c == "\\") and not esc
                if c == '"' and not esc:
                    in_str = False
                continue
            if string_aware and c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:i + 1]
                    break


def _normalise_args(action: str, obj: dict) -> dict:
    args = obj.get("args")
    if isinstance(args, str):
        args = {_PRIMARY_ARG.get(action, "text"): args}
    elif not isinstance(args, dict):
        args = {k: v for k, v in obj.items() if k not in ("thought", "action", "args")}
    out = dict(args)
    for canonical, names in _ARG_ALIASES.get(action, {}).items():
        if canonical not in out:
            for name in names:
                if name in args:
                    out[canonical] = args[name]
                    break
    return out


def parse_action(text: str) -> tuple[str, dict, str] | None:
    """(action, args, thought) from a model reply, or None if no action can be recovered."""
    text = re.sub(r"^```(?:json|python)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE)
    for cand in [text, *_balanced_objects(text)]:
        obj = _loads(cand)
        if not isinstance(obj, dict):
            continue
        action = str(obj.get("action", "")).strip().lower()
        if action in ACTIONS:
            return action, _normalise_args(action, obj), str(obj.get("thought", ""))[:400]
    return None


# ---------------------------------------------------------------- observations
def overview(db: ReadOnlyDB) -> str:
    lines = []
    for t in db.catalog.values():
        first = re.split(r"(?<=[.!?])\s", t.comment, maxsplit=1)[0] if t.comment else ""
        lines.append(f"- {t.name} ({t.n_rows} rows): {first}")
    return "\n".join(lines)


def _fmt_cell(v: Any) -> str:
    s = "NULL" if v is None else str(v)
    return s if len(s) <= 120 else s[:119] + "…"


def format_result(qid: str, r: QueryResult) -> str:
    head = f"{qid}: {len(r.rows)}{'+' if r.truncated else ''} row(s); columns: {', '.join(r.columns)}"
    if r.truncated:
        head += f"  [capped at {len(r.rows)} rows - add LIMIT/aggregation if you need the full picture]"
    body = "\n".join(" | ".join(_fmt_cell(c) for c in row) for row in r.rows[:SHOWN_ROWS])
    more = f"\n… {len(r.rows) - SHOWN_ROWS} more row(s) not shown" if len(r.rows) > SHOWN_ROWS else ""
    return head + ("\n" + body if body else "\n(no rows)") + more


def format_describe(d: dict) -> str:
    out = [f"Table {d['table']} ({d['n_rows']} rows): {d['comment']}", "Columns:"]
    for c in d["columns"]:
        note = f" -- {c['comment']}" if c["comment"] else ""
        flag = " [ALWAYS NULL]" if c["non_null"] == 0 and d["n_rows"] else ""
        out.append(f"  {c['name']} {c['type']}{'' if c['nullable'] else ' NOT NULL'} "
                   f"[{c['non_null']} non-null]{flag}{note}")
    if d["foreign_keys"]:
        out.append("Foreign keys: " + "; ".join(d["foreign_keys"]))
    out.append("Sample rows (" + ", ".join(c["name"] for c in d["columns"]) + "):")
    out += ["  " + " | ".join(_fmt_cell(v) for v in r) for r in d["sample_rows"]] or ["  (table is empty)"]
    return "\n".join(out)


# ---------------------------------------------------------------- the loop
def run_agent(question: str, llm: LLM, db: ReadOnlyDB, *, max_steps: int = 8) -> AgentResult:
    res = AgentResult(question=question, outcome="budget_exhausted")
    messages = [{"role": "system", "content": SYSTEM.format(max_steps=max_steps, overview=overview(db))},
                {"role": "user", "content": question}]
    results: dict[str, QueryResult] = {}  # successful run_sql results by id (Q1, Q2, ...)

    for n in range(1, max_steps + 1):
        reply = llm.complete(messages)
        res.input_tokens += reply.input_tokens
        res.output_tokens += reply.output_tokens
        res.cost_usd += reply.cost_usd
        res.latency_s += reply.latency_s
        messages.append({"role": "assistant", "content": reply.text})

        parsed = parse_action(reply.text)
        if parsed is None:
            obs, ok, action, args, thought = BAD_REPLY, False, "invalid", {}, ""
        else:
            action, args, thought = parsed
            obs, ok, done = _execute(action, args, db, results, question, res)
            if done:
                res.steps.append(Step(n, thought, action, args, obs, ok, reply.text))
                break
        res.steps.append(Step(n, thought, action, args, obs, ok, reply.text))
        suffix = f"\n\n{LAST_STEP_NUDGE}" if n == max_steps - 1 else ""
        messages.append({"role": "user", "content": f"OBSERVATION:\n{obs}{suffix}"})

    _finalize(res, results)
    return res


def _execute(action: str, args: dict, db: ReadOnlyDB, results: dict[str, QueryResult],
             question: str, res: AgentResult) -> tuple[str, bool, bool]:
    """Run one action. Returns (observation, ok, finished)."""
    try:
        if action == "list_tables":
            return overview(db), True, False
        if action == "describe_table":
            return format_describe(db.describe(str(args.get("table", "")))), True, False
        if action == "search_values":
            t, c, p = (str(args.get(k, "")) for k in ("table", "column", "pattern"))
            hits = db.search_values(t, c, p)
            if not hits:
                return f"No values in {t}.{c} contain {p!r}.", True, False
            return (f"Stored values in {t}.{c} containing {p!r} (value: count):\n"
                    + "\n".join(f"  {v!r}: {n}" for v, n in hits)), True, False
        if action == "run_sql":
            r = db.run(str(args.get("sql", "")))
            qid = f"Q{len(results) + 1}"
            results[qid] = r
            return format_result(qid, r), True, False
        if action == "decline":
            res.outcome, res.answer = "declined", str(args.get("reason", "")).strip() or "Declined."
            return res.answer, True, True
        if action == "answer":
            if not results:
                return NO_QUERY_YET, False, False
            qid = str(args.get("query") or "").upper() or list(results)[-1]
            if qid not in results:
                return f"Unknown query {qid!r}; available: {', '.join(results)}.", False, False
            res.outcome, res.answer = "answered", str(args.get("text", "")).strip()
            res.chosen_query = qid
            return res.answer, True, True
    except QueryError as e:
        return f"ERROR ({e.kind}): {e.message}", False, False
    return f"unsupported action {action!r}", False, False


def _finalize(res: AgentResult, results: dict[str, QueryResult]) -> None:
    if results:
        res.last_sql = list(results.values())[-1].sql
    if res.outcome == "answered":
        r = results[res.chosen_query]
        res.sql, res.columns, res.rows, res.truncated = r.sql, r.columns, r.rows, r.truncated
        # the answer may combine several queries (e.g. one per gene), so check against all the evidence
        evidence = [row for r2 in results.values() for row in r2.rows]
        res.grounding = check_grounding(res.answer or "", res.question, evidence, res.truncated)
