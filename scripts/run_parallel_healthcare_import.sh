#!/usr/bin/env bash
#
# Launch multiple healthcare import workers against disjoint chunk shards.
#
# Why this script exists:
#   The importer now supports deterministic chunk sharding, but manually
#   starting N background workers with the correct shard flags is error-prone.
#   This wrapper keeps the launch shape obvious and repeatable for VM-side
#   throughput tests on a clean Neo4j database.

set -euo pipefail

INPUT_DIR="${1:-}"
WORKER_COUNT="${2:-}"
WRITE_BATCH_SIZE="${3:-250}"
IMPORT_MODE="${4:-bulk}"
LOG_DIR="${5:-/root/healthcare-import-logs}"

if [[ -z "${INPUT_DIR}" || -z "${WORKER_COUNT}" ]]; then
  cat <<'USAGE'
Usage:
  scripts/run_parallel_healthcare_import.sh <input_dir> <worker_count> [write_batch_size] [import_mode] [log_dir]

Example:
  scripts/run_parallel_healthcare_import.sh /root/experiment-embeddings 4 250 bulk /root/healthcare-import-logs

Notes:
  - This is intended for Linux/VM use.
  - Use on a clean database with the Memory uniqueness constraint in place.
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
  echo "Starting worker ${shard_index}/${WORKER_COUNT} -> ${log_path}"
  nohup ./.venv-agentic-memory/bin/python scripts/import_embedded_healthcare_chunks.py \
    --input-dir "${INPUT_DIR}" \
    --write-batch-size "${WRITE_BATCH_SIZE}" \
    --import-mode "${IMPORT_MODE}" \
    --shard-count "${WORKER_COUNT}" \
    --shard-index "${shard_index}" \
    > "${log_path}" 2>&1 < /dev/null &
  echo "  pid=$!"
done

echo
echo "Workers launched. Useful commands:"
echo "  pgrep -af 'scripts/import_embedded_healthcare_chunks.py'"
echo "  tail -f ${LOG_DIR}/worker-0.log"
