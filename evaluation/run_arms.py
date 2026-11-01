"""Run one arm of the experiment for one model and save its predictions.

    python -m evaluation.run_arms --arm baseline  --model gemini-3.5-flash-lite
    python -m evaluation.run_arms --arm annotated --model gemini-3.5-flash-lite
    python -m evaluation.run_arms --arm agent     --model gemini-3.5-flash-lite

Arms
  baseline   the shipped system: original prompt + raw DDL, one call, no tools
  annotated  baseline + the schema annotations (db/annotations.sql) in the prompt - a control
             that isolates "better context" from "agentic tool use"
  agent      the SQL agent (agent/loop.py): schema/value tools, read-only SQL, error repair

All arms call the model through the same adapter (Kaggle model proxy, reasoning pinned),
so cost is metered identically. Predictions are written incrementally and the run resumes
where it stopped; spend is recorded in a ledger and the run stops at the daily budget.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from agent.database import ReadOnlyDB
from agent.llm import GeminiLLM, ProxyLLM
from agent.loop import run_agent
from db.connection import get_schema
from baseline.sql_chain import PROMPT_TEMPLATE

HERE = Path(__file__).parent
RUNS = HERE / "runs"
LEDGER = RUNS / "spend.jsonl"
ANNOTATIONS = Path(__file__).parent.parent / "db" / "annotations.sql"
_lock = threading.Lock()


def single_shot_prompt(arm: str, question: str) -> str:
    schema = get_schema()
    if arm == "annotated":
        schema += "\n-- Semantics notes (what the columns actually contain)\n" + ANNOTATIONS.read_text(encoding="utf-8")
    return PROMPT_TEMPLATE.format(schema=schema, question=question)


def spent_today() -> float:
    if not LEDGER.exists():
        return 0.0
    today = date.today().isoformat()
    return sum(json.loads(line)["usd"] for line in LEDGER.read_text().splitlines()
               if line and json.loads(line)["day"] == today)


def record_spend(arm: str, model: str, usd: float) -> None:
    with _lock:
        with open(LEDGER, "a") as f:
            f.write(json.dumps({"day": date.today().isoformat(), "arm": arm, "model": model, "usd": round(usd, 6)}) + "\n")


def predict(arm: str, q: dict, llm, db: ReadOnlyDB, max_steps: int) -> dict:
    if arm in ("baseline", "annotated"):
        r = llm.complete([{"role": "user", "content": single_shot_prompt(arm, q["q"])}])
        return {"id": q["id"], "raw_output": r.text, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                "input_cost_nanodollars": int(r.cost_usd * 1e9), "output_cost_nanodollars": 0,
                "latency_ms": r.latency_s * 1000}
    res = run_agent(q["q"], llm, db, max_steps=max_steps)
    return {
        "id": q["id"], "outcome": res.outcome, "final_sql": res.sql, "answer": res.answer, "last_sql": res.last_sql,
        "attempted_sql": [s.args.get("sql") for s in res.steps if s.action == "run_sql" and s.args.get("sql")],
        "steps": len(res.steps), "n_errors": sum(1 for s in res.steps if not s.ok),
        "trace": [{"n": s.n, "action": s.action, "args": s.args, "ok": s.ok, "thought": s.thought,
                   "obs": s.observation[:600], "raw": s.raw[:800]} for s in res.steps],
        "grounding_ok": None if res.grounding is None else res.grounding.ok,
        "ungrounded": None if res.grounding is None else res.grounding.describe(),
        "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
        "input_cost_nanodollars": int(res.cost_usd * 1e9), "output_cost_nanodollars": 0,
        "latency_ms": res.latency_s * 1000,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["baseline", "annotated", "agent"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--provider", default="proxy", choices=["proxy", "gemini"])
    ap.add_argument("--reasoning", default="low")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", default=None, help="comma-separated question ids")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--daily-budget", type=float, default=6.0, help="stop when today's spend (all runs) exceeds this, USD")
    args = ap.parse_args()

    questions = [json.loads(line) for line in (HERE / "questions.jsonl").read_text().splitlines()]
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    slug = re.sub(r"[^A-Za-z0-9._-]", "_", args.model)
    out_dir = RUNS / args.arm
    out_dir.mkdir(parents=True, exist_ok=True)
    partial, final = out_dir / f"{slug}.partial.jsonl", out_dir / f"{slug}.json"
    done = {}
    if partial.exists():
        done = {p["id"]: p for p in map(json.loads, filter(None, partial.read_text().splitlines()))
                if not p.get("error")}  # errored predictions are retried, never frozen as "done"
    todo = [q for q in questions if q["id"] not in done]
    print(f"{args.arm}/{args.model}: {len(done)} done, {len(todo)} to run (spent today ${spent_today():.2f})")

    llm = GeminiLLM(args.model) if args.provider == "gemini" else ProxyLLM(args.model, reasoning=args.reasoning, env_file=str(HERE / ".env"))
    db = ReadOnlyDB(os.environ.get("EVAL_DATABASE_URL", "postgresql://app_readonly@localhost:5433/uniprot"))
    db.catalog  # load once, before threads

    stop = threading.Event()
    run_cost = [0.0]

    def work(q: dict) -> None:
        if stop.is_set():
            return
        if spent_today() >= args.daily_budget:
            print(f"daily budget ${args.daily_budget:.2f} reached - stopping; re-run to resume")
            stop.set()
            return
        try:
            pred = predict(args.arm, q, llm, db, args.max_steps)
        except Exception as e:  # noqa: BLE001 - a failed call is a scored failure, never silently dropped
            pred = {"id": q["id"], "error": f"{type(e).__name__}: {str(e)[:300]}"}
        usd = (pred.get("input_cost_nanodollars", 0) + pred.get("output_cost_nanodollars", 0)) / 1e9
        record_spend(args.arm, args.model, usd)
        with _lock:
            run_cost[0] += usd
            with open(partial, "a") as f:
                f.write(json.dumps(pred, ensure_ascii=False) + "\n")
            done[q["id"]] = pred
            n = len(done)
        flag = " ERROR " + pred["error"][:80] if pred.get("error") else ""
        print(f"[{n}/{len(questions)}] {q['id']} ${usd:.4f}{flag}", flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))

    complete = all(q["id"] in done for q in questions)
    errors = sum(1 for p in done.values() if p.get("error"))
    if complete:
        final.write_text(json.dumps({
            "arm": args.arm, "model": args.model, "provider": args.provider, "reasoning": args.reasoning,
            "max_steps": args.max_steps if args.arm == "agent" else None,
            "n_questions": len(questions), "n_errors": errors, "finished": date.today().isoformat(),
            "predictions": [done[q["id"]] for q in questions]}, ensure_ascii=False, indent=1))
        print(f"wrote {final} ({errors} errored) in {time.time() - t0:.0f}s, run cost ${run_cost[0]:.3f}")
    else:
        print(f"incomplete ({len(done)}/{len(questions)}); re-run the same command to resume")
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
