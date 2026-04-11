# W11-CALLS-06 Handoff

## What changed

- Updated `src/agentic_memory/ingestion/graph.py`.
- Updated `src/agentic_memory/cli.py`.
- Updated `tests/test_graph.py`.
- Updated `tests/test_cli.py`.

## Result

- Pass 4 now persists repo-level analyzer batch failures and unavailable states
  in `CallAnalysisIssue` records.
- `call-status` now returns and prints `analyzer_issues` so a long indexing run
  leaves a durable summary even if the operator missed the console warning.
- This specifically covers cases like:
  - `TypeScript call analyzer timed out after 60s.`
  - analyzer unavailable because local tooling is missing

## Verified

- `python -m pytest tests/test_graph.py -k "call_diagnostics or pass_4_records_typescript_analyzer_batch_failures" -q`
- `python -m pytest tests/test_cli.py -k "call_status_json_success" -q`

## Residual risks

- This stores only the latest repo-level issue per analyzer family, not a full
  historical event log.
- The next live indexing run still needs to confirm the new record is written
  on the VM timeout path and appears in `call-status --json` afterward.
