## W11-CALLS-10

- Goal:
  - Recover semantic TypeScript results on slow repos by splitting timed-out batches into smaller retry groups instead of failing the whole 10-file batch.

- What changed:
  - Added adaptive retry logic in `src/agentic_memory/ingestion/typescript_call_analyzer.py`.
  - When a TypeScript helper batch times out and still contains more than one file, the analyzer now recursively retries smaller sub-batches until it either succeeds or reaches a single-file failure boundary.
  - Added regression coverage in `tests/test_typescript_call_analyzer.py` to prove timed-out coarse batches split into smaller retries and still return semantic results.

- Verification:
  - `python -m pytest tests/test_typescript_call_analyzer.py -q`
  - `python -m pytest tests/test_graph.py -k "pass_4_records_partial_typescript_batch_failures or call_diagnostics" -q`

- Residual risks:
  - A single pathological file can still time out on its own and will fall back to parser-only calls for that file.
  - The helper still pays repo startup cost per subprocess batch, so a future optimization may need project-root caching or a more persistent TS server strategy.

- Next thread should know:
  - The live validation step is a fresh VM re-run. The expected behavior is fewer wholesale `10 files` failures and more smaller retry logs such as batch retry splits before any leaf-level failure remains.
