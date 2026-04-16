#!/usr/bin/env bash
# run_exp2.sh — Run Experiment 2: Multi-hop Clinical Reasoning (Cypher vs Vector)
#
# Prerequisites:
#   1. Neo4j running with NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD set
#   2. Data ingested: python scripts/ingest_synthea.py --data-dir "$SYNTHEA_DATA_DIR"
#   3. Embedding API key set (GOOGLE_API_KEY for Gemini, or OPENAI_API_KEY)
#
# Quick dev run:
#   bash scripts/run_exp2.sh
#
# With pre-generated tasks (skip re-generating from CSV):
#   bash scripts/run_exp2.sh --tasks-file experiments/healthcare/results/exp2_tasks_generated.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

SYNTHEA_DATA_DIR="${SYNTHEA_DATA_DIR:-G:/My Drive/kubuntu/agentic-memory/big-healtcare-data/synthetic-data}"

exec python "$REPO_ROOT/experiments/healthcare/exp2_multihop.py" \
    --data-dir "$SYNTHEA_DATA_DIR" \
    --output-dir "$REPO_ROOT/experiments/healthcare/results" \
    "$@"
