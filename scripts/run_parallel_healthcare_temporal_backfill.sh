#!/usr/bin/env bash
#
# Launch multiple temporal-only healthcare backfill workers on disjoint shards.
#
# Why this script exists:
#   The temporal backfill now supports deterministic chunk sharding and batched
#   claim writes, but manually launching N workers with the correct shard flags
#   is still tedious and easy to get wrong. This wrapper gives us one repeatable
#   VM-side command for parallel temporal throughput runs against the local
#   SpacetimeDB instance.

set -euo pipefail

INPUT_DIR="${1:-}"
WORKER_COUNT="${2:-}"
CLAIM_BATCH_SIZE="${3:-250}"
LOG_DIR="${4:-/root/healthcare-temporal-logs}"

if [[ -z "${INPUT_DIR}" || -z "${WORKER_COUNT}" ]]; then
  cat <<'USAGE'
Usage:
  scripts/run_parallel_healthcare_temporal_backfill.sh <input_dir> <worker_count> [claim_batch_size] [log_dir]

Example:
  scripts/run_parallel_healthcare_temporal_backfill.sh /root/embedded-exports 4 250 /root/healthcare-temporal-logs

Notes:
  - This is intended for Linux/VM use.
  - Point STDB_URI at the VM-local SpacetimeDB instance before using this.
  - Run the smoke-project integrity check first on a small subset.
  - Each worker gets a disjoint chunk subset via --shard-count / --shard-index.
USAGE
  exit 1
fi

if ! [[ "${WORKER_COUNT}" =~ ^[0-9]+$ ]] || [[ "${WORKER_COUNT}" -lt 1 ]]; then
  echo "worker_count must be a positive integer" >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

for (( shard_index=0; shard_index<WORKER_COUNT; shard_index++ )); do
  log_path="${LOG_DIR}/worker-${shard_index}.log"
  echo "Starting temporal worker ${shard_index}/${WORKER_COUNT} -> ${log_path}"
  nohup ./.venv-agentic-memory/bin/python scripts/backfill_healthcare_temporal.py \
    --input-dir "${INPUT_DIR}" \
    --claim-batch-size "${CLAIM_BATCH_SIZE}" \
    --shard-count "${WORKER_COUNT}" \
    --shard-index "${shard_index}" \
    > "${log_path}" 2>&1 < /dev/null &
  echo "  pid=$!"
done

echo
echo "Workers launched. Useful commands:"
echo "  pgrep -af 'scripts/backfill_healthcare_temporal.py'"
echo "  tail -f ${LOG_DIR}/worker-0.log"
