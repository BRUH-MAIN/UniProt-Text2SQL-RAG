"""Draw the agent-arm bar charts used in the README.

    python -m evaluation.make_figures            # uses the cached answer stats if present
    python -m evaluation.make_figures --refresh  # recompute grounding (needs the local database)

Inputs : evaluation/results/agent/scores.json   (python -m evaluation.score --arm agent)
         evaluation/runs/agent/*.json            (only for --refresh: grounding is recomputed from the traces)
Outputs: docs/figures/agent_accuracy.png, agent_outcomes.png, agent_behaviour.png

Every number drawn comes from those files; nothing is typed in. Requires matplotlib (requirements-eval.txt).
"""
import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).parent
ROOT = HERE.parent
OUT = ROOT / "docs" / "figures"
STATS_CACHE = HERE / "results" / "agent" / "answer_stats.json"

# Chart ink and surface. The surface is drawn into the image so it reads the same on GitHub's light and dark themes.
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
BLUE, BLUE_LIGHT, ORANGE, GREY_LIGHT, GREY_DARK = "#2a78d6", "#86b6ef", "#eb6834", "#c3c2b7", "#6f6e69"
DPI = 200

plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK2,
                     "xtick.color": MUTED, "ytick.color": INK2, "axes.edgecolor": AXIS})


def short(model: str) -> str:
    return re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model.split("/")[-1])


def _frame(fig, title: str, subtitle: str, footnote: str) -> None:
    fig.patch.set_facecolor(SURFACE)
    fig.text(0.03, 0.95, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.03, 0.895, subtitle, fontsize=9, color=INK2, va="top")
    fig.text(0.03, 0.025, footnote, fontsize=8, color=MUTED, va="bottom")


def _style(ax, xmax: float, fmt) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_xlim(0, xmax)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", length=0, labelsize=8)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_formatter(fmt)


def accuracy(summaries: list[dict], n_q: int) -> None:
    rows = sorted(summaries, key=lambda s: s["ex"])  # barh draws bottom-up, so best ends on top
    fig, ax = plt.subplots(figsize=(9, 4.3))
    fig.subplots_adjust(left=0.2, right=0.96, top=0.8, bottom=0.2)
    _style(ax, 112, lambda v, _: f"{v:.0f}%" if v <= 100 else "")
    h = 0.3
    for i, s in enumerate(rows):
        strict, lo, hi, relaxed = s["ex"] * 100, s["ex_lo"] * 100, s["ex_hi"] * 100, s["ex_relaxed"] * 100
        ax.barh(i + h / 2 + 0.02, strict, h, color=BLUE, zorder=3)
        ax.barh(i - h / 2 - 0.02, relaxed, h, color=ORANGE, zorder=3)
        ax.plot([lo, hi], [i + h / 2 + 0.02] * 2, color=INK2, linewidth=1, zorder=4)
        for x in (lo, hi):
            ax.plot([x, x], [i + h / 2 - 0.05, i + h / 2 + 0.09], color=INK2, linewidth=1, zorder=4)
        ax.text(max(hi, strict) + 1.2, i + h / 2 + 0.02, f"{strict:.0f}%", va="center", fontsize=9, color=INK, fontweight="bold")
        ax.text(relaxed + 1.2, i - h / 2 - 0.02, f"{relaxed:.0f}%", va="center", fontsize=9, color=INK2)
    ax.set_yticks(range(len(rows)), [short(s["model"]) for s in rows], fontsize=9.5)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)]
    fig.legend(handles, ["Strict: result matches the gold result column for column",
                         "Relaxed: also accepts extra columns beside the right data"],
               loc="lower left", bbox_to_anchor=(0.2, 0.065), frameon=False, fontsize=8.5, ncol=1, labelcolor=INK2)
    _frame(fig, "SQL agent: execution accuracy by model",
           f"{n_q} answerable questions run against the real database; one run per model",
           "Whisker on the strict bar: 95% bootstrap interval, resampling paraphrase groups.")
    fig.savefig(OUT / "agent_accuracy.png", dpi=DPI, facecolor=SURFACE)
    plt.close(fig)


def outcomes(summaries: list[dict], n_q: int) -> None:
    rows = sorted(summaries, key=lambda s: s["ex"])
    parts = [("Correct", BLUE, "#ffffff"), ("Right data, extra columns", BLUE_LIGHT, INK),
             ("Wrong result", ORANGE, "#ffffff"), ("Declined", GREY_LIGHT, INK), ("Step budget exhausted", GREY_DARK, "#ffffff")]

    def split(o: dict) -> list[int]:
        wrong = sum(v for k, v in o.items() if k in ("wrong_values", "wrong_rowcount", "empty_result", "capped_at_200")
                    or k.startswith("error:") or k == "timeout")
        return [o.get("correct", 0), o.get("correct_extra_columns", 0), wrong, o.get("declined", 0), o.get("budget_exhausted", 0)]

    fig, ax = plt.subplots(figsize=(9, 4.3))
    fig.subplots_adjust(left=0.2, right=0.96, top=0.8, bottom=0.22)
    _style(ax, n_q, lambda v, _: f"{v:.0f}")
    for i, s in enumerate(rows):
        counts = split(s["outcomes"])
        assert sum(counts) == s["n_answerable"], (s["model"], counts, s["outcomes"])
        left = 0
        for (name, colour, text), c in zip(parts, counts):
            if c:
                ax.barh(i, c, 0.5, left=left, color=colour, edgecolor=SURFACE, linewidth=1.5, zorder=3)
                if c >= 7:
                    ax.text(left + c / 2, i, str(c), ha="center", va="center", fontsize=9, color=text, fontweight="bold", zorder=4)
            left += c
    ax.set_yticks(range(len(rows)), [short(s["model"]) for s in rows], fontsize=9.5)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel("questions", fontsize=8.5)
    fig.legend([plt.Rectangle((0, 0), 1, 1, color=c) for _, c, _ in parts], [n for n, _, _ in parts],
               loc="lower center", bbox_to_anchor=(0.58, 0.065), frameon=False, fontsize=8.5, ncol=5, columnspacing=1.2,
               handlelength=1.2, labelcolor=INK2)
    _frame(fig, "How each agent run ended",
           f"Outcome of every one of the {n_q} answerable questions, by model",
           "Segments under 7 questions are not labelled; the counts are in evaluation/RESULTS.md.")
    fig.savefig(OUT / "agent_outcomes.png", dpi=DPI, facecolor=SURFACE)
    plt.close(fig)


def behaviour(summaries: list[dict], stats: dict[str, dict]) -> None:
    rows = sorted(summaries, key=lambda s: s["ex"])
    fig, axes = plt.subplots(1, 3, figsize=(9, 3.9), sharey=True)
    fig.subplots_adjust(left=0.2, right=0.97, top=0.78, bottom=0.2, wspace=0.2)
    panels = [("Answers grounded in query results", [stats[s["model"]]["grounded"] * 100 for s in rows], 118,
               lambda v, _: f"{v:.0f}%" if v <= 100 else "", lambda v: f"{v:.0f}%"),
              ("Cost of the full run (USD)", [s["cost_usd"] for s in rows], max(s["cost_usd"] for s in rows) * 1.35,
               lambda v, _: f"${v:.2f}", lambda v: f"${v:.2f}"),
              ("Seconds per question", [s["mean_latency_s"] for s in rows], max(s["mean_latency_s"] for s in rows) * 1.28,
               lambda v, _: f"{v:.0f}", lambda v: f"{v:.0f}s")]
    for ax, (title, values, xmax, tick_fmt, label_fmt) in zip(axes, panels):
        _style(ax, xmax, tick_fmt)
        ax.barh(range(len(rows)), values, 0.5, color=BLUE, zorder=3)
        for i, v in enumerate(values):
            ax.text(v + xmax * 0.015, i, label_fmt(v), va="center", fontsize=8.5, color=INK2)
        ax.set_title(title, fontsize=9, color=INK, loc="left", pad=8)
        ax.tick_params(axis="x", labelsize=7.5)
        ax.set_ylim(-0.6, len(rows) - 0.4)
    axes[0].set_yticks(range(len(rows)), [short(s["model"]) for s in rows], fontsize=9.5)
    n_ans = {s["model"]: stats[s["model"]]["answered"] for s in rows}
    weak = [short(m) for m, n in n_ans.items() if n < 50]
    foot = ("Grounded = every number and accession in the answer occurs in a query result the agent obtained "
            "(strict: correct derived numbers are flagged).")
    if weak:
        foot += f"\n{', '.join(weak)} produced an answer for only {min(n_ans.values())} of {rows[0]['n_answerable']} questions."
    _frame(fig, "What the agent costs and how far its answers can be trusted",
           "Each panel has its own scale; the cost panel covers all 116 benchmark items",
           foot)
    fig.savefig(OUT / "agent_behaviour.png", dpi=DPI, facecolor=SURFACE)
    plt.close(fig)


def answer_stats(refresh: bool) -> dict[str, dict]:
    if STATS_CACHE.exists() and not refresh:
        return json.loads(STATS_CACHE.read_text())
    from agent.database import ReadOnlyDB
    from evaluation.answers import agent_answer_stats

    db = ReadOnlyDB("postgresql://app_readonly@localhost:5433/uniprot")
    questions = {q["id"]: q for q in map(json.loads, (HERE / "questions.jsonl").read_text().splitlines())}
    gold = json.loads((HERE / "gold_results.json").read_text())
    stats = {}
    for f in sorted((HERE / "runs" / "agent").glob("*.json")):
        st = agent_answer_stats(json.loads(f.read_text()), questions, gold, db)
        stats[st["model"]] = {k: st[k] for k in ("answered", "grounded", "recall", "within_limit")}
    STATS_CACHE.write_text(json.dumps(stats, indent=2) + "\n")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="recompute answer-quality stats from the run traces (needs the database)")
    args = ap.parse_args()
    scores = json.loads((HERE / "results" / "agent" / "scores.json").read_text())
    summaries = scores["summaries"]
    n_q = {s["n_answerable"] for s in summaries}
    assert len(n_q) == 1, f"models scored on different question counts: {n_q}"
    OUT.mkdir(parents=True, exist_ok=True)
    stats = answer_stats(args.refresh)
    accuracy(summaries, n_q.pop())
    outcomes(summaries, summaries[0]["n_answerable"])
    behaviour(summaries, stats)
    print(f"wrote {OUT}/agent_accuracy.png, agent_outcomes.png, agent_behaviour.png")


if __name__ == "__main__":
    main()
