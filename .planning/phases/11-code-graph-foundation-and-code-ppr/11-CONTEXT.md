# Phase 11: Code Graph Foundation + Code PPR - Context

**Gathered:** 2026-04-09  
**Status:** Contract locked; implementation in progress

<domain>
## Phase Boundary

Phase 11 is the code-memory hardening phase that follows the cross-module work from Phase 10.

Its job is not to invent a new cross-domain retrieval system. Its job is to make the code graph
trustworthy enough for graph-aware retrieval and to add the first code-side PPR rollout without
mixing in temporal semantics that do not belong to most code queries.

This phase has five responsibilities:

1. Introduce stable `repo_id` identity for code-domain nodes and lookups.
2. Consolidate parsing into one canonical extraction layer for Python and JS/TS-like files.
3. Remove or fence off low-confidence graph edges from the primary retrieval graph.
4. Add repo-scoped code retrieval plumbing that can optionally run non-temporal PPR.
5. Keep the rollout behind a feature flag until graph quality and retrieval tests pass.

This phase does NOT include:
- moving code memory into the temporal SpacetimeDB sidecar,
- adding temporal decay or validity windows to code retrieval,
- using Neo4j GDS as the first code-PPR runtime,
- turning `CALLS` into a mandatory v1 traversal edge before its precision improves.

</domain>

<decisions>
## Implementation Decisions

### Identity and scoping
- **D-01:** `repo_id` is the stable code-domain partition key.
- **D-02:** `project_id` remains a higher-level work-context identifier and is not a substitute for repository identity.
- **D-03:** Code graph uniqueness must be repo-scoped:
  - `File(repo_id, path)`
  - `Function(repo_id, signature)`
  - `Class(repo_id, qualified_name)`

### Graph quality first
- **D-04:** Approximate edges should not be part of the primary retrieval graph.
- **D-05:** Fuzzy import fallback (`path CONTAINS ...`) is not acceptable for v1 code PPR.
- **D-06:** File-level call lists cannot be copied onto every function in a file.
- **D-07:** JS/TS call extraction must use the canonical parser, not the Python parser.

### Retrieval rollout
- **D-08:** Code PPR is non-temporal in v1.
- **D-09:** Code PPR stays behind `ENABLE_CODE_PPR` until benchmark gates pass.
- **D-10:** v1 PPR traverses high-confidence edges only:
  - `IMPORTS`
  - `DEFINES`
  - `HAS_METHOD`
- **D-11:** `CALLS` is excluded from the v1 traversal set until its precision gate passes.

### Architecture
- **D-12:** Query-time ranking logic belongs in the server/retrieval layer, not in the ingestion writer.
- **D-13:** The canonical parser in `src/agentic_memory/ingestion/parser.py` becomes the shared structural extraction contract.
- **D-14:** Watcher updates should route through repo-scoped file reindex/delete helpers rather than bypassing the new graph contract.

</decisions>

<canonical_refs>
## Canonical References

Downstream agents should read these before planning follow-on work:

- `.planning/phases/09-temporal-ppr-retrieval-benchmark/09-CONTEXT.md`
- `.planning/phases/09-temporal-ppr-retrieval-benchmark/09-RESEARCH.md`
- `.planning/phases/10-cross-module-integration-hardening/10-CONTEXT.md`
- `src/agentic_memory/ingestion/graph.py`
- `src/agentic_memory/ingestion/parser.py`
- `src/agentic_memory/ingestion/watcher.py`
- `src/agentic_memory/ingestion/git_graph.py`
- `src/agentic_memory/server/code_search.py`
- `src/agentic_memory/server/app.py`
- `src/agentic_memory/server/tools.py`
- `src/agentic_memory/server/unified_search.py`
- `src/am_server/routes/search.py`

</canonical_refs>

<code_context>
## Existing Code Insights

1. Code search was previously scoped operationally by one active repo root, not by a durable graph partition key.
2. The git graph already used `repo_id`, which made it the correct identity model to copy into the code graph.
3. The old call graph was especially noisy because it matched callees by short name and reused a file-level call list for every function in that file.
4. The parser module existed, but the active graph builder still duplicated weaker extraction logic internally.
5. Conversation and research retrieval already used seeded graph reranking, but code retrieval remained vector-only.

</code_context>

<current_status>
## Current Status

Implemented in this phase so far:

- repo-scoped constraints and lookup plumbing for code-domain graph entities,
- canonical parser rewrite for Python and JS/TS-like extraction,
- removal of fuzzy import edge creation from the primary retrieval path,
- conservative same-file `CALLS` reconstruction to avoid false positives,
- watcher migration to repo-scoped reindex/delete helpers,
- repo-scoped git/code joins,
- new `server/code_search.py` module with optional non-temporal PPR,
- code search surface wiring through MCP, REST, and unified search,
- targeted regression tests for parser, graph, server, unified search, and am-server contracts.

Still intentionally deferred:

- using `CALLS` inside code PPR,
- broad graph-benchmark fixtures for multi-repo collision stress cases,
- default-on cutover for `ENABLE_CODE_PPR`.

## Field Feedback (2026-04-10)

Live indexing across two real repositories refined the remaining problem:

1. `D:\code\agentic-memory` now records analyzer-backed JS/TS `CALLS` edges, so
   the TypeScript semantic path is real rather than hypothetical.
2. `/home/josh/m26pipeline` can resolve outgoing calls through
   `debug-ts-calls`, but those analyzer results still fail to map into the
   graph at repository scale.
3. The shared weakness is not "this repo needs a custom language server". The
   shared weakness is the analyzer-to-graph contract:
   - parser symbol identity,
   - analyzer symbol identity,
   - graph-side target resolution and drop visibility.
4. Python still has no semantic call analyzer at all, which means a
   generalizable `CALLS` feature cannot be considered ready.

That changes the next execution priority:

- add first-class diagnostics for why analyzer-backed edges are dropped,
- harden TypeScript/JavaScript target resolution generically,
- add a Python semantic analyzer path behind the same confidence model,
- keep `CALLS` out of ranking until these gates pass across multiple repos.

</current_status>
