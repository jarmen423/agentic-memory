# W11-CALLS-07 Handoff

## What changed

- Updated `src/agentic_memory/ingestion/graph.py`.
- Updated `tests/test_graph.py`.

## Result

- `pass_1_structure_scan` now returns the repo-relative paths whose content hash
  changed during the scan.
- `run_pipeline` now threads that changed-file set into:
  - `pass_2_entity_definition`
  - `pass_3_imports`
- `reindex_file` now scopes Pass 2 and Pass 3 to the single changed file while
  still leaving Pass 4 repo-wide for call-graph consistency.
- Full `agentic-memory index` runs no longer needlessly re-embed unchanged files
  before entering Pass 4.

## Verified

- `python -m pytest tests/test_graph.py -k "run_pipeline_scopes_pass_2_and_pass_3_to_changed_files or reindex_file_scopes_entity_and_import_passes_to_one_file" -q`

## Residual risks

- Pass 4 is still repo-wide and can still appear stalled at startup until the
  analyzer batching strategy is improved.
- This change targets unnecessary re-embedding and import relinking only; it
  does not yet solve the large upfront analyzer batch issue.
