# Phase 10: Cross-Module Integration & Hardening - Context

**Gathered:** 2026-03-28
**Status:** Discuss complete; ready for execution planning

<domain>
## Phase Boundary

Phase 10 is the cross-module consolidation and hardening phase that follows the temporal retrieval
cutover work from Phase 9.

It is not a new temporal-schema phase and it is not a graph-algorithm phase. The temporal model,
SpacetimeDB maintenance layer, and temporal bridge already exist. The remaining job is to make the
whole system behave like one product rather than three adjacent modules with different runtime
surfaces.

This phase has five responsibilities:

1. Add a unified cross-module retrieval surface (`search_all_memory`) across code, research, and conversation memory.
2. Normalize cross-module result contracts and ranking semantics so aggregation is deterministic.
3. Finish runtime embedding-provider selection so Nvidia Nemotron is actually selectable in live code paths.
4. Standardize logging, observability, and retry/error behavior across the active Python services.
5. Deliver end-to-end tests and operator-facing documentation for the full stack.

This phase does NOT include:
- inventing a new retrieval algorithm beyond the current temporal-first + fallback architecture,
- migrating code memory into SpacetimeDB,
- removing Neo4j fallback behavior,
- redesigning the external MCP protocol surface from scratch.

</domain>

<decisions>
## Implementation Decisions

### Scope and sequencing
- **D-01:** Phase 10 execution remains gated on Phase 9 verification closure, but discuss/research/planning can proceed now.
- **D-02:** Treat Phase 10 as integration and hardening work over existing delivery, not a greenfield architecture phase.
- **D-03:** Preserve the PRD’s hot/cold hybrid model:
  - SpacetimeDB remains the hot temporal layer for conversation/research retrieval.
  - Neo4j remains the cold analytics + fallback layer.

### Unified retrieval surface
- **D-04:** `search_all_memory` is the primary new user-facing deliverable for this phase.
- **D-05:** Because a single FastMCP server already exists, the main missing piece is not “router creation” but a unified internal result contract and aggregator service.
- **D-06:** The unified search service should aggregate these retrieval families:
  - code memory (`search_codebase` / underlying semantic search),
  - conversation memory (temporal-first, Neo4j fallback),
  - research memory (temporal-first, Neo4j fallback).
- **D-07:** Result normalization must happen in Python before tool formatting. Do not merge string-formatted tool outputs.

### Cross-module ranking semantics
- **D-08:** Temporal weighting applies only to modules that actually carry temporal evidence today (conversation and research).
- **D-09:** Code search remains eligible in unified ranking even without temporal intervals. It should be tagged `temporal_applied=false` rather than forced through a fake temporal score.
- **D-10:** Cross-module ranking should use module-normalized relevance plus explicit metadata explaining whether temporal reranking was applied.
- **D-11:** Per-module fallback behavior must remain intact inside unified search. A failure in one module must not suppress healthy modules.

### Provider/config boundary
- **D-12:** “Nemotron support” for Phase 10 means runtime-selectable embeddings in live factories and CLI paths, not just a dormant abstraction.
- **D-13:** Embedding-provider selection must come from config/env resolution (`Config.get_module_config(...)` or a shared resolver), not hardcoded `provider="gemini"` call sites.
- **D-14:** Extraction-LLM selection and embedding-provider selection should remain separate concerns.

### Hardening boundary
- **D-15:** Logging must become structured enough for request correlation, fallback diagnosis, and cross-module debugging.
- **D-16:** Retry logic should be standardized only around transient provider/network boundaries. Do not wrap deterministic graph operations or validation errors in generic retry loops.
- **D-17:** End-to-end integration tests are part of the phase definition, not optional follow-up work.

### the agent's Discretion
- Exact internal result type names and module-specific score normalization formulae.
- Whether `search_all_memory` is exposed as MCP only or MCP + REST parity.
- Exact logging format (JSON logger vs consistent key/value log lines) as long as correlation and event fields are standardized.
- Exact docs file names and directory layout.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project intent and roadmap
- `.planning/PRD-SpacetimeDB-TGRAG.md` - hot/cold hybrid recommendation, temporal-first retrieval intent, cutover sequence.
- `.planning/ROADMAP.md` - Phase 10 goal, deliverables, success criteria, and risks.
- `.planning/STATE.md` - current project execution state and active-phase gating.

### Prior phase outputs
- `.planning/phases/09-temporal-ppr-retrieval-benchmark/09-CONTEXT.md` - scope boundary between Phase 9 and Phase 10.
- `.planning/phases/09-temporal-ppr-retrieval-benchmark/09-RESEARCH.md` - temporal bridge and retrieval integration findings.
- `.planning/phases/09-temporal-ppr-retrieval-benchmark/09-UAT.md` - current verification state for the temporal retrieval cutover.

### Current runtime surfaces
- `src/codememory/server/app.py` - primary FastMCP server, code search tools, web memory tools, tool logging wrapper.
- `src/codememory/server/tools.py` - conversation tools, conversation retrieval logic, schedule tools.
- `src/am_server/app.py` - FastAPI app mounting the MCP server at `/mcp`.
- `src/am_server/routes/conversation.py` - REST conversation search/ingest surface.
- `src/am_server/routes/research.py` - REST research search/ingest surface.

### Current provider and configuration surfaces
- `src/codememory/config.py` - module config defaults and provider config blocks, including Nemotron.
- `src/codememory/core/embedding.py` - embedding abstraction already supporting Gemini/OpenAI/Nemotron.
- `src/codememory/core/extraction_llm.py` - extraction provider resolver added independently of embedding providers.
- `src/am_server/dependencies.py` - current live pipeline factories with hardcoded Gemini embedder selection.
- `src/codememory/cli.py` - CLI paths that still hardcode Gemini for chat/research.

### Current temporal integration
- `src/codememory/temporal/bridge.py` - Python temporal bridge.
- `src/codememory/temporal/seeds.py` - seed extraction and `as_of` parsing helpers.
- `packages/am-temporal-kg/scripts/query_temporal.ts` - TypeScript helper process for temporal retrieval and ingest.

</canonical_refs>

<code_context>
## Existing Code Insights

### Important Non-Obvious Facts

1. **A single MCP server already exists.**
   - `src/codememory/server/app.py` defines `mcp = FastMCP("Agentic Memory")`.
   - `src/am_server/app.py` mounts that same MCP server at `/mcp`.
   Phase 10 therefore does not need to create a new router process; it needs to unify search behavior and contracts.

2. **Temporal-first retrieval already exists for conversation and research.**
   - `src/codememory/server/tools.py` applies temporal retrieval with fallback for conversation search/context.
   - `src/codememory/server/app.py` applies temporal retrieval with fallback for web research search.

3. **Code search is still isolated from the temporal stack.**
   - `search_codebase(...)` lives in `src/codememory/server/app.py`.
   - It is still shaped around the older `KnowledgeGraphBuilder` semantics and not part of any normalized cross-module search contract.

4. **`search_all_memory` does not exist yet.**
   Repo-wide search shows only roadmap mentions, not implementation.

5. **Nemotron is only partially integrated.**
   - `src/codememory/core/embedding.py` supports provider `"nemotron"`.
   - `src/codememory/config.py` contains a `nemotron` provider block.
   - But `src/am_server/dependencies.py`, `src/codememory/server/tools.py`, and multiple CLI paths still construct `EmbeddingService(provider="gemini", ...)` directly.

6. **Observability is inconsistent today.**
   - `src/codememory/server/app.py` has useful telemetry hooks and tool-call wrappers.
   - The wider codebase still mixes emoji-oriented logs, plain error strings, and ad hoc fallback messages without a shared request context or event schema.

7. **Retry/error handling is inconsistent today.**
   - Legacy retry logic exists in `src/codememory/ingestion/graph.py`.
   - Current active pipelines, provider clients, and FastAPI/MCP surfaces do not share a standard retry/error taxonomy.

8. **End-to-end integration coverage is missing at the product boundary.**
   There are strong unit tests around individual modules and recent temporal retrieval behavior, but no single full-stack integration suite proving code + web + conversation work together through unified search.

</code_context>

<specifics>
## Specific Ideas

- Introduce an internal `UnifiedMemoryHit` contract rather than composing human-formatted tool strings.
- Build `search_all_memory` as a thin wrapper over a dedicated aggregator service; keep MCP/REST presentation out of ranking logic.
- Keep per-module failure isolation: if code search fails but conversation/web succeed, return partial results with explicit metadata rather than hard-failing the whole query.
- Treat code results as non-temporal but not second-class; annotate them clearly in output and ranking metadata.
- Use request-scoped correlation ids so a single query can be traced across MCP tool call, module search calls, temporal fallback, and FastAPI logs.

</specifics>

<deferred>
## Deferred Ideas

- Replacing Neo4j with SpacetimeDB as the sole store is out of scope.
- Moving code memory onto the temporal graph is out of scope.
- New frontend/admin UI for observability or debugging is out of scope.
- Reworking passive connectors (`am-proxy`, `am-ext`) beyond compatibility updates is out of scope unless required by integration tests.

</deferred>

---

*Phase: 10-cross-module-integration-hardening*
*Context gathered: 2026-03-28*
