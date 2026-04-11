# Wave Roadmap

## Active Track: `w11-calls`

### Wave 0: Contract lock

- Lock Phase 11 plan update for semantic `CALLS` generalization.
- Freeze worker ownership and merge gates in `tasks.json`.
- Keep shared graph integration local to the orchestrator.

### Wave 1: Parallel analyzer work

- `W11-CALLS-01`: Python semantic analyzer scaffold and fixtures.
- `W11-CALLS-02`: JS/TS analyzer identity and diagnostics hardening.
- `W11-CALLS-03`: Shared graph integration, CLI diagnostics, and merge tests.

### Wave 2: Integration review

- Merge worker outputs through the shared graph contract.
- Reconcile diagnostics naming, confidence rules, and repo-level reporting.

### Wave 3: Verification

- Run analyzer unit suites.
- Run graph and CLI regression suites.
- Reassess whether `CALLS` is trustworthy enough for later ranking work.

### Wave 4: Parser contract stabilization

- `W11-CALLS-04`: Fix Unicode-safe parser slicing so Python symbol identity stays
  stable when semantic analyzers run on real repo files.
- Align packaging metadata so the new Python analyzer dependency is present in
  both `pyproject.toml` and `requirements.txt`.

### Wave 5: Python diagnostic cleanup

- `W11-CALLS-05`: Distinguish repo-external Python calls from repo-local
  constructor/class targets so the unresolved bucket only represents real
  mapping debt.

### Wave 6: Durable failure reporting

- `W11-CALLS-06`: Persist analyzer batch failures and unavailability states so
  `call-status` reports them after long indexing runs without requiring log
  babysitting.

### Wave 7: Incremental full-index orchestration

- `W11-CALLS-07`: Reuse Pass 1's changed-file set so full `index` runs stop
  re-embedding unchanged files before the call-graph stage.
