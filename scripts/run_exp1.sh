#!/usr/bin/env bash
# run_exp1.sh — Run Experiment 1: Temporal Decay for Clinical Relevance
#
# Prerequisites:
#   1. Neo4j running with NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD set
#   2. SpacetimeDB running on the VM with STDB_BINDINGS_MODULE set
#   3. Data ingested WITH temporal writes enabled:
#        python scripts/ingest_synthea.py \
#          --data-dir "$SYNTHEA_DATA_DIR" \
#          --enable-temporal \
#          [--max-patients 1000]
#   4. npx / tsx available on PATH
#
# Quick smoke test (20 tasks):
#   bash scripts/run_exp1.sh --n-tasks 20
#
# Full run (200 tasks, 4 decay variants):
#   bash scripts/run_exp1.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env so STDB_URI, STDB_TOKEN, STDB_BINDINGS_MODULE, NEO4J_* are all set
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

SYNTHEA_DATA_DIR="${SYNTHEA_DATA_DIR:-G:/My Drive/kubuntu/agentic-memory/big-healtcare-data/synthetic-data}"

# STDB_BINDINGS_MODULE is set in .env as a relative path from the repo root.
# The bridge resolves it with path.resolve() so we make it absolute here.
if [[ -z "${STDB_BINDINGS_MODULE:-}" ]]; then
    echo "ERROR: STDB_BINDINGS_MODULE is not set. Check .env."
    exit 1
fi
export STDB_BINDINGS_MODULE="$REPO_ROOT/$STDB_BINDINGS_MODULE"

if [[ -z "${STDB_URI:-}" ]]; then
    echo "ERROR: STDB_URI is not set. Check .env."
    exit 1
fi

exec python "$REPO_ROOT/experiments/healthcare/exp1_temporal_decay.py" \
    --data-dir "$SYNTHEA_DATA_DIR" \
    --output-dir "$REPO_ROOT/experiments/healthcare/results" \
    "$@"
