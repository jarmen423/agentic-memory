# W11-CALLS-08 Handoff

## What changed

- Updated `src/agentic_memory/ingestion/typescript_call_analyzer.py`.
- Updated `src/agentic_memory/ingestion/graph.py`.
- Updated `tests/test_typescript_call_analyzer.py`.
- Updated `tests/test_graph.py`.

## Result

- The TypeScript analyzer no longer relies on one giant repo-wide helper call.
- Large JS/TS analysis runs are split into smaller helper batches.
- When a batch fails and the caller opts into continuation, the analyzer:
  - preserves successful batches
  - records the failed batch in `last_run_issues`
  - returns per-file placeholder diagnostics for the failed batch so graph code
    can fall back selectively instead of losing the entire repo's TS semantic run
- Pass 4 now runs the TypeScript analyzer with:
  - smaller batches
  - shorter per-batch timeout
  - continuation on batch failure
- Repo-level analyzer issues now record `partial_failure` when only some TS
  batches fail.

## Verified

- `python -m pytest tests/test_typescript_call_analyzer.py -q`
- `python -m pytest tests/test_graph.py -k "pass_4_records_typescript_analyzer_batch_failures or pass_4_records_partial_typescript_batch_failures or call_diagnostics" -q`

## Residual risks

- Repeated project loading per batch is a pragmatic fix for now, not the final
  architecture. A long-lived TS service could still be worth doing later.
- We still need a fresh real-repo indexing run to confirm the chosen batch size
  and timeout values are good enough on both `agentic-memory` and `m26pipeline`.
