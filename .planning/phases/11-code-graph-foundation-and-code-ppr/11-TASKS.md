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

- [x] Add a TypeScript semantic call analyzer so JS/TS `CALLS` can be validated with real symbol resolution instead of parser-only fallbacks.
- [x] Add a repo-level `call-status` diagnostic so analyzer-backed vs fallback `CALLS` coverage is measurable.
- [x] Add multi-repo stress fixtures for duplicate paths and duplicate symbol names.
- [ ] Benchmark exact-hit vs neighborhood-query behavior with `ENABLE_CODE_PPR=1`.
- [ ] Decide when `CALLS` can enter the traversal graph.
- [ ] Decide when to flip `ENABLE_CODE_PPR` on by default.

## Wave 4

- [x] Add a Python semantic call analyzer with a repo-local debug surface and fixtures.
- [x] Harden JS/TS analyzer-to-graph target resolution without relying on repo-specific symbol rules.
- [x] Record analyzer drop reasons so failed semantic edges are inspectable by file, function, and reason.
- [x] Extend `call-status` / debug tooling so Python and JS/TS analyzer coverage can be compared by repo.
- [x] Stabilize parser symbol extraction so semantic analyzers keep correct names when repo files contain Unicode text before later definitions.
- [x] Classify Python builtin/library calls and repo-local class constructor hits separately so unresolved diagnostics only represent real mapping debt.
- [x] Persist analyzer batch failures and unavailable states so `call-status` shows them after a long indexing run even if the operator missed the logs.
- [ ] Re-run real-repo indexing on both `D:\code\agentic-memory` and `/home/josh/m26pipeline` to verify analyzer-backed `CALLS` survive full indexing.
