# Agentic Memory — v1 Roadmap

**Project:** Modular Knowledge Graph (Code + Web Research + Conversation Memory)
**Created:** 2026-03-20
**Status:** Planning

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

## Phase 3: Web Research Scheduling *(Deferred — post-v1)*

**Status:** Deferred. Classified as a research agent extension, not core agentic memory infrastructure. Will be revisited after Phase 7 (Cross-Module Integration). Current phase advances to Phase 4.

**Goal:** Smart automated research pipeline — set a research template, system runs it on a schedule with LLM-driven variation, building cumulative knowledge over time.

**Deliverables:**
- Prompt template system with variable placeholders (e.g. `{topic}`, `{angle}`, `{timeframe}`)
- LLM-driven variable substitution each run: reads existing research graph + conversation history to select variable values that explore new angles, avoids repeating covered topics
- Topic coverage tracker: graph-based record of what has been researched, used to steer future runs
- Schedule management: cron-based execution, configurable frequency (daily, weekly, custom)
- Research session orchestrator: template → variable fill → search → ingest → update coverage
- Circuit breakers: rate limit handling, cost caps, graceful degradation on API failures
- MCP tools: `schedule_research`, `run_research_session`, `list_research_schedules`
- CLI commands: `web-schedule`, `web-run-research`

**Success Criteria:**
- User defines a research template once; system runs autonomously on schedule
- Each run produces meaningfully different queries based on what's already in the graph
- Coverage tracker correctly identifies and avoids already-researched topics
- Failed runs (API errors, rate limits) are logged and retried gracefully
- Research output is cumulative — graph grows richer over time without duplication

**Key Risks:**
- LLM variable substitution quality — prompt engineering for consistent, useful variation
- Cost management for automated LLM calls on schedule
- Scheduler library choice (APScheduler vs system cron vs custom)

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

## Phase 7: Cross-Module Integration & Hardening

**Goal:** Unified agent interface across all three modules, Nvidia Nemotron embedding support, production hardening.

**Deliverables:**
- Unified MCP router: single server aggregates code + web + conversation results
- Cross-module search: `search_all_memory` queries all databases, merges and ranks results
- Nvidia Nemotron embedding service (NIM API, OpenAI-compatible — ~20 lines via existing abstraction)
- Structured logging and observability across all modules
- Error recovery and retry logic standardized across modules
- Documentation: setup guides, MCP tool reference, provider integration guides
- End-to-end integration tests across all three modules

**Success Criteria:**
- Single MCP server exposes all tools from all three modules
- `search_all_memory` returns coherent ranked results across code, web, and conversation content
- Nvidia Nemotron can be selected as embedding model via config
- All three modules pass integration tests end-to-end
- Setup guide enables a new user to have all three modules running in under 30 minutes

**Key Risks:**
- Cross-module result ranking/merging quality
- MCP server routing complexity with many tools
- Neo4j Community Edition limits on concurrent connections across 3 databases

---

## Phase Dependencies

```
Phase 1 (Foundation)
    └── Phase 2 (Web Research Core + REST API foundation)
            ├── Phase 3 (Web Research Scheduling)
            └── Phase 4 (Conversation Memory Core)
                    ├── Phase 5 (am-proxy)
                    └── Phase 6 (am-ext)
Phase 2 + Phase 4
    └── Phase 7 (Cross-Module Integration & Hardening)
```

Phases 3 and 4 can run in parallel after Phase 2 completes.
Phases 5 and 6 can run in parallel after Phase 4 completes.
Phase 7 depends on all prior phases.

---

## Open Research Questions (Pre-Implementation)

| Question | Blocks | Priority |
|----------|--------|----------|
| Gemini embedding API: model name, dimensionality, auth (Vertex AI vs AI Studio) | Phase 1, 2 | Critical |
| Neo4j Community Edition: multi-database support on single instance | Phase 1 | Critical |
| Vercel agent-browser: current API surface, install method, JS rendering reliability | Phase 2 | High |
| Crawl4AI: current stable version, PDF support status | Phase 2 | High |
| Brave Search: rate limits, response schema, free tier constraints | Phase 2, 3 | High |
| Cursor/Windsurf/ChatGPT: available hooks or integration points for conversation capture | Phase 4 | Medium |
| APScheduler vs system cron vs custom: best fit for research scheduling | Phase 3 | Medium |

---
*Last updated: 2026-03-21 after passive ingestion spec integration (am-proxy Phase 5, am-ext Phase 6; former Phase 5 renumbered to Phase 7; total phases: 7)*
