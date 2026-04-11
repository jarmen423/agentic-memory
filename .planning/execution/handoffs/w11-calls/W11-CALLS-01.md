# W11-CALLS-01 Handoff

## What changed

- Added `src/agentic_memory/ingestion/python_call_analyzer.py`.
- Added `tests/test_python_call_analyzer.py`.
- Added runtime dependency `basedpyright>=1.39.0` to `pyproject.toml`.

## Result

- Python now has a language-server-backed semantic call analyzer.
- The analyzer uses AST call-site positions plus
  `basedpyright-langserver --stdio` `textDocument/definition` requests.
- Output is repo-local and shaped for the graph layer:
  - `rel_path`
  - `name`
  - `qualified_name_guess`
  - `definition_line`
  - `definition_column`
  - diagnostics and drop-reason counts

## Verified

- `python -m pytest tests/test_python_call_analyzer.py -q`

## Residual risks

- Python analysis depends on `basedpyright-langserver` being installed in the
  runtime environment.
- Some dynamic Python dispatch patterns still will not resolve semantically,
  which is expected; those should degrade into explicit drop reasons.
