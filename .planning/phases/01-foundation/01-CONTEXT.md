# Phase 1: Foundation - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish the shared infrastructure all memory modules build on: abstract ingestion pipeline, embedding service abstraction, entity extraction service, source registry, graph schema with Memory/Entity dual-layer model, config validation, Docker setup, and CLI scaffolding. Existing `KnowledgeGraphBuilder` adopts the new base class via subclassing.

</domain>

<decisions>
## Implementation Decisions

### Package Structure
- New modules live as submodules inside `codememory/`: `codememory/web/`, `codememory/chat/`
- Shared infrastructure lives in `codememory/core/` submodule
- Single pip package (`agentic-memory`) — no separate installable packages

### Base Class Strategy
- `BaseIngestionPipeline` base class in `codememory/core/`
- Parsing/chunking is NOT shared — each module implements its own (code ASTs, web pages, and conversation JSON are fundamentally different)
- Embedding is NOT shared — each module independently instantiates with the right model, but the embedding service abstraction handles API differences (Gemini vs OpenAI vs Nemotron)
- Graph writing patterns ARE shared — `BaseIngestionPipeline` handles node creation with proper labels, entity extraction, entity relationship wiring, and metadata population
- `KnowledgeGraphBuilder` adopts via subclassing: `DOMAIN_LABEL = "Code"`, `super().__init__()`, internal parsing logic unchanged

### Graph Schema: Memory/Entity Dual Layer
- **Entity Layer** — first-class `:Entity` nodes: `:Entity:Project`, `:Entity:Person`, `:Entity:Business`, `:Entity:Technology`, `:Entity:Concept`
- **Memory Layer** — `:Memory:{Domain}:{Source}` multi-label scheme: `:Memory:Code:Chunk`, `:Memory:Conversation:Perplexity`, `:Memory:Research:Finding`
- **Relationships** — Memory nodes connect to Entity nodes via `:ABOUT`, `:MENTIONS`, `:BELONGS_TO`
- **Entity types** — fixed core taxonomy (`project`, `person`, `business`, `technology`, `concept`) extensible via config
- **Universal cross-agent query**: `MATCH (m:Memory)-[:ABOUT]->(:Entity:Project {name: "X"})` returns all memory from any agent/source

### First-Class Node Metadata (Required on every Memory node)
- `source_key` — ingestor ID (e.g., `web_crawl4ai`, `chat_claude_code`, `code_treesitter`)
- `session_id` — session that produced this node
- `source_type` — content category (code, web, conversation)
- `ingested_at` — datetime of ingestion
- `ingestion_mode` — `active` (agent explicitly triggered) | `passive` (hook, watcher, schedule)
- `embedding_model` — which model produced the embedding (enables future re-embedding migrations)
- `project_id` — explicit project context (first-class field, not inferred)
- `entities` — denormalized array of entity names (cache of relationship data for speed)
- `entity_types` — denormalized array of entity types (parallel to entities array)
- Extensible sub-categories supported (e.g., `deep_research`, etc.)

### Denormalized Entity Metadata + Enriched Embeddings
- Entities stored as BOTH relationships (source of truth for traversal) AND property arrays on Memory nodes (cache for speed)
- **Entity-enriched embedding text**: prepend entity context before generating embeddings
  ```python
  def build_embed_text(chunk_text: str, entities: list[dict]) -> str:
      entity_str = ", ".join(f"{e['name']} ({e['type']})" for e in entities)
      return f"Context: {entity_str}\n\n{chunk_text}"
  ```
- This makes semantically related chunks cluster in vector space even when wording differs

### Auto Entity Extraction at Ingest Time
- One LLM call per document (not per chunk) to extract entities
- LLM requirements: extremely high structured output reliability (must return valid JSON every call), low latency, low cost, high throughput
- Target providers: Groq or Cerebras (OpenAI-compatible API via `base_url` override) — fast inference on open-source models with JSON mode
- Extraction prompt constrained to allowed entity types list for consistency
- Configurable via `extraction_llm` config entry (separate from embedding model config)

### Source Registry
- Dict mapping ingestion source -> label tier: `source_registry["web_crawl4ai"]` -> `["Memory", "Research", "Crawl4AI"]`
- Each ingestion adapter registers its source key
- Router handles label construction automatically from the registry
- Registration via explicit imports in `__init__.py` + auto-registration at import time
- `node_labels()` method on base class reads from the registry

### Database Topology — REVISED from Roadmap
- **Single Neo4j database** (NOT three separate databases — 3-port infrastructure removed)
- Multiple vector indexes on different label sets handle embedding dimension differences:
  - `code_embeddings` index on `:Memory:Code` nodes (3072d, OpenAI)
  - `web_embeddings` index on `:Memory:Research` nodes (768d, Gemini)
  - `chat_embeddings` index on `:Memory:Conversation` nodes (768d, Gemini)
- Entity layer naturally shared — no replication, no cross-database queries needed
- Connection manager supports both local Docker and remote (Neo4j Aura cloud) via URI config

### Backward Compatibility
- Legacy code project branched separately — this is a fresh project, no migration concerns
- Existing `KnowledgeGraphBuilder` subclasses `BaseIngestionPipeline` with `DOMAIN_LABEL = "Code"`
- No migration scripts needed — users re-index from source

### Config UX
- Defer detailed config UX decisions — not blocking for Phase 1
- Config must support: per-module embedding model selection, extraction LLM config, entity type extensions, Neo4j URI (local or remote)
- Priority hierarchy preserved: env vars > config file > defaults

### Claude's Discretion
- Exact config file schema/structure (as long as it supports the requirements above)
- Abstract base class method signatures (as long as entity extraction flow and metadata fields are implemented)
- Docker Compose service configuration details
- CLI scaffolding command structure (as long as web-init, web-ingest, web-search, chat-init, chat-ingest are stubbed)
- Unit test framework and structure

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing codebase (adopt/extend these patterns)
- `src/codememory/config.py` — Config class, DEFAULT_CONFIG, env var priority hierarchy, deep merge pattern
- `src/codememory/ingestion/graph.py` — KnowledgeGraphBuilder (will subclass BaseIngestionPipeline), CircuitBreaker pattern, retry decorator, 4-pass pipeline
- `src/codememory/ingestion/parser.py` — CodeParser using tree-sitter (domain-specific parsing — NOT shared)
- `src/codememory/server/app.py` — FastMCP server, tool registration pattern
- `src/codememory/server/tools.py` — Toolkit class, rate limiting, telemetry decorators

### Project planning
- `.planning/PROJECT.md` — Full requirements, constraints, key decisions
- `.planning/ROADMAP.md` — Phase plan (NOTE: database topology section is OUTDATED — single DB replaces 3-port design)
- `.planning/research/ARCHITECTURE.md` — Hub-and-spoke pattern (NOTE: topology revised per this context)
- `.planning/research/PITFALLS.md` — 18 pitfalls with prevention strategies
- `.planning/codebase/CONVENTIONS.md` — Coding conventions (Black, Ruff, MyPy strict, Google docstrings)
- `.planning/codebase/STRUCTURE.md` — Directory layout, where to add new code

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CircuitBreaker` class in `graph.py` — move to `codememory/core/` for shared use across modules
- `retry_on_openai_error` decorator — generalize to `retry_on_api_error` for any provider
- `Config` class with deep merge pattern — extend with module-specific sections
- `@rate_limit`, `@log_tool_call` decorators — reusable for new MCP tools
- `TelemetryStore` — can track entity extraction and embedding operations

### Established Patterns
- 4-pass pipeline (structure scan -> entities -> relationships -> embeddings) — code module keeps this internally, not enforced on other modules
- Environment variable priority: env vars > config file > defaults
- Neo4j session context managers: `with self.driver.session() as session:`
- Module-level logging: `logger = logging.getLogger(__name__)`

### Integration Points
- `cli.py` main() function — add new subparsers for web-* and chat-* commands
- `server/app.py` — add new MCP tools for web and chat modules
- `config.py` DEFAULT_CONFIG — extend with web, chat, extraction_llm, entity_types sections
- `docker-compose.yml` — simplify to single Neo4j instance (remove 3-port setup)

</code_context>

<specifics>
## Specific Ideas

- Entity-enriched embeddings: prepend `"Context: {entity_names}\n\n"` before chunk text to improve vector clustering
- Groq or Cerebras for entity extraction — OpenAI-compatible API, sub-100ms latency, JSON mode for structured output reliability
- Nvidia Nemotron embedding support uses same `base_url` override pattern as Groq/Cerebras — OpenAI SDK with different endpoint
- The ingestion flow end-to-end: acquire -> chunk -> extract_entities (one LLM call per doc) -> for each chunk: build_embed_text -> embed -> write_node (with metadata) -> upsert_entity_nodes -> write_relationships

</specifics>

<deferred>
## Deferred Ideas

- Detailed config UX (config file format, interactive init prompts) — decide when building actual module inits
- Web UI for entity browsing — out of scope for v1
- Entity deduplication/merging (e.g., "React" vs "ReactJS" vs "React.js") — future improvement, basic UPSERT by name is sufficient for v1
- Entity relationship types between entities (e.g., `:Entity:Person -[:WORKS_AT]-> :Entity:Business`) — future capability

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-03-20*
