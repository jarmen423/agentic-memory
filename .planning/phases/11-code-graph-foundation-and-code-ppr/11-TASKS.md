# Phase 11 Task Registry

## Wave 0

- [x] Lock the identity contract: `repo_id` for code, `project_id` as higher-level context only.
- [x] Lock the v1 retrieval contract: non-temporal PPR behind `ENABLE_CODE_PPR`.
- [x] Lock the v1 traversal graph: `IMPORTS`, `DEFINES`, `HAS_METHOD`.

## Wave 1

- [x] Rewrite the canonical parser for Python and JS/TS-like extraction.
- [x] Route graph ingestion through the canonical parser contract.
- [x] Add repo-scoped code graph constraints and lookups.
- [x] Remove fuzzy import edge creation from the primary retrieval graph.
- [x] Replace file-level call duplication with conservative function-level call extraction.
- [x] Route watcher updates through repo-scoped reindex/delete helpers.
- [x] Add repo-scoped git/code joins.

## Wave 2

- [x] Add code search module with optional non-temporal PPR.
- [x] Wire code search through MCP, REST, and unified search surfaces.
- [x] Preserve backward-compatible baseline call shapes when `repo_id` is not explicitly passed.
- [x] Add targeted tests for parser, graph, server, unified search, code search, and auth contracts.

## Wave 3

- [ ] Add multi-repo stress fixtures for duplicate paths and duplicate symbol names.
- [ ] Benchmark exact-hit vs neighborhood-query behavior with `ENABLE_CODE_PPR=1`.
- [ ] Decide when `CALLS` can enter the traversal graph.
- [ ] Decide when to flip `ENABLE_CODE_PPR` on by default.
