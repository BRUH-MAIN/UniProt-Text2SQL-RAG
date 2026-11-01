"""Deterministic quality checks on the agent's final answer text.

The single-shot arms produce SQL only, so this applies to the agent arm (whose answer is part of its output).
No LLM judge: each check is a rule that can be re-run and argued about.

  grounded       every number/accession in the answer occurs in the rows it cites (agent.grounding)
  value recall   share of the gold result's values (up to 10) that appear in the answer text
  within limit   the answer is at most 100 words, as the prompt requires
  empty honesty  when the gold result is empty, the answer says nothing is recorded
"""
import re

from evaluation.compare import norm_value

_NONE = re.compile(r"\b(no|none|not|nothing|zero|n/?a|cannot|can't|isn't|aren't|doesn't|does not)\b", re.I)


def _flat_values(rows: list[list], cap: int = 10) -> list[str]:
    seen, out = set(), []
    for row in rows:
        for v in row:
            nv = norm_value(v)
            if nv is None:
                continue
            s = f"{nv:g}" if isinstance(nv, float) else str(nv)
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out[:cap]


def value_recall(answer: str, gold_rows: list[list]) -> float | None:
    """Fraction of the gold values present in the answer; None when the gold result is empty."""
    vals = _flat_values(gold_rows)
    if not vals:
        return None
    text = (answer or "").replace(",", "").lower()
    return sum(v.lower() in text for v in vals) / len(vals)


def answer_metrics(answer: str | None, gold_rows: list[list]) -> dict:
    answer = answer or ""
    return {
        "recall": value_recall(answer, gold_rows),
        "within_limit": len(answer.split()) <= 100,
        "empty_ok": (bool(_NONE.search(answer)) if not gold_rows else None),
    }


def agent_answer_stats(run: dict, questions: dict, gold: dict, db) -> dict:
    """Answer-quality numbers for one agent run, recomputed from the stored trace.

    Grounding is recomputed (not read from the run file) so improvements to the checker apply to old runs:
    every query the agent ran successfully is re-executed and the answer is checked against all of them.
    """
    from agent.database import QueryError
    from agent.grounding import check_grounding

    answered = [p for p in run["predictions"] if p.get("outcome") == "answered" and questions[p["id"]]["expect"] == "rows"]
    grounded, recalls, within, flagged = 0, [], 0, []
    for p in answered:
        evidence, truncated = [], False
        for step in p.get("trace", []):
            if step["action"] == "run_sql" and step["ok"]:
                try:
                    r = db.run(step["args"].get("sql", ""))
                except QueryError:
                    continue
                evidence += r.rows
                truncated = truncated or r.truncated
        g = check_grounding(p["answer"], questions[p["id"]]["q"], evidence, truncated)
        grounded += g.ok
        if not g.ok:
            flagged.append((p["id"], g.describe()))
        m = answer_metrics(p["answer"], gold[p["id"]]["rows"])
        within += m["within_limit"]
        if m["recall"] is not None:
            recalls.append(m["recall"])
    n = max(1, len(answered))
    return {"model": run["model"], "answered": len(answered), "grounded": grounded / n,
            "recall": sum(recalls) / max(1, len(recalls)), "within_limit": within / n, "flagged": flagged}
