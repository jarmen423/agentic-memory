# Project Research Summary

**Project:** Agentic Memory — Web Research + Conversation Memory Modules
**Domain:** Knowledge Graph & Agent Memory Systems
**Researched:** 2026-03-20
**Confidence:** MEDIUM

## Executive Summary

This project extends an existing code-focused knowledge graph tool (codememory CLI/MCP, backed by Neo4j + tree-sitter + OpenAI embeddings) with two new independently-deployable modules: Web Research Memory and Agent Conversation Memory. The dominant architectural recommendation across all four research areas is a **hub-and-spoke design with database-per-module isolation**: each module owns its own Neo4j instance and embedding model, connected through a unified MCP server that routes and aggregates agent queries. This approach is non-negotiable given that the existing code module uses OpenAI embeddings (3072-dimensional) while the new modules are likely to use Gemini embeddings (768-dimensional) — mixing them in a single vector index causes runtime failures and corrupted similarity scores.

The recommended build sequence is Foundation first (abstract ingestion pipeline, config schema extension, module registry), then Web Research Module, then Conversation Module, with advanced cross-module features deferred to later phases. Web crawling relies on Crawl4AI + Playwright; this stack is reasonable but carries LOW-to-MEDIUM confidence — both tools need version and API verification before implementation begins. Conversation memory is lower-risk because it uses infrastructure already proven in the codebase (Neo4j graph, Python async driver, MCP via FastMCP). The new Google Vertex AI / Gemini embedding dependency is the highest-risk external integration and should be validated against live API documentation before committing to it in the roadmap.

The top risks are: (1) embedding model dimension conflicts if modules share a database, (2) rate limiting cascade failures in automated web research pipelines, (3) context window pollution from unscoped conversation retrieval, (4) extraction quality degradation as crawled sites change over time, and (5) incremental update graph inconsistency if insert and update code paths diverge. All five are design-level concerns that must be addressed before writing ingestion code — retrofitting them is expensive.

## Key Findings

### Recommended Stack

The existing stack (Neo4j 5.25, OpenAI embeddings, FastMCP, Click/Typer CLI, asyncio, pytest) requires no changes. New dependencies are additive: Google Vertex AI / Gemini for multimodal embeddings on web and conversation content, Crawl4AI for intelligent web extraction, Playwright for JavaScript-heavy sites, and Brave Search API for automated research pipelines. The Docker Compose configuration needs two additional Neo4j service definitions (ports 7688 and 7689) for the web and conversation databases.

**Core technologies:**
- Google Gemini (`gemini-embedding-2-preview` via `google-cloud-aiplatform>=1.65.0`): multimodal embeddings for web/chat content — chosen over OpenAI CLIP because it co-embeds text and images in a single model. MEDIUM confidence; API name and pricing need live verification.
- Crawl4AI (`>=0.3.0`): primary web extraction — handles PDFs, JavaScript rendering, and content filtering in one package. LOW confidence; version and feature set need verification against the GitHub repo.
- Playwright (`>=1.45.0`): browser automation for dynamic content — industry standard with strong async support. HIGH confidence.
- Brave Search API: automated search for research pipelines — free tier (~2,500 queries/month), JSON responses. MEDIUM confidence; rate limits need verification.
- Neo4j (additional instances): conversation graph storage — already proven in codebase; graph model preserves conversation structure natively.

**Defer:** Vercel agent-browser (LOW confidence, Python compatibility unverified), Nvidia Nemotron embeddings (LOW confidence), local embedding models (sentence-transformers) as bulk-ingestion optimization only.

### Expected Features

**Web Research Memory — must have:**
- URL ingestion with content filtering (readability extraction, boilerplate removal)
- PDF parsing with extraction quality validation and OCR detection
- Semantic search across all ingested content (vector + graph)
- Web crawling with robots.txt compliance and loop prevention
- Metadata extraction (title, author, date, source URL)
- Content deduplication using composite keys (content hash + URL + crawl date)
- Batch ingestion with progress tracking
- Brave Search API integration for query-driven research
- Basic scheduling ("re-crawl this daily") with resource quotas and auto-pause on failure

**Conversation Memory — must have:**
- Conversation persistence with message-level granularity
- Session and conversation boundary management with explicit identifiers
- User/agent attribution (role tagging)
- Semantic search with temporal decay (recency bias)
- Scoped context retrieval (current session vs. all history)
- Incremental append (no full re-index on new messages)
- Manual import from JSON/CSV/text
- Basic filters by date, participant, conversation ID

**Should have (differentiators):**
- Automated research schedule variation (generate query permutations)
- Smart conversation summarization for long-context compression
- Cross-conversation topic linking
- Dynamic content handling via Playwright for JavaScript-heavy sites
- Source credibility signals (domain reputation, recency)
- Context injection into agent prompts (auto-prepend relevant history)
- Web archive integration (Wayback Machine for historical versions)

**Defer to v2+:**
- Unified graph query across all three modules
- Topic clustering and conversation analytics (need usage data first)
- Plugin architecture (premature generalization)
- Research question evolution (query self-refinement)
- Conflict detection across sources
- Collaborative / multi-tenant features
- Web UI dashboard

**Anti-features (do not build):**
- Full-text-only search (embeddings are required, not optional)
- Built-in LLM inference (use MCP, let users choose models)
- Custom embedding training
- Video/audio transcription (accept transcripts from external tools)

### Architecture Approach

The recommended architecture is a **Hub-and-Spoke** pattern: three independent Neo4j databases (code :7687, web :7688, conversation :7689), each with its own ingestion pipeline built on shared abstract base classes (`ContentParser`, `IngestorPipeline`, `EmbeddingService`). A unified FastMCP server acts as the hub, routing agent queries to one or more modules and aggregating results asynchronously via `asyncio.gather()`. Modules communicate only through the MCP router — no direct cross-module imports. The existing 4-pass ingestion pipeline (structure scan → entity extraction → relationship linking → embedding generation) is the shared template that all modules implement.

**Major components:**
1. MCP Server (FastMCP hub) — tool registration, module routing, result aggregation, scoped queries
2. Ingestion Framework — abstract base classes for the 4-pass pipeline, shared embedding service with retry and circuit breaker
3. Web Research Module — Crawl4AI integration, Brave Search, Gemini embeddings, scheduled crawls, :7688
4. Conversation Module — multi-format parser, incremental append, temporal decay retrieval, Gemini embeddings, :7689
5. Config Manager — per-module settings, embedding model validation (enforces same model = same database)
6. Module Registry — loads enabled modules, handles graceful unavailability

### Critical Pitfalls

1. **Embedding model mixing in a unified database** — Use separate Neo4j instances per embedding model (or separate named vector indexes if unified). Add config validation that fails fast if two modules share a database URI but specify different embedding models. This is a schema design decision; it cannot be fixed after ingestion has started.

2. **Rate limiting cascade failures** — Implement token bucket rate limiting and a circuit breaker before sending any web requests. Track per-source quotas (Brave API daily limit, per-domain crawl rate). Auto-pause schedules after N consecutive failures. Log rate-limit response headers and adjust proactively.

3. **Context window pollution in conversation retrieval** — Design user_id and conversation_id as first-class graph citizens from the start. All retrieval queries must filter by scope (session / conversation / user). Apply temporal decay scoring so stale results don't outrank recent ones. Add integration tests that verify user A cannot retrieve user B's data.

4. **Extraction quality degradation** — Validate extracted content immediately: minimum text length, boilerplate detection, coherence checks. Store `extraction_quality` and `extractor_version` on every ingested node. Implement content diffing on re-crawl to flag wildly different results. Do not store empty or garbage nodes.

5. **Incremental update graph inconsistency** — Use `MERGE` not `CREATE` for all graph operations. Share a single code path for initial ingestion and incremental updates. Add unique constraints on composite keys. Ingest the same content twice in tests and assert a single node exists.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Foundation
**Rationale:** Web and Conversation modules both depend on abstract ingestion framework, multi-database config, and module registry. Building these first prevents duplicate code and ensures embedding model isolation is enforced from day one — the hardest pitfall to retrofit.
**Delivers:** Abstract `ContentParser`, `IngestorPipeline`, `EmbeddingService` base classes; extended `.codememory/config.json` schema with per-module database URIs and embedding model settings; config validation that rejects mixed-model unified databases; module registry and MCP routing scaffold; Docker Compose with two additional Neo4j service definitions; `codememory status` command showing module health.
**Addresses:** Table-stakes shared infrastructure (CLI, config management, multi-database support, MCP server integration).
**Avoids:** Pitfall 1 (embedding mixing), Pitfall 17 (dimension mismatch), Pitfall 16 (error opacity).

### Phase 2: Web Research Module — Core Ingestion
**Rationale:** Web content ingestion is the higher-complexity of the two new modules and introduces all the external service dependencies (Crawl4AI, Playwright, Gemini, Brave). Validating the Gemini embedding API and Crawl4AI behavior here unblocks the Conversation module, which uses the same embedding service.
**Delivers:** URL ingestion with content filtering; PDF parsing with type detection and quality validation; Crawl4AI + Playwright integration; Gemini embedding service; composite deduplication keys; `web-init` and `web-ingest` CLI commands; `search_web_memory` and `ingest_url` MCP tools.
**Uses:** Crawl4AI, Playwright, Google Vertex AI / Gemini, Brave Search API, Neo4j :7688.
**Avoids:** Pitfall 2 (naive deduplication), Pitfall 4 (rate limiting), Pitfall 5 (extraction quality), Pitfall 13 (PDF inconsistency).

### Phase 3: Web Research Module — Scheduled Research
**Rationale:** Scheduling is the primary differentiator for the web module. It builds directly on Phase 2 ingestion and adds the resource-quota and circuit-breaker concerns that are safest to address after core ingestion is proven.
**Delivers:** Schedule registry (create, list, pause, delete); per-schedule resource quotas; auto-pause on N consecutive failures; schedule expiration; Brave Search query variation; `codememory web-schedule` CLI commands; `schedule_research` MCP tool.
**Avoids:** Pitfall 12 (schedule runaway), Pitfall 4 (rate limiting cascade in scheduled context), Pitfall 9 (stale content detection).

### Phase 4: Conversation Memory Module
**Rationale:** Conversation module can be built in parallel with Phase 3 but is listed sequentially here because Gemini embedding service is validated in Phase 2 and can be reused directly. Conversation schema requires the privacy and scoping design to be locked in before any data is ingested.
**Delivers:** Multi-format conversation parser (JSON, CSV, markdown); session and conversation boundary management; incremental message append with idempotent MERGE; user/session-scoped semantic search with temporal decay; `chat-init` and `chat-ingest` CLI commands; `search_conversations` and `add_message` MCP tools; manual import from historical chat logs; export to JSON/CSV.
**Avoids:** Pitfall 3 (context pollution), Pitfall 6 (incremental update inconsistency), Pitfall 7 (privacy boundary violations), Pitfall 11 (conversation boundary ambiguity).

### Phase 5: Cross-Module Integration and Hardening
**Rationale:** Cross-module queries (search code + web + conversations in a single call) are deferred until each module proves its retrieval quality independently. Operational hardening (query timeouts, index tuning, embedding bottleneck optimization) belongs here when real data volumes are available.
**Delivers:** Cross-module aggregation in MCP router (`scope=["code", "web", "chat"]`); `asyncio.gather()` parallelism across modules; batch embedding optimization; Neo4j index tuning (user_id, timestamp, content_hash); query depth limits and timeouts; migration guide; documentation.
**Avoids:** Pitfall 8 (embedding bottleneck), Pitfall 10 (query explosion), Pitfall 15 (metadata explosion).

### Phase Ordering Rationale

- Foundation must come before any module because the abstract base classes and config validation enforce the embedding isolation guarantee. Writing module code before this leads to copy-pasted pipelines that drift.
- Web Research before Conversation because it introduces and validates the higher-risk external dependencies (Gemini, Crawl4AI, Brave). Conversation module reuses the validated embedding service.
- Scheduled research after core web ingestion because it multiplies the blast radius of rate limiting and storage bugs — safer to harden on single-URL ingestion first.
- Cross-module aggregation last because retrieval quality per-module must be independently validated before combining results; mixing noisy modules compounds retrieval quality problems.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Web Research Core):** Gemini embedding API — model name `gemini-embedding-2-preview`, input format for images, dimensionality, quota limits, and Vertex AI project setup all need live API documentation verification before implementation. Crawl4AI version and JavaScript rendering reliability also need hands-on evaluation.
- **Phase 3 (Scheduled Research):** Brave Search API rate limit details (requests per day, per minute) and response schema need verification. Scheduler implementation (cron vs. apscheduler vs. custom) needs a concrete decision.
- **Phase 5 (Cross-Module):** Neo4j 5.25 multi-database federation capabilities need verification — the research notes this as a gap.

Phases with standard patterns (skip research-phase unless blocked):
- **Phase 1 (Foundation):** Abstract base classes, config schema extension, and Docker Compose multi-service patterns are well-documented. No novel integrations.
- **Phase 4 (Conversation Module):** Conversation graph schema (`User → Conversation → Message → Message`) and incremental append with MERGE are established Neo4j patterns. Gemini embedding service reused from Phase 2.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Playwright HIGH; Neo4j reuse HIGH; Gemini API MEDIUM (unverified model name/pricing); Crawl4AI LOW (unverified version/features); Brave Search MEDIUM (unverified rate limits) |
| Features | MEDIUM | Table-stakes features well-understood from ecosystem analysis; differentiator priority is opinionated but reasonable; competitive landscape based on 2025 training data |
| Architecture | MEDIUM | Hub-and-spoke pattern and 4-pass pipeline grounded in existing codebase analysis (HIGH); Neo4j 5.25 vector index behavior and multi-database federation unverified (MEDIUM-LOW) |
| Pitfalls | MEDIUM | Critical pitfalls (1-7) derived from established graph DB and RAG system patterns; some are directly validated by existing codebase CONCERNS.md; specifics of Crawl4AI and Gemini edge cases unverified |

**Overall confidence:** MEDIUM — the architectural direction is sound and grounded in the existing codebase, but two of the four major new dependencies (Gemini embeddings, Crawl4AI) have LOW confidence on version and API specifics.

### Gaps to Address

- **Gemini API verification:** Before Phase 2 begins, confirm `gemini-embedding-2-preview` model ID, output dimensionality, image input format, quota tiers, and Python SDK initialization pattern against live Vertex AI docs.
- **Crawl4AI hands-on evaluation:** Install and test against representative target sites before committing to it as primary extractor. Identify fallback (BeautifulSoup + Playwright directly) if Crawl4AI is unstable.
- **Brave Search API response schema:** Confirm response structure, result count limits, and rate limit headers before building the research pipeline around it.
- **Neo4j multi-database support:** Verify that the Docker Compose multi-service approach is supported in Neo4j 5.25 Community Edition (multi-database may require Enterprise). If Community Edition doesn't support it, the fallback is separate named indexes within a single instance with strict embedding model enforcement.
- **Scheduler library decision:** Choose between APScheduler, Celery Beat, or a simpler cron-file approach for Phase 3 scheduled research. This affects persistence model for schedule state.
- **Embedding dimensionality of Gemini:** The research assumes 768 dimensions for Gemini. If the actual model uses a different dimensionality, the separate-database design still holds but schema docs will need correction.

## Sources

### Primary (HIGH confidence)
- Existing codebase (`D:\code\agentic-memory\src\codememory`) — architecture patterns, proven Neo4j/OpenAI integration, CONCERNS.md pitfall analysis
- Playwright official documentation (playwright.dev/python) — async support, browser automation patterns

### Secondary (MEDIUM confidence)
- Training data knowledge of Neo4j 5.x vector indexes and Cypher MERGE patterns
- Training data knowledge of Brave Search API free tier and response format
- Training data knowledge of Google Vertex AI / Gemini Embeddings API
- Competitive landscape analysis: MemGPT, mem0, Zep, LangChain Memory, LlamaIndex (as of 2025)

### Tertiary (LOW confidence — requires verification)
- Crawl4AI (`github.com/unclecode/crawl4ai`) — version, PDF extraction, JS rendering reliability
- Vercel agent-browser — Python compatibility, production readiness (recommend deferring to v2)
- Nvidia Nemotron embeddings — availability, API status (recommend deferring)

---
*Research completed: 2026-03-20*
*Ready for roadmap: yes*
