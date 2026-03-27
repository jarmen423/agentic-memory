# Phase 9: Temporal PPR Retrieval + Benchmark - Context

**Gathered:** 2026-03-27
**Status:** Ready for research and planning

<domain>
## Phase Boundary

Phase 9 is the retrieval cutover phase for the temporal GraphRAG path introduced in Phases 7 and 8.
It does not introduce a new temporal graph model. Instead, it operationalizes the existing
SpacetimeDB temporal graph for ranked retrieval and validates the result quality against the
current Neo4j vector-search baseline.

This phase has three responsibilities:

1. Make temporal Personalized PageRank the primary retrieval path for conversation and research memory.
2. Preserve backward compatibility by keeping the existing vector-search path as fallback.
3. Build a benchmark harness that measures token reduction, temporal consistency, and latency on real traces.

This phase does NOT include cross-module unified search, general MCP routing redesign, or broader
production hardening. Those remain Phase 10 work.

</domain>

<decisions>
## Implementation Decisions

### Retrieval Boundary
- **D-01:** Treat the existing `temporal_ppr_retrieve` SpacetimeDB procedure as the starting point, not a greenfield deliverable.
- **D-02:** Phase 9 work is primarily integration and validation: retrieval wiring, fallback behavior, benchmark harness, and tuning.
- **D-03:** Keep Neo4j vector search as the compatibility baseline and operational fallback until benchmark results justify broader cutover.

### Primary Retrieval Surfaces
- **D-04:** Phase 9 targets these retrieval entry points first:
  - MCP `get_conversation_context`
  - MCP `search_web_memory`
  - REST `GET /search/conversations`
- **D-05:** The old retrieval path remains callable internally for fallback and benchmark comparison.
- **D-06:** Code-memory retrieval is out of scope for Phase 9. The roadmap explicitly scopes this phase to conversation and research traces.

### Seed Selection for PPR
- **D-07:** Seed node selection should be derived from existing retrieval artifacts rather than inventing a second semantic stack.
- **D-08:** The practical first implementation is a hybrid:
  - use the current embedding/vector search path to identify candidate turns/chunks/findings
  - map those results to temporal graph node ids
  - call `temporal_ppr_retrieve(...)` over that seed set
- **D-09:** If seed-node extraction fails, fall back directly to the baseline vector-search response.

### Temporal Validity Rules
- **D-10:** `as_of` remains the user-facing temporal filter for Python/MCP/REST callers.
- **D-11:** The SpacetimeDB procedure owns temporal distance weighting and interval logic in microseconds.
- **D-12:** Python-side post-filtering should be minimal; the procedure result should already exclude temporally inconsistent edges for the chosen `as_of_us`.

### Benchmark Scope
- **D-13:** The benchmark compares:
  - baseline vector retrieval result set
  - temporal PPR result set
- **D-14:** The benchmark must measure at least:
  - token count per result set
  - temporal consistency rate
  - latency
- **D-15:** Use real captured conversation/research traces where available; do not rely solely on synthetic fixtures.
- **D-16:** Benchmark reporting should emit a Markdown artifact that can be committed under a dedicated benchmark output path.

### Runtime and Package Boundary
- **D-17:** Phase 9 may add new TypeScript scripts under a dedicated benchmark area, but should not disturb the Python package layout.
- **D-18:** The existing local SpacetimeDB publish/generate workflow established in Phase 8 is the canonical dev path for this phase.
- **D-19:** Benchmark scripts may depend on the generated SpacetimeDB bindings, but runtime service code should continue to load them dynamically from config.

### Fallback and Failure Semantics
- **D-20:** If SpacetimeDB is unavailable, bindings are missing, seed resolution fails, or procedure execution errors, the public retrieval APIs must still return results from the vector-search baseline.
- **D-21:** Fallback should be logged clearly server-side but must not break MCP or REST response shape contracts.

### the agent's Discretion
- Exact score blending between vector seed selection and PPR ranking.
- Whether the benchmark stores raw JSON alongside the Markdown summary.
- Whether latency measurement lives inside `run_queries.ts` or a dedicated helper.
- Exact directory layout under `bench/` or similar benchmarking subtree.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap and Prior Phase Artifacts
- `.planning/ROADMAP.md` - Phase 9 goal, deliverables, success criteria, and dependency chain.
- `.planning/phases/08-spacetimedb-maintenance-layer/08-CONTEXT.md` - Phase 8 architectural boundary and shadow-mode assumptions.
- `.planning/phases/08-spacetimedb-maintenance-layer/08-SUMMARY.md` - Phase 8 delivered runtime stack and verification outcome.
- `.planning/phases/07-temporal-schema/07-CONTEXT.md` - Locked temporal semantics from the Neo4j side.

### SpacetimeDB Temporal Graph
- `packages/am-temporal-kg/src/procedures/retrieve.ts` - existing `temporal_ppr_retrieve` implementation.
- `packages/am-temporal-kg/src/schema.ts` - canonical temporal graph tables and public/private table shape.
- `packages/am-temporal-kg/generated-bindings/index.ts` - generated client contract that retrieval integration will rely on.

### Existing Retrieval Entry Points
- `src/codememory/server/tools.py` - MCP retrieval tools (`search_conversations`, `get_conversation_context`, schedule tools).
- `src/codememory/server/app.py` - MCP `search_web_memory` implementation and current vector-search formatting.
- `src/am_server/routes/conversation.py` - REST `/search/conversations` baseline vector-search path.

### Existing Ingestion and Search Data Shapes
- `src/codememory/chat/pipeline.py` - conversation graph shape and turn semantics.
- `src/codememory/web/pipeline.py` - research graph shape and finding/chunk semantics.
- `src/codememory/core/graph_writer.py` - Neo4j relationship/property conventions that still define the baseline search surface.

</canonical_refs>

<code_context>
## Existing Code Insights

### Important Non-Obvious Fact
`temporal_ppr_retrieve` already exists in Phase 8 and is exported from the module. Phase 9 should not spend effort re-specifying the procedure from scratch unless research shows it is incomplete or wrong for the roadmap contract.

### Current Baseline Retrieval Paths
- `src/am_server/routes/conversation.py` uses Neo4j vector search over `chat_embeddings`, with text-search fallback.
- `src/codememory/server/tools.py` implements MCP `search_conversations` and `get_conversation_context` with vector search over Neo4j.
- `src/codememory/server/app.py` implements `search_web_memory` with Neo4j vector search over `research_embeddings`.

### Current Temporal Gap
- The public retrieval surfaces currently use `as_of` only as a Python-side heuristic or post-filter.
- They do not yet call into the SpacetimeDB temporal graph for graph-aware retrieval.
- There is no benchmark harness in the repo yet for comparing vector search vs temporal PPR.

### Existing Phase 8 Runtime Path
- Local SpacetimeDB publish/generate flow is working.
- The real `am-sync-neo4j` worker now starts, subscribes, and mirrors temporal rows into Neo4j.
- This means Phase 9 can assume the hot temporal layer exists and is queryable in local development.

### Likely Integration Shape
- Python retrieval code will need a bridge to SpacetimeDB procedure calls.
- The existing codebase is Python-first, while the generated SpacetimeDB bindings are TypeScript.
- Planning must decide whether:
  - Python calls a lightweight Node helper process/script for PPR retrieval, or
  - Phase 9 introduces a separate service/client boundary for temporal retrieval.
- This is the main integration design decision for research/planning; it is not yet locked by existing code.

</code_context>

<specifics>
## Specific Ideas

- Reuse the current vector-search result set as seed-node discovery for the first PPR rollout.
- Keep response shapes stable: callers should receive the same top-level fields even when the ranking source changes.
- Benchmark outputs should include both raw retrieval counts and token-normalized summaries so tuning decisions are evidence-backed.
- Measure temporal consistency directly from returned interval fields instead of treating “PPR ran” as success.

</specifics>

<deferred>
## Deferred Ideas

- Cross-module unified retrieval and reranking across code + research + conversation belongs to Phase 10.
- Eliminating Neo4j vector search entirely is out of scope; Phase 9 keeps fallback.
- Large-scale ops concerns like production SpacetimeDB deployment, observability expansion, and unified documentation remain Phase 10.
- Reworking ingestion to produce different seed-node semantics is out of scope unless strictly required by retrieval correctness.

</deferred>

---

*Phase: 09-temporal-ppr-retrieval-benchmark*
*Context gathered: 2026-03-27*
