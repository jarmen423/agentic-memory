# Phase 2: Web Research Core — Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the functional web research ingestion pipeline. Agents call `memory_ingest_research` MCP tool to persist research output (reports, findings) to Neo4j as `:Memory:Research` nodes. `web-ingest <url>` provides explicit user-directed source preservation. Vector search over Research nodes via `search_web_memory` MCP tool and CLI. Brave Search API exposed as an agent tool for live web search during research sessions — it does NOT auto-ingest results.

</domain>

<decisions>
## Implementation Decisions

### Mental Model Correction: Output-Centric Ingestion

**The research pipeline does NOT bulk-ingest source pages.** Source pages are ephemeral context in the agent's context window. What goes into Neo4j is the synthesized output the agent produced:

- `:Memory:Research:Report` — the full synthesized report (parent node, metadata only)
- `:Memory:Research:Chunk` — embeddable text slices of a Report (children, carry text + embedding)
- `:Memory:Research:Finding` — discrete atomic facts extracted from sources (single nodes, embedded)
- `:Entity:Source` — deduplicated source URL nodes (one node per unique URL)
- `:CITES` — relationship from Finding to Entity:Source, carries citation metadata as properties

`web-ingest <url>` is a separate, intentional path for user-directed source preservation. It is NOT triggered automatically by Brave Search results.

---

### Graph Schema: Research Layer

```
// Report parent — metadata only, no text, no embedding
(:Memory:Research:Report {
    session_id, project_id, source_agent,
    research_question, ingested_at, ingestion_mode,
    source_key: "deep_research_agent",
    source_type: "web",
    embedding_model: null,    ← no embedding on parent
    entities, entity_types    ← denormalized from findings
})

// Chunk children — text + embedding, what vector search hits
(:Memory:Research:Chunk {
    text, embedding,
    chunk_index, chunk_total,
    session_id, project_id, source_agent,
    ingested_at, embedding_model: "gemini-embedding-2-preview",
    source_key: "deep_research_agent",
    source_type: "web"
})

// Relationships
(:Memory:Research:Report)-[:HAS_CHUNK {order: chunk_index}]->(:Memory:Research:Chunk)
(:Memory:Research:Report)-[:ABOUT]->(:Entity:Project)
(:Memory:Research:Chunk)-[:PART_OF]->(:Memory:Research:Report)

// Finding — atomic fact, single node, embedded
(:Memory:Research:Finding {
    text, embedding,
    content_hash,              ← dedup key
    confidence,                ← "high" | "medium" | "low"
    session_id, project_id, source_agent,
    research_question,
    ingested_at, ingestion_mode,
    embedding_model: "gemini-embedding-2-preview",
    source_key: "deep_research_agent",
    source_type: "web",
    entities, entity_types
})

// Citation as relationship property, not a node
(:Memory:Research:Finding)-[:CITES {
    url, title, snippet,
    accessed_at, source_agent
}]->(:Entity:Source {url})

// Cross-layer entity wiring
(:Memory:Research:Finding)-[:ABOUT]->(:Entity:Project)
(:Memory:Research:Finding)-[:MENTIONS]->(:Entity:*)
```

**Source registry:** `register_source("deep_research_agent", ["Memory", "Research", "Finding"])` and `register_source("web_crawl4ai", ["Memory", "Research", "Chunk"])` at module import time.

---

### MCP Write Path (Primary)

The primary ingestion path for Phase 2 is MCP tool invocation by agents:

```python
@mcp.tool(
    description="""
    ALWAYS call this tool when you complete any research task,
    analysis, or produce a substantive report. This saves your
    work to persistent memory so it's available in future sessions.
    Call this BEFORE presenting results to the user.
    """
)
async def memory_ingest_research(
    type: str,                          # "report" | "finding"
    content: str,                       # text to store
    project_id: str,                    # entity anchor
    session_id: str,                    # agent session
    source_agent: str,                  # "claude" | "perplexity" | "chatgpt" | "custom"
    research_question: str | None,      # original query that prompted this
    findings: list[dict] | None,        # [{text, confidence, citations: [{url, title, snippet}]}]
    citations: list[dict] | None,       # top-level citations for reports
) -> dict: ...
```

**Tool description quality is critical.** "ALWAYS call this tool..." language drives reliable invocation. Make it a config option (default: "always", override: "on-demand") for users who prefer manual control.

**`ingestion_mode` mapping:**
- `"active"` — agent called MCP tool intentionally
- `"passive"` — parsed from prompt-structured output (future Path 2)
- `"manual"` — user ran `codememory web-ingest <url>` explicitly

---

### Ingest Routing in ResearchIngestionPipeline

```python
async def ingest(self, source: dict) -> dict:
    content_type = source["type"]

    if content_type == "report":
        # 1. Create Report parent node (no embedding)
        # 2. Chunk content via self.chunk()
        # 3. Extract entities (one LLM call on full content)
        # 4. For each chunk: build_embed_text → embed → write Chunk node
        # 5. Wire :HAS_CHUNK relationships
        # 6. Write :ABOUT/:MENTIONS entity relationships

    elif content_type == "finding":
        # 1. Single node — no chunking
        # 2. Extract entities
        # 3. embed(build_embed_text(text, entities))
        # 4. write_memory_node() as :Memory:Research:Finding
        # 5. For each citation: MERGE :Entity:Source, write :CITES relationship
```

**Citations do NOT get embeddings.** They are reference nodes, not searchable content. You find them by traversing from a Finding, not by vector search.

---

### Chunking Strategy

All input normalized to markdown first. Chunking implemented in `ResearchIngestionPipeline.chunk()` — not shared infrastructure.

```python
class RawContent:
    text: str
    format: str   # "markdown" | "html" | "pdf" | "text"
    path: str | None  # required for PDF

def _to_markdown(self, content: RawContent) -> str:
    if content.format == "markdown": return content.text       # crawl4ai — pass through
    elif content.format == "html":   return markdownify(content.text)
    elif content.format == "pdf":    return pymupdf4llm.to_markdown(content.path)
    else:                            return content.text

def _chunk_markdown(self, markdown: str) -> list[Chunk]:
    # Primary: split on ## / ### headers
    header_chunks = self._split_on_headers(markdown)
    result = []
    for chunk in header_chunks:
        if token_count(chunk.text) <= 512:
            result.append(chunk)
        else:
            # Recursive fixed-size fallback
            sub_chunks = self._recursive_split(chunk.text, max_tokens=512, overlap_tokens=50)
            result.extend(sub_chunks)
    return result
```

- **Max chunk size:** 512 tokens (well within Gemini's 8192 limit; sized for precision retrieval)
- **Overlap:** 50 tokens (~10%) on recursive fallback splits only
- **PDF:** `pymupdf4llm` for page-aware markdown extraction
- **HTML:** `markdownify` library

---

### Deduplication

| Node | Dedup key | On match |
|------|-----------|----------|
| `:Memory:Research:Report` | `(project_id, session_id)` | MERGE — update `ingested_at`, overwrite properties |
| `:Memory:Research:Chunk` | `(session_id, chunk_index)` | MERGE — update text, re-embed |
| `:Memory:Research:Finding` | `content_hash` (global) | MERGE — update `project_id`, `entities`, `citations` |
| `:Entity:Source` | `url` | MERGE — update `title` if changed |
| `:CITES` relationship | `(finding_id, source_url)` | MERGE — update `snippet`, `accessed_at` |

---

### Stored Content & Metadata

**Report parent node:** metadata only — no `text`, no `embedding`.

**Chunk nodes:** `text` (the slice) + `embedding` + standard Phase 1 fields + `chunk_index`, `chunk_total`.

**Finding nodes:** `text` + `embedding` + standard Phase 1 fields + `confidence` + `research_question`.

**Extra fields on all Research nodes beyond Phase 1 standard:**
- `source_agent` — `"claude"` | `"perplexity"` | `"chatgpt"` | `"custom"`
- `research_question` — original query that prompted this output
- `confidence` — `"high"` | `"medium"` | `"low"` (Findings only)
- `chunk_index` + `chunk_total` — on Chunk nodes only

---

### Brave Search Integration

Brave Search is an **agent tool for live search during research sessions**, not an ingestion trigger.

```python
@mcp.tool(description="Search the web for current information. Returns top N results with title, URL, and snippet.")
async def brave_search(query: str, count: int = 10) -> list[dict]: ...
```

Results are returned to the agent's context window. The agent decides what to do with them (read further, summarize, call `memory_ingest_research`). No auto-ingestion.

**`codememory web-search` CLI:** deferred — decision tabled.

---

### Manual Source Ingestion (`web-ingest`)

`codememory web-ingest <url>` is the explicit, user-directed path for preserving a specific source page in full:

1. Crawl4AI fetches page → markdown
2. JS-rendered fallback: Crawl4AI async with `js_code` → if content quality check fails, raise error (Vercel agent-browser deferred)
3. Full chunking pipeline (same as Report chunks)
4. Source registered as `:Memory:Research:Chunk` nodes with `source_key: "web_crawl4ai"`
5. Parent `:Memory:Research:Report`-equivalent metadata node (or standalone chunks with `source_url` property)

---

### MCP Tools for Phase 2

| Tool | Description |
|------|-------------|
| `memory_ingest_research` | Primary write path — agent persists report or findings |
| `search_web_memory` | Vector search over Research nodes (Chunks + Findings) |
| `brave_search` | Live web search via Brave API — returns results to agent, no auto-ingest |

`search_web_memory` follows existing `search_codebase` pattern: returns title, source_url, text snippet, similarity score, entities.

---

### Claude's Discretion

- Exact Crawl4AI API call structure and async handling
- `markdownify` vs `html2text` library choice (prefer `markdownify`)
- `pymupdf4llm` API details
- Brave Search HTTP client implementation (requests vs httpx)
- MCP tool response schema structure (as long as it includes url, title, snippet, score)
- Unit test structure and fixtures

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 outputs (extend these)
- `src/codememory/core/base.py` — `BaseIngestionPipeline` ABC to subclass
- `src/codememory/core/embedding.py` — `EmbeddingService` with `gemini-embedding-2-preview` provider
- `src/codememory/core/entity_extraction.py` — `EntityExtractionService`, `build_embed_text`
- `src/codememory/core/graph_writer.py` — `GraphWriter.write_memory_node()`, `upsert_entity()`, `write_relationship()`
- `src/codememory/core/connection.py` — `ConnectionManager` with `research_embeddings` vector index
- `src/codememory/core/registry.py` — `register_source()`, `SOURCE_REGISTRY`
- `src/codememory/web/__init__.py` — stub, implement here
- `src/codememory/cli.py` — `web-ingest`, `web-search` stub commands to implement

### Existing patterns
- `src/codememory/server/app.py` — MCP server, `@mcp.tool()` pattern
- `src/codememory/server/tools.py` — `@rate_limit`, `@log_tool_call`, `validate_tool_output()`
- `src/codememory/ingestion/graph.py` — `KnowledgeGraphBuilder` as reference for pipeline structure

### Planning docs
- `.planning/phases/01-foundation/01-CONTEXT.md` — all Phase 1 decisions (graph schema, metadata fields, entity extraction)
- `.planning/ROADMAP.md` — phase boundaries
- `.planning/codebase/CONVENTIONS.md` — Black, Ruff, MyPy strict, Google docstrings
- `.planning/research/PITFALLS.md` — 18 pitfalls with prevention strategies

</canonical_refs>

<code_context>
## Existing Code Insights

### Phase 1 Assets Ready to Use
- `ConnectionManager` already creates `research_embeddings` vector index (768d, Gemini) on `:Memory:Research` nodes
- `EmbeddingService.PROVIDERS["gemini"]` configured for `gemini-embedding-2-preview`, 768d, `output_dimensionality` explicit
- `build_embed_text(chunk_text, entities)` prepends entity context before embedding
- `GraphWriter.write_memory_node(labels, properties, namespace)` handles MERGE on `(source_key, content_hash)`
- `GraphWriter.upsert_entity(name, entity_type)` handles MERGE on `(name, type)`
- `GraphWriter.write_relationship(from_id, to_id, rel_type, props)` for :ABOUT, :MENTIONS, :CITES, :HAS_CHUNK
- `SOURCE_REGISTRY` ready for `register_source("deep_research_agent", [...])` at module import

### MCP Server Pattern
```python
# server/app.py
mcp = FastMCP("agentic-memory")

# server/tools.py
class Toolkit:
    @mcp.tool()
    @rate_limit(calls_per_minute=60)
    @log_tool_call
    async def search_codebase(self, query: str, ...) -> str:
        result = await self._search(query)
        return validate_tool_output(result)
```

### New Packages Required
- `crawl4ai` — web crawling and markdown extraction
- `markdownify` — HTML → markdown conversion
- `pymupdf4llm` — PDF → markdown (page-aware)
- `httpx` — async HTTP for Brave Search API

</code_context>

<specifics>
## Specific Implementation Notes

- **Gemini multimodal note:** `gemini-embedding-2-preview` can natively embed images — pymupdf4llm extracts images with surrounding context from PDFs. Multimodal embedding path available for free given model choice. Deferred to future phase.
- **Token counting:** use `len(text.split()) * 1.3` as fast approximation, or tiktoken if already in deps. Exact token count not critical at 512 ceiling with 8192 model limit.
- **Brave Search rate limits:** free tier ~2,500 queries/month. Rate limit the `brave_search` MCP tool accordingly.
- **JS rendering fallback:** Crawl4AI async with `wait_for` selectors as first attempt. Hard error (not silent fallback) if content quality check fails. Vercel agent-browser deferred.
- **`web-search` CLI:** decision tabled — implement as stub that prints "not yet implemented".
- **REST API architecture:** noted as strategic direction (REST core + thin MCP connector). Deferred — Phase 2 builds MCP-first, REST refactor is its own future phase.
- **Interactive connector cards (Anthropic):** noted as high-value future integration. Deferred.

</specifics>

<deferred>
## Deferred Ideas

- **Gemini multimodal (image) embeddings from PDFs** — available for free given model choice, defer to later phase
- **Prompt-instructed ingestion (Path 2)** — parsing `<memory_ingest>` blocks from agent conversation exports — defer to Phase 4 (chat module)
- **OAuth 2.1 / ChatGPT App connector** — legitimate sanctioned path for ChatGPT integration — future phase
- **REST API core + thin connector architecture** — strategic refactor, defer until after all modules are working
- **Anthropic interactive connector cards** — inline cards + fullscreen graph explorer in Claude — future phase
- **Vercel agent-browser fallback** — for JS-rendered pages — defer, hard error instead
- **`web-search` CLI behavior** — tabled, implement as stub for now
- **Gemini Vertex AI vs AI Studio auth** — Phase 1 already uses google-genai (AI Studio key), stay consistent
- **Confidence-weighted search ranking** — use `confidence` field for re-ranking search results — future improvement

</deferred>

---

*Phase: 02-web-research-core*
*Context gathered: 2026-03-21*
