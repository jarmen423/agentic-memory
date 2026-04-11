# W11-CALLS-05 Handoff

## What changed

- Updated `src/agentic_memory/ingestion/python_call_analyzer.py`.
- Updated `tests/test_python_call_analyzer.py`.

## Result

- Python semantic diagnostics now classify stdlib, builtin, and site-packages
  calls as `external_target` instead of inflating `unresolved_target_symbol`.
- Repo-local class constructor calls such as `Config(...)` or
  `ConnectionManager(...)` are now classified as `non_function_target` because
  the Phase 11 CALLS graph only admits `Function -> Function` edges.
- Live `debug-py-calls` output for `D:\code\agentic-memory\src\agentic_memory\cli.py`
  now reports:
  - `external_target = 648`
  - `non_function_target = 31`
  - `no_definition = 2`
  - `unresolved_target_symbol = 0`

## Verified

- `python -m pytest tests/test_python_call_analyzer.py -q`
- `PYTHONPATH=src python -m agentic_memory.cli debug-py-calls src\agentic_memory\cli.py --repo D:\code\agentic-memory --json`

## Residual risks

- The remaining `no_definition` cases still need inspection if we want every
  dropped Python call bucket to be fully explained.
- We still need a fresh full indexing run to verify these cleaner diagnostics
  survive Neo4j ingestion and improve `call-status` at the graph layer.
