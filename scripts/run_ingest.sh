#!/usr/bin/env bash
# run_ingest.sh — Ingest Synthea data into Neo4j + SpacetimeDB
#
# Sources .env from the repo root for all required env vars.
# Runs with --enable-temporal by default since SpacetimeDB is the core
# differentiator for Experiment 1.
#
# Dev run (100 patients, temporal enabled):
#   bash scripts/run_ingest.sh --max-patients 100
#
# Skip observations (faster, still valid for Exp 2):
#   bash scripts/run_ingest.sh --max-patients 1000 --skip-observations
#
# Full dataset (no patient cap):
#   bash scripts/run_ingest.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load environment from .env if present
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

SYNTHEA_DATA_DIR="${SYNTHEA_DATA_DIR:-G:/My Drive/kubuntu/agentic-memory/big-healtcare-data/synthetic-data}"

# Guard: STDB_URI must be set (fixed from localhost:3001 → maincloud in .env)
if [[ -z "${STDB_URI:-}" ]]; then
    echo "ERROR: STDB_URI is not set. Check .env or export it before running."
    exit 1
fi

# Guard: NEO4J credentials
if [[ -z "${NEO4J_URI:-}" || -z "${NEO4J_PASSWORD:-}" ]]; then
    echo "ERROR: NEO4J_URI or NEO4J_PASSWORD not set. Check .env."
    exit 1
fi

echo "Neo4j:       $NEO4J_URI"
echo "SpacetimeDB: $STDB_URI  module=${STDB_MODULE_NAME:-agentic-memory-temporal}"
echo "Data dir:    $SYNTHEA_DATA_DIR"
echo ""

exec python "$REPO_ROOT/scripts/ingest_synthea.py" \
    --data-dir "$SYNTHEA_DATA_DIR" \
    --enable-temporal \
    "$@"
