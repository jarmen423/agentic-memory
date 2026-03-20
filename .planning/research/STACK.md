# Technology Stack - Universal Knowledge Graph Extensions

**Project:** Agentic Memory (Web Research + Conversation Memory)
**Researched:** 2026-03-20
**Confidence:** MEDIUM (based on training data, official docs inaccessible during research)

## Executive Summary

Extending existing code-focused knowledge graph (Neo4j + tree-sitter + OpenAI embeddings) with two new modules: Web Research Memory and Agent Conversation Memory. Core architectural principle: **separate databases by default** to prevent embedding model conflicts, with optional unified mode when using consistent embedding models.

**Key stack additions:**
- **Multimodal embeddings**: Google Gemini (`gemini-embedding-2-preview`) for web/conversation content
- **Web crawling**: Crawl4AI for PDF/web extraction + Playwright for dynamic content
- **Conversation storage**: Neo4j graph with conversational structure preservation
- **API integrations**: Brave Search API for automated research pipelines

## Recommended Stack

### Multimodal Embeddings

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Google Gemini Embeddings** | `gemini-embedding-2-preview` | Multimodal embeddings (text, images, future video/audio) | Unified embedding model for multimodal content. Supports text + images natively. Vertex AI integration required. **MEDIUM confidence** - training data indicates this model exists, but official API status unverified. |
| `google-cloud-aiplatform` | `>=1.65.0` | Python client for Vertex AI / Gemini API | Official Google SDK for Gemini embeddings. Handles auth, rate limiting, batching. |
| Alternative: OpenAI `text-embedding-3-large` | `latest` | Fallback text-only embeddings | Already in use for code memory. Use if Gemini access unavailable or unified database mode needed. Does NOT support images. |
| Alternative: Nvidia Nemotron | `latest` via API | High-performance embeddings | Good performance on retrieval tasks. **LOW confidence** - availability/API status unverified. |

**Rationale:**
- Gemini chosen over OpenAI CLIP because: (1) better text+image co-embedding, (2) single API vs separate models, (3) future-proof for video/audio
- Separate embedding models per module (OpenAI for code, Gemini for web/chat) requires separate Neo4j databases to prevent vector space conflicts
- If unified database desired, standardize on ONE model across all modules

**Installation:**
```bash
# Gemini/Vertex AI
pip install google-cloud-aiplatform>=1.65.0

# OpenAI (already installed)
pip install openai>=1.0.0
```

### Web Crawling & Content Extraction

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Crawl4AI** | `>=0.3.0` | Web scraping, PDF parsing, content extraction | All-in-one solution for web research workflows. Handles PDFs, JavaScript rendering, intelligent content extraction. **LOW confidence** - training data awareness only, version/status unverified. |
| **Playwright** | `>=1.45.0` | Browser automation for dynamic content | For sites requiring JavaScript execution. Industry standard, well-maintained. |
| `playwright-python` | `>=1.45.0` | Python bindings for Playwright | Official Python API. Async-compatible. |
| Optional: **Vercel agent-browser** | `latest` | AI-agent-friendly browser abstraction | Wraps Playwright with agent-optimized APIs. **LOW confidence** - may not be production-ready or Python-compatible. |
| **Brave Search API** | API-based | Web search results for research automation | Free tier available (2,500 queries/month). |
| `PyPDF2` or `pypdf` | `>=3.0.0` | PDF parsing fallback | If Crawl4AI PDF extraction insufficient. |
| `beautifulsoup4` | `>=4.12.0` | HTML parsing | For simpler scraping tasks or as Crawl4AI fallback. |
| `lxml` | `>=5.0.0` | Fast XML/HTML parsing | Backend for BeautifulSoup. C-based, faster. |

**Rationale:**
- **Crawl4AI** as primary: integrates browser automation + PDF + intelligent extraction in one package
- **Playwright** over Selenium: better async support, faster, modern API
- **Vercel agent-browser**: promising but unverified - keep as research flag for Phase 2+
- **Brave Search API** over alternatives: free tier for prototyping, JSON responses

**Installation:**
```bash
# Primary stack
pip install crawl4ai>=0.3.0
pip install playwright>=1.45.0
python -m playwright install  # Install browser binaries

# Fallbacks/utilities
pip install beautifulsoup4>=4.12.0 lxml>=5.0.0
pip install pypdf>=3.0.0
```

### Conversation Memory Storage

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Neo4j** | `5.25+` | Conversation graph storage | Already in stack. Models conversations as graphs (User→Message→Conversation→Session). |
| `neo4j` (Python driver) | `>=5.14.0` | Neo4j Python client | Already in use. Supports vector indexes for semantic search. |
| Alternative: **PostgreSQL + pgvector** | `16+` with pgvector | Relational + vector hybrid | Simpler model if graph relationships not needed. **Consider if:** conversation queries are purely semantic. |
| Alternative: **ChromaDB** | `>=0.5.0` | Purpose-built vector database | Lightweight, embedded option. **Limitation:** loses conversation structure. |

**Rationale:**
- **Neo4j chosen** because: (1) already in stack, (2) preserves conversation structure, (3) enables hybrid queries (semantic + graph traversal)
- Separate database instance recommended (avoids embedding model conflicts)

**Graph Schema (Conversation Module):**
```cypher
(:User)-[:SENT]->(:Message)-[:IN_CONVERSATION]->(:Conversation)
(:Message)-[:NEXT]->(:Message)  // Temporal ordering
(:Message)-[:MENTIONS]->(:Topic)
(:Conversation)-[:IN_SESSION]->(:Session)
```

### API Integrations

| Service | Client Library | Purpose | Why |
|---------|---------------|---------|-----|
| **Brave Search API** | `requests` + custom client | Automated web research | Free tier, good results, JSON responses. |
| **Google Vertex AI** | `google-cloud-aiplatform` | Gemini embeddings | Required for Gemini access. |
| **OpenAI API** | `openai>=1.0.0` | Code embeddings (existing) | Already in use for code memory module. |

**Configuration:**
```bash
# Required API keys (add to .env or config.json)
GOOGLE_CLOUD_PROJECT=<project-id>
GOOGLE_APPLICATION_CREDENTIALS=<path-to-service-account-json>
BRAVE_SEARCH_API_KEY=<api-key>
OPENAI_API_KEY=<api-key>  # Existing
```

### Shared Infrastructure (Existing + Extensions)

| Component | Technology | Notes |
|-----------|-----------|-------|
| **CLI framework** | Click/Typer | Existing. Extend with `web-init`, `web-ingest`, `chat-init`, `chat-ingest` commands. |
| **MCP server** | FastMCP | Existing. Add tools: `search_web_memory`, `ingest_url`, `search_conversations`, `add_message`. |
| **File watching** | watchdog | Existing. Not needed for web/chat modules (different ingestion pattern). |
| **Async runtime** | asyncio | Neo4j driver + Playwright both support async. |
| **Configuration** | python-dotenv + JSON config | Existing pattern. Extend config schema with module-specific settings. |
| **Testing** | pytest + pytest-asyncio | Existing. Add fixtures for web/conversation test data. |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| **Multimodal embeddings** | Google Gemini | OpenAI CLIP | CLIP is image-focused; Gemini better text+image co-embedding. |
| **Web crawling** | Crawl4AI | Scrapy | Scrapy overkill for simple URL ingestion. |
| **Browser automation** | Playwright | Selenium | Selenium legacy, slower, poorer async support. |
| **Conversation storage** | Neo4j graph | PostgreSQL + pgvector | Postgres simpler but loses conversation structure. |
| **Search API** | Brave Search | Google Custom Search API | Google CSE complex pricing, lower free tier. |

## Installation Summary

### Core Dependencies (New)

```bash
# Multimodal embeddings
pip install google-cloud-aiplatform>=1.65.0

# Web crawling
pip install crawl4ai>=0.3.0
pip install playwright>=1.45.0
python -m playwright install  # Browser binaries

# Utilities
pip install beautifulsoup4>=4.12.0 lxml>=5.0.0
pip install pypdf>=3.0.0
```

### Existing Dependencies (No Changes)

```bash
# Already installed for code memory
pip install neo4j>=5.14.0
pip install openai>=1.0.0
pip install python-dotenv
pip install watchdog
pip install mcp
```

## Configuration Schema Extensions

Extend `.codememory/config.json`:

```json
{
  "modules": {
    "code": {
      "enabled": true,
      "database": "bolt://localhost:7687",
      "embedding_model": "openai:text-embedding-3-large"
    },
    "web_research": {
      "enabled": true,
      "database": "bolt://localhost:7688",  // Separate instance
      "embedding_model": "gemini:gemini-embedding-2-preview",
      "brave_api_key": "${BRAVE_SEARCH_API_KEY}",
      "crawl_config": {
        "max_depth": 2,
        "allow_pdf": true,
        "javascript_rendering": true
      }
    },
    "conversation": {
      "enabled": true,
      "database": "bolt://localhost:7689",  // Separate instance
      "embedding_model": "gemini:gemini-embedding-2-preview",
      "auto_capture": false,
      "session_timeout_hours": 24
    }
  },
  "vertex_ai": {
    "project_id": "${GOOGLE_CLOUD_PROJECT}",
    "location": "us-central1",
    "credentials_path": "${GOOGLE_APPLICATION_CREDENTIALS}"
  }
}
```

**Validation rules:**
- If any two modules share same `database` URI, they MUST use same `embedding_model`
- Warn user if mixing embedding models in unified database

## Docker Compose Extensions

Extend `docker-compose.yml` for multiple Neo4j instances:

```yaml
services:
  neo4j-code:
    image: neo4j:5.25-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/password

  neo4j-web:
    image: neo4j:5.25-community
    ports:
      - "7475:7474"
      - "7688:7687"
    environment:
      NEO4J_AUTH: neo4j/password
    volumes:
      - neo4j-web-data:/data

  neo4j-conversation:
    image: neo4j:5.25-community
    ports:
      - "7476:7474"
      - "7689:7687"
    environment:
      NEO4J_AUTH: neo4j/password
    volumes:
      - neo4j-conversation-data:/data

volumes:
  neo4j-web-data:
  neo4j-conversation-data:
```

## Confidence Assessment

| Technology | Confidence | Rationale |
|------------|------------|-----------|
| Google Gemini embeddings | **MEDIUM** | Training data indicates existence, API details unverified. |
| Crawl4AI | **LOW** | Training data awareness only. Verify version, API stability. |
| Playwright | **HIGH** | Industry standard, well-documented, stable Python bindings. |
| Vercel agent-browser | **LOW** | Uncertain maturity, Python compatibility. Flag for Phase 2. |
| Neo4j for conversations | **HIGH** | Proven in existing codebase, graph model well-suited. |
| Brave Search API | **MEDIUM** | Known API, free tier confirmed in training data. |

## Research Flags

**Requires official verification before implementation:**

1. **Google Gemini API**: Confirm `gemini-embedding-2-preview` model name, pricing, quotas, image input format
2. **Crawl4AI**: Verify current version, PDF extraction capabilities, JavaScript rendering reliability
3. **Vercel agent-browser**: Evaluate maturity, Python SDK existence, production readiness
4. **Brave Search API**: Confirm free tier limits (2,500/month in training data), response format, rate limits

## Sources

**Confidence note:** This research was conducted with web search tools unavailable. Recommendations based on training data knowledge (cutoff: January 2025). **All recommendations require verification with official documentation** before implementation.

**Recommended verification sources:**
- Google Gemini: https://cloud.google.com/vertex-ai/docs/generative-ai/embeddings/get-text-embeddings
- Crawl4AI: https://github.com/unclecode/crawl4ai
- Playwright: https://playwright.dev/python/
- Brave Search API: https://brave.com/search/api/
- Neo4j Vector Indexes: https://neo4j.com/docs/cypher-manual/current/indexes-for-vector-search/

---

**Next steps:** Validate HIGH/MEDIUM confidence recommendations with official docs. Investigate LOW confidence items for feasibility before roadmap creation.
