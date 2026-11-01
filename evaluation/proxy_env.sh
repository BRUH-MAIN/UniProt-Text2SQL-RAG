#!/usr/bin/env bash
# Usage: evaluation/proxy_env.sh <command...>
# Creates/refreshes evaluation/.env (Kaggle model-proxy credentials, valid ~1 hour) from the Kaggle API
# credentials in $KAGGLE_JSON (default ~/.kaggle/kaggle.json) and runs the command with them exported.
# The key is never printed. run_arms.py also refreshes it on its own if it expires mid-run.
set -euo pipefail
cd "$(dirname "$0")"
json="${KAGGLE_JSON:-$HOME/.kaggle/kaggle.json}"
export PYTHONUTF8=1
export KAGGLE_USERNAME="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['username'])" "$json")"
export KAGGLE_KEY="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['key'])" "$json")"
kaggle benchmarks init -y >/dev/null
set -a; . ./.env; set +a
cd ..
exec "$@"
