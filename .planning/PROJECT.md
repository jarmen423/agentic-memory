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
- [ ] Scheduled automated research (daily/periodic variations on research questions)
- [ ] Crawl4AI integration for robust web content extraction
- [ ] Vercel agent-browser integration for interactive/dynamic content
- [ ] Google Gemini multimodal embeddings (gemini-embedding-2-preview)
- [ ] Separate Neo4j database for web research content
- [ ] MCP tools: search_web_memory, ingest_url, schedule_research

**Agent Conversation Memory Module:**
- [ ] Ingest conversation logs and chat transcripts
- [ ] Auto-capture mode (live conversation ingestion)
- [ ] Manual import option for historical conversations
- [ ] Query conversational context (retrieve relevant past exchanges)
- [ ] Incremental message updates (add new messages without full re-index)
- [ ] User/session tracking (who said what, conversation boundaries)
- [ ] Google Gemini multimodal embeddings (gemini-embedding-2-preview)
- [ ] Separate Neo4j database for conversation content
- [ ] MCP tools: search_conversations, add_message, get_conversation_context

**Shared Infrastructure:**
- [ ] Modular architecture supporting independent or unified databases
- [ ] Configurable embedding model selection (Gemini vs OpenAI vs Nvidia Nemotron)
- [ ] Config validation: warn if mixing embedding models in unified database
- [ ] CLI commands: web-init, web-ingest, web-search, chat-init, chat-ingest
- [ ] Documentation for module setup and configuration

### Out of Scope

- Web UI dashboard — Nice-to-have, not v1 priority
- IDE extensions (VS Code, Cursor) — Future, after proven via MCP
- Desktop Electron app — Future, CLI + MCP proven first
- Real-time collaboration features — Single-user focus for v1
- Advanced conversation analytics (sentiment, topic modeling) — Basic retrieval first
- Video/audio transcription — Rely on external tools, ingest transcripts only
- OpenClaw/Codex-specific adapters — Universal adapter layer is post-v1

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
| Separate databases by default | Prevents embedding model conflicts, cleaner separation of concerns | — Pending |
| Google Gemini embeddings for non-code | Multimodal support (text, images, future video/audio) | — Pending |
| Brave Search API as default | Free tier available, good results, configurable for alternatives | — Pending |
| Vercel agent-browser over raw Playwright | Agent-friendly abstraction, better for AI-driven workflows | — Pending |
| Crawl4AI for web ingestion | PDF support built-in, robust extraction, actively maintained | — Pending |
| Modular architecture | Each module independently usable, scales to future content types | — Pending |

---
*Last updated: 2026-03-20 after initialization*
