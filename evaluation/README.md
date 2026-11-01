# Evaluation

Measures three versions of the system on the same 116-item benchmark and answers one question:
**does an agent loop actually beat a single prompt, and by how much of that is just better context?**

| arm | what it is |
|---|---|
| `baseline` | the original system: its prompt, the raw DDL, one model call, its guard and executor |
| `annotated` | `baseline` plus the column notes from `db/annotations.sql` appended to the prompt. A control: any gain here is "better context", not "agent" |
| `agent` | `agent/`: schema and value-lookup tools, read-only SQL, error repair, hardened guard and executor |

Models are called through the Kaggle Benchmarks model proxy (free quota, OpenAI-compatible), one adapter
for every arm, `reasoning` pinned to `low`, real metered cost recorded per call.

## Files

| file | purpose |
|---|---|
| `questions_src.py` | the benchmark: questions and hand-written gold SQL, with the trap each one tests |
| `build_questions.py` | executes every gold query, rejects bad items (error, >200 rows, empty, ties at a LIMIT boundary), writes `questions.jsonl`, `gold_results.json`, `data_snapshot.json` |
| `compare.py` | result-set comparison (column order/aliases ignored; ranking order scored only when asked, ties tolerated) |
| `safety.py` | independent unsafe-SQL classifier (PostgreSQL parser), so the evaluation does not trust the guard it is testing |
| `redteam.py`, `redteam_report.py` | 21 hostile statements through the legacy and the hardened stack |
| `run_arms.py` | run one arm for one model; resumable; spend ledger enforces a daily budget |
| `score.py` | execute and score predictions: EX, relaxed EX, failure taxonomy, bootstrap CIs, paired differences |
| `report.py` | regenerate `RESULTS.md` from the scored runs |
| `make_figures.py` | draw the agent-arm bar charts in `docs/figures/` (used by the README) from `results/agent/scores.json` |
| `kaggle/make_task.py` | fallback: generate a self-contained Kaggle Benchmarks task for the single-shot arms |

## Reproduce

```bash
# 1. database (PostgreSQL 16+, a SELECT-only role app_readonly) - see docs/SETUP.md
python -m db.init_db && python -m ingest.fetch_uniprot && python -m ingest.parse_and_load --truncate

# 2. the benchmark must match the pinned snapshot
python -m evaluation.build_questions      # fails if a gold query breaks; compare data_snapshot.json

# 3. harness self-tests (an oracle must score 100%, a constant guess 0%)
pytest tests

# 4. Kaggle Benchmarks credentials, once per session (the proxy key lasts about an hour)
kaggle auth login && kaggle benchmarks init -y      # writes MODEL_PROXY_URL / MODEL_PROXY_API_KEY to .env
set -a; . ./.env; set +a

# 5. run, score, report
for arm in baseline annotated agent; do
  python -m evaluation.run_arms --arm $arm --model gemini-3.5-flash-lite
  python -m evaluation.score --arm $arm
done
python -m evaluation.score --arm baseline_hardened --runs-from baseline
python -m evaluation.redteam --executor legacy   --out evaluation/results/redteam_legacy.json
python -m evaluation.redteam --executor hardened --out evaluation/results/redteam_hardened.json
python -m evaluation.redteam_report
python -m evaluation.report
```

Kaggle's free quota is capped (about $10/day). `run_arms.py --daily-budget` stops cleanly and resumes
from `runs/<arm>/<model>.partial.jsonl` when re-run.

## Metrics

* **EX (execution accuracy)** — the primary metric: the executed result equals the gold result.
  *Strict* requires the same columns; *relaxed* also accepts extra columns (e.g. the name next to a requested accession).
* **Failure taxonomy** — every miss is labelled: SQL error by type, wrong values, wrong row count, empty result,
  capped at 200 rows, refused by the guard, declined, step budget exhausted.
* **Fabrication** — on 5 questions the schema cannot answer, any returned row counts as a fabricated answer.
* **Unsafe SQL** — on 9 hostile requests, whether unsafe SQL was *emitted* and whether it was *executed*.
* **Confidence intervals** — bootstrap over paraphrase groups, so near-duplicate questions are not counted as independent.

## What this evaluation can and cannot say

* The gold SQL was written by one author (assisted by an LLM) against one data snapshot, and every item was executed and
  inspected, but it has not been independently reviewed. Gold errors would depress every arm equally.
* 102 answerable questions: differences under roughly 8 percentage points between two models are within noise.
  The paired intervals in `RESULTS.md` say which comparisons are resolved.
* One prompt per arm, one reasoning level, one run per model. No prompt-sensitivity or seed-variance analysis.
* The benchmark data is a single-species, 12,000-protein subset; results do not transfer to other schemas.
* The questions were written by the author of the system, not collected from users.
* The agent arm is limited to 8 steps; the baseline gets one call. That asymmetry is the thing being measured, so
  cost and latency are reported next to accuracy.
