"""Build evaluation/RESULTS.md from the scored runs.

    python -m evaluation.score --arm baseline
    python -m evaluation.score --arm annotated
    python -m evaluation.score --arm agent
    python -m evaluation.score --arm baseline_hardened --runs-from baseline
    python -m evaluation.report

Everything in RESULTS.md is regenerated from evaluation/results/*/scores.json; nothing is typed by hand
except the static limitations text at the bottom.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from agent.database import ReadOnlyDB
from evaluation.answers import agent_answer_stats
from evaluation.score import paired_diff

HERE = Path(__file__).parent
ARM_LABEL = {"baseline": "baseline (original prompt, raw DDL)",
             "annotated": "annotated (baseline + schema notes)",
             "agent": "agent (tools + repair)"}
OUTCOME_ORDER = ["correct", "correct_extra_columns", "wrong_values", "wrong_rowcount", "empty_result",
                 "capped_at_200", "error:UndefinedColumn", "error:UndefinedTable", "error:SyntaxError",
                 "error:InvalidTextRepresentation", "error:DatatypeMismatch", "timeout",
                 "blocked_or_no_sql", "declined", "budget_exhausted", "missing"]


def load(results: Path, arm: str) -> dict | None:
    f = results / arm / "scores.json"
    return json.loads(f.read_text()) if f.exists() else None


def pct(x: float) -> str:
    return f"{x:.1%}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default=str(HERE / "results"))
    ap.add_argument("--out", default=str(HERE / "RESULTS.md"))
    args = ap.parse_args()
    results = Path(args.results_dir)

    arms = {a: load(results, a) for a in ("baseline", "annotated", "agent")}
    arms = {a: d for a, d in arms.items() if d}
    hardened = load(results, "baseline_hardened")
    snapshot = json.loads((HERE / "data_snapshot.json").read_text())
    n_q = len(json.loads((HERE / "gold_results.json").read_text()))
    models = sorted({s["model"] for d in arms.values() for s in d["summaries"]})
    summ = {a: {s["model"]: s for s in d["summaries"]} for a, d in arms.items()}

    out = ["# Evaluation results", "",
           f"{n_q} answerable questions plus 5 unanswerable and 9 adversarial ones, executed against a pinned "
           f"snapshot (`data_snapshot.json`, proteins md5 `{snapshot['proteins_md5'][:12]}…`, PostgreSQL "
           f"{snapshot['postgres']}). **EX** = execution accuracy: the executed result equals the gold result "
           "as a multiset of rows (see `compare.py`). Confidence intervals are 95% cluster-bootstrap intervals "
           "that resample paraphrase groups, not single questions.", ""]

    if (HERE / "FINDINGS.md").exists():
        out += [(HERE / "FINDINGS.md").read_text(), ""]

    # ---- headline
    out += ["## Execution accuracy by arm", "",
            "Strict EX is the pre-set primary metric: the executed result must equal the gold result column for column. "
            "Relaxed EX also accepts a result that contains the gold columns plus extra ones (e.g. the accession "
            "shown next to the entry name that was asked for). Both are shown because they diverge for the agent.", "",
            "| model | " + " | ".join(f"{ARM_LABEL[a]}" for a in arms) + " |", "|---|" + "---|" * len(arms)]
    order = sorted(models, key=lambda m: -max(summ[a][m]["ex"] for a in arms if m in summ[a]))
    for m in order:
        cells = []
        for a in arms:
            s_ = summ[a].get(m)
            cells.append(f"**{pct(s_['ex'])}** ({pct(s_['ex_lo'])}–{pct(s_['ex_hi'])}) · relaxed {pct(s_['ex_relaxed'])}" if s_ else "not run")
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    v1 = load(results, "agent_v1")
    if v1:
        for s1 in v1["summaries"]:
            if s1["n_answerable"] >= 100:
                out += ["", f"*Disclosure — agent v1.* The first agent run for `{s1['model']}` scored {pct(s1['ex'])} strict / "
                        f"{pct(s1['ex_relaxed'])} relaxed. Its trace showed the reply parser rejecting valid answers "
                        "(single-quoted dicts, raw newlines inside the SQL string, arguments at the wrong level), so the "
                        "parser was made tolerant and every agent run was redone with v2 (`runs/agent_v1/` keeps the first). "
                        "That fix was made after seeing failures on this benchmark; it changes reply parsing, not prompts or tools."]

    # ---- paired gains
    if "baseline" in arms and len(arms) > 1:
        out += ["", "## What each change buys (same model, same questions, paired)", "",
                "| model | comparison | Δ EX | 95% CI | |", "|---|---|---|---|---|"]
        for m in models:
            base = arms["baseline"]["per_question"].get(m)
            for a in ("annotated", "agent"):
                if a in arms and base and m in arms[a]["per_question"]:
                    d, lo, hi = paired_diff([r for r in arms[a]["per_question"][m] if r["expect"] == "rows"],
                                            [r for r in base if r["expect"] == "rows"])
                    out.append(f"| {m} | {a} − baseline | {d:+.1%} | {lo:+.1%} to {hi:+.1%} | {'●' if lo > 0 or hi < 0 else ''} |")
            if "annotated" in arms and "agent" in arms and m in arms["agent"]["per_question"] and m in arms["annotated"]["per_question"]:
                d, lo, hi = paired_diff([r for r in arms["agent"]["per_question"][m] if r["expect"] == "rows"],
                                        [r for r in arms["annotated"]["per_question"][m] if r["expect"] == "rows"])
                out.append(f"| {m} | agent − annotated | {d:+.1%} | {lo:+.1%} to {hi:+.1%} | {'●' if lo > 0 or hi < 0 else ''} |")
        out += ["", "● = the interval excludes 0. The `annotated − baseline` row isolates better context; "
                "`agent − annotated` isolates tool use and error repair.", ""]

    # ---- per category
    cats = sorted({c for d in arms.values() for s in d["summaries"] for c in s["by_cat"]})
    out += ["## EX by question category", ""]
    for a in arms:
        out += [f"**{ARM_LABEL[a]}**", "", "| model | " + " | ".join(cats) + " |", "|---|" + "---|" * len(cats)]
        for s in sorted(arms[a]["summaries"], key=lambda s: -s["ex"]):
            out.append(f"| {s['model']} | " + " | ".join(f"{s['by_cat'].get(c, 0):.0%}" for c in cats) + " |")
        out.append("")

    # ---- failure taxonomy
    out += ["## Why answerable questions fail", "", "Counts over all models and answerable questions.", "",
            "| outcome | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    tot = {a: Counter() for a in arms}
    for a, d in arms.items():
        for s in d["summaries"]:
            tot[a].update(s["outcomes"])
    seen = [o for o in OUTCOME_ORDER if any(tot[a][o] for a in arms)] + \
           sorted({o for a in arms for o in tot[a]} - set(OUTCOME_ORDER))
    for o in seen:
        out.append(f"| {o} | " + " | ".join(str(tot[a][o]) for a in arms) + " |")

    # ---- agent specifics
    if "agent" in arms:
        out += ["", "## How the agent ends", "", "| model | answered correctly | right data, extra columns | wrong result | declined | step budget exhausted |",
                "|---|---|---|---|---|---|"]
        for s_ in sorted(arms["agent"]["summaries"], key=lambda s_: -s_["ex"]):
            o = s_["outcomes"]
            wrong = sum(v for k, v in o.items() if k in ("wrong_values", "wrong_rowcount", "empty_result", "capped_at_200") or k.startswith("error:"))
            out.append(f"| {s_['model']} | {o.get('correct', 0)} | {o.get('correct_extra_columns', 0)} | {wrong} | "
                       f"{o.get('declined', 0)} | {o.get('budget_exhausted', 0)} |")
        out += ["", "## Answer text quality (agent only)", "",
                "The single-shot arms produce SQL only, so only the agent's answers are checked. Deterministic rules, no LLM judge "
                "(`answers.py`): **grounded** = every number and accession in the answer occurs in some query result the agent obtained "
                "(deliberately strict: a correct but *derived* number, such as 12000 − 11597, is flagged); **value recall** = share of the gold "
                "result's values (up to 10) that appear in the answer; **≤100 words** = the prompt's length limit.", "",
                "| model | answered | grounded | value recall | ≤100 words |", "|---|---|---|---|---|"]
        db = ReadOnlyDB("postgresql://app_readonly@localhost:5433/uniprot")
        qmap = {q["id"]: q for q in map(json.loads, (HERE / "questions.jsonl").read_text().splitlines())}
        goldmap = json.loads((HERE / "gold_results.json").read_text())
        for f in sorted((HERE / "runs" / "agent").glob("*.json")):
            st = agent_answer_stats(json.loads(f.read_text()), qmap, goldmap, db)
            out.append(f"| {st['model']} | {st['answered']} | {pct(st['grounded'])} | {pct(st['recall'])} | {pct(st['within_limit'])} |")
        out.append("")

    # ---- unanswerable / adversarial
    out += ["", "## Unanswerable and adversarial requests", "",
            "| arm | model | fabricated rows (of 5 unanswerable) | unsafe SQL emitted | unsafe SQL **executed** | unbounded result |",
            "|---|---|---|---|---|---|"]
    for a, d in arms.items():
        for s in sorted(d["summaries"], key=lambda s: s["model"]):
            fab = "n/a" if s["fabricated_rate"] is None else f"{round(s['fabricated_rate'] * s['n_unanswerable'])}"
            out.append(f"| {a} | {s['model']} | {fab} | {s['unsafe_emitted']}/{s['n_safe']} | "
                       f"{s['unsafe_executed']}/{s['n_safe']} | {s['unbounded']} |")
    if hardened:
        out += ["", "**Cost of the stricter guard.** The baseline's own SQL, re-scored through the agent's guard and "
                "executor: "]
        for s in sorted(hardened["summaries"], key=lambda s: s["model"]):
            b = summ.get("baseline", {}).get(s["model"])
            if b:
                out.append(f"- {s['model']}: EX {pct(b['ex'])} → {pct(s['ex'])} "
                           f"(legitimate queries newly refused: {round((b['ex'] - s['ex']) * s['n_answerable'])})")
    red = HERE / "results" / "redteam.md"
    if red.exists():
        out += ["", "## Safety layer red-team (no model involved)", "", red.read_text()]

    missing = [m for m in models if m not in summ.get("agent", {})]
    if missing:
        out += ["", f"**Not run for the agent arm:** {', '.join(missing)} (cost: its single-shot arm alone cost "
                f"${summ['baseline'][missing[0]]['cost_usd']:.2f}, and the agent arm makes about 4–5 calls per question with a growing context)."]

    # ---- cost
    out += ["", "## Cost and latency", "", "| arm | model | $ for all questions | mean s/question | mean agent steps |", "|---|---|---|---|---|"]
    for a, d in arms.items():
        for s in sorted(d["summaries"], key=lambda s: s["model"]):
            out.append(f"| {a} | {s['model']} | {s['cost_usd']:.3f} | {s['mean_latency_s']:.1f} | "
                       f"{s['mean_steps']:.1f} |" if a == "agent" else
                       f"| {a} | {s['model']} | {s['cost_usd']:.3f} | {s['mean_latency_s']:.1f} | — |")

    Path(args.out).write_text("\n".join(out) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
