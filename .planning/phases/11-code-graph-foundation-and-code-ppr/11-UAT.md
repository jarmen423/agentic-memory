# Phase 11: Code Graph Foundation + Code PPR - UAT

## Acceptance Checklist

- [x] Code-domain graph nodes support repo-scoped identity.
- [x] Code search surfaces accept optional `repo_id` without breaking older call shapes.
- [x] Git/code history joins are repo-scoped.
- [x] Parser coverage includes Python classes/functions/imports and JS/TS-like class methods, function declarations, arrow functions, and function expressions assigned to names.
- [x] JS/TS call extraction no longer routes through the Python parser.
- [x] Fuzzy import edge creation is removed from the primary retrieval graph.
- [x] Watcher updates go through repo-scoped `reindex_file` / `delete_file` helpers.
- [x] Code PPR module exists and is guarded by `ENABLE_CODE_PPR`.
- [x] v1 code PPR traverses `IMPORTS`, `DEFINES`, and `HAS_METHOD` only.
- [ ] Python semantic `CALLS` analysis exists and produces repo-local high-confidence edges without requiring per-repo customization.
- [ ] JS/TS semantic `CALLS` mapping surfaces drop reasons so analyzer output can be debugged without manual Neo4j forensics.
- [ ] Real-world repos with different TS/JS shapes retain analyzer-backed `CALLS` edges after indexing, not just in `debug-ts-calls`.
- [ ] `CALLS` precision is high enough to enter the PPR traversal set.
- [ ] Multi-repo collision fixtures are added for duplicate paths and duplicate symbol names.
- [ ] Default-on cutover for `ENABLE_CODE_PPR` is benchmark-approved.

## Verification Notes

- Parser/unit graph/server/unified-search regressions should stay green before further rollout.
- `tests/test_am_server.py` is slower than the unit suites because it spins up the FastAPI app per case; budget a longer timeout for that suite.
- Neo4j-backed integration tests may skip locally when the configured credentials are unavailable.
