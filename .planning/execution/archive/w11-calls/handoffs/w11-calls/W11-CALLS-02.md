# W11-CALLS-02 Handoff

## What changed

- Updated `scripts/query_typescript_calls.js`.
- Updated `src/agentic_memory/ingestion/typescript_call_analyzer.py`.
- Updated `tests/test_typescript_call_analyzer.py`.

## Result

- JS/TS semantic analyzer output now carries richer target identity:
  - `definition_line`
  - `definition_column`
- The helper now reports explicit dropped-target counts for non-repo or
  unsupported targets instead of silently discarding them.
- The Python wrapper now parses and exposes those drop-reason counts.

## Verified

- `python -m pytest tests/test_typescript_call_analyzer.py -q`

## Residual risks

- The TypeScript analyzer still depends on the Agentic Memory repo having a
  usable local TypeScript runtime in `node_modules`.
- Graph-side symbol matching still has to map analyzer targets onto function
  nodes; this handoff improved the data quality for that step but did not own
  `graph.py`.
