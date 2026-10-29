#!/bin/sh
# Runs load-test flows against the target named by BASE_URL and DATABASE_URL.
#
#   tests/load/run.sh all        smoke first, then every other flow, one at a time
#   tests/load/run.sh <flow>     a single flow from tests/load/flows/
#
# Seeds the load-test data, removes what an earlier run left, runs the flows and
# removes what they wrote, even when one fails. Results go to tests/load/results/.
set -eu

cd "$(dirname "$0")/../.."

FLOWS_DIR=tests/load/flows
RESULTS_DIR=tests/load/results

log() {
  echo "load-test: $*"
}

require() {
  for name in "$@"; do
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
      log "$name must be set (see tests/load/.env.example)" >&2
      exit 2
    fi
  done
}

available_flows() {
  for file in "$FLOWS_DIR"/*.js; do
    [ -e "$file" ] && basename "$file" .js
  done
}

selected_flows() {
  if [ "$1" != "all" ]; then
    if [ ! -f "$FLOWS_DIR/$1.js" ]; then
      log "unknown flow '$1'; available: $(available_flows | tr '\n' ' ')" >&2
      exit 2
    fi
    echo "$1"
    return
  fi
  # Smoke goes first, so a broken target stops the run before the heavy flows.
  [ -f "$FLOWS_DIR/smoke.js" ] && echo smoke
  available_flows | grep -vx smoke || true
}

wait_until_ready() {
  python - "$BASE_URL/ready" <<'EOF'
import sys
import time
import urllib.request

url = sys.argv[1]
for _ in range(30):
    try:
        urllib.request.urlopen(url, timeout=5)
        sys.exit(0)
    except Exception:
        time.sleep(2)
sys.exit(f"{url} did not answer")
EOF
}

write_run_metadata() {
  python - "$RESULTS_DIR/run.json" "$1" "$2" <<'EOF'
import json
import os
import sys
from datetime import datetime, timezone

path, flows, failed = sys.argv[1:]
with open(path, "w") as file:
    json.dump(
        {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "base_url": os.environ["BASE_URL"],
            "target_revision": os.environ.get("TARGET_REVISION") or None,
            "flows": flows.split(),
            "failed": failed.split(),
        },
        file,
        indent=2,
    )
EOF
}

collect_summaries() {
  : >"$RESULTS_DIR/summary.md"
  for flow in $1; do
    if [ -f "$RESULTS_DIR/$flow.md" ]; then
      cat "$RESULTS_DIR/$flow.md" >>"$RESULTS_DIR/summary.md"
      echo >>"$RESULTS_DIR/summary.md"
    fi
  done
}

main() {
  require BASE_URL DATABASE_URL LOAD_TEST_PASSWORD
  flows=$(selected_flows "${1:-all}")
  if [ -z "$flows" ]; then
    log "no flows found in $FLOWS_DIR" >&2
    exit 2
  fi

  mkdir -p "$RESULTS_DIR"
  rm -f "$RESULTS_DIR"/*.json "$RESULTS_DIR"/*.md

  log "waiting for $BASE_URL/ready"
  wait_until_ready
  log "seeding the load-test data"
  python -m tests.load.data.seed
  log "removing what an earlier run left"
  python -m tests.load.data.cleanup
  trap 'log "removing what this run wrote"; python -m tests.load.data.cleanup' EXIT

  failed=""
  for flow in $flows; do
    log "running $flow"
    if ! k6 run --quiet "$FLOWS_DIR/$flow.js"; then
      failed="$failed $flow"
      if [ "$flow" = "smoke" ]; then
        log "smoke failed; skipping the other flows" >&2
        break
      fi
    fi
  done

  write_run_metadata "$flows" "$failed"
  collect_summaries "$flows"

  if [ -n "$failed" ]; then
    log "failed:$failed" >&2
    exit 1
  fi
  log "done; results in $RESULTS_DIR"
}

main "$@"
