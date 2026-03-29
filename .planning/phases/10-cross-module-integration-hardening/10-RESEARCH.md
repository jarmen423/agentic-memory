# Phase 10: Cross-Module Integration & Hardening - Research

**Date:** 2026-03-28  
**Status:** Ready for execution planning  
**Primary sources:** local repo code, roadmap, PRD, Phase 9 artifacts

## Executive Summary

Phase 10 is narrower than the roadmap text first suggests because some of the original integration
work already landed during Phase 9:

1. there is already a single FastMCP server,
2. web and conversation retrieval already use the temporal bridge with baseline fallback,
3. the extraction LLM path is already provider-shaped.

The main remaining repo gaps are different:

- there is no normalized cross-module search contract,
- `search_all_memory` does not exist,
- code search still sits outside the temporal/unified retrieval path,
- Nemotron support exists in abstraction but is not selectable in the actual live factories/CLI,
- observability and retry behavior are inconsistent,
- there is no end-to-end integration suite or operator-quality setup documentation.

The practical Phase 10 split should therefore be:

1. unified search contract and `search_all_memory`,
2. provider/config completion plus hardening,
3. end-to-end tests and documentation.

## Key Findings

### 1. The “single MCP router” success criterion is already partially satisfied

**Confidence:** High

- `src/codememory/server/app.py` defines one `FastMCP("Agentic Memory")` server.
- `src/am_server/app.py` mounts that MCP server at `/mcp`.
- `src/codememory/server/app.py` also imports and registers the conversation tools from
  `src/codememory/server/tools.py`.

Implication:
- Phase 10 should not spend effort creating a new router process or splitting tools into another
  server.
- The missing work is unified search semantics, not server bootstrapping.

### 2. Temporal retrieval is already wired for conversation and research, but not for code

**Confidence:** High

- `src/codememory/server/tools.py`
  - `search_conversations(...)`
  - `get_conversation_context(...)`
- `src/codememory/server/app.py`
  - `search_web_memory(...)`

Those paths already:
- discover temporal seeds,
- call the temporal bridge when available,
- fall back to Neo4j/vector behavior on failure.

By contrast:
- `search_codebase(...)` still lives on the legacy code-memory path and has no shared result model
  with the newer temporal-first retrieval surfaces.

Implication:
- Phase 10 unified search must aggregate unlike retrieval implementations.
- The right abstraction boundary is a normalized result contract, not a forced shared backend.

### 3. `search_all_memory` is completely absent

**Confidence:** High

Repo search found only roadmap mentions of `search_all_memory`, with no implementation in `src/` or
`tests/`.

Implication:
- The central new deliverable of the phase remains untouched.
- Planning must specify both internal service boundaries and user-facing output shape.

### 4. Current result shapes are too heterogeneous to merge safely

**Confidence:** High

Today:
- `search_codebase(...)` is a human-facing MCP tool from the older code-memory stack.
- `search_web_memory(...)` formats research results differently from conversation search.
- conversation REST search returns structured JSON rows.

The existing tools are optimized for their individual callers, not for cross-module ranking.

Implication:
- Phase 10 should add an internal normalized result object such as `UnifiedMemoryHit`.
- The aggregator should call module-level search helpers that return structured hits, then hand that
  unified list to MCP/REST formatters.

### 5. Nemotron support exists in the core embedding abstraction but not in live runtime selection

**Confidence:** High

What exists:
- `src/codememory/core/embedding.py`
  - provider `"nemotron"`
  - default model `nvidia/nv-embedqa-e5-v5`
- `src/codememory/config.py`
  - per-module embedding settings
  - `nemotron` provider block with default base URL

What is still hardcoded:
- `src/am_server/dependencies.py`
  - `EmbeddingService(provider="gemini", ...)`
- `src/codememory/server/tools.py`
  - cached pipeline factories use Gemini directly
- `src/codememory/cli.py`
  - web/chat ingest and search commands instantiate Gemini directly

Implication:
- “Nemotron selectable” is not a trivial config edit in practice until those live constructors are
  redirected through config resolution.
- The right fix is a shared embedding resolver/factory used by CLI, MCP, and FastAPI dependencies.

### 6. Observability is fragmented

**Confidence:** High

Strengths:
- `src/codememory/server/app.py` already records telemetry and wraps tool calls with duration
  logging.

Weaknesses:
- module logs do not share a consistent event schema,
- fallback messages vary by path,
- no request/correlation id is propagated through FastAPI to module calls,
- logs are not structured enough for reliable cross-module debugging.

Implication:
- Hardening should focus on standardization and propagation, not adding a second telemetry system.

### 7. Retry behavior is not standardized on the active runtime paths

**Confidence:** High

- Legacy retry logic exists in `src/codememory/ingestion/graph.py`.
- Current active embedding, extraction, bridge, and HTTP entry points mostly rely on direct calls
  plus ad hoc fallback handling.

Implication:
- Phase 10 should define a small retry policy for transient provider/network boundaries only.
- It should not add broad retries around graph writes, validation failures, or deterministic parsing
  paths.

### 8. There is still no full-stack integration story for the whole product

**Confidence:** High

The repo has good unit coverage for:
- embedding behavior,
- entity/claim extraction,
- conversation and research pipelines,
- temporal bridge behavior,
- specific fallback paths.

What is still missing:
- a single integration suite that boots the app and proves code + research + conversation are all
  queryable through one interface,
- a documented operator path for starting Neo4j, SpacetimeDB, the sync worker, and `am-server`.

Implication:
- Docs and integration tests are phase-defining deliverables, not polish.

## Recommended Architecture

### 1. Introduce a normalized internal result contract

Recommended type:

```text
UnifiedMemoryHit
  module: "code" | "web" | "conversation"
  source_kind: str
  source_id: str
  title: str | None
  excerpt: str
  score: float
  baseline_score: float | None
  temporal_score: float | None
  temporal_applied: bool
  as_of: str | None
  metadata: dict[str, Any]
```

Why:
- it makes cross-module merge/rerank deterministic,
- it keeps formatting concerns out of retrieval,
- it avoids parsing formatted tool strings back into data.

### 2. Use module-aware ranking, not fake temporal semantics

Recommended ranking policy:

- conversation and research:
  - use temporal-first results when available,
  - keep baseline scores and temporal scores in metadata,
  - mark `temporal_applied=true`
- code:
  - use current semantic/hybrid score,
  - leave `temporal_score=None`,
  - mark `temporal_applied=false`

Then normalize scores into a common `score` field before global ordering.

Do not invent fake validity intervals for code search just to satisfy a uniform formula.

### 3. Build unified search as a service, not inside tool decorators

Recommended shape:

- new service module in `src/codememory/server/` or `src/codememory/retrieval/`
- one orchestrator function:
  - accepts `query`, `project_id`, `as_of`, `modules`, `limit`
  - calls module-specific structured search helpers
  - merges, reranks, trims, and annotates results
- MCP tool and optional REST route become thin wrappers

Why:
- easier to test,
- easier to reuse,
- avoids duplicating logic between MCP and REST.

### 4. Finish provider wiring via a shared embedding resolver

Recommended shape:

- new shared helper that resolves:
  - provider
  - api key
  - model
  - dimensions
  - base URL
  from `Config.get_module_config(...)` plus env/provider blocks

Callers that should use it:
- `src/am_server/dependencies.py`
- `src/codememory/server/tools.py`
- `src/codememory/cli.py`

Why:
- this is the real completion step for Nemotron support,
- it prevents future provider drift between CLI, MCP, and REST.

### 5. Standardize observability at request boundaries

Recommended minimum:

- request/correlation id generated in FastAPI middleware,
- propagated into log context for module calls,
- standardized event names for:
  - baseline search success,
  - temporal search success,
  - temporal fallback,
  - provider failure,
  - bridge unavailable,
  - partial unified-search result

Do not build a full tracing system in this phase unless the repo already needs it.

### 6. Apply retries only to transient transport/provider failures

Good retry boundaries:
- embedding provider calls,
- extraction LLM calls,
- external search HTTP requests,
- temporal bridge process transport if the failure is clearly transient and idempotent

Bad retry boundaries:
- Neo4j writes after partial side effects,
- validation failures,
- malformed user payloads,
- deterministic transformation logic.

## Do Not Hand-Roll

- Do not build a second MCP server to satisfy the “unified router” wording.
- Do not rewrite code search in TypeScript or force it through the temporal bridge.
- Do not parse existing human-readable MCP tool strings back into structured data.
- Do not make every exception retriable; classify transient vs deterministic failures explicitly.
- Do not introduce fake temporal scores for code results just for symmetry.

## Common Pitfalls

### 1. Treating “single server” as the missing deliverable

That work is mostly already done. Spending Phase 10 on router reshuffling would miss the actual gap:
normalized search and hardened runtime behavior.

### 2. Letting one module failure poison unified search

`search_all_memory` must degrade per module, not all-or-nothing.

### 3. Leaving hardcoded Gemini constructors in place

If runtime factories still hardcode Gemini, Nemotron support remains theoretical.

### 4. Mixing formatting and ranking

Once tool presentation and merge logic are coupled, both MCP and REST become hard to evolve.

### 5. Over-scoping observability

The repo needs consistent structured logs and request correlation, not a large telemetry rewrite.

## Recommended Plan Split

### Plan 10-01

Unified cross-module retrieval:
- normalized result contract,
- aggregator service,
- `search_all_memory`,
- module-aware reranking and fallback tests.

### Plan 10-02

Provider and runtime hardening:
- config-driven embedding resolution across live factories/CLI,
- Nemotron selectable end to end,
- shared retry/error classification,
- structured logging and correlation ids.

### Plan 10-03

Validation and operator usability:
- end-to-end integration tests across code/web/conversation,
- fallback-path integration coverage,
- full-stack setup guide,
- MCP/provider/SpacetimeDB docs.

## Confidence Notes

- High confidence that the plan split matches the real repo gaps.
- Medium confidence on whether a REST `/search/all` endpoint is worth doing in the same plan as the
  MCP tool; it is useful for testability, but not strictly required by the roadmap text.
- Medium confidence on the exact global ranking formula; the phase should keep it simple and
  explainable first, then tune from evidence.

---

*Phase: 10-cross-module-integration-hardening*
*Research completed: 2026-03-28*
