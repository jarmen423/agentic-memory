# W11-CALLS-04 Handoff

## What changed

- Updated `src/agentic_memory/ingestion/parser.py`.
- Updated `tests/test_parser.py`.
- Updated `pyproject.toml`.
- Updated `requirements.txt`.

## Result

- Parser node text extraction now slices UTF-8 bytes instead of slicing the raw
  Python string with Tree-sitter byte offsets.
- Python symbol names remain stable even when a file contains emoji or other
  multi-byte characters before later function definitions.
- The Phase 11 Python semantic analyzer now produces clean function identities
  for real repo files such as `src/agentic_memory/cli.py`.
- Packaging metadata no longer contains a duplicate `basedpyright` entry, and
  `requirements.txt` now includes the Python semantic analyzer dependency.

## Verified

- `python -m pytest tests/test_parser.py tests/test_python_call_analyzer.py tests/test_graph.py tests/test_cli.py -q`
- `PYTHONPATH=src python -m agentic_memory.cli debug-py-calls src\agentic_memory\cli.py --repo D:\code\agentic-memory --json`

## Residual risks

- The plain installed CLI can still resolve an older package copy if the branch
  checkout is not installed in editable mode or `PYTHONPATH` is not pointed at
  `src`. That is an environment issue, not a parser correctness issue.
- `CALLS` still needs another live indexing pass after the 429 interruption to
  verify graph ingestion quality on both real repositories.
