# Architecture Patterns

**Project:** Agentic Memory - Modular Knowledge Graph
**Researched:** 2026-03-20
**Confidence:** MEDIUM (existing codebase analysis HIGH, external patterns MEDIUM)

## Executive Summary

Recommended architecture: **Hub-and-Spoke** pattern where each content module (code, web, chat) operates independently with its own database and ingestion pipeline, connected through a unified MCP server interface that routes and aggregates queries.

**Key principles:**
- Database-per-module by default (prevents embedding model conflicts)
- Shared ingestion framework (abstract base classes for code reuse)
- Modular independence (each module works standalone)
- Unified agent interface via MCP server (routing + aggregation)

## Recommended Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────┐
│            AI Agent (Claude, GPT, etc.)         │
└────────────────┬────────────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────────────┐
│              MCP Server (FastMCP)               │
│  ┌──────────────────────────────────────────┐  │
│  │         Module Router                     │  │
│  │  - Dispatch queries based on scope/type  │  │
│  │  - Aggregate cross-module results         │  │
│  └──────────────────────────────────────────┘  │
└──┬───────────────┬────────────────┬────────────┘
   │               │                │
   v               v                v
┌──────────┐  ┌──────────┐  ┌──────────┐
│   Code   │  │   Web    │  │   Chat   │
│  Module  │  │ Research │  │  Module  │
│          │  │  Module  │  │          │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │              │
     v             v              v
┌──────────┐  ┌──────────┐  ┌──────────┐
│  Neo4j   │  │  Neo4j   │  │  Neo4j   │
│   :7687  │  │   :7688  │  │   :7689  │
│ (OpenAI) │  │ (Gemini) │  │ (Gemini) │
└──────────┘  └──────────┘  └──────────┘
```

### Data Flow

**Ingestion:**
```
Content → Parser → Pass 1-4 → Neo4j → Vector Index
```

**Query:**
```
Agent → MCP → Router → Module(s) → Aggregator → Formatted Results
```

**Configuration:**
```
.codememory/config.json → Config Manager → Module Init
```

## Component Boundaries

### 1. MCP Server
**Responsibility:** Unified agent interface
- Tool registration (`search_web_memory`, `search_conversations`, `semantic_search`)
- Request routing based on scope parameter
- Result aggregation across modules
- Authentication and rate limiting

**Interface:**
```python
@mcp.tool()
def semantic_search(query: str, scope: list[str] = ["code", "web", "chat"]):
    """Search across specified modules."""
    results = []
    for module_name in scope:
        if module_name in MODULES:
            results.extend(MODULES[module_name].search(query))
    return aggregate_results(results)
```

### 2. Module Router
**Responsibility:** Dispatch queries based on scope/type
- Load enabled modules from config
- Route queries to appropriate modules
- Handle module unavailability gracefully
- Normalize results across different embedding models

### 3. Code Module (Existing)
**Responsibility:** Tree-sitter parsing, AST analysis
- Python/JavaScript/TypeScript parsing
- Function/class extraction
- Import dependency tracking
- OpenAI text embeddings

### 4. Web Research Module (New)
**Responsibility:** Web content ingestion and search
- Crawl4AI integration for web pages
- PDF text extraction
- Brave Search API integration
- Gemini multimodal embeddings
- Scheduled research automation

### 5. Conversation Module (New)
**Responsibility:** Chat log ingestion and context retrieval
- Conversation log parsing (JSON, text, markdown)
- Session boundary detection
- Incremental message append
- User/session tracking
- Gemini embeddings for semantic search

### 6. Ingestion Framework (Shared)
**Responsibility:** Common 4-pass pipeline orchestration
- Pass 1: Structure scan (identify changed content)
- Pass 2: Entity extraction (messages, sections, functions)
- Pass 3: Relationship linking (connections between entities)
- Pass 4: Embedding generation (vector representations)

**Abstract Base Classes:**
```python
class ContentParser(ABC):
    @abstractmethod
    def parse(self, content: Any) -> ParsedContent:
        pass

class IngestorPipeline(ABC):
    @abstractmethod
    def pass_1_structure_scan(self) -> list[ContentItem]:
        pass

    @abstractmethod
    def pass_2_entity_extraction(self, items: list[ContentItem]) -> list[Entity]:
        pass

    # ... etc

class EmbeddingService(ABC):
    @abstractmethod
    def get_embedding(self, text: str) -> list[float]:
        pass
```

### 7. Embedding Service (Shared)
**Responsibility:** Model-specific embedding generation
- OpenAI client for code module
- Gemini client for web/chat modules
- Retry logic and circuit breaker
- Batch processing support

### 8. Config Manager
**Responsibility:** Per-repo + per-module configuration
- Load `.codememory/config.json`
- Environment variable overrides
- Module enablement flags
- Embedding model validation (prevent conflicts)

## Patterns to Follow

### Pattern 1: 4-Pass Ingestion Pipeline

**What:** All modules use same multi-pass structure
1. **Pass 1 - Structure Scan**: Identify changed content
2. **Pass 2 - Entity Extraction**: Parse entities (functions, messages, sections)
3. **Pass 3 - Relationship Linking**: Create graph relationships
4. **Pass 4 - Embedding Generation**: Generate vectors

**Why:** Consistent architecture, code reuse, proven pattern

### Pattern 2: Separate Databases by Default

**What:** Each module uses its own Neo4j database
- Code: `bolt://localhost:7687`
- Web: `bolt://localhost:7688`
- Chat: `bolt://localhost:7689`

**Why:** Prevents embedding model conflicts, enables independent scaling

### Pattern 3: Module Independence

**What:** Each module works standalone
- No direct imports between modules
- Communication via events or MCP routing
- Shared dependencies only via abstract interfaces

**Why:** Modular deployment, easier testing, clear ownership

### Pattern 4: Incremental Ingestion

**What:** Only reprocess changed content
- Code: MD5 hash comparison
- Web: Last-Modified headers
- Chat: Sequence numbers

**Why:** Performance, cost savings (embedding API calls)

### Pattern 5: MCP-Centric Integration

**What:** All agent access via MCP tools
- No direct database access from agents
- Unified search interface
- Module routing handled server-side

**Why:** Clean abstraction, agent-agnostic, future-proof

## Anti-Patterns to Avoid

### 1. Mixed Embedding Models in Unified Database
**Problem:** OpenAI (3072d) + Gemini (768d) in same vector index
**Consequence:** Runtime errors, corrupted similarity scores
**Solution:** Separate databases OR standardize on one embedding model

### 2. Hardcoded Module Dependencies
**Problem:** Code module directly imports WebModule
**Consequence:** Cannot deploy modules independently
**Solution:** Event-based communication or MCP routing

### 3. Storing Raw Content in Graph Nodes
**Problem:** 50KB file contents as node properties
**Consequence:** Neo4j memory bloat, slow queries
**Solution:** Store only metadata, reference external storage

### 4. Synchronous Cross-Module Queries
**Problem:** Sequential blocking calls across modules
**Consequence:** Latency compounds (500ms → 1500ms for 3 modules)
**Solution:** Async parallel queries with `asyncio.gather()`

## Scalability Considerations

| Scale | 100 Files/Pages | 10K Files/Pages | 1M Files/Pages |
|-------|----------------|-----------------|----------------|
| **Ingestion Time** | Minutes | Hours (parallel) | Days (distributed) |
| **Neo4j Memory** | 100MB heap | 2-4GB heap | 32GB+ heap |
| **Vector Search** | <50ms p99 | <200ms p99 | <500ms p99 |
| **Module Isolation** | Optional | Recommended | **Required** |

## Component Build Order

**Phase 1: Foundation** (Weeks 1-2)
1. Ingestion Framework Refactor (extract abstract base classes)
2. Config Schema Extension (module-specific settings)
3. Module Registry + Routing (MCP server loader)

**Phase 2: Web Research Module** (Weeks 3-5)
4. WebParser + Crawl4AI Integration
5. Web Ingestion Pipeline (4-pass)
6. Gemini Embedding Service
7. Web Module CLI + MCP Tools

**Phase 3: Conversation Module** (Weeks 6-7)
8. ChatParser (JSON/text format support)
9. Chat Ingestion Pipeline (incremental append)
10. Chat Module CLI + MCP Tools

**Phase 4: Advanced Features** (Weeks 8-9)
11. Scheduled Research (Web Module)
12. Cross-Module Aggregation

**Phase 5: Operational Hardening** (Week 10)
13. Multi-Database Support
14. Documentation + Migration Guide

### Critical Path Dependencies

```
Foundation (1-3)
    ├─> Web Module (4-7)  ───┐
    │                        ├─> Cross-Module (12)
    └─> Chat Module (8-10) ──┘
```

**Parallelization:** Web and Chat modules can be built in parallel after Foundation

## Module Isolation vs Integration Tradeoffs

### Isolation (Separate Databases) - **Recommended**

**Pros:**
- Embedding model flexibility
- Independent scaling
- Fault isolation
- Clear ownership

**Cons:**
- Operational complexity (3 databases)
- Cross-module queries require federation
- Higher resource usage

**Best for:** Production deployments, different embedding models, large scale

### Integration (Unified Database)

**Pros:**
- Simpler operations
- Cross-module queries are native Cypher
- Lower resource usage

**Cons:**
- **MUST use same embedding model** (vector index constraint)
- Performance interference
- Schema conflicts

**Best for:** Development/testing, single embedding model, small scale

### Hybrid Approach - **Recommended**

Separate databases, unified schema patterns. Can deploy unified initially, split later without code changes.

## Sources

**Confidence:** MEDIUM
- Existing codebase analysis: HIGH (D:\code\agentic-memory\src\codememory)
- Neo4j patterns: MEDIUM (general knowledge, not verified against Neo4j 5.25 docs)
- GraphRAG architecture: MEDIUM (established pattern, not specific vendor docs)
- Embedding model characteristics: MEDIUM (training data, not verified against current APIs)

**Gaps:** Latest Neo4j 5.25 vector index capabilities, current Google Gemini embedding API specifications, Brave Search API current rate limits, Crawl4AI current feature set

---

*Architecture research completed: 2026-03-20*
*Recommendation: Validate Neo4j 5.25 multi-database support and Gemini API specs before implementation*
