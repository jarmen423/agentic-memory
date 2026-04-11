# Agentic Memory — v1 Roadmap

**Project:** Modular Knowledge Graph (Code + Web Research + Conversation Memory)
**Created:** 2026-03-20
**Last Updated:** 2026-04-11
**Status:** Active — OpenClaw foundation wave is now the active delivery track; Phase 10 and Phase 11 are paused but preserved

---

## Milestone: v1.0 — Full Multi-Module Memory System

**Goal:** Extend the existing code memory tool into a universal agent memory system with Web Research Memory and Agent Conversation Memory modules, accessible via CLI and MCP.

---

## Phase 1: Foundation

**Goal:** Establish the shared infrastructure all modules build on: core package with BaseIngestionPipeline ABC, EmbeddingService (Gemini/OpenAI/Nemotron), EntityExtractionService (Groq), GraphWriter, ConnectionManager, ConfigValidator, source registry, Memory/Entity dual-layer graph schema, and CLI scaffolding. Single Neo4j instance with multiple vector indexes.

**Plans:** 4/4 plans complete

Plans:
- [ ] 01-01-PLAN.md — Core plumbing: source registry, connection manager, config extension
- [ ] 01-02-PLAN.md — AI service layer: EmbeddingService + EntityExtractionService
- [ ] 01-03-PLAN.md — Core abstractions: BaseIngestionPipeline ABC, GraphWriter, ConfigValidator
- [ ] 01-04-PLAN.md — Integration: KnowledgeGraphBuilder adoption, CLI scaffolding, Docker, stubs

**Deliverables:**
- Abstract ingestion base classes (`BaseIngestionPipeline`, `GraphWriter`)
- Embedding service abstraction layer supporting Gemini, OpenAI, and Nvidia Nemotron (NIM-compatible, OpenAI SDK with `base_url` override)
- Entity extraction service (Groq JSON mode with type-constrained prompts)
- Config validation system — detects embedding model mismatches, warns loudly
- Single Neo4j connection manager with multiple vector indexes (3072d code, 768d web/chat)
- Source registry for label resolution
- Docker Compose (single Neo4j instance)
- CLI scaffolding for new commands (`web-init`, `web-ingest`, `web-search`, `chat-init`, `chat-ingest`) — structure only, not yet implemented
- Unit tests for all new core modules

**Success Criteria:**
- Neo4j instance starts cleanly via `docker-compose up`
- Embedding service abstraction passes correct model/dimensions per provider
- Config validation catches and rejects dimension mismatches
- KnowledgeGraphBuilder subclasses BaseIngestionPipeline (backward compatible)
- Existing code module continues to work unchanged

**Key Risks:**
- Gemini embedding API specifics (model name, dimensionality, auth method) — verified in research
- Neo4j Community Edition multi-index support — confirmed in research

---

## Phase 2: Web Research Core

**Goal:** Output-centric web research ingestion — agent-produced reports and findings persist to Neo4j as :Memory:Research nodes with Gemini embeddings, searchable via MCP tools and REST API. User-directed URL ingestion via Crawl4AI. Brave Search as agent tool for live web search.

**Plans:** 3 plans + 1 (REST API foundation)

Plans:
- [ ] 02-01-PLAN.md — GraphWriter extensions, content normalization/chunking, Crawl4AI wrapper, package deps
- [ ] 02-02-PLAN.md — ResearchIngestionPipeline (report + finding ingest paths)
- [ ] 02-03-PLAN.md — MCP tools (memory_ingest_research, search_web_memory, brave_search) + CLI commands
- [ ] 02-04-PLAN.md — REST API server foundation (FastAPI + auth + web research endpoints)

**Deliverables:**
- `ResearchIngestionPipeline` subclassing `BaseIngestionPipeline` — handles report, finding, and chunk ingest
- Content normalization pipeline: Crawl4AI (pass-through markdown), HTML (markdownify), PDF (pymupdf4llm)
- Header-based chunking with 512-token max, 50-token overlap; chunks keyed by (session_id, chunk_index)
- `memory_ingest_research` MCP tool — primary write path for agents (type: "report" | "finding")
- Graph schema: `:Memory:Research:Report` → `[:HAS_CHUNK]` → `:Memory:Research:Chunk` (embedded); `:Memory:Research:Finding` → `[:CITES {url,title,snippet}]` → `:Entity:Source`
- Deduplication: Report on (project_id + session_id), Finding on content_hash, Source MERGE on url
- `search_web_memory` MCP tool — vector search over Research Chunks + Findings
- `brave_search` MCP tool — live Brave Search API query, returns results to agent context only (NO auto-ingest)
- `web-ingest <url|path>` CLI — explicit user-directed page or PDF ingestion
- `web-init` CLI — initializes research_embeddings vector index
- `web-search` CLI — stub (tabled)
- GraphWriter: 5 new methods (write_report_node, write_source_node, write_cites_relationship, write_has_chunk_relationship, write_part_of_relationship)
- **`am-server` FastAPI REST API foundation** (`src/am_server/`):
  - `POST /ingest/research` — REST equivalent of `memory_ingest_research` MCP tool
  - `GET /search/research` — REST equivalent of `search_web_memory` MCP tool
  - `GET /ext/selectors.json` — remote DOM selectors endpoint for am-ext
  - Bearer token API key authentication middleware
  - Runs alongside FastMCP on the same process (separate port or unified via ASGI mount)

**Success Criteria:**
- `codememory web-ingest <url>` ingests a static or JS-rendered page and makes it semantically searchable
- PDF ingested via `codememory web-ingest <path>.pdf` and retrievable via semantic search
- `memory_ingest_research` MCP tool persists agent-produced reports and findings to Neo4j
- `search_web_memory` returns semantically relevant chunks and findings
- `brave_search` returns live web results to agent without touching Neo4j
- Dedup: re-ingesting same URL/report produces no duplicate nodes
- `POST /ingest/research` REST endpoint accepts the same payload as the MCP tool and produces identical results
- `GET /search/research?q=...` returns semantically relevant results via REST
- Unauthenticated requests to REST endpoints return 401

---

## Phase 3: Web Research Scheduling *(Complete — folded into Phase 7)*

**Status:** Done. The coverage tracker and topic-steering logic are superseded by the temporal KG (Phase 7) which naturally tracks what has been researched via temporal edges. The remaining deliverables — cron trigger, prompt template system, and simplified LLM variable substitution — are incorporated into Phase 7 scope. All Phase 3 success criteria are satisfied by the combination of Phase 7 (temporal coverage graph + scheduling) and Phase 9 (PPR-guided coverage gap retrieval).

**Original deliverables absorbed into Phase 7:**
- Prompt template system with variable placeholders → Phase 7
- LLM-driven variable substitution (reads temporal KG for coverage) → Phase 7
- Topic coverage tracker → replaced by temporal edge graph in Phase 7
- Schedule management (cron trigger) → Phase 7
- MCP tools: `schedule_research`, `run_research_session`, `list_research_schedules` → Phase 7
- CLI commands: `web-schedule`, `web-run-research` → Phase 7

---

## Phase 4: Conversation Memory Core

**Goal:** Conversation ingestion pipeline — extends the `am-server` REST API (built in Phase 2) with `/ingest/conversation`, enabling both passive connectors (am-proxy, am-ext) and explicit MCP writes.

**Deliverables:**
- `ConversationIngestionPipeline` subclassing `BaseIngestionPipeline` — handles turn-by-turn conversation ingestion
- Graph schema: `:Memory:Conversation:Turn` nodes with role, text, embedding; grouped by session_id and project_id
- `chat_embeddings` vector index (768d, Gemini) on `:Memory:Conversation` nodes
- Turn deduplication: MERGE on (session_id, turn_index) — append-only, idempotent
- **Extend `am-server`** (REST API foundation from Phase 2) with conversation endpoints:
  - `POST /ingest/conversation` — receives turn payloads from am-proxy and am-ext
  - `GET /search/conversations` — REST equivalent of `search_conversations` MCP tool
- `search_conversations` MCP tool — semantic search over conversation turns
- `add_message` MCP tool — explicit turn write for agents without passive capture
- `get_conversation_context` MCP tool — ranked relevant history for a given query
- `chat-init` CLI — initializes chat_embeddings vector index
- `chat-ingest` CLI — manual JSON/JSONL conversation log import
- `chat-search` CLI — semantic search over conversation memory

**Success Criteria:**
- `POST /ingest/conversation` REST endpoint accepts and persists turn payloads from am-proxy and am-ext
- `chat-ingest` correctly imports a real conversation export (JSON/JSONL)
- `search_conversations` returns semantically relevant turns
- `get_conversation_context` returns ranked history for a query
- REST and MCP tools produce identical results for equivalent inputs
- All auth via Bearer API key — same middleware as Phase 2 REST foundation

**Key Risks:**
- Conversation schema must be locked before first passive ingest (hard to migrate)
- Turn dedup key (session_id + turn_index) assumes ordered delivery — proxy must guarantee ordering

---

## Phase 5: am-proxy (ACP Proxy)

**Goal:** Transparent stdio proxy that wraps any ACP-compliant agent CLI and passively tees conversations to the memory server. Zero latency impact on the agent session.

**Deliverables:**
- `packages/am-proxy/` — standalone Python package, distributed via `pipx install am-proxy`
- `ACPProxy` class: async stdio pass-through with fire-and-forget ingest via `POST /ingest/conversation`
- Message filtering: ingest `threads/create`, `threads/message`, `threads/tool_call`, `threads/tool_result`, `threads/update`; skip protocol noise
- Request/response pairing via `_buffer` dict with `asyncio.call_later` TTL (300s) — per-entry cancel handle prevents unbounded growth
- Agent detection from binary name: claude → `claude_code`, codex → `codex`, gemini → `gemini_cli`, opencode → `opencode`, kiro → `kiro`
- TOML config: `~/.config/am-proxy/config.toml` — endpoint, api_key, default_project_id, per-agent binary paths
- CLI: `am-proxy --agent claude --project my-project`
- Setup helper: `am-proxy setup` — auto-detects installed ACP agents, prints editor config snippets
- Silent failure on all error paths — proxy never surfaces exceptions to agent or editor
- `ingestion_mode: "passive"` on all payloads

**Success Criteria:**
- `am-proxy --agent claude --project test` starts cleanly and passes stdin/stdout transparently
- Agent session runs with zero measurable latency overhead
- `threads/message` turns are POSTed to `/ingest/conversation` and appear in Neo4j
- Protocol noise (ping/pong, $/progress) is never forwarded to the memory server
- Memory server downtime (5s timeout) is swallowed silently — agent session unaffected
- Buffer TTL: unbuffered requests are evicted after 300s with no memory leak

**Key Risks:**
- ACP spec stability — message method names may change across agent CLI versions
- asyncio stream handling on Windows (subprocess pipes behave differently)
- Buffer TTL edge case: very long tool calls (>300s) lose request context on response arrival

---

## Phase 6: am-ext (Browser Extension)

**Goal:** Passive conversation capture from AI chat web UIs — install once, all supported platform conversations are silently ingested to the user's memory server.

**Deliverables:**
- `packages/am-ext/` — Chrome/Firefox Manifest V3 extension
- Platform adapters (MutationObserver + 800ms debounce for streaming detection):
  - `adapters/chatgpt.js` — `chat.openai.com`
  - `adapters/claude.js` — `claude.ai`
  - `adapters/perplexity.js` — `perplexity.ai`
  - `adapters/gemini.js` — `gemini.google.com`
- `selectors.json` — per-platform DOM selectors, remotely updatable without extension release
- Remote selectors endpoint: `GET {memory_endpoint}/ext/selectors.json` — checked at startup
- Background service worker: routes NEW_TURN events to `POST /ingest/conversation`
- Onboarding page: endpoint + API key configuration, per-platform enable/disable toggles, connection test
- Popup: live session status (platform, turns saved, session ID), pause/resume toggle
- Silent failure on all fetch paths — `.catch(() => {})` everywhere
- `ingestion_mode: "passive"`, `source_key: "browser_ext_{platform}"` on all payloads
- Session ID from platform conversation URL (not generated UUID)

**Success Criteria:**
- Install + onboard takes under 2 minutes
- ChatGPT turn captured and appears in Neo4j after assistant message completes
- 800ms debounce fires exactly once per completed streaming response (not per token)
- Platform disabled in popup: no turns sent to server
- Memory server unreachable: no errors visible to user, conversation continues normally
- Selector hotpatch: updating remote selectors.json restores capture without extension re-release

**Key Risks:**
- Platform DOM structure changes — primary maintenance burden; mitigated by remote selectors
- Chrome Store review cycle for updates — remote selectors reduce frequency
- MV3 service worker lifecycle: may be killed between turns in long sessions (use chrome.alarms as keepalive if needed)
- Same-origin restrictions on some platforms may block content script injection

---

## Phase 7: Temporal Schema + Claim Extraction + Research Scheduling

**Goal:** Add time as a first-class dimension to the knowledge graph. Extend all Neo4j relationships with validity intervals, upgrade entity NER to full SPO triple extraction, and deliver the research scheduling capability originally scoped in Phase 3 — now powered by the temporal coverage graph instead of a custom tracker.

**Deliverables:**

*Temporal schema (Neo4j):*
- Add `valid_from`, `valid_to`, `confidence`, `support_count`, `contradiction_count` as first-class properties on all relationship types in Neo4j — on edges, not nodes
- Extend `GraphWriter` with temporal relationship methods (`write_temporal_relationship`, `update_relationship_validity`, `increment_contradiction`)
- Update all three ingestion pipelines (code, web, conversation) to populate temporal fields at write time
- MCP tools gain temporal filter parameters (`as_of`, `valid_at`, time-range) on existing search tools

*Claim extraction (upgrade entity NER → SPO triples):*
- New `ClaimExtractionService` using Groq: produces `(subject_entity, predicate, object_entity, valid_from, valid_to)` triples from text, not just entity name/type lists
- Predicate catalog: typed relation labels aligned to existing relationship taxonomy (`WORKS_AT`, `KNOWS`, `RESEARCHED`, `REFERENCES`, etc.) — extensible via config
- Update `EntityExtractionService` to call claim extraction as secondary pass; existing entity NER preserved

*Research scheduling (Phase 3 remnants):*
- Prompt template system with variable placeholders (e.g. `{topic}`, `{angle}`, `{timeframe}`)
- `ResearchScheduler`: cron/interval trigger (APScheduler) → fill template variables via LLM call that reads temporal KG for coverage context → Brave Search → `ResearchIngestionPipeline`
- LLM variable fill reads the temporal graph (what predicates exist, what topics have recent edges) to steer toward uncovered angles
- MCP tools: `schedule_research`, `run_research_session`, `list_research_schedules`
- CLI commands: `web-schedule`, `web-run-research`
- Circuit breakers: rate limit handling, cost caps, graceful degradation on API failures

**Success Criteria:**
- All ingested relationships in Neo4j carry `valid_from` and `confidence` properties
- `ClaimExtractionService` produces SPO triples from sample conversation turns and research findings
- `web-schedule` creates a recurring schedule; `web-run-research` triggers a manual run
- Each scheduled run produces queries that explore different angles than prior runs (verified via temporal edge inspection)
- MCP `search_conversations` and `search_web_memory` accept `as_of` parameter and filter accordingly

**Key Risks:**
- SPO triple extraction quality — predicate normalization across sessions is hard; start with a closed predicate catalog
- Temporal backfill — existing Phase 1-6 data has no `valid_from`; handle gracefully (use `ingested_at` as fallback)
- APScheduler persistence — schedule state survives server restarts (use SQLite job store)

**Plans:** 4 plans

Plans:
- [ ] 07-01-PLAN.md — GraphWriter temporal methods + APScheduler/SQLAlchemy dependencies
- [ ] 07-02-PLAN.md — Pipeline temporal wiring + migrate-temporal backfill CLI command
- [ ] 07-03-PLAN.md — ClaimExtractionService + web pipeline SPO extraction pass
- [ ] 07-04-PLAN.md — ResearchScheduler + CLI commands + MCP tools + as_of search filter

---

## Phase 8: SpacetimeDB Maintenance Layer

**Goal:** Add an autonomous temporal maintenance engine. SpacetimeDB runs inside-the-database maintenance (decay, pruning, archival) via scheduled reducers, ensuring the temporal graph stays consistent and performant without external orchestration. Neo4j receives only validated, curated edges via a subscription-based sync worker.

**Deliverables:**
- `packages/am-temporal-kg/` — TypeScript SpacetimeDB module
  - Tables: `Node`, `Edge` (with `valid_from_us`/`valid_to_us` as identity fields), `Evidence`, `EdgeEvidence`, `EdgeStats` (Welford online variance), `EdgeArchive`, `MaintenanceJob`
  - Reducers: `upsert_node`, `ingest_temporal_edge`, `check_contradictions_on_insert`
  - Scheduled reducers (via schedule tables): `nightly_decay` (update `relevance` scores), `archive_expired` (move dead edges to `EdgeArchive`), `mdl_prune` (suppress high-variance contradictory edges)
  - `edge_id` = `hash(project_id, subj_id, pred, obj_id, valid_from_us, valid_to_us)` — time interval is part of edge identity
- `packages/am-sync-neo4j/` — TypeScript sync worker
  - Subscribes to SpacetimeDB `Edge`, `Node`, `Evidence`, `EdgeArchive` tables
  - On insert/update/delete: applies idempotent Cypher MERGE to Neo4j
  - Checkpoint system for replay protection
- **Shadow mode**: SpacetimeDB writes run in parallel with existing Neo4j writes; retrieval unchanged until Phase 9

**Success Criteria:**
- `spacetime publish` deploys the module cleanly
- Ingesting a temporal edge via reducer creates the correct row with hash-based `edge_id`
- Contradictory edges (same subj/pred, different obj, overlapping interval) increment `contradiction_count`
- Nightly maintenance job archives edges with `valid_to_us < now`; `EdgeStats.n` increments correctly on each ingest
- Sync worker propagates a new Edge row to Neo4j within 5 seconds of insertion
- Main Python test suite still passes (shadow mode — no retrieval regression)

**Key Risks:**
- SpacetimeDB procedures API is beta — `withTx` semantics may change; pin SDK version
- Sync worker replay correctness — idempotent edge ids (hash includes time interval) make MERGE safe
- Over-pruning: MDL thresholds conservative by default; archive rather than hard delete

---

## Phase 9: Temporal PPR Retrieval + Benchmark

**Goal:** Replace pure vector similarity search with Personalized PageRank guided by temporal weighting. Validate token reduction and temporal consistency against the baseline vector search on real conversation and research traces.

**Deliverables:**
- SpacetimeDB procedure: `temporal_ppr_retrieve(project_id, seed_node_ids, as_of_us, max_edges, max_hops, alpha, half_life_hours, min_relevance)`
  - Bounded PPR over local subgraph (BFS expansion + indexed adjacency lookups)
  - Temporal decay: `w = confidence × 2^(−Δt / half_life)` where Δt = distance from `as_of` to edge validity interval
  - Returns ranked edges with `subj_id`, `pred`, `obj_id`, `valid_from_us`, `valid_to_us`, `relevance`, `confidence`
- Update MCP tools `get_conversation_context` and `search_web_memory` to use temporal PPR as primary retrieval; vector search as fallback
- `bench/` harness:
  - `build_temporal_kg.ts` — replay captured conversation traces through ingest reducers
  - `run_queries.ts` — same query set against baseline (vector) and temporal PPR
  - `measure_tokens.ts` — count LLM context tokens for each result set
  - `report_results.ts` — markdown summary with token reduction %, temporal consistency rate

**Success Criteria:**
- `temporal_ppr_retrieve` returns non-empty results for a seeded query on a populated SpacetimeDB instance
- PPR results contain only edges valid within ±window of `as_of` time (no temporally inconsistent evidence)
- Benchmark shows measurable token reduction vs baseline vector search on real traces (target: validate STAR-RAG's directional claim)
- `get_conversation_context` latency p95 ≤ 200ms on 10k+ edge graph
- Existing test suites still pass (backward compatible via fallback)

**Key Risks:**
- PPR latency on large graphs — bounded BFS mitigates; tune `max_hops` and `max_nodes` per workload
- Token reduction may not reach 97% on all query types — benchmark first, tune thresholds
- SpacetimeDB procedure `withTx` determinism requirement — no external I/O inside procedure

---

## Phase 10: Cross-Module Integration & Hardening *(original Phase 7)*

**Goal:** Unified agent interface across all three modules, now temporal-aware throughout. Nvidia Nemotron embedding support, production hardening, documentation.

**Plans:** 3 plans drafted

Plans:
- [x] 10-01-PLAN.md — Unified result contract + `search_all_memory` + MCP/REST exposure
- [x] 10-02-PLAN.md — Config-driven embedding runtime + Nemotron selection + logging/retry hardening
- [x] 10-03-PLAN.md — End-to-end integration tests + setup/provider/operations docs

**Deliverables:**
- Unified MCP router: single server aggregates code + web + conversation results with temporal PPR ranking
- Cross-module search: `search_all_memory` queries all three modules, merges and re-ranks via temporal relevance
- Nvidia Nemotron embedding service (NIM API, OpenAI-compatible — ~20 lines via existing abstraction)
- Structured logging and observability across all modules
- Error recovery and retry logic standardized across modules
- Documentation: setup guides, MCP tool reference, SpacetimeDB deployment guide, provider integration guides
- End-to-end integration tests across all modules including temporal retrieval paths

**Success Criteria:**
- Single MCP server exposes all tools from all three modules
- `search_all_memory` returns temporally coherent ranked results across code, web, and conversation content
- Nvidia Nemotron selectable as embedding model via config
- All modules pass integration tests end-to-end including temporal PPR paths
- Setup guide enables a new user to have all modules + SpacetimeDB running in under 30 minutes

**Key Risks:**
- Cross-module temporal ranking (different validity semantics for code vs conversation vs research)
- MCP server routing complexity with many tools
- SpacetimeDB deployment complexity for new users

---

## Phase Dependencies

```
Phase 1 (Foundation)
    └── Phase 2 (Web Research Core + REST API foundation)
            └── Phase 4 (Conversation Memory Core)
                    ├── Phase 5 (am-proxy)          ─┐
                    └── Phase 6 (am-ext) ─────────────┤ parallel
                                                       │
Phase 2 + Phase 4 + Phase 5                           │
    └── Phase 7 (Temporal Schema + Claim Extraction   ─┘ (6 & 7 parallel)
                + Research Scheduling)
            └── Phase 8 (SpacetimeDB Maintenance Layer)
                    └── Phase 9 (Temporal PPR Retrieval + Benchmark)
                            └── Phase 10 (Cross-Module Integration & Hardening)
```

Phase 6 (am-ext) and Phase 7 (Temporal Schema) run in parallel — no shared code.
Phases 8, 9, 10 are strictly sequential.

---

## Branch Strategy

- `v1-baseline` — frozen at end of Phase 5; original v1 (no temporal layer). Finish with Phase 6 + original Phase 7 for A/B comparison.
- `main` — full v1 with temporal GraphRAG (Phases 6-10 as above).

---

## Open Research Questions

| Question | Blocks | Priority |
|----------|--------|----------|
| SpacetimeDB TypeScript module SDK version to pin | Phase 8 | Critical |
| SpacetimeDB deployment: maincloud vs self-hosted for dev | Phase 8 | High |
| Predicate catalog: closed set or open with normalization? | Phase 7 | High |
| APScheduler SQLite job store: persistence across Docker restarts | Phase 7 | Medium |
| PPR half-life default: what values work for conversation vs research memory? | Phase 9 | Medium |

### Phase 11: Code Graph Foundation and Code PPR

**Goal:** Harden the code graph so code retrieval is generalizable across repositories, then add repo-scoped non-temporal code graph reranking without making agents depend on untrusted `CALLS` edges.

**Plans:** 1 draft plan + execution artifacts in progress

Plans:
- [ ] 11-01-PLAN.md — Repo-scoped identity, canonical parser rollout, retrieval hardening, and code-side PPR plumbing

**Deliverables:**
- Stable repo-scoped code graph identity (`repo_id`) for files, functions, and classes
- Canonical parser coverage for Python and JS/TS-like code, including the typed TS arrow-function cases that currently break mapping quality
- Generic analyzer-to-graph mapping diagnostics so repos degrade predictably instead of requiring per-codebase debugging
- Agent-safe code retrieval defaults that expose provenance and exclude `CALLS` from ranking until precision gates pass
- Multi-repo collision fixtures and rollout gates for deciding when code PPR can become default-on

**Success Criteria:**
- Agents can use code retrieval safely without depending on `CALLS`
- Repo-scoped code search works across multiple indexed repositories without path/symbol collisions
- Analyzer-backed edges are observable, confidence-gated, and degrade cleanly when unavailable
- `m26pipeline`-style repo differences are handled by generic mapping logic, not repo-specific customization
- The code search contract remains stable across MCP, REST, and unified search surfaces

**Key Risks:**
- Symbol identity mismatches between parser output and language-service output
- Monorepo/project-layout variance making analyzer coverage look repo-specific when the real problem is generic mapping
- Prematurely enabling `CALLS` in traversal before analyzer-backed precision is high enough

### Phase 12: OpenClaw Foundation

**Goal:** Turn the existing OpenClaw integration from a functional prototype into a stable operator-facing foundation by locking execution ownership, hardening the backend contract, replacing fragile local state persistence, adding plugin transport retries/tests, and enforcing minimal TypeScript CI.

**Plans:** 1 execution plan + wave registry

Plans:
- [x] 12-01-PLAN.md — OpenClaw foundation wave: registry alignment, backend hardening, product-state durability, plugin transport robustness, and CI/contract gates

**Deliverables:**
- `.planning` truth updated so OpenClaw is the active delivery track and the previous `w11-calls` registry is archived, not lost
- `am-server` accepts `AM_SERVER_API_KEYS` with backward compatibility for `AM_SERVER_API_KEY`
- error responses across auth/validation/runtime failures use one machine-readable envelope that includes the request id
- authenticated `/metrics` endpoint for foundation observability
- `ProductStateStore` uses SQLite-backed persistence behind the same method contract used by routes and CLI
- `packages/am-openclaw` retries transient backend failures, preserves non-retry behavior for 4xx responses, and has package-local TypeScript tests
- CI validates Python coverage against the current package names and enforces the OpenClaw TypeScript build/test gate

**Success Criteria:**
- OpenClaw planning state is truthful in `PROJECT.md`, `ROADMAP.md`, `STATE.md`, and `.planning/execution/*`
- rotated and missing backend API keys behave correctly under the new auth contract
- all OpenClaw error responses expose a request id and stable error code
- SQLite-backed product state preserves session/project semantics and survives repeated updates without JSON corruption risk
- `packages/am-openclaw` has passing transport/runtime/setup tests
- merge gates pass:
  - `python -m pytest tests/test_am_server.py tests/test_openclaw_shared_memory.py tests/test_product_state.py -q`
  - `python -m pytest tests/test_openclaw_contract.py -q`
  - `npm run test --workspace agentic-memory`
  - `npm run build --workspace agentic-memory`
  - `npm run typecheck --workspace agentic-memory`

**Key Risks:**
- global error-envelope changes can unintentionally break older API tests if not normalized carefully
- switching local product state from JSON to SQLite must preserve current callers and migrate existing state safely
- the plugin package already has local in-flight changes, so transport hardening must avoid trampling unrelated edits

---
*Last updated: 2026-04-11 after Phase 12 was added as the active OpenClaw foundation wave (total phases: 12)*
