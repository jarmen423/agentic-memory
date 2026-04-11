## W11-CALLS-09

- Goal:
  - Batch Python semantic call analysis during Pass 4 so Python-heavy repos no longer appear frozen after TypeScript batches complete.

- What changed:
  - Added Python analyzer batch execution with per-batch progress logs and `last_run_issues` tracking in `src/agentic_memory/ingestion/python_call_analyzer.py`.
  - Updated Pass 4 to call the Python analyzer in bounded batches and persist repo-level `partial_failure` diagnostics just like the TypeScript path in `src/agentic_memory/ingestion/graph.py`.
  - Added regressions for analyzer-side partial batch preservation and graph-side partial failure recording in:
    - `tests/test_python_call_analyzer.py`
    - `tests/test_graph.py`

- Verification:
  - `python -m pytest tests/test_python_call_analyzer.py -q`
  - `python -m pytest tests/test_graph.py -k "pass_4_records_partial_python_batch_failures or pass_4_records_partial_typescript_batch_failures or call_diagnostics" -q`

- Residual risks:
  - Python batch timeouts are still cooperative rather than a hard subprocess kill. This improves visibility and failure isolation, but an individual basedpyright request can still block inside a batch if the language server itself stalls.
  - Real-repo indexing is still the remaining gate for confirming analyzer-backed `CALLS` survive ingestion on both local and VM repos.

- Next thread should know:
  - The next live validation step is a fresh `agentic-memory index` on `D:\code\agentic-memory` and `/home/josh/m26pipeline`, followed by `agentic-memory call-status --json`.
