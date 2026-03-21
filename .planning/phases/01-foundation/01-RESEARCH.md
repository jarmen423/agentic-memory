# Phase 1: Foundation - Research

**Researched:** 2026-03-20
**Domain:** Python abstract base classes, embedding service abstraction, Neo4j vector indexes, entity extraction LLMs, config validation, Docker Compose
**Confidence:** HIGH (key claims verified against official docs and installed packages)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Package Structure**
- New modules live as submodules inside `codememory/`: `codememory/web/`, `codememory/chat/`
- Shared infrastructure lives in `codememory/core/` submodule
- Single pip package (`agentic-memory`) — no separate installable packages

**Base Class Strategy**
- `BaseIngestionPipeline` base class in `codememory/core/`
- Parsing/chunking is NOT shared — each module implements its own
- Embedding is NOT shared — each module independently instantiates with the right model, but the embedding service abstraction handles API differences
- Graph writing patterns ARE shared — `BaseIngestionPipeline` handles node creation with proper labels, entity extraction, entity relationship wiring, and metadata population
- `KnowledgeGraphBuilder` adopts via subclassing: `DOMAIN_LABEL = "Code"`, `super().__init__()`, internal parsing logic unchanged

**Graph Schema: Memory/Entity Dual Layer**
- Entity Layer: first-class `:Entity` nodes — `:Entity:Project`, `:Entity:Person`, `:Entity:Business`, `:Entity:Technology`, `:Entity:Concept`
- Memory Layer: `:Memory:{Domain}:{Source}` multi-label scheme
- Relationships: Memory nodes connect to Entity nodes via `:ABOUT`, `:MENTIONS`, `:BELONGS_TO`
- Entity types: fixed core taxonomy (project, person, business, technology, concept) extensible via config

**First-Class Node Metadata** (Required on every Memory node)
- `source_key`, `session_id`, `source_type`, `ingested_at`, `ingestion_mode`, `embedding_model`, `project_id`, `entities`, `entity_types`

**Denormalized Entity Metadata + Enriched Embeddings**
- Entities stored as BOTH relationships AND property arrays on Memory nodes
- Entity-enriched embedding text: `f"Context: {entity_str}\n\n{chunk_text}"`

**Auto Entity Extraction**
- One LLM call per document (not per chunk)
- Target providers: Groq or Cerebras (OpenAI-compatible, JSON mode required)
- Extraction prompt constrained to allowed entity types list

**Source Registry**
- Dict mapping source key to label tier
- `node_labels()` method on base class reads from registry
- Registration via explicit imports + auto-registration at import time

**Database Topology**
- Single Neo4j database (NOT three separate instances)
- Multiple vector indexes on different label sets for different dimensions:
  - `code_embeddings` on `:Memory:Code` nodes (3072d, OpenAI)
  - `web_embeddings` on `:Memory:Research` nodes (768d, Gemini)
  - `chat_embeddings` on `:Memory:Conversation` nodes (768d, Gemini)
- Connection manager supports both local Docker and remote (Neo4j Aura) via URI config

**Backward Compatibility**
- No migration scripts needed — fresh project, users re-index from source

**Config UX**
- Defer detailed config UX decisions — not blocking for Phase 1
- Config must support: per-module embedding model selection, extraction LLM config, entity type extensions, Neo4j URI (local or remote)
- Priority hierarchy: env vars > config file > defaults

### Claude's Discretion
- Exact config file schema/structure (as long as it supports requirements above)
- Abstract base class method signatures (as long as entity extraction flow and metadata fields are implemented)
- Docker Compose service configuration details
- CLI scaffolding command structure (as long as web-init, web-ingest, web-search, chat-init, chat-ingest are stubbed)
- Unit test framework and structure

### Deferred Ideas (OUT OF SCOPE)
- Detailed config UX (config file format, interactive init prompts)
- Web UI for entity browsing
- Entity deduplication/merging ("React" vs "ReactJS")
- Entity relationship types between entities
</user_constraints>

---

## Summary

Phase 1 establishes the shared infrastructure all memory modules build on. The core challenge is designing a `BaseIngestionPipeline` ABC with the right abstraction boundaries: parsing is NOT shared, embedding is NOT shared, but graph-writing and entity extraction patterns ARE shared. The embedding service abstraction must handle Gemini (via `google-genai` SDK with AI Studio API key — no Vertex AI required), OpenAI (already in codebase), and Nvidia Nemotron (OpenAI SDK with `base_url` override). The critical architecture insight is that a single Neo4j instance supports multiple vector indexes on different label sets with different dimensions — this is confirmed available in Community Edition — so three Neo4j instances are NOT needed.

The entity extraction LLM must support JSON mode. Both Groq and Cerebras satisfy this — Groq SDK 0.33.0 is already installed, uses `response_format={"type": "json_object"}` pattern, and the `groq` library follows OpenAI SDK conventions exactly. The `google-genai` SDK 1.32.0 is also already installed, authenticates via `GEMINI_API_KEY` env var, and `gemini-embedding-001` outputs 3072d by default (configurable down to 768d via `output_dimensionality` parameter).

**Primary recommendation:** Use `abc.ABC` + `@abstractmethod` for `BaseIngestionPipeline`. Build `EmbeddingService` as a provider-dispatching class (not ABC) that wraps all three providers behind a single `.embed(text)` interface. Use the existing `Config` deep-merge pattern to extend DEFAULT_CONFIG with new sections.

---

## Standard Stack

### Core (Phase 1 specific additions)

| Library | Installed Version | Purpose | Why Standard |
|---------|------------------|---------|--------------|
| `google-genai` | 1.32.0 (already installed) | Gemini embedding calls | New official Google Gen AI SDK; AI Studio API key, no Vertex AI needed |
| `groq` | 0.33.0 (already installed) | Entity extraction LLM | Sub-100ms inference, JSON mode, OpenAI-compatible client |
| `pydantic` | not installed (add) | Config validation, structured outputs | Industry standard for schema validation + dataclass replacement |
| `abc` (stdlib) | Python 3.10+ | Abstract base classes | No deps; `@abstractmethod` enforces subclass contracts |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `cerebras-cloud-sdk` | not installed (optional) | Entity extraction fallback | If Groq is unavailable; same OpenAI-compatible interface |
| `openai` | 2.3.0 (already installed) | Code embeddings + Nemotron (base_url override) | Already in codebase; Nemotron uses same SDK with `base_url` override |
| `neo4j` | 6.1.0 (already installed) | Database connection + vector index creation | Already in codebase |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `google-genai` (AI Studio) | `google-cloud-aiplatform` (Vertex AI) | Vertex AI requires GCP project + service account; AI Studio just needs `GEMINI_API_KEY` — simpler for Phase 1 |
| `groq` SDK | OpenAI SDK with `base_url` | Groq's own SDK is thinner and already installed; either works |
| `abc.ABC` | `typing.Protocol` | Protocol is structural (duck-typed); ABC enforces inheritance + provides better `isinstance` checks for registry pattern |

**Installation (new deps only):**
```bash
pip install pydantic>=2.0.0
```

`google-genai` 1.32.0 and `groq` 0.33.0 are already installed in the environment.

**Version verification (run before implementing):**
```bash
pip show google-genai groq pydantic neo4j openai
```

---

## Architecture Patterns

### Recommended Project Structure (new for Phase 1)

```
src/codememory/
├── core/                        # NEW: shared infrastructure
│   ├── __init__.py
│   ├── base.py                  # BaseIngestionPipeline ABC
│   ├── embedding.py             # EmbeddingService (provider dispatch)
│   ├── entity_extraction.py     # EntityExtractionService (Groq/Cerebras)
│   ├── registry.py              # SOURCE_REGISTRY dict + node_labels()
│   ├── graph_writer.py          # Shared Neo4j MERGE patterns
│   ├── connection.py            # ConnectionManager (single DB + Aura)
│   └── config_validator.py      # validate_embedding_consistency()
├── web/                         # NEW: stub submodule
│   └── __init__.py
├── chat/                        # NEW: stub submodule
│   └── __init__.py
├── ingestion/
│   ├── graph.py                 # KnowledgeGraphBuilder (subclasses BaseIngestionPipeline)
│   └── ...                      # unchanged
└── config.py                    # Extended DEFAULT_CONFIG
```

### Pattern 1: Abstract Base Class (ABC) with Class Variables

**What:** `BaseIngestionPipeline` uses `abc.ABC` with `@abstractmethod` for domain-specific methods. Class-level `DOMAIN_LABEL` forces subclass to declare its memory domain.

**When to use:** Any new memory module (web, chat) that needs to write Memory nodes to Neo4j.

**Example:**
```python
# Source: Python stdlib abc docs + project CONVENTIONS.md pattern
import abc
from typing import Any

class BaseIngestionPipeline(abc.ABC):
    """Base class for all memory ingestion pipelines."""

    DOMAIN_LABEL: str  # Subclass MUST declare: "Code", "Research", "Conversation"

    def __init__(self, connection_manager: "ConnectionManager") -> None:
        self._conn = connection_manager

    @abc.abstractmethod
    def ingest(self, source: Any) -> dict[str, Any]:
        """Ingest a source document. Returns ingestion summary."""

    def node_labels(self, source_key: str) -> list[str]:
        """Get node labels from source registry."""
        from codememory.core.registry import SOURCE_REGISTRY
        return SOURCE_REGISTRY.get(source_key, ["Memory", self.DOMAIN_LABEL])
```

**KnowledgeGraphBuilder adoption:**
```python
class KnowledgeGraphBuilder(BaseIngestionPipeline):
    DOMAIN_LABEL = "Code"

    def __init__(self, uri: str, user: str, password: str, ...) -> None:
        conn = ConnectionManager(uri=uri, user=user, password=password)
        super().__init__(conn)
        # ... rest of existing __init__ unchanged
```

### Pattern 2: EmbeddingService Provider Dispatch

**What:** Single class with provider string selects backend. Not an ABC — one class handles all providers. Uses OpenAI SDK for both OpenAI and Nemotron (via `base_url`); uses `google-genai` for Gemini.

**When to use:** Any module needing embeddings. Each module instantiates with its own config.

**Example:**
```python
# Source: google-genai SDK docs, OpenAI SDK docs, CONTEXT.md decisions
from google import genai
from openai import OpenAI

class EmbeddingService:
    """Provider-dispatching embedding service."""

    PROVIDERS = {
        "openai": {"model": "text-embedding-3-large", "dimensions": 3072},
        "gemini": {"model": "gemini-embedding-001", "dimensions": 768},
        "nemotron": {"model": "nvidia/nv-embedqa-e5-v5", "dimensions": 4096},
    }

    def __init__(self, provider: str, api_key: str, base_url: str | None = None,
                 output_dimensions: int | None = None) -> None:
        self.provider = provider
        self.model = self.PROVIDERS[provider]["model"]
        self.dimensions = output_dimensions or self.PROVIDERS[provider]["dimensions"]

        if provider == "gemini":
            self._client = genai.Client(api_key=api_key)
        else:
            self._client = OpenAI(api_key=api_key, base_url=base_url)

    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        if self.provider == "gemini":
            result = self._client.models.embed_content(
                model=self.model,
                contents=text,
                config={"output_dimensionality": self.dimensions},
            )
            return result.embeddings[0].values
        else:
            response = self._client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dimensions,
            )
            return response.data[0].embedding
```

### Pattern 3: Entity Extraction with Groq JSON Mode

**What:** One LLM call per document using `response_format={"type": "json_object"}`. Prompt constrains to allowed entity types list. Returns validated list of `{name, type}` dicts.

**When to use:** At ingest time, once per source document before chunking loop.

**Example:**
```python
# Source: Groq structured outputs docs (console.groq.com/docs/structured-outputs)
import json
from groq import Groq

ENTITY_EXTRACTION_PROMPT = """\
Extract named entities from the following text.
Return a JSON object with key "entities" containing a list of objects,
each with "name" (string) and "type" (one of: {allowed_types}).
Only extract entities clearly present in the text."""

class EntityExtractionService:
    """LLM-based entity extraction using Groq JSON mode."""

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile",
                 allowed_types: list[str] | None = None) -> None:
        self._client = Groq(api_key=api_key)
        self.model = model
        self.allowed_types = allowed_types or [
            "project", "person", "business", "technology", "concept"
        ]

    def extract(self, document_text: str) -> list[dict[str, str]]:
        """Extract entities from a document. Returns [{name, type}, ...]."""
        prompt = ENTITY_EXTRACTION_PROMPT.format(
            allowed_types=", ".join(self.allowed_types)
        )
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": document_text[:8000]},  # budget guard
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("entities", [])
```

### Pattern 4: Neo4j Vector Index Creation (Multiple Indexes, Single DB)

**What:** Create separate named vector indexes for each memory domain label set. Each index has its own `vector.dimensions` — confirmed supported in Community Edition.

**When to use:** `setup_database()` method on connection manager or base class.

**Example:**
```cypher
-- Source: neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
CREATE VECTOR INDEX code_embeddings IF NOT EXISTS
FOR (n:Memory:Code) ON n.embedding
OPTIONS { indexConfig: {
  `vector.dimensions`: 3072,
  `vector.similarity_function`: 'cosine'
}};

CREATE VECTOR INDEX web_embeddings IF NOT EXISTS
FOR (n:Memory:Research) ON n.embedding
OPTIONS { indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}};

CREATE VECTOR INDEX chat_embeddings IF NOT EXISTS
FOR (n:Memory:Conversation) ON n.embedding
OPTIONS { indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}};
```

**Note:** Neo4j 5.x Community Edition supports `LIST<INTEGER | FLOAT>` as the embedding property type. The newer native `VECTOR` type requires Enterprise/Aura. Use `LIST<FLOAT>` for Community compatibility.

### Pattern 5: Source Registry

**What:** Module-level dict in `codememory/core/registry.py`. Each ingestor registers its key at import time. `node_labels()` on the base class resolves labels from the registry.

**Example:**
```python
# codememory/core/registry.py
from typing import Final

SOURCE_REGISTRY: dict[str, list[str]] = {}

def register_source(source_key: str, labels: list[str]) -> None:
    """Register an ingestion source's label tier."""
    SOURCE_REGISTRY[source_key] = labels

# codememory/ingestion/graph.py  — registers at module import
from codememory.core.registry import register_source
register_source("code_treesitter", ["Memory", "Code", "Chunk"])
```

### Pattern 6: Config Validation (Embedding Model Consistency Check)

**What:** At startup, validate that no two label sets indexed by the same property share a vector index with incompatible dimensions. Warn loudly (log + stderr) if mismatch detected in config.

**Example:**
```python
# codememory/core/config_validator.py
import logging
from codememory.core.embedding import EmbeddingService

logger = logging.getLogger(__name__)

LABEL_DIMENSION_MAP: dict[str, int] = {
    "Code": 3072,      # OpenAI text-embedding-3-large
    "Research": 768,   # Gemini gemini-embedding-001 @ 768d
    "Conversation": 768,
}

def validate_embedding_config(config: dict) -> None:
    """Fail fast if embedding model dimensions don't match index expectations."""
    modules = config.get("modules", {})
    for module_name, module_cfg in modules.items():
        model = module_cfg.get("embedding_model", "")
        expected_dims = LABEL_DIMENSION_MAP.get(module_name.capitalize())
        # validate provider dimensions match expected index dimensions
        # raise ValueError with clear message if mismatch
```

### Anti-Patterns to Avoid

- **Parsing logic in base class:** `BaseIngestionPipeline` must NOT touch ASTs, HTML, or conversation JSON — that logic stays in subclasses. The base handles ONLY graph writing and entity extraction.
- **Shared embedding client:** Do not create a singleton `EmbeddingService` shared across modules. Each module instantiates its own with the right provider + credentials.
- **MERGE on content_hash alone:** Use composite keys `(source_key, content_hash)` — or `(source_key, source_url)` for web — to prevent cross-module node collisions.
- **CREATE instead of MERGE:** ALL Neo4j node writes must use `MERGE` for idempotency (re-ingest same content = same node).
- **Bare `except:` clauses:** Project convention is specific exception types. Use `except (openai.RateLimitError, openai.APIConnectionError)`.
- **Storing api_key in config file:** Existing `config.py` pattern already handles this — empty string means fall back to env var. Follow the same pattern for new keys.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON schema validation | Custom dict validation | `pydantic` BaseModel | Pydantic handles coercion, missing fields, type errors with clear messages |
| Retry with exponential backoff | New decorator | Generalize existing `retry_on_openai_error` → `retry_on_api_error` | Already battle-tested in codebase; just broaden exception types |
| Circuit breaker | New class | Move existing `CircuitBreaker` to `codememory/core/` | Already implemented; just relocate |
| Embedding dimension lookup | Hardcoded ifs | `EmbeddingService.PROVIDERS` dict | Single source of truth for model→dimension mapping |
| Groq/Cerebras client | Custom HTTP client | Groq SDK (installed) or OpenAI SDK with `base_url` | Both already follow OpenAI SDK patterns; no custom HTTP needed |

**Key insight:** The existing codebase already solved retry logic, circuit breaker, and config merge patterns. Phase 1 is about relocating and generalizing these, not rebuilding them.

---

## Common Pitfalls

### Pitfall 1: `IF NOT EXISTS` Missing on Vector Index Creation
**What goes wrong:** Running `CREATE VECTOR INDEX` without `IF NOT EXISTS` throws an error on second startup.
**Why it happens:** Forgetting the guard clause in `setup_database()`.
**How to avoid:** Always use `CREATE VECTOR INDEX index_name IF NOT EXISTS FOR ...`.
**Warning signs:** `Index already exists` errors in logs on service restart.

### Pitfall 2: Gemini Output Dimensions Not Specified
**What goes wrong:** `gemini-embedding-001` default is 3072d, not 768d. If you rely on defaults and set up a 768d vector index, every embed call stores a 3072d vector → Neo4j dimension mismatch error at query time.
**Why it happens:** The model default (3072d) differs from the recommended compact size (768d) for web/chat content.
**How to avoid:** Always pass `config={"output_dimensionality": 768}` (or whatever target) explicitly in every `embed_content` call. Store `self.dimensions` in `EmbeddingService` and always pass it.
**Warning signs:** `Invalid vector dimension: expected 768, got 3072` in Neo4j logs.

### Pitfall 3: Multi-Label Vector Index Syntax
**What goes wrong:** `FOR (n:Memory:Code)` syntax requires Neo4j 5.x. On older versions (< 5.18), multi-label indexes may not be supported.
**Why it happens:** Existing docker-compose uses `neo4j:5.25-community` which is fine, but developers may test against older versions.
**How to avoid:** Document minimum Neo4j version (5.18+) in setup docs. The existing docker-compose.yml already uses 5.25-community.
**Warning signs:** `SyntaxError` on index creation Cypher.

### Pitfall 4: Entity Extraction Prompt Returns Wrong JSON Key
**What goes wrong:** LLM returns `{"results": [...]}` instead of `{"entities": [...]}`. Code fails silently, returning empty entity list.
**Why it happens:** Models interpret prompt differently, especially smaller ones.
**How to avoid:** Use `response_format={"type": "json_schema", ...}` with explicit schema on Groq instead of `json_object` mode. Set `temperature=0.0`. Add fallback: if `data.get("entities") is None`, scan `data.values()` for the first list.
**Warning signs:** Every ingest produces 0 entities — nodes have empty `entities` arrays.

### Pitfall 5: `KnowledgeGraphBuilder` Constructor Signature Change
**What goes wrong:** Refactoring `KnowledgeGraphBuilder` to subclass `BaseIngestionPipeline` changes its `__init__` signature, breaking all callers in `cli.py`.
**Why it happens:** Base class constructor requires `ConnectionManager` but existing code passes raw `uri/user/password`.
**How to avoid:** Keep the existing `KnowledgeGraphBuilder.__init__(uri, user, password, ...)` signature intact. Construct `ConnectionManager` internally inside it and call `super().__init__(conn)`. Never force callers to change.
**Warning signs:** `TypeError` when running `codememory index`.

### Pitfall 6: Source Registry Import Cycle
**What goes wrong:** `codememory/core/registry.py` imports from `codememory/ingestion/graph.py` (or vice versa), causing circular import at module load.
**Why it happens:** Auto-registration at import time requires graph.py to import registry, but registry shouldn't import from graph.
**How to avoid:** `registry.py` is a leaf module — no imports from other `codememory` modules. All other modules import FROM registry, never the reverse. Registration happens in the ingestion module, not the registry module.

### Pitfall 7: Embedding Model Name Staleness
**What goes wrong:** Using `"text-embedding-004"` (old Gemini model name) instead of `"gemini-embedding-001"` in config defaults — the old model name returns an API error.
**Why it happens:** Previous STACK.md research referenced `gemini-embedding-2-preview` which is in preview and the old name `text-embeddings-004` which is legacy.
**How to avoid:** Use `"gemini-embedding-001"` — this is the stable GA model as of March 2026. The `gemini-embedding-2-preview` model exists but is in preview and may not be available on all API keys.

---

## Code Examples

### Gemini Embedding (google-genai 1.32.0)

```python
# Source: https://ai.google.dev/gemini-api/docs/embeddings (verified March 2026)
# google-genai 1.32.0 already installed
from google import genai

client = genai.Client(api_key="GEMINI_API_KEY")  # or reads GEMINI_API_KEY env var

result = client.models.embed_content(
    model="gemini-embedding-001",
    contents="Your text here",
    config={"output_dimensionality": 768},  # MUST specify — default is 3072
)
embedding = result.embeddings[0].values  # list[float], length 768
```

### Groq Entity Extraction with JSON Mode

```python
# Source: https://console.groq.com/docs/structured-outputs (verified March 2026)
# groq 0.33.0 already installed
from groq import Groq
import json

client = Groq(api_key="GROQ_API_KEY")  # or reads GROQ_API_KEY env var

response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",  # supports json_object mode
    messages=[
        {"role": "system", "content": "Extract entities. Return JSON with key 'entities'."},
        {"role": "user", "content": document_text},
    ],
    response_format={"type": "json_object"},
    temperature=0.0,
)
entities = json.loads(response.choices[0].message.content).get("entities", [])
```

### OpenAI SDK with Nemotron base_url Override

```python
# Source: CONTEXT.md decision + NVIDIA NIM docs
from openai import OpenAI

client = OpenAI(
    api_key="NVIDIA_API_KEY",
    base_url="https://integrate.api.nvidia.com/v1",
)
response = client.embeddings.create(
    model="nvidia/nv-embedqa-e5-v5",
    input="Your text here",
)
embedding = response.data[0].embedding
```

### Neo4j Multi-Label Vector Index Creation

```python
# Source: neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
# Verified: Community Edition supports LIST<FLOAT> vector indexes in 5.x

setup_queries = [
    """
    CREATE VECTOR INDEX code_embeddings IF NOT EXISTS
    FOR (n:Memory:Code) ON n.embedding
    OPTIONS { indexConfig: {
      `vector.dimensions`: 3072,
      `vector.similarity_function`: 'cosine'
    }}
    """,
    """
    CREATE VECTOR INDEX web_embeddings IF NOT EXISTS
    FOR (n:Memory:Research) ON n.embedding
    OPTIONS { indexConfig: {
      `vector.dimensions`: 768,
      `vector.similarity_function`: 'cosine'
    }}
    """,
    """
    CREATE VECTOR INDEX chat_embeddings IF NOT EXISTS
    FOR (n:Memory:Conversation) ON n.embedding
    OPTIONS { indexConfig: {
      `vector.dimensions`: 768,
      `vector.similarity_function`: 'cosine'
    }}
    """,
    # Entity uniqueness constraints
    "CREATE CONSTRAINT entity_unique IF NOT EXISTS FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE",
]

with driver.session() as session:
    for query in setup_queries:
        session.run(query)
```

### Entity-Enriched Embedding Text (from CONTEXT.md)

```python
# Source: CONTEXT.md decision (locked)
def build_embed_text(chunk_text: str, entities: list[dict[str, str]]) -> str:
    """Prepend entity context to improve vector clustering."""
    if not entities:
        return chunk_text
    entity_str = ", ".join(f"{e['name']} ({e['type']})" for e in entities)
    return f"Context: {entity_str}\n\n{chunk_text}"
```

### Memory Node MERGE with Required Metadata

```cypher
// Source: project CONTEXT.md + Pitfalls.md (MERGE for idempotency)
MERGE (m:Memory {source_key: $source_key, content_hash: $content_hash})
ON CREATE SET
  m.session_id = $session_id,
  m.source_type = $source_type,
  m.ingested_at = $ingested_at,
  m.ingestion_mode = $ingestion_mode,
  m.embedding_model = $embedding_model,
  m.project_id = $project_id,
  m.entities = $entities,
  m.entity_types = $entity_types,
  m.embedding = $embedding,
  m.text = $text
ON MATCH SET
  m.ingested_at = $ingested_at
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `google-cloud-aiplatform` for Gemini | `google-genai` SDK | 2024-2025 | Simpler — no GCP project needed, just `GEMINI_API_KEY` from AI Studio |
| `text-embeddings-004` model name | `gemini-embedding-001` (GA) | Early 2025 | `gemini-embedding-001` is the stable GA model; `text-embeddings-004` is legacy |
| 3 Neo4j instances for dimension isolation | 1 Neo4j instance + multiple vector indexes | CONTEXT.md revision | Simpler ops; entity layer naturally shared without cross-DB queries |
| `retry_on_openai_error` (OpenAI-specific) | `retry_on_api_error` (provider-agnostic) | Phase 1 | Generalize to cover Groq, Gemini, Nemotron errors too |

**Deprecated/outdated from previous research:**
- `gemini-embedding-2-preview`: Still in preview as of March 2026. Use `gemini-embedding-001` (GA) for Phase 1.
- 3-port database topology (`:7687/:7688/:7689`): REPLACED by single-instance multi-index design per CONTEXT.md decision.
- `google-cloud-aiplatform` for embeddings: Superseded by `google-genai` SDK which is already installed.

---

## Open Questions

1. **Groq model name for JSON mode**
   - What we know: `llama-3.3-70b-versatile` is a commonly-used Groq model. The docs show `openai/gpt-oss-20b` for strict structured outputs.
   - What's unclear: Which specific model gives best JSON reliability + speed tradeoff in March 2026. Groq model availability changes frequently.
   - Recommendation: Make model name configurable in `extraction_llm` config section. Default to `llama-3.3-70b-versatile` as a reasonable starting point; document how to override.

2. **Gemini `output_dimensionality` parameter name in google-genai 1.32.0**
   - What we know: The official docs show `output_dimensionality` as the config key for MRL truncation.
   - What's unclear: Whether it's `config={"output_dimensionality": 768}` or `config=types.EmbedContentConfig(output_dimensionality=768)` in SDK version 1.32.0.
   - Recommendation: Write a quick integration test first. The EmbeddingService should verify the correct parameter form before committing to it.

3. **Neo4j multi-label index for labels not yet existing**
   - What we know: `CREATE VECTOR INDEX IF NOT EXISTS` runs without error even if no nodes with that label exist yet.
   - What's unclear: Whether the index becomes queryable once nodes are created, or requires a refresh.
   - Recommendation: Test in docker-compose before writing `setup_database()`. Based on standard Neo4j behavior this should work — indexes are populated lazily.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7.0+ (already configured in pyproject.toml) |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `pytest tests/ -m unit -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|-------------|
| EmbeddingService dispatches to correct provider | unit | `pytest tests/test_embedding.py -x` | Wave 0 |
| EmbeddingService returns correct dimension count per provider | unit | `pytest tests/test_embedding.py -x` | Wave 0 |
| EntityExtractionService returns valid entity list (mocked Groq) | unit | `pytest tests/test_entity_extraction.py -x` | Wave 0 |
| Config validator raises on dimension mismatch | unit | `pytest tests/test_config_validator.py -x` | Wave 0 |
| SOURCE_REGISTRY resolves correct labels for source_key | unit | `pytest tests/test_registry.py -x` | Wave 0 |
| `build_embed_text` prepends entity context correctly | unit | `pytest tests/test_base.py::test_build_embed_text -x` | Wave 0 |
| KnowledgeGraphBuilder still initializes (backward compat) | unit | `pytest tests/test_graph.py -x` | exists |
| BaseIngestionPipeline cannot be instantiated directly | unit | `pytest tests/test_base.py::test_abc_enforcement -x` | Wave 0 |
| All 5 CLI commands are registered (web-init, etc.) | unit | `pytest tests/test_cli.py -x` | add to existing |

### Sampling Rate
- **Per task commit:** `pytest tests/ -m unit -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps (must create before implementation begins)

- [ ] `tests/test_embedding.py` — EmbeddingService unit tests (mock all API clients)
- [ ] `tests/test_entity_extraction.py` — EntityExtractionService unit tests (mock Groq)
- [ ] `tests/test_config_validator.py` — dimension mismatch validation tests
- [ ] `tests/test_registry.py` — source registry label resolution
- [ ] `tests/test_base.py` — ABC enforcement, `build_embed_text`, `node_labels()` method

---

## Sources

### Primary (HIGH confidence)
- `https://ai.google.dev/gemini-api/docs/embeddings` — Gemini embedding models, dimensions, API key auth, `google-genai` SDK usage
- `https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/` — CREATE VECTOR INDEX syntax, Community Edition support confirmed, multiple indexes with different dimensions confirmed
- `https://console.groq.com/docs/structured-outputs` — Groq JSON mode, `response_format` parameter, supported models
- Installed packages (verified with `pip show`): `google-genai==1.32.0`, `groq==0.33.0`, `neo4j==6.1.0`, `openai==2.3.0`
- Existing codebase: `src/codememory/config.py`, `src/codememory/ingestion/graph.py`, `.planning/codebase/CONVENTIONS.md`

### Secondary (MEDIUM confidence)
- WebSearch verified: Cerebras supports OpenAI-compatible API + JSON mode (cross-referenced with cerebras.ai)
- WebSearch verified: NVIDIA NIM embedding models use `base_url="https://integrate.api.nvidia.com/v1"` with OpenAI SDK (cross-referenced with NVIDIA docs)
- `.planning/research/PITFALLS.md` — pitfall inventory from earlier project research

### Tertiary (LOW confidence)
- Specific Groq model names (llama-3.3-70b-versatile for JSON mode) — model availability changes frequently; treat as starting point, not guaranteed

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified installed versions, official docs checked
- Architecture patterns: HIGH — ABC pattern is Python stdlib, Neo4j syntax verified against official docs, entity extraction pattern verified against Groq docs
- Embedding API specifics (Gemini `output_dimensionality` exact param form): MEDIUM — docs confirm the feature, exact SDK method form needs quick integration verification
- Groq model names: LOW — changes frequently; make configurable

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (Groq model availability: check before implementing)
