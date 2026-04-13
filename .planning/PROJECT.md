# Agentic Memory - Universal Knowledge Graph

## What This Is

A modular knowledge graph system that gives AI agents long-term memory across any content type. Currently handles code repositories via tree-sitter parsing and Neo4j graph storage. Expanding with two new modules: Web Research Memory for automated research pipelines (web search, crawling, PDFs) and Agent Conversation Memory for persistent chat/conversation context. Each module operates independently with its own database or optionally shares a unified graph. Agents access memory via MCP tools.

## Core Value

AI agents get seamless, persistent memory that works regardless of content type or AI system - making workflows feel magical and enabling deep, cumulative research over time.

## Requirements

### Validated

<!-- Existing code memory capabilities - proven and working -->

- ✓ Code repository indexing with tree-sitter (Python, JavaScript/TypeScript) — existing
- ✓ Multi-pass ingestion pipeline (structure scan → entities → relationships → embeddings) — existing
- ✓ Neo4j graph database with vector search — existing
- ✓ MCP server exposing search, dependency, and impact analysis tools — existing
- ✓ CLI interface (init, index, watch, serve, search, deps, impact) — existing
- ✓ Incremental file watching for code changes — existing
- ✓ Git history graph ingestion (commits, provenance tracking) — existing
- ✓ OpenAI text embeddings for semantic code search — existing
- ✓ Per-repository configuration with environment variable fallbacks — existing

### Active

<!-- v1 scope - building these now -->

**Web Research Memory Module:**
- [ ] Ingest web pages via URL (manual input)
- [ ] Auto-crawl from web search results (Brave Search API)
- [ ] Parse and index PDF documents
- [ ] Semantic search across all ingested web content
- [ ] Crawl4AI integration for robust web content extraction (primary)
- [ ] Vercel agent-browser fallback for JS-rendered/dynamic content (Playwright abstraction optimized for agent workflows — more efficient than raw Playwright)
- [ ] Smart scheduled research: prompt templates with variables; LLM fills variables each run based on past research graph + conversation history; avoids repeating covered topics
- [ ] Google Gemini multimodal embeddings (gemini-embedding-2-preview)
- [ ] Separate Neo4j database for web research content (port 7688)
- [ ] MCP tools: search_web_memory, ingest_url, schedule_research, run_research_session

**Agent Conversation Memory Module:** *(Validated in Phase 4: Conversation Memory Core)*
- ✓ Ingest conversation logs and chat transcripts (manual import: JSON/JSONL) — `chat-ingest` CLI
- [ ] Fully automated set-and-forget capture: once configured, conversations are captured without user or agent intervention — requires am-proxy (Phase 5) and am-ext (Phase 6)
- [ ] Provider-specific automatic integration: Claude Code stop-session hook; survey and implement equivalent zero-friction hooks for other major providers (ChatGPT, Cursor, Windsurf, etc.)
- ✓ MCP tool (add_message) as universal fallback for providers without native hook support
- ✓ Query conversational context (retrieve relevant past exchanges) — search_conversations + get_conversation_context MCP tools
- ✓ Incremental message updates (add new messages without full re-index) — MERGE on (session_id, turn_index)
- ✓ User/session tracking (who said what, conversation boundaries, provider attribution) — Session nodes + source_agent field
- ✓ Google Gemini multimodal embeddings (gemini-embedding-2-preview) — 768d, user/assistant turns only
- ✓ Single Neo4j database, chat_embeddings vector index (768d) on :Memory:Conversation nodes
- ✓ MCP tools: search_conversations, add_message, get_conversation_context
- ✓ REST API: POST /ingest/conversation, GET /search/conversations (Bearer auth, passive connector target)

**Shared Infrastructure:**
- [ ] Modular architecture supporting independent or unified databases
- [ ] Configurable embedding model selection: Gemini, OpenAI, Nvidia Nemotron
- [ ] Config validation: warn if mixing embedding models in unified database
- [ ] CLI commands: web-init, web-ingest, web-search, chat-init, chat-ingest
- [ ] Documentation for module setup and configuration

**OpenClaw Testing + Dashboard Wave (`w13-openclaw-dashboard-and-testing`) — Completed in Phase 13:**
- [x] Replace the static desktop shell under `desktop_shell/static/` with a workspace-backed React dashboard in `packages/am-dashboard/`
- [x] Add authenticated dashboard read APIs for OpenClaw metrics, sessions, search quality, and workspace views
- [x] Add OpenClaw operational verification harnesses: E2E, load, chaos, and dashboard shell coverage
- [x] Wire `am-dashboard` into the npm workspace and CI build/test/typecheck gates
- [x] Keep packaging, marketplace, hosted auth, and GTM rollout deferred until this wave is green

**OpenClaw Scaling + Packaging Wave (`w14-openclaw-scaling-and-packaging`) — Completed in Phase 14:**
- [x] Scale the OpenClaw backend for the GTM plan's 10-agent target with load-path observability, cache hardening, MCP surface boundary clarity, and fail-fast runtime defaults
- [x] Package `packages/am-openclaw` for distribution by removing private-only metadata, locking release/package fields, and validating installable artifacts
- [x] Add production deployment and release artifacts for `am-server`, including Docker/release workflow outputs aligned to the GTM plan
- [x] Close the CI/release integration gate so package validation no longer depends on the unresolved public package name

**OpenClaw Docs + Private Beta Wave (`w15-openclaw-docs-and-private-beta`) — Completed in Phase 15:**
- [x] Finalize the public install/setup story around the locked install path `openclaw plugin install agentic-memory-openclaw`
- [x] Commit the OpenAPI contract for the OpenClaw-facing backend surface and keep it aligned with the actual app routes
- [x] Prepare marketplace listing artifacts and publish metadata for private beta distribution
- [x] Write the user, operator, and support docs needed to onboard the first 5 private beta partners
- [x] Keep public beta, hosted multi-tenant auth, SSO, and GA launch collateral deferred until the next follow-on phase

**OpenClaw Whole-Stack Onboarding Wave (`w16-openclaw-whole-stack-onboarding`) — Completed in Phase 16:**
- [x] Replace implicit local-service assumptions with an explicit, validated whole-stack bootstrap path
- [x] Add whole-stack doctor/preflight surfaces for the plugin, backend, Neo4j, and optional temporal services
- [x] Remove hardcoded SpacetimeDB port/alias assumptions from scripts and docs so Grafana, SpacetimeDB, and other local services can coexist cleanly
- [x] Collapse the current install/docs/runbook story into one supported onboarding path that matches what the code actually validates
- [x] Keep public beta, hosted multi-tenant auth, SSO, and GA launch collateral deferred until the onboarding path is credible in practice

### Out of Scope

- Web UI dashboard — Nice-to-have, not v1 priority
- IDE extensions (VS Code, Cursor) — Future, after proven via MCP
- Desktop Electron app — Future, CLI + MCP proven first
- Real-time collaboration features — Single-user focus for v1
- Advanced conversation analytics (sentiment, topic modeling) — Basic retrieval first
- Video/audio transcription — Rely on external tools, ingest transcripts only
- Broad universal adapter expansion beyond the current shipped integrations — post-v1. The targeted OpenClaw docs + private beta wave is active now.
- Simple cron scheduling (repeat same query) — Replaced by smart scheduled research with LLM-driven variable substitution

## Context

**Existing system:**
- Proven architecture with Neo4j + MCP + CLI for code memory
- Multi-pass ingestion pipeline adaptable to new content types
- Production telemetry system tracking tool usage for research

**User's immediate use case:**
- Research pipeline for deep topic exploration
- Daily automated research on evolving questions
- Build cumulative knowledge graph on specific domains

**Long-term vision:**
- One-click install for any AI workflow
- Universal adapter layer for OpenClaw, Claude Code, Codex, etc.
- Seamless integration regardless of which AI system users choose

**Technical foundation:**
- Tree-sitter works for code; Crawl4AI + agent-browser handle web/documents
- OpenAI embeddings proven for code; Google Gemini for multimodal content
- Separate databases by default prevents embedding model conflicts

## Constraints

- **Embedding consistency**: If unified database, all modules must use same embedding model
- **Existing code memory**: Must maintain full functionality of current code ingestion
- **Modular independence**: Each module works standalone (no hard cross-dependencies)
- **Tech stack**: Python 3.10+, Neo4j 5.18+, existing CLI/MCP patterns
- **API availability**: Requires Google Vertex AI access, Brave Search API key
- **One-click install**: Must be pip/CLI installable without complex setup

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Separate databases by default | Prevents embedding model conflicts (OpenAI 3072d vs Gemini 768d incompatible in same vector index) | ✓ Confirmed |
| Google Gemini embeddings for web/chat | Multimodal support (text, images, future video/audio); OpenAI stays for code module | ✓ Confirmed |
| Nvidia Nemotron in v1 | NIM API is OpenAI-compatible — ~20 line addition once abstraction layer exists; near-zero cost | ✓ Confirmed |
| Crawl4AI primary + agent-browser fallback | Crawl4AI handles static pages; Vercel agent-browser for JS-rendered dynamic content (more efficient than raw Playwright for agent workflows) | ✓ Confirmed |
| Brave Search API as default | Free tier available, good results, configurable for alternatives | ✓ Confirmed |
| Smart scheduled research (not simple cron) | Prompt templates with LLM-driven variable substitution; context-aware (no topic repetition); steered by past research + conversation history | ✓ Confirmed |
| Set-and-forget automated capture | UX goal: configure once, captures forever with zero friction; provider-native hooks where available (Claude Code confirmed); MCP tool as fallback for unsupported providers | ✓ Confirmed |
| Modular architecture | Each module independently usable, scales to future content types | ✓ Confirmed |

---
*Last updated: 2026-04-13 after Phase 16 (OpenClaw whole-stack onboarding) completed and the execution snapshot was archived*
