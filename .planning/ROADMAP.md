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

**Goal:** Functional web research ingestion — URLs, PDFs, and web search results land in the knowledge graph and are semantically searchable.

**Deliverables:**
- Crawl4AI integration: URL ingestion, content filtering (boilerplate removal), metadata extraction (title, author, date, source URL)
- PDF parsing via Crawl4AI built-in support
- Vercel agent-browser integration as fallback for JS-rendered/dynamic content (more efficient than raw Playwright for agent workflows)
- Brave Search API integration: web search → auto-ingest top results
- Gemini multimodal embedding service (gemini-embedding-2-preview) for web content
- Neo4j web database schema + vector indexes
- Content deduplication (hash-based, update vs create logic)
- MCP tools: `ingest_url`, `search_web_memory`
- CLI commands: `web-init`, `web-ingest`, `web-search` (fully functional)

**Success Criteria:**
- `codememory web-ingest <url>` ingests a static page and makes it searchable
- PDF documents ingested and retrievable via semantic search
- JS-rendered pages fall back to agent-browser automatically, transparently
- `codememory web-search "query"` runs Brave Search and auto-ingests results
- No duplicate entries for the same URL on re-ingest (updates instead)
- Semantic search returns relevant results across all ingested web content

**Key Risks:**
- Crawl4AI version stability and JS rendering reliability
- Vercel agent-browser API surface — verify current documentation
- Brave Search API rate limits and response schema
- Gemini embedding API access (Vertex AI vs AI Studio auth)

---

## Phase 3: Web Research Scheduling

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

## Phase 4: Conversation Memory

**Goal:** Set-and-forget conversation capture — configure once, all conversations are automatically stored and semantically searchable across providers.

**Deliverables:**
- Neo4j conversation database schema: conversations, messages, participants, sessions (port 7689)
- Gemini embeddings for conversation content
- Claude Code integration: stop-session hook auto-exports and ingests conversation on session end
- Provider survey: research hook/integration mechanisms for ChatGPT, Cursor, Windsurf, and other major agent platforms
- Provider-specific integrations for surveyed platforms (wherever native hooks exist)
- Manual import fallback: JSON/JSONL conversation log ingestion
- MCP tool fallback: `add_message()` for providers with no native hook support
- Incremental message updates (append-only, no full re-index on new messages)
- User/session tracking: provider attribution, conversation boundaries, role tagging (user/assistant/system)
- MCP tools: `search_conversations`, `add_message`, `get_conversation_context`
- CLI commands: `chat-init`, `chat-ingest`, `chat-search`

**Success Criteria:**
- Claude Code sessions captured automatically with zero user action after initial setup
- At least two additional providers integrated with native hooks
- Manual import handles real-world conversation export formats
- Semantic search retrieves relevant past exchanges across all captured conversations
- `get_conversation_context` returns ranked relevant history for a given query
- Provider attribution is correct (no mixing conversations across providers)

**Key Risks:**
- Provider hook availability varies significantly — some may have no hook mechanism
- Conversation data privacy — clear scoping of what gets captured vs excluded
- Schema must be locked before first ingest (hard to migrate conversation graph later)

---

## Phase 5: Cross-Module Integration & Hardening

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
    └── Phase 2 (Web Research Core)
            └── Phase 3 (Web Research Scheduling)
    └── Phase 4 (Conversation Memory)
Phase 2 + Phase 4
    └── Phase 5 (Cross-Module Integration)
```

Phases 2 and 4 can run in parallel after Phase 1 completes.
Phase 3 depends on Phase 2 (requires working ingestion pipeline).
Phase 5 depends on all prior phases.

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
*Last updated: 2026-03-20 after phase 1 planning*
