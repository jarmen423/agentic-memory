# Phase 2: Web Research Core — Research

**Researched:** 2026-03-21
**Domain:** Web crawling, content normalization, chunking, MCP tool authoring, Brave Search API, Neo4j MERGE patterns
**Confidence:** HIGH (verified against installed packages, official docs, and existing Phase 1 codebase)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Mental Model:** Output-centric ingestion. Neo4j stores synthesized agent output (Reports, Findings), not bulk source pages. `web-ingest <url>` is a separate explicit user path.

**Graph Schema:**
- `:Memory:Research:Report` — parent node, no text, no embedding
- `:Memory:Research:Chunk` — text + embedding, child of Report, what vector search hits
- `:Memory:Research:Finding` — atomic fact, text + embedding, embedded as single node
- `:Entity:Source {url}` — deduplicated reference node, no embedding
- `:CITES {url, title, snippet, accessed_at, source_agent}` — relationship from Finding to Source
- `:HAS_CHUNK {order}` — relationship from Report to Chunk
- `:ABOUT` — Finding/Report → Entity:Project
- `:MENTIONS` — Finding → Entity:*

**MCP Write Path:** `memory_ingest_research(type, content, project_id, session_id, source_agent, title, research_question, confidence, findings, citations)` — primary agent write path

**Ingest Routing:** `type == "report"` → create Report parent + Chunk children; `type == "finding"` → single Finding node + Source MERGE + CITES relationship

**Chunking:** Markdown-first normalization → header-based split → recursive fixed-size fallback (512 tokens max, 50 token overlap)

**Content Normalization:** crawl4ai = pass-through markdown; HTML = markdownify; PDF = pymupdf4llm

**Dedup Keys:**
- Report: `(project_id, session_id)` MERGE
- Chunk: `(session_id, chunk_index)` MERGE
- Finding: `content_hash` MERGE (global)
- Source: `url` MERGE
- CITES: `(finding_id, source_url)` MERGE

**MCP Tools:**
- `memory_ingest_research` — agent write path
- `search_web_memory` — vector search over Research Chunks + Findings
- `brave_search` — live web search, returns to agent, NO auto-ingest

**CLI:**
- `web-ingest <url>` — explicit user source preservation via crawl4ai
- `web-init` — initialize research_embeddings vector index
- `web-search` — stub only, prints "not yet implemented"

**Registration:**
- `register_source("deep_research_agent", ["Memory", "Research", "Finding"])`
- `register_source("web_crawl4ai", ["Memory", "Research", "Chunk"])`

**Tool description quality:** "ALWAYS call this tool..." language for reliable invocation

### Claude's Discretion

- Exact Crawl4AI API call structure and async handling
- `markdownify` vs `html2text` library choice (prefer `markdownify`)
- `pymupdf4llm` API details
- Brave Search HTTP client implementation (requests vs httpx)
- MCP tool response schema structure (as long as it includes url, title, snippet, score)
- Unit test structure and fixtures

### Deferred Ideas (OUT OF SCOPE)

- Gemini multimodal (image) embeddings from PDFs
- Prompt-instructed ingestion (Path 2) — `<memory_ingest>` blocks
- OAuth 2.1 / ChatGPT App connector
- REST API core + thin connector architecture
- Anthropic interactive connector cards
- Vercel agent-browser fallback — hard error instead
- `web-search` CLI full implementation — stub only
- Gemini Vertex AI vs AI Studio auth change
- Confidence-weighted search ranking
</user_constraints>

---

## Summary

Phase 2 builds the web research ingestion pipeline atop the Phase 1 foundation. The primary complexity is authoring `ResearchIngestionPipeline` (subclassing `BaseIngestionPipeline`) with three content paths: report chunking, atomic finding writing, and explicit URL crawling. All four new packages are straightforward to install; `httpx` is already present. The main risks are (1) the Crawl4AI async API surface (now verified: `AsyncWebCrawler` with `CrawlerRunConfig`), (2) the `write_relationship` gap for `:CITES` relationships (the existing Phase 1 signature uses `source_key + content_hash` lookups, not the direct node-ID pattern that `:CITES` requires — a new `write_cites_relationship` method is needed), and (3) the `research_embeddings` vector index dimension: it is currently 3072d (consistent with EmbeddingService Gemini at 3072d) — do NOT change this.

**Primary recommendation:** Build `ResearchIngestionPipeline` in `src/codememory/web/pipeline.py`, add three MCP tools in `src/codememory/server/tools.py` following the existing `@mcp.tool()` + `@rate_limit` + `@log_tool_call` pattern, implement `web-ingest` and `web-init` in `cli.py`, and extend `GraphWriter` with `write_cites_relationship()` for the Finding → Source edge.

---

## Standard Stack

### Core (already installed or verified)
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `google-genai` | ≥1.0.0 (1.32.0 installed) | Gemini embedding via `EmbeddingService` | Already in `pyproject.toml` |
| `groq` | ≥0.10.0 | Entity extraction via `EntityExtractionService` | Already in `pyproject.toml` |
| `neo4j` | latest | Graph reads/writes via `GraphWriter` + `ConnectionManager` | Already in `pyproject.toml` |
| `mcp` | latest | `FastMCP` / `@mcp.tool()` for new tools | Already in `pyproject.toml` |
| `httpx` | 0.28.1 | Async HTTP for Brave Search API | Already installed |

### New Packages Required
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `crawl4ai` | 0.8.5 | Async web crawling → markdown output | Locked decision; provides markdown directly without manual HTML parsing |
| `markdownify` | 1.2.2 | HTML string → markdown | Locked decision (preferred over `html2text`); handles inline HTML passed to pipeline |
| `pymupdf4llm` | 1.27.2.2 | PDF file → markdown with layout awareness | Locked decision; page-aware extraction with header/footer filtering |

### Installation
```bash
pip install "crawl4ai==0.8.5" "markdownify==1.2.2" "pymupdf4llm==1.27.2.2"
# One-time playwright browser installation (required for crawl4ai):
crawl4ai-setup
# OR: python -m playwright install
```

Add to `pyproject.toml` dependencies:
```toml
"crawl4ai>=0.8.0",
"markdownify>=1.2.0",
"pymupdf4llm>=1.27.0",
```

`httpx` is already installed (0.28.1) but add to `pyproject.toml` explicitly:
```toml
"httpx>=0.27.0",
```

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `markdownify` | `html2text` | `html2text` is older, less maintained; `markdownify` is the locked choice |
| `pymupdf4llm` | `pdfminer.six`, `pypdf` | `pymupdf4llm` includes layout analysis; others require manual markdown formatting |
| `httpx` (async) | `requests` (sync) | `httpx` already present, supports async; consistent with async pipeline pattern |

---

## Architecture Patterns

### Recommended File Structure
```
src/codememory/
├── web/
│   ├── __init__.py          # Already exists as stub — implement here or split
│   ├── pipeline.py          # ResearchIngestionPipeline (main class)
│   ├── chunker.py           # _to_markdown(), _chunk_markdown(), _recursive_split()
│   └── crawler.py           # crawl4ai async wrapper for web-ingest path
├── core/
│   ├── graph_writer.py      # Add write_cites_relationship() method
│   └── connection.py        # web-init calls setup_database() — already handles IF NOT EXISTS
├── server/
│   └── tools.py             # Add memory_ingest_research, search_web_memory, brave_search tools
└── cli.py                   # Implement cmd_web_init, cmd_web_ingest (stubs already exist)
```

### Pattern 1: ResearchIngestionPipeline (subclassing BaseIngestionPipeline)
**What:** Concrete subclass implementing the two-branch ingest() routing.
**When to use:** All research content — both agent-submitted (MCP tool) and user-directed (CLI).

```python
# Source: src/codememory/core/base.py (Phase 1)
class ResearchIngestionPipeline(BaseIngestionPipeline):
    DOMAIN_LABEL = "Research"

    def __init__(
        self,
        connection_manager: ConnectionManager,
        embedding_service: EmbeddingService,
        entity_extractor: EntityExtractionService,
    ) -> None:
        super().__init__(connection_manager)
        self._embedder = embedding_service
        self._extractor = entity_extractor
        self._writer = GraphWriter(connection_manager)

    def ingest(self, source: dict[str, Any]) -> dict[str, Any]:
        content_type = source["type"]
        if content_type == "report":
            return self._ingest_report(source)
        elif content_type == "finding":
            return self._ingest_finding(source)
        else:
            raise ValueError(f"Unknown content type: {content_type}")
```

### Pattern 2: Crawl4AI Async API (verified against official docs)
**What:** AsyncWebCrawler with CrawlerRunConfig for JS-rendered pages.
**When to use:** `web-ingest <url>` CLI path.

```python
# Source: https://docs.crawl4ai.com/core/simple-crawling/ (verified)
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

async def crawl_url(url: str) -> str:
    """Fetch URL and return markdown. Raises RuntimeError on quality failure."""
    config = CrawlerRunConfig(
        wait_until="networkidle",    # wait for JS rendering
        page_timeout=30000,          # 30s max
    )
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config)
    if not result.success or not result.markdown:
        raise RuntimeError(f"Crawl failed for {url}: {result.error_message}")
    # result.markdown is clean markdown; result.markdown.fit_markdown is condensed
    return result.markdown
```

**JS wait_for (for dynamic pages):**
```python
config = CrawlerRunConfig(
    wait_for="css:.content-loaded",      # CSS selector
    # OR: wait_for="js:() => window.loaded === true",  # JS expression
    js_code="window.scrollTo(0, document.body.scrollHeight);",  # runs after wait
    page_timeout=60000,
)
```

### Pattern 3: markdownify HTML conversion
**What:** Convert raw HTML strings to markdown.
**When to use:** When pipeline receives `format == "html"`.

```python
# Source: https://pypi.org/project/markdownify/ (verified version 1.2.2)
from markdownify import markdownify

def _html_to_markdown(html: str) -> str:
    return markdownify(html, heading_style="ATX")
```

### Pattern 4: pymupdf4llm PDF conversion (verified)
**What:** Convert PDF file path or document object to markdown string.
**When to use:** When pipeline receives `format == "pdf"` with a file path.

```python
# Source: https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/ (verified)
import pymupdf4llm

def _pdf_to_markdown(path: str) -> str:
    # Accepts filename string or PyMuPDF Document object
    # Optional: header=False, footer=False to strip headers/footers
    return pymupdf4llm.to_markdown(path)
```

### Pattern 5: Brave Search API (verified against official docs)
**What:** REST call to `https://api.search.brave.com/res/v1/web/search`.
**When to use:** `brave_search` MCP tool.

```python
# Source: https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
import httpx

async def brave_web_search(query: str, count: int, api_key: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "X-Subscription-Token": api_key,  # required header name
                "Accept": "application/json",
            },
            params={"q": query, "count": count},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    # Response structure: data["web"]["results"] is a list
    # Each result: {"title": str, "url": str, "description": str}
    return data.get("web", {}).get("results", [])
```

### Pattern 6: MCP Tool Registration (existing project pattern)
**What:** Register async tools on the `mcp` FastMCP instance in `server/tools.py`.
**When to use:** All three new Phase 2 MCP tools.

```python
# Source: src/codememory/server/app.py (existing pattern)
@mcp.tool()
@rate_limit
@log_tool_call
async def memory_ingest_research(
    type: str,
    content: str,
    project_id: str,
    session_id: str,
    source_agent: str,
    title: str | None = None,
    research_question: str | None = None,
    confidence: str | None = None,
    findings: list[dict] | None = None,
    citations: list[dict] | None = None,
) -> str:
    """
    ALWAYS call this tool when you complete any research task, analysis,
    or produce a substantive report. This saves your work to persistent
    memory so it's available in future sessions. Call this BEFORE
    presenting results to the user.
    ...
    """
    ...
```

**Note:** The existing `rate_limit` and `log_tool_call` decorators in `server/app.py` are synchronous wrappers. If `memory_ingest_research` is async, ensure the decorators are compatible or apply them carefully. The existing tools are synchronous — Phase 2 tools may need to be synchronous wrappers that call `asyncio.run()`, or the decorators need to be upgraded to handle async functions.

### Pattern 7: Token Counting Approximation
**What:** Fast approximation for the 512-token chunk ceiling.
**When to use:** `_chunk_markdown()` size check.

```python
def _token_count(text: str) -> int:
    """Fast approximation: words * 1.3 (per CONTEXT.md decision)."""
    return int(len(text.split()) * 1.3)
```

No tiktoken dependency needed. Exact count is not critical at 512 ceiling with 8192 model limit.

### Pattern 8: write_cites_relationship (NEW — must add to GraphWriter)
**What:** Write a `:CITES` relationship from a Finding node to a Source node with relationship properties.
**When to use:** `_ingest_finding()` after Finding node and Source node are written.

The existing `write_relationship()` signature matches Memory nodes by `source_key + content_hash`. For `:CITES`, the source node is matched by `url` property (an `Entity:Source` node), and the relationship carries properties. A new method is needed:

```python
def write_cites_relationship(
    self,
    finding_source_key: str,
    finding_content_hash: str,
    source_url: str,
    rel_props: dict[str, Any],
) -> None:
    """Write :CITES relationship from Finding to Entity:Source node.

    Args:
        finding_source_key: source_key of the :Memory:Research:Finding node.
        finding_content_hash: content_hash of the Finding node.
        source_url: url property of the :Entity:Source node.
        rel_props: Properties for the :CITES relationship
            (url, title, snippet, accessed_at, source_agent).
    """
    cypher = (
        "MATCH (f {source_key: $source_key, content_hash: $content_hash})\n"
        "MATCH (s:Entity:Source {url: $source_url})\n"
        "MERGE (f)-[r:CITES]->(s)\n"
        "ON CREATE SET r += $rel_props\n"
        "ON MATCH SET r.snippet = $rel_props.snippet, r.accessed_at = $rel_props.accessed_at"
    )
    with self._conn.session() as session:
        session.run(
            cypher,
            source_key=finding_source_key,
            content_hash=finding_content_hash,
            source_url=source_url,
            rel_props=rel_props,
        )
```

### Pattern 9: Report Parent Node (no text, no embedding)
**What:** The Report parent uses a different dedup key than standard Memory nodes — `(project_id, session_id)`, not `(source_key, content_hash)`.
**When to use:** `_ingest_report()` creates the parent.

This does NOT fit the `write_memory_node()` pattern (which MERGEs on `source_key + content_hash`). The Report MERGE must be written with custom Cypher or a specialized method. Options:
1. Add `write_report_node(properties)` to `GraphWriter`
2. Issue raw Cypher directly in `ResearchIngestionPipeline._ingest_report()`

**Recommendation:** Add `write_report_node()` to `GraphWriter` for testability.

### Anti-Patterns to Avoid
- **Using `CREATE` instead of `MERGE`:** All writes in this codebase use MERGE. The Report + Chunk + Finding + Source nodes must all use MERGE with their respective dedup keys.
- **Embedding the Report parent node:** Report has no `embedding` and no `text` field. Do not pass it to `EmbeddingService`.
- **Auto-ingesting Brave Search results:** `brave_search` tool returns results to the agent; it must never trigger `ResearchIngestionPipeline`.
- **Changing research_embeddings dimensions:** The index is 3072d (consistent with Gemini at 3072d). Do not attempt to change to 768d — it was already established at 3072d in Phase 1.
- **Using synchronous crawl4ai calls:** The library is async-native; use `AsyncWebCrawler` in an async context.
- **Installing playwright browsers manually:** Use `crawl4ai-setup` post-install, which handles browser setup.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Web crawling with JS rendering | Custom Playwright/Selenium wrapper | `crawl4ai` `AsyncWebCrawler` | Handles stealth, content filtering, markdown output in one call |
| HTML → markdown | Custom regex/BeautifulSoup pipeline | `markdownify` | Handles tables, links, code blocks, nested structure |
| PDF → markdown | Direct PyMuPDF page iteration | `pymupdf4llm.to_markdown()` | Layout analysis, header/footer detection, semantic structure |
| Rate limiting | Custom timestamp tracking | Existing `rate_limit` decorator in `server/app.py` | Already implements sliding window; reuse |
| MCP tool logging | Custom logging wrapper | Existing `log_tool_call` decorator | Already handles telemetry, timing, error logging |
| Entity extraction | Inline LLM call | `EntityExtractionService` from Phase 1 | Already tested, handles Groq JSON mode, deterministic |
| Embedding | Direct genai API calls | `EmbeddingService` from Phase 1 | Already handles `output_dimensionality`, batching |
| Graph upserts | Raw Cypher MERGE in pipeline | `GraphWriter.write_memory_node()` + `upsert_entity()` | Already tested, handles labels, namespace, composite key |

**Key insight:** Phase 1 built precisely the abstractions Phase 2 needs. The pipeline should be thin orchestration over existing services.

---

## Common Pitfalls

### Pitfall 1: Dimension Mismatch — research_embeddings is 3072d, NOT 768d
**What goes wrong:** Developer assumes Gemini embeddings are 768d (common confusion from older Gemini embedding models), passes 768d vectors to the 3072d index, gets runtime errors.
**Why it happens:** `gemini-embedding-2-preview` at full dimensionality is 3072d. The CONTEXT.md mentions `embedding_model: "gemini-embedding-2-preview"` without specifying dimensions. The EmbeddingService PROVIDERS dict confirms `"gemini": {"model": "gemini-embedding-2-preview", "dimensions": 3072}`.
**How to avoid:** Instantiate `EmbeddingService(provider="gemini", api_key=key)` with no dimension override. Default 3072d matches the index.
**Warning signs:** `Invalid vector dimension` errors from Neo4j at query time.

### Pitfall 2: rate_limit / log_tool_call Decorators Are Synchronous
**What goes wrong:** Applying `@rate_limit` and `@log_tool_call` (both synchronous wrappers using `@wraps`) to an `async def` tool strips the coroutine. The decorated function becomes a sync function that returns a coroutine object rather than awaiting it.
**Why it happens:** Existing decorators in `server/app.py` call `func(*args, **kwargs)` without `await`. The existing tools are sync. New research tools involve async I/O (Brave Search, crawl4ai).
**How to avoid:** Make `memory_ingest_research`, `search_web_memory`, and `brave_search` synchronous wrappers that use `asyncio.get_event_loop().run_until_complete()` or `asyncio.run()` for any internal async operations — matching the existing tool pattern. OR upgrade the decorator to handle both sync and async via `inspect.iscoroutinefunction()`. Keep decorator behavior consistent with existing tools.
**Warning signs:** MCP tool calls silently return `None` or a coroutine object instead of a string.

### Pitfall 3: Report Dedup Key is Not source_key + content_hash
**What goes wrong:** Using `write_memory_node()` for the Report parent with a `content_hash` derived from report content. The CONTEXT.md dedup key is `(project_id, session_id)`, meaning re-submitting a report for the same session overwrites the previous one.
**Why it happens:** `write_memory_node()` is designed for `(source_key, content_hash)` MERGE. The Report node needs `(project_id, session_id)` MERGE — a completely different key.
**How to avoid:** Implement a separate `write_report_node()` in `GraphWriter` or issue custom Cypher for Report writes. Do NOT use `write_memory_node()` for the Report parent.
**Warning signs:** Duplicate Report nodes accumulating in the graph for the same session.

### Pitfall 4: Crawl4AI Requires playwright Browser Installation
**What goes wrong:** `crawl4ai` is installed via pip but `AsyncWebCrawler` raises an error because Playwright browsers are not downloaded.
**Why it happens:** crawl4ai depends on Playwright for headless browser rendering. `pip install crawl4ai` downloads the Python package but not the browser binaries.
**How to avoid:** Run `crawl4ai-setup` (or `python -m playwright install chromium`) after installing. Add to Docker setup / developer onboarding.
**Warning signs:** `BrowserType.launch: Executable doesn't exist` or similar Playwright errors on first crawl.

### Pitfall 5: Brave Search API Rate Limit — Free Tier is Monthly
**What goes wrong:** Burning through 2,500 monthly quota during development/testing with actual API calls in unit tests.
**Why it happens:** Free tier is 2,500 queries/month total, not per day. Tests that mock HTTP must never call the real API.
**How to avoid:** All tests must mock `httpx.AsyncClient.get()`. Add `@rate_limit` to `brave_search` tool with appropriate CPM. Configure `BRAVE_SEARCH_API_KEY` as optional env var — tool should fail gracefully when not set.
**Warning signs:** 429 responses or "Subscription quota exceeded" JSON from Brave API.

### Pitfall 6: HAS_CHUNK Relationship Must Carry chunk_index
**What goes wrong:** Chunk nodes are written but the `:HAS_CHUNK` relationship is created without the `order` property, making ordered reconstruction impossible.
**Why it happens:** `write_relationship()` in Phase 1 does not support relationship properties. CONTEXT.md defines `[:HAS_CHUNK {order: chunk_index}]`.
**How to avoid:** Either extend `write_relationship()` with optional `props` dict, or issue this Cypher directly: `MERGE (r)-[:HAS_CHUNK {order: $order}]->(c)`. Use a dedicated `write_has_chunk_relationship()` method in `GraphWriter`.
**Warning signs:** Chunk nodes exist but can't be retrieved in order.

### Pitfall 7: Content Hash for Findings Must Be Deterministic
**What goes wrong:** Using `uuid4()` or timestamp as content_hash for Finding nodes defeats deduplication — the same finding is stored multiple times across sessions.
**Why it happens:** Developer reaches for `uuid4()` for node IDs. But Finding dedup key is `content_hash` (global), so it must be a hash of the content.
**How to avoid:** Use `hashlib.sha256(text.encode()).hexdigest()` or `hashlib.md5(text.encode()).hexdigest()` as `content_hash` for all Memory nodes. This is the same approach as Phase 1.
**Warning signs:** Finding count grows linearly with research sessions even for duplicate facts.

---

## Code Examples

### ResearchIngestionPipeline skeleton
```python
# Source: based on Phase 1 BaseIngestionPipeline contract + CONTEXT.md schema
import hashlib
from datetime import datetime, timezone
from typing import Any

from codememory.core.base import BaseIngestionPipeline
from codememory.core.connection import ConnectionManager
from codememory.core.embedding import EmbeddingService
from codememory.core.entity_extraction import EntityExtractionService, build_embed_text
from codememory.core.graph_writer import GraphWriter
from codememory.core.registry import register_source

register_source("deep_research_agent", ["Memory", "Research", "Finding"])
register_source("web_crawl4ai", ["Memory", "Research", "Chunk"])


class ResearchIngestionPipeline(BaseIngestionPipeline):
    DOMAIN_LABEL = "Research"

    def ingest(self, source: dict[str, Any]) -> dict[str, Any]:
        if source["type"] == "report":
            return self._ingest_report(source)
        return self._ingest_finding(source)

    def _content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
```

### Vector search over Research nodes
```python
# Source: based on existing semantic_search pattern in KnowledgeGraphBuilder
RESEARCH_SEARCH_CYPHER = """
CALL db.index.vector.queryNodes('research_embeddings', $limit, $embedding)
YIELD node, score
RETURN
    node.text AS text,
    node.source_agent AS source_agent,
    node.research_question AS research_question,
    labels(node) AS node_labels,
    score
ORDER BY score DESC
"""
```

### web-init CLI implementation
```python
# Source: based on existing cmd_init pattern in cli.py
def cmd_web_init(args: argparse.Namespace) -> None:
    """Initialize research_embeddings vector index."""
    conn = ConnectionManager(uri, user, password)
    conn.setup_database()   # IF NOT EXISTS — safe to re-run
    print("web-init: research_embeddings vector index ready.")
    conn.close()
```

**Note:** `setup_database()` already creates the `research_embeddings` index with `IF NOT EXISTS`. The `web-init` command just needs to call it.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pymupdf4llm 0.x` API | `pymupdf4llm 1.27.x` API — same `to_markdown()` signature | v1.0.0 | No breaking change to function signature |
| `crawl4ai 0.4.x` sync API | `crawl4ai 0.8.x` async `AsyncWebCrawler` with `CrawlerRunConfig` | v0.5.0+ | Must use async context manager; old sync calls removed |
| `markdownify 0.x` | `markdownify 1.2.2` | v1.0.0 | API stable; `heading_style="ATX"` still works |
| Brave Search `Accept-Encoding` header | Only `X-Subscription-Token` + `Accept` required | Ongoing | Simple header set |

**Deprecated/outdated:**
- `crawl4ai` synchronous usage: removed in 0.5.0+. All calls must be async.
- `result.markdown_v2`: older crawl4ai versions; current API is `result.markdown` (returns object) or `result.markdown.raw_markdown` for string.

---

## GraphWriter Extension Requirements

The following methods must be added to `GraphWriter` in Phase 2 (currently absent):

| Method | Purpose | Dedup Key |
|--------|---------|-----------|
| `write_report_node(props)` | Write `:Memory:Research:Report` parent | `(project_id, session_id)` MERGE |
| `write_has_chunk_relationship(report_key, report_hash, chunk_key, chunk_hash, order)` | Write `[:HAS_CHUNK {order}]` | MERGE on relationship |
| `write_cites_relationship(finding_key, finding_hash, source_url, rel_props)` | Write `[:CITES {url, title, snippet, ...}]` | MERGE on `(finding, source)` pair |
| `write_source_node(url, title)` | Write `:Entity:Source {url}` | MERGE on `url` |

The existing `upsert_entity()` handles `Entity:*` nodes by `(name, type)` composite key, but `:Entity:Source` is matched by `url` alone — a new `write_source_node()` method is needed.

---

## Open Questions

1. **rate_limit / log_tool_call compatibility with async tools**
   - What we know: Current decorators are synchronous wrappers.
   - What's unclear: Whether `FastMCP` expects `async def` tools or accepts `def` with internal `asyncio.run()`.
   - Recommendation: Keep new tools as `def` (not `async def`) matching existing pattern. Use `asyncio.run()` internally for crawl4ai and httpx calls. If that causes event loop conflicts in an async MCP context, upgrade the decorators instead.

2. **MCP tool function location**
   - What we know: Existing tools are top-level functions in `server/app.py`, not methods in a `Toolkit` class (despite `tools.py` having a `Toolkit` class — it's not connected to MCP decorators).
   - What's unclear: Whether Phase 2 tools go in `server/app.py` or a new `server/research_tools.py`.
   - Recommendation: Add to `server/app.py` for consistency with existing MCP tool registration pattern.

3. **BRAVE_SEARCH_API_KEY configuration path**
   - What we know: Config (`Config` class) handles Neo4j and OpenAI keys. Groq key is via env var.
   - What's unclear: Whether Brave API key should go in `.codememory/config.json` or environment variable.
   - Recommendation: Environment variable `BRAVE_SEARCH_API_KEY` (consistent with `GROQ_API_KEY` pattern). Fail gracefully with clear error when not set.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.x with pytest-asyncio, pytest-mock |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_web_pipeline.py -x -q --tb=short` |
| Full suite command | `pytest tests/ -q --tb=short` |

### Phase Requirements → Test Map

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|-------------|
| `ResearchIngestionPipeline` subclasses `BaseIngestionPipeline` | unit | `pytest tests/test_web_pipeline.py::test_subclass_contract -x` | ❌ Wave 0 |
| Report ingest creates parent node (no embedding) + chunk children | unit | `pytest tests/test_web_pipeline.py::test_ingest_report -x` | ❌ Wave 0 |
| Finding ingest creates single embedded node | unit | `pytest tests/test_web_pipeline.py::test_ingest_finding -x` | ❌ Wave 0 |
| `_to_markdown()` dispatches html/pdf/text/markdown correctly | unit | `pytest tests/test_web_pipeline.py::test_to_markdown_dispatch -x` | ❌ Wave 0 |
| `_chunk_markdown()` splits on headers, falls back on oversize | unit | `pytest tests/test_web_pipeline.py::test_chunker -x` | ❌ Wave 0 |
| Dedup: same finding content_hash merges, no duplicate node | unit | `pytest tests/test_web_pipeline.py::test_finding_dedup -x` | ❌ Wave 0 |
| `brave_search` tool returns list with title/url/description | unit | `pytest tests/test_web_tools.py::test_brave_search_response -x` | ❌ Wave 0 |
| `brave_search` does NOT call ingest pipeline | unit | `pytest tests/test_web_tools.py::test_brave_search_no_ingest -x` | ❌ Wave 0 |
| `search_web_memory` calls research_embeddings index | unit | `pytest tests/test_web_tools.py::test_search_web_memory -x` | ❌ Wave 0 |
| `GraphWriter.write_report_node()` uses `(project_id, session_id)` MERGE | unit | `pytest tests/test_web_pipeline.py::test_write_report_node -x` | ❌ Wave 0 |
| `GraphWriter.write_cites_relationship()` writes CITES with props | unit | `pytest tests/test_web_pipeline.py::test_write_cites -x` | ❌ Wave 0 |
| `web-ingest <url>` CLI calls crawl4ai and ingest pipeline | unit | `pytest tests/test_cli.py::test_web_ingest_cmd -x` | ❌ Wave 0 |
| `web-init` CLI calls `setup_database()` | unit | `pytest tests/test_cli.py::test_web_init_cmd -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_web_pipeline.py tests/test_web_tools.py -x -q --tb=short`
- **Per wave merge:** `pytest tests/ -q --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_web_pipeline.py` — covers `ResearchIngestionPipeline`, `GraphWriter` extensions, chunker, content normalization
- [ ] `tests/test_web_tools.py` — covers MCP tools (`memory_ingest_research`, `search_web_memory`, `brave_search`)
- [ ] All tests mock Neo4j (`mock_conn`), `EmbeddingService` (`mock_embedder`), `EntityExtractionService` (`mock_extractor`), and `httpx.AsyncClient` — no live connections needed for unit tests

---

## Sources

### Primary (HIGH confidence)
- `D:/code/agentic-memory/src/codememory/core/base.py` — BaseIngestionPipeline ABC contract
- `D:/code/agentic-memory/src/codememory/core/embedding.py` — EmbeddingService; Gemini=3072d confirmed
- `D:/code/agentic-memory/src/codememory/core/graph_writer.py` — write_memory_node / write_relationship signatures (gaps identified)
- `D:/code/agentic-memory/src/codememory/core/connection.py` — research_embeddings at 3072d confirmed
- `D:/code/agentic-memory/src/codememory/server/app.py` — @mcp.tool() + decorators pattern
- `D:/code/agentic-memory/pyproject.toml` — installed deps; httpx 0.28.1 already present
- `https://docs.crawl4ai.com/core/simple-crawling/` — arun() signature, result.markdown
- `https://docs.crawl4ai.com/core/browser-crawler-config/` — CrawlerRunConfig, wait_for, js_code
- `https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/` — to_markdown() signature
- `https://api-dashboard.search.brave.com/app/documentation/web-search/get-started` — endpoint URL, X-Subscription-Token header, response schema

### Secondary (MEDIUM confidence)
- PyPI version listings (pip index versions) — confirmed crawl4ai=0.8.5, markdownify=1.2.2, pymupdf4llm=1.27.2.2
- `https://pypi.org/project/markdownify/` — markdownify API (heading_style parameter)

### Tertiary (LOW confidence)
- Training data: token counting approximation (`len(text.split()) * 1.3`) — standard heuristic, unverified against specific models

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified via pip index versions and official docs
- Architecture: HIGH — derived directly from CONTEXT.md decisions + Phase 1 source inspection
- GraphWriter gaps: HIGH — confirmed by reading Phase 1 source
- Crawl4AI API: MEDIUM-HIGH — verified against official docs (0.8.x async pattern confirmed)
- pymupdf4llm API: MEDIUM-HIGH — verified against official docs
- Brave Search API: HIGH — verified against official dashboard docs
- Pitfalls: HIGH for gaps found in Phase 1 code inspection; MEDIUM for async decorator concern

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (stable libraries; crawl4ai moves fast — re-verify if >30 days)

---

## 02-04: REST API Foundation

**Researched:** 2026-03-21
**Domain:** FastAPI, ASGI mounting, Bearer token auth, FastMCP co-serving
**Confidence:** HIGH (verified via live pip introspection, FastMCP source inspection, ASGI mount test)

### Summary

Plan 02-04 builds `src/am_server/` as a FastAPI application that runs in the same uvicorn process as the existing FastMCP server via ASGI sub-application mounting. The key finding is that `FastMCP.sse_app()` returns a plain `Starlette` instance, and `FastAPI.mount()` accepts Starlette ASGI apps directly — confirmed by live Python test. This means zero separate process, zero port conflict: FastAPI owns a port (default 8765), mounts the MCP server at `/mcp`, and adds REST endpoints alongside it.

`fastapi` is NOT in `pyproject.toml` yet — it must be added. `uvicorn` is already pulled in transitively by `mcp` (1.26.0) but should be pinned explicitly. Both packages are already installed on this machine.

The three Phase 2 REST endpoints are thin wrappers over existing pipeline and service objects: `POST /ingest/research` delegates to `ResearchIngestionPipeline.ingest()` (the exact same payload the MCP tool accepts), `GET /search/research` delegates to the same Neo4j vector index query used by `search_web_memory`, and `GET /ext/selectors.json` serves a static JSON file from disk at `src/am_server/data/selectors.json`.

Bearer token auth is implemented as a FastAPI dependency function using `fastapi.security.HTTPBearer` — applied via `Depends(require_auth)` on every endpoint except `GET /health` and `GET /ext/selectors.json`. The API key is read from `AM_SERVER_API_KEY` environment variable. This middleware is intentionally designed to be reused in Phase 4 with zero changes.

**Primary recommendation:** Build `src/am_server/` as a standalone FastAPI package. Mount FastMCP's Starlette app at `/mcp`. Wire `uvicorn.run(app, host="0.0.0.0", port=8765)` as the server entrypoint. Add `fastapi>=0.115.0` and `uvicorn[standard]>=0.30.0` to `pyproject.toml`.

---

### Standard Stack (02-04)

#### Packages to Add to pyproject.toml

| Library | Latest | Purpose | Status |
|---------|--------|---------|--------|
| `fastapi` | 0.135.1 | REST API framework — routing, dependency injection, request/response models | NOT in pyproject.toml — must add |
| `uvicorn` | 0.42.0 | ASGI server — already required by `mcp` 1.26.0, but should be explicit | NOT in pyproject.toml — must add |

#### Already Present (no action needed)

| Library | Installed Version | Used For |
|---------|------------------|---------|
| `starlette` | 0.49.3 | FastMCP.sse_app() returns Starlette; FastAPI is built on Starlette |
| `pydantic` | >=2.0.0 | FastAPI request body models |
| `httpx` | 0.28.1 | Already in project; not needed by am-server itself but available |
| `mcp` | 1.26.0 | FastMCP instance already initialized in `server/app.py` |

**Installation:**
```bash
pip install "fastapi>=0.115.0" "uvicorn[standard]>=0.30.0"
```

**Add to pyproject.toml:**
```toml
"fastapi>=0.115.0",
"uvicorn[standard]>=0.30.0",
```

**Version note:** `fastapi>=0.115.0` is a safe lower bound — covers 0.115.x through 0.135.x (current). The `standard` extra for uvicorn adds `websockets` and `uvloop` (Linux only) for production throughput.

---

### Architecture Patterns (02-04)

#### Recommended File Structure
```
src/am_server/
├── __init__.py              # Package marker
├── app.py                   # FastAPI app factory: create_app(), mounts MCP at /mcp
├── auth.py                  # require_auth() dependency — HTTPBearer + env key check
├── dependencies.py          # get_pipeline() — lru_cache singleton
├── models.py                # Pydantic request/response models
├── routes/
│   ├── __init__.py
│   ├── health.py            # GET /health — unauthenticated
│   ├── ingest.py            # POST /ingest/research — auth required
│   ├── search.py            # GET /search/research — auth required
│   └── selectors.py         # GET /ext/selectors.json — unauthenticated
├── data/
│   └── selectors.json       # Static DOM selector file for am-ext
└── server.py                # uvicorn.run() entrypoint
```

**pyproject.toml update — add am_server to packaged sources:**
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/codememory", "src/am_server"]
```

#### Pattern 1: FastAPI + FastMCP ASGI Mount (VERIFIED)
**What:** Mount the existing FastMCP Starlette app as a sub-application inside FastAPI. Both run in the same uvicorn process on the same port.
**Verified:** `app.mount('/mcp', mcp.sse_app())` confirmed working with fastapi 0.121.2 + mcp 1.26.0.

```python
# Source: live introspection — mcp 1.26.0 FastMCP.sse_app() returns Starlette instance (verified 2026-03-21)
# src/am_server/app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from codememory.server.app import mcp  # existing FastMCP instance

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast on missing env vars — better than 500 on first request
    from am_server.dependencies import get_pipeline
    get_pipeline()
    yield

def create_app() -> FastAPI:
    app = FastAPI(title="am-server", version="0.1.0", lifespan=lifespan)

    # Mount FastMCP SSE transport at /mcp
    # MCP clients connect to http://host:8765/mcp/sse
    app.mount("/mcp", mcp.sse_app())

    from am_server.routes import health, ingest, search, selectors
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(search.router)
    app.include_router(selectors.router)

    return app
```

#### Pattern 2: Bearer Token Auth Dependency
**What:** FastAPI dependency that validates `Authorization: Bearer <token>` on every protected route.
**Pattern:** `Depends(require_auth)` injected at the router level via `APIRouter(dependencies=[...])`.
**Header standard:** `Authorization: Bearer <key>` — NOT `X-API-Key`. Consistent with OAuth 2.1 patterns for future compatibility.

```python
# src/am_server/auth.py
import os
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_bearer = HTTPBearer()

def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    """Validate Bearer token against AM_SERVER_API_KEY env var."""
    expected = os.environ.get("AM_SERVER_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AM_SERVER_API_KEY not configured",
        )
    if credentials.credentials != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
```

**Applying auth to a router:**
```python
# All routes in this router require auth:
router = APIRouter(dependencies=[Depends(require_auth)])
```

#### Pattern 3: POST /ingest/research — Pipeline Delegation
**What:** Same payload as `memory_ingest_research` MCP tool. Delegates to `ResearchIngestionPipeline.ingest()`.
**session_id rule:** Caller MUST provide `session_id`. Server NEVER generates it. This preserves the dedup contract `(project_id, session_id)`.

```python
# src/am_server/models.py
from pydantic import BaseModel

class CitationModel(BaseModel):
    url: str
    title: str | None = None
    snippet: str | None = None

class FindingModel(BaseModel):
    text: str
    confidence: str | None = None
    citations: list[CitationModel] = []

class ResearchIngestRequest(BaseModel):
    type: str                          # "report" | "finding"
    content: str
    project_id: str
    session_id: str                    # REQUIRED — caller owns session identity
    source_agent: str                  # "claude" | "perplexity" | "chatgpt" | "custom"
    title: str | None = None
    research_question: str | None = None
    confidence: str | None = None
    findings: list[FindingModel] | None = None
    citations: list[CitationModel] | None = None
```

```python
# src/am_server/routes/ingest.py (sketch)
import asyncio
from fastapi import APIRouter, Depends
from am_server.auth import require_auth
from am_server.dependencies import get_pipeline
from am_server.models import ResearchIngestRequest

router = APIRouter(dependencies=[Depends(require_auth)])

@router.post("/ingest/research", status_code=202)
async def ingest_research(body: ResearchIngestRequest) -> dict:
    pipeline = get_pipeline()
    # pipeline.ingest() is synchronous — run in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, pipeline.ingest, body.model_dump())
    return {"status": "ok", "result": result}
```

#### Pattern 4: GET /search/research — Vector Search Delegation

```python
# src/am_server/routes/search.py
from fastapi import APIRouter, Depends, Query
from am_server.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

@router.get("/search/research")
async def search_research(
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    # Reuse the same Neo4j vector search called by search_web_memory MCP tool
    # Exact implementation follows the RESEARCH_SEARCH_CYPHER pattern in main RESEARCH.md
    results = await _run_research_search(q, limit)
    return {"results": results}
```

#### Pattern 5: GET /ext/selectors.json — Static File from Disk
**Rationale for disk over hardcoded dict:** Remote-updatability is the entire point. Edit the file, selectors update instantly. No code change needed.
**Auth decision:** This endpoint is intentionally UNAUTHENTICATED. am-ext fetches selectors at browser startup before the user has entered an API key in the extension settings.

```python
# src/am_server/routes/selectors.py
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter()  # No auth dependency

_SELECTORS_PATH = Path(__file__).parent.parent / "data" / "selectors.json"

@router.get("/ext/selectors.json")
async def get_selectors() -> dict:
    try:
        return json.loads(_SELECTORS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="selectors.json not found")
```

**Initial selectors.json shape** (matches PASSIVE-INGESTION.md am-ext platform list):
```json
{
  "version": 1,
  "platforms": {
    "chatgpt": {
      "host": "chat.openai.com",
      "turn_selector": "[data-message-author-role]",
      "role_attr": "data-message-author-role",
      "text_selector": ".markdown"
    },
    "claude": {
      "host": "claude.ai",
      "turn_selector": "[data-testid*='human-turn']",
      "role_attr": "data-testid",
      "text_selector": ".prose"
    },
    "perplexity": {
      "host": "perplexity.ai",
      "turn_selector": ".message-block",
      "role_attr": "data-role",
      "text_selector": ".prose"
    },
    "gemini": {
      "host": "gemini.google.com",
      "turn_selector": "message-content",
      "role_attr": "class",
      "text_selector": ".response-content"
    }
  }
}
```

**Confidence note on selector values:** LOW — platform DOM changes frequently. The shape and serving pattern are HIGH confidence. Actual selectors will need validation against live DOM when Phase 6 is implemented.

#### Pattern 6: GET /health — Unauthenticated
```python
# src/am_server/routes/health.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

#### Pattern 7: uvicorn entrypoint
```python
# src/am_server/server.py
import os
import uvicorn
from am_server.app import create_app

def run() -> None:
    app = create_app()
    uvicorn.run(
        app,
        host=os.environ.get("AM_SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("AM_SERVER_PORT", "8765")),
    )

if __name__ == "__main__":
    run()
```

**Port 8765:** Chosen to avoid conflict with Neo4j (7687) and common dev ports. Configurable via `AM_SERVER_PORT`.

#### Pattern 8: Pipeline Dependency Singleton
```python
# src/am_server/dependencies.py
import os
from functools import lru_cache
from codememory.core.connection import ConnectionManager
from codememory.core.embedding import EmbeddingService
from codememory.core.entity_extraction import EntityExtractionService
from codememory.web.pipeline import ResearchIngestionPipeline

@lru_cache(maxsize=1)
def get_pipeline() -> ResearchIngestionPipeline:
    """Return singleton ResearchIngestionPipeline. Called at startup via lifespan."""
    conn = ConnectionManager(
        uri=os.environ["NEO4J_URI"],
        user=os.environ["NEO4J_USER"],
        password=os.environ["NEO4J_PASSWORD"],
    )
    embedder = EmbeddingService(provider="gemini", api_key=os.environ["GEMINI_API_KEY"])
    extractor = EntityExtractionService(api_key=os.environ["GROQ_API_KEY"])
    return ResearchIngestionPipeline(conn, embedder, extractor)
```

#### Anti-Patterns to Avoid (02-04)

- **Running FastAPI and FastMCP as two separate processes:** ASGI mount is confirmed. Two processes = two ports + double lifecycle management. Use mount.
- **Generating session_id server-side in POST /ingest/research:** Breaks the `(project_id, session_id)` dedup key. Caller owns session identity.
- **Putting selectors.json as a hardcoded Python dict:** Defeats remote-updatability. Must be a file on disk.
- **Applying auth to /health:** Load balancers and monitoring must reach health checks without credentials.
- **Applying auth to /ext/selectors.json:** am-ext fetches at startup before user configures API key. Must be open.
- **Using `X-API-Key` header:** Use `Authorization: Bearer` for OAuth 2.1 forward compatibility.
- **Calling pipeline.ingest() directly inside async def without thread pool:** Blocks the event loop. Use `run_in_executor`.

---

### Don't Hand-Roll (02-04)

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ASGI server | Custom TCP server | `uvicorn` | Already in dep tree via `mcp`; one-line startup |
| Request validation | Manual JSON parsing + isinstance | Pydantic models via FastAPI | Type coercion, error messages, OpenAPI docs for free |
| Auth header parsing | `request.headers.get("Authorization")` | `fastapi.security.HTTPBearer` | Handles missing header, malformed header, structured credentials |
| FastAPI + FastMCP integration | Custom ASGI wrapper | `mcp.sse_app()` + `FastAPI.mount()` | FastMCP exposes Starlette app directly; mount is one line (verified) |
| Static file serving | Custom ASGI middleware | `json.loads(path.read_text())` in endpoint | Two lines; no middleware complexity needed |
| Pipeline lifecycle | Manual init in every request | `lru_cache` singleton + lifespan hook | Fail-fast on startup, single connection pool |

---

### Common Pitfalls (02-04)

#### Pitfall 1: fastapi Not in pyproject.toml
**What goes wrong:** `fastapi` is installed on this machine (0.121.2) but is NOT in `pyproject.toml`. A fresh `pip install -e .` will fail to import `fastapi` in `am_server`.
**How to avoid:** Add `"fastapi>=0.115.0"` and `"uvicorn[standard]>=0.30.0"` to `pyproject.toml` in the first task of this plan.
**Warning signs:** `ModuleNotFoundError: No module named 'fastapi'` on a clean install.

#### Pitfall 2: MCP SSE Path Changes After Mounting
**What goes wrong:** After `app.mount("/mcp", mcp.sse_app())`, MCP clients connecting to the old path `/sse` (without the `/mcp` prefix) get 404.
**Why it happens:** The mount prefix is prepended to all internal FastMCP routes. The full SSE path becomes `/mcp/sse`.
**How to avoid:** Document and configure MCP client connection URL as `http://localhost:8765/mcp/sse`. Add integration test that confirms this path responds.
**Warning signs:** MCP client connects but receives 404; tools not discoverable.

#### Pitfall 3: /ext/selectors.json Must Be Unauthenticated
**What goes wrong:** Router-level `dependencies=[Depends(require_auth)]` applies to ALL routes in that router. If selectors shares a router with protected endpoints, it gets auth too — breaking am-ext on first install.
**How to avoid:** Put `/ext/selectors.json` in its own router with no `dependencies`. Pattern 5 above shows this explicitly.
**Warning signs:** am-ext console shows 401/403 at startup; selector loading fails.

#### Pitfall 4: lru_cache Hides Startup Errors Until First Request
**What goes wrong:** `get_pipeline()` with `lru_cache` defers env var validation to first request. Server starts without error, then returns 500 on first `/ingest/research` call.
**How to avoid:** Call `get_pipeline()` inside a FastAPI `lifespan` context manager (Pattern 1 above) so failures surface at startup.
**Warning signs:** Server logs show clean startup; first POST returns 500 with a KeyError on `NEO4J_URI`.

#### Pitfall 5: Blocking the Event Loop with Sync Pipeline
**What goes wrong:** `ResearchIngestionPipeline.ingest()` is synchronous (Phase 1/2 pattern). Calling it directly inside `async def` blocks uvicorn's event loop for the duration of the ingest, stalling all concurrent requests.
**How to avoid:** Use `await loop.run_in_executor(None, pipeline.ingest, body.model_dump())` to offload to a thread pool.
**Warning signs:** Requests queue up under light concurrency; uvicorn shows long response times.

#### Pitfall 6: HTTPBearer Returns 403 (Not 401) on Missing Header
**What goes wrong:** Tests assert `status_code == 401` for missing `Authorization` header, but `fastapi.security.HTTPBearer` returns HTTP 403 when the header is absent entirely. Tests fail unexpectedly.
**Why it happens:** FastAPI's `HTTPBearer` distinguishes "no credentials" (403) from "wrong credentials" (401). This is intentional per HTTP spec — 403 means "I know who you are (nobody) and you can't enter".
**How to avoid:** Tests must assert 403 for missing header, 401 for wrong token. Pattern shown in test fixture section below.
**Warning signs:** `AssertionError: 401 != 403` in test output.

---

### Open Questions (02-04)

1. **MCP SSE path after mounting**
   - What we know: `FastMCP.sse_app()` returns Starlette with internal routes. After `app.mount("/mcp", ...)`, full path is `/mcp` + internal path (likely `/mcp/sse`).
   - What's unclear: Exact internal SSE path in mcp 1.26.0 without running the full server.
   - Recommendation: Wave 0 integration test hits `/mcp/sse` and validates the path. Document in server README.

2. **am_server package registration in pyproject.toml**
   - What we know: Current `[tool.hatch.build.targets.wheel] packages = ["src/codememory"]`. am_server is a new package at `src/am_server/`.
   - Recommendation: Add `"src/am_server"` to the `packages` list. Splitting into a separate distributable is Phase 5/6 scope.

3. **Port assignment**
   - Recommendation: Default `AM_SERVER_PORT=8765`. Document in `.env.example`.

---

## Validation Architecture (02-04 addition)

### Test Framework
(Same as existing phase — pytest 7.x + pytest-asyncio + pytest-mock)

| Property | Value |
|----------|-------|
| Framework | pytest 7.x + `fastapi.testclient.TestClient` (uses httpx internally) |
| Quick run command | `pytest tests/test_am_server.py -x -q --tb=short` |
| Full suite command | `pytest tests/ -q --tb=short` |

**Note:** `TestClient` is included in FastAPI and uses `httpx` (already installed). No additional test dependency needed.

### Phase 02-04 Requirements to Test Map

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|-------------|
| `GET /health` returns `{"status": "ok"}` without auth | unit | `pytest tests/test_am_server.py::test_health -x` | ❌ Wave 0 |
| `POST /ingest/research` with valid Bearer token returns 202 | unit | `pytest tests/test_am_server.py::test_ingest_research_ok -x` | ❌ Wave 0 |
| `POST /ingest/research` without Bearer header returns 403 | unit | `pytest tests/test_am_server.py::test_ingest_no_auth -x` | ❌ Wave 0 |
| `POST /ingest/research` with wrong token returns 401 | unit | `pytest tests/test_am_server.py::test_ingest_bad_token -x` | ❌ Wave 0 |
| `POST /ingest/research` delegates to `ResearchIngestionPipeline.ingest()` with correct payload | unit | `pytest tests/test_am_server.py::test_ingest_delegates -x` | ❌ Wave 0 |
| `GET /search/research?q=...&limit=5` returns `{"results": [...]}` with auth | unit | `pytest tests/test_am_server.py::test_search_research_ok -x` | ❌ Wave 0 |
| `GET /ext/selectors.json` returns `{"version": 1, "platforms": {...}}` without auth | unit | `pytest tests/test_am_server.py::test_selectors_shape -x` | ❌ Wave 0 |
| `GET /ext/selectors.json` does not require Authorization header | unit | `pytest tests/test_am_server.py::test_selectors_no_auth -x` | ❌ Wave 0 |
| `require_auth` raises 503 when `AM_SERVER_API_KEY` env var is not set | unit | `pytest tests/test_am_server.py::test_auth_missing_key -x` | ❌ Wave 0 |
| FastMCP app is accessible at `/mcp` path (returns non-404) | unit | `pytest tests/test_am_server.py::test_mcp_mounted -x` | ❌ Wave 0 |

### Test Fixture Pattern

```python
# tests/test_am_server.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AM_SERVER_API_KEY", "test-key-abc")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    # Patch pipeline to avoid real service connections
    with patch("am_server.dependencies.ResearchIngestionPipeline") as mock_cls:
        mock_cls.return_value = MagicMock()
        # Clear lru_cache between tests
        from am_server import dependencies
        dependencies.get_pipeline.cache_clear()
        from am_server.app import create_app
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ingest_no_auth(client):
    # Missing Authorization header -> HTTPBearer returns 403
    resp = client.post("/ingest/research", json={
        "type": "finding", "content": "test",
        "project_id": "p1", "session_id": "s1", "source_agent": "claude"
    })
    assert resp.status_code == 403


def test_ingest_bad_token(client):
    # Wrong token -> require_auth returns 401
    resp = client.post(
        "/ingest/research",
        headers={"Authorization": "Bearer wrong-key"},
        json={"type": "finding", "content": "test",
              "project_id": "p1", "session_id": "s1", "source_agent": "claude"},
    )
    assert resp.status_code == 401


def test_selectors_no_auth(client):
    # No auth header needed for selectors
    resp = client.get("/ext/selectors.json")
    assert resp.status_code in (200, 404)  # 404 acceptable if file not yet created
```

### Sampling Rate
- **Per task commit:** `pytest tests/test_am_server.py -x -q --tb=short`
- **Per wave merge:** `pytest tests/ -q --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps (02-04)
- [ ] `tests/test_am_server.py` — FastAPI TestClient tests for all endpoints
- [ ] `src/am_server/data/selectors.json` — initial selectors file (required for `test_selectors_shape`)
- [ ] `src/am_server/__init__.py` and package skeleton — required before any test imports
- [ ] `dependencies.get_pipeline.cache_clear()` call pattern in fixture — requires `lru_cache` on `get_pipeline`
