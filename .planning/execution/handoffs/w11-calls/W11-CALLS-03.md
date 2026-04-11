# W11-CALLS-03 Handoff

## What changed

- Updated `src/agentic_memory/ingestion/graph.py`.
- Updated `src/agentic_memory/cli.py`.
- Updated `tests/test_graph.py`.
- Updated `tests/test_cli.py`.

## Result

- Pass 4 now supports both semantic analyzer families:
  - `python_service`
  - `typescript_service`
- Semantic target resolution is shared through one graph-matching helper.
- File-level drop reasons are persisted in Neo4j via `CALL_ANALYSIS_DROP`
  relationships so repo summaries can show why semantic edges failed.
- `call-status` now surfaces:
  - analyzer attempts
  - files with drop reasons
  - aggregated drop reasons by source
- Added `debug-py-calls` to mirror `debug-ts-calls`.

## Verified

- `python -m pytest tests/test_python_call_analyzer.py tests/test_typescript_call_analyzer.py tests/test_graph.py tests/test_cli.py -q`

## Residual risks

- `CALLS` is still not ready to enter ranking by default. We now have the
  diagnostic machinery to evaluate that decision repo by repo, but not the
  benchmark evidence yet.
- Live Neo4j-backed integration tests remain skipped locally when Neo4j is not
  running.
