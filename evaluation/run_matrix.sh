#!/usr/bin/env bash
# Run one arm for several models, one after another (so the proxy key is refreshed by a single process).
#   KAGGLE_JSON=~/.kaggle/kaggle.json evaluation/proxy_env.sh evaluation/run_matrix.sh <arm> [model ...]
# Env: WORKERS (default 4), DAILY_BUDGET in USD across all runs today (default 8).
# Stops cleanly at the budget; re-run the same command to resume where it left off.
set -uo pipefail
arm="$1"; shift
models=("$@")
if [ ${#models[@]} -eq 0 ]; then
  models=(gemini-3.5-flash-lite gemini-3.6-flash openai/gpt-5.4-nano-2026-03-17 openai/gpt-oss-120b
          ibm/granite-4.0-h-small anthropic/claude-sonnet-5@default)
fi
for m in "${models[@]}"; do
  python -m evaluation.run_arms --arm "$arm" --model "$m" --workers "${WORKERS:-4}" --daily-budget "${DAILY_BUDGET:-8}" \
    || echo "!! $arm/$m did not complete (exit $?)"
done
