# Phase 4: Conversation Memory Core — Research

**Researched:** 2026-03-22
**Domain:** Conversation ingestion pipeline, GraphWriter extensions, Neo4j vector search, CLI batch ingest
**Confidence:** HIGH (all findings derived from direct codebase reads and locked CONTEXT.md decisions)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Turn schema: role, content, session_id, project_id, turn_index (required) plus 10 optional fields — see CONTEXT.md
- MERGE key: `(session_id, turn_index)` — idempotent, content_hash = `sha256(f"{session_id}:{turn_index}")`
- Embedding: user and assistant roles only. system and tool stored without embedding.
- Entity extraction: per-turn on user/assistant only. One LLM call per turn.
- Graph schema: Turn node with labels `Memory:Conversation:Turn`, Session node `Memory:Conversation:Session`, relationships HAS_TURN, PART_OF, ABOUT, MENTIONS
- MCP tool signatures: `search_conversations`, `get_conversation_context`, `add_message` — exact signatures in CONTEXT.md
- REST endpoints: `POST /ingest/conversation`, `GET /search/conversations` in `src/am_server/routes/conversation.py`
- `ConversationIngestionPipeline` subclasses `BaseIngestionPipeline` with `DOMAIN_LABEL = "Conversation"`
- Source registry: chat_mcp, chat_proxy, chat_ext, chat_cli all registered at import time
- Bug fix scope: fix `research_embeddings` and `chat_embeddings` to 768d (currently 3072d)
- Role validation: accept only ["user", "assistant", "system", "tool"], raise ValueError otherwise
- Token count approximation: `int(len(content.split()) * 1.3)` — no tiktoken
- REST ingest is the primary passive path for am-proxy and am-ext

### Claude's Discretion
- Exact Cypher for Session MERGE and last_turn_index tracking
- GraphWriter new methods needed for conversation
- Unit test fixtures and mock strategy
- CLI output formatting (tabulate or manual)

### Deferred Ideas (OUT OF SCOPE)
- Conversation analytics (sentiment, topic modeling)
- Streaming ingest (SSE or WebSocket)
- Session summarization
- Cross-session conversation threads
- Provider-specific import adapters (Claude Code export, ChatGPT export JSON)
- Confidence-weighted search
- Retroactive re-embedding of system/tool turns
</user_constraints>

---

## Summary

Phase 4 extends an already-well-structured codebase. The `ResearchIngestionPipeline` in `src/codememory/web/pipeline.py` provides a near-exact mirror for `ConversationIngestionPipeline` — the conversation pipeline is simpler because there is no chunking step (each turn is a single atomic node). The `GraphWriter` already implements the MERGE patterns for Memory nodes, entity nodes, and relationships; three new methods handle Session-specific topology. The vector index bug is confirmed: both `research_embeddings` and `chat_embeddings` are created at 3072d in `connection.py` lines 63-73 and must become 768d.

The hardest implementation decision is the `last_turn_index` MERGE pattern on the Session node — a `CASE` expression inside `ON MATCH SET` handles the max(existing, new) requirement cleanly. The surrounding-turn Cypher for `get_conversation_context` is a two-query pattern: first the vector search, then a MATCH by `(session_id, turn_index ± 1)` for context window expansion.

**Primary recommendation:** Mirror the Research pipeline structure exactly. One turn = one node = one ingest call. The pipeline is simpler than Research because no chunking and no parent node — the Session node is a lightweight grouping node, not a content container.

---

## GraphWriter Extensions

### Confirmed Existing Methods (DO NOT duplicate)

The existing `write_relationship()` method in `GraphWriter` already handles ABOUT and MENTIONS relationships from a Memory node to an Entity node. It matches on `(source_key, content_hash)`. **This method works for Turn → Entity wiring unchanged** — no new method needed for entity relationships.

```python
# Existing signature — works as-is for Turn entity relationships
def write_relationship(
    self,
    source_key: str,       # e.g. "chat_mcp"
    content_hash: str,     # sha256(f"{session_id}:{turn_index}")
    entity_name: str,
    entity_type: str,
    rel_type: str = "ABOUT",   # "ABOUT" for project, "MENTIONS" for others
) -> None: ...
```

### New Method 1: `write_session_node(props: dict) -> None`

MERGE key: `session_id` alone (globally unique caller-owned boundary).

On first turn: CREATE with `started_at`, `turn_count=1`, `last_turn_index=turn_index`.
On subsequent turns: update `last_turn_index` using CASE to track max, increment `turn_count`.

```cypher
MERGE (s:Memory:Conversation:Session {session_id: $session_id})
ON CREATE SET
    s += $props,
    s.started_at = $started_at,
    s.turn_count = 1,
    s.last_turn_index = $turn_index
ON MATCH SET
    s.last_turn_index = CASE
        WHEN s.last_turn_index < $turn_index THEN $turn_index
        ELSE s.last_turn_index
    END,
    s.turn_count = s.turn_count + 1,
    s.source_agent = $props.source_agent
```

**Parameters:** `session_id`, `turn_index` (passed separately for CASE expression), `started_at` (ISO UTC string), `props` (full Session property dict).

**Note:** `turn_count` increments on every call — this is an approximation. If the same turn is re-ingested (idempotent), the count will be off by one. This is acceptable per CONTEXT.md design (append-only, idempotent turns are a no-op at the Turn node level, but the Session node cannot know without an extra lookup). Simpler than tracking per-turn existence before writing.

### New Method 2: `write_has_turn_relationship(session_id, turn_source_key, turn_content_hash, order) -> None`

Mirrors `write_has_chunk_relationship`. Session → Turn with `order = turn_index`.

```cypher
MATCH (s:Memory:Conversation:Session {session_id: $session_id})
MATCH (t {source_key: $source_key, content_hash: $content_hash})
MERGE (s)-[rel:HAS_TURN {order: $order}]->(t)
```

**Parameters:** `session_id`, `turn_source_key` (e.g. "chat_mcp"), `turn_content_hash` (sha256 of session_id:turn_index), `order` (turn_index integer).

### New Method 3: `write_part_of_turn_relationship(turn_source_key, turn_content_hash, session_id) -> None`

Reverse arc. Turn → Session. No properties needed on the relationship.

```cypher
MATCH (t {source_key: $source_key, content_hash: $content_hash})
MATCH (s:Memory:Conversation:Session {session_id: $session_id})
MERGE (t)-[:PART_OF]->(s)
```

**Parameters:** `turn_source_key`, `turn_content_hash`, `session_id`.

### Relationship Wiring Summary

| Relationship | Method | Notes |
|---|---|---|
| Session → Turn `:HAS_TURN` | `write_has_turn_relationship()` (new) | order = turn_index |
| Turn → Session `:PART_OF` | `write_part_of_turn_relationship()` (new) | no properties |
| Turn → Entity:Project `:ABOUT` | existing `write_relationship()` | rel_type="ABOUT" |
| Turn → Entity:* `:MENTIONS` | existing `write_relationship()` | rel_type="MENTIONS" |

---

## Vector Search Patterns

### Pattern 1: `chat_embeddings` vector search (for `search_conversations` and `search_research` parity)

The existing `search_research` route uses a text fallback (no embedding in the route, relies on pipeline having access to the conn). The conversation routes should follow the same pattern but query `chat_embeddings`.

**Vector search Cypher (primary path when embedding is available):**
```cypher
CALL db.index.vector.queryNodes('chat_embeddings', $limit, $embedding)
YIELD node, score
WHERE ($project_id IS NULL OR node.project_id = $project_id)
  AND ($role IS NULL OR node.role = $role)
RETURN
    node.session_id     AS session_id,
    node.turn_index     AS turn_index,
    node.role           AS role,
    node.content        AS content,
    node.source_agent   AS source_agent,
    node.timestamp      AS timestamp,
    node.entities       AS entities,
    score
ORDER BY score DESC
LIMIT $limit
```

**Text fallback (when embedding service unavailable):**
```cypher
MATCH (n:Memory:Conversation:Turn)
WHERE toLower(n.content) CONTAINS toLower($q)
  AND ($project_id IS NULL OR n.project_id = $project_id)
  AND ($role IS NULL OR n.role = $role)
RETURN
    n.session_id    AS session_id,
    n.turn_index    AS turn_index,
    n.role          AS role,
    n.content       AS content,
    n.source_agent  AS source_agent,
    n.timestamp     AS timestamp,
    n.entities      AS entities,
    1.0 AS score
LIMIT $limit
```

**Where to embed search:** The MCP tools and the REST route both need to embed the query before hitting `db.index.vector.queryNodes`. The GraphWriter does not embed — it's a write-only service. The pipeline should expose a `search()` method that handles embedding + Cypher, or the route/tool layer handles embedding directly. **Recommendation:** add `search_conversations(query_embedding, project_id, role, limit)` to `GraphWriter` that accepts a pre-computed embedding vector (tool layer embeds the query, passes to writer). This mirrors no existing pattern exactly but keeps graph ops in GraphWriter. Alternative: put search Cypher inline in the route/tool layer the same way `search_research` does (inline `_query` closure). **Use the inline closure approach** to stay consistent with the existing `search_research` implementation.

### Pattern 2: `get_conversation_context` surrounding turns

After vector search returns matching turns, fetch ±1 turns from same session:

```cypher
MATCH (t:Memory:Conversation:Turn {session_id: $session_id})
WHERE t.turn_index IN [$prev_index, $next_index]
RETURN
    t.turn_index    AS turn_index,
    t.role          AS role,
    t.content       AS content
ORDER BY t.turn_index
```

**Implementation notes:**
- `$prev_index = max(0, turn_index - 1)` — guard against negative index
- `$next_index = turn_index + 1` — if no next turn exists, MATCH simply returns nothing
- For turn_index=0: `$prev_index = 0` and `$next_index = 1`. If prev == current, filter by `turn_index <> $current_index` to avoid returning the matched turn itself.
- Cleaner guard: pass `$prev_index = turn_index - 1` and handle turn_index=0 by passing `$prev_index = -1` (which never matches any node since turn_index >= 0).

**Preferred formulation:**
```cypher
MATCH (t:Memory:Conversation:Turn {session_id: $session_id})
WHERE t.turn_index IN [$prev_index, $next_index]
  AND t.turn_index <> $matched_turn_index
RETURN t.turn_index AS turn_index, t.role AS role, t.content AS content
ORDER BY t.turn_index
```
Where `$prev_index = turn_index - 1` (will be -1 for turn 0, no match) and `$next_index = turn_index + 1`.

**Fetch strategy:** Run one Cypher per matched turn (in a loop or batch). For `limit=5` matched turns, this is 5 additional Cypher queries. Acceptable for the typical small limit. Do NOT batch all session lookups into one query — it complicates parameterization significantly.

---

## Vector Index Bug Fix

### Current DDL (confirmed by reading `src/codememory/core/connection.py` lines 62-73)

```python
# Line 63-66 — WRONG: 3072d for a Gemini 768d index
"CREATE VECTOR INDEX research_embeddings IF NOT EXISTS "
"FOR (n:Memory:Research) ON n.embedding "
"OPTIONS { indexConfig: { `vector.dimensions`: 3072, `vector.similarity_function`: 'cosine' }}"

# Line 67-70 — WRONG: 3072d for a Gemini 768d index
"CREATE VECTOR INDEX chat_embeddings IF NOT EXISTS "
"FOR (n:Memory:Conversation) ON n.embedding "
"OPTIONS { indexConfig: { `vector.dimensions`: 3072, `vector.similarity_function`: 'cosine' }}"
```

### Corrected DDL

```python
"CREATE VECTOR INDEX research_embeddings IF NOT EXISTS "
"FOR (n:Memory:Research) ON n.embedding "
"OPTIONS { indexConfig: { `vector.dimensions`: 768, `vector.similarity_function`: 'cosine' }}"

"CREATE VECTOR INDEX chat_embeddings IF NOT EXISTS "
"FOR (n:Memory:Conversation) ON n.embedding "
"OPTIONS { indexConfig: { `vector.dimensions`: 768, `vector.similarity_function`: 'cosine' }}"
```

### Migration Approach: Drop-and-Recreate Required

**Critical finding:** Neo4j's `CREATE VECTOR INDEX IF NOT EXISTS` does NOT update an existing index's configuration. If the index already exists at 3072d, changing the DDL to 768d and re-running `setup_database()` will silently leave the existing 3072d index in place. The `IF NOT EXISTS` clause causes the statement to be a no-op when the index exists.

**Consequence:** Fixing only the DDL string in `connection.py` is insufficient for databases that already ran `chat-init` or `web-init`. A migration step is needed for existing databases.

**Fix strategy (two parts):**

Part 1 — Fix the DDL in `connection.py` (for fresh databases and new installs):
```python
# Change 3072 → 768 for both research_embeddings and chat_embeddings
```

Part 2 — Add migration Cypher in `setup_database()` or a separate migration function:
```cypher
// Drop old index if it exists at wrong dimensions
DROP INDEX research_embeddings IF EXISTS;
DROP INDEX chat_embeddings IF EXISTS;
// Then the CREATE statements run fresh at 768d
```

**Recommended approach:** Add a `migrate_vector_indexes()` helper method that runs DROP + CREATE unconditionally (no IF NOT EXISTS on the CREATE after a DROP). Call this from `chat-init` CLI with a `--fix-dimensions` flag, or unconditionally from `chat-init` since the index rebuild is fast on empty/small databases.

**Test implication:** `test_connection.py::test_setup_database_runs_all_queries` currently checks that `mock_session.run.call_count == 4`. Adding DROP statements changes this count. Update the test to check for the presence of "768" in the executed statements and not hardcode the call count, or add the DROP statements as a separate method that `chat-init` calls explicitly (keeping `setup_database()` idempotent for CI).

**Decision for implementation:** Keep `setup_database()` unchanged (4 statements, creates with IF NOT EXISTS, correct 768d values). Add a separate `fix_vector_index_dimensions()` method that drops and recreates only the two affected indexes. `chat-init` CLI calls both: `setup_database()` then optionally `fix_vector_index_dimensions()`. This preserves the existing test without breakage.

---

## CLI Pattern

### Existing Stubs (confirmed from `src/codememory/cli.py`)

```python
# Line 1067-1070
def cmd_chat_init(args: argparse.Namespace) -> None:
    print("chat-init: Not yet implemented. Coming in Phase 4.")
    sys.exit(0)

# Line 1073-1076
def cmd_chat_ingest(args: argparse.Namespace) -> None:
    print("chat-ingest: Not yet implemented. Coming in Phase 4.")
    sys.exit(0)
```

**`chat-search` is NOT stubbed** — no `cmd_chat_search` function exists and no `chat-search` subparser is registered. Both must be added in Phase 4.

### Parser Registration Gaps

Current `main()` registers:
```python
subparsers.add_parser("chat-init", ...)
chat_ingest_parser = subparsers.add_parser("chat-ingest", ...)
chat_ingest_parser.add_argument("source", nargs="?", ...)
# chat-search is MISSING — must be added
```

The dispatch block handles `chat-init` and `chat-ingest` but has no `elif args.command == "chat-search"` branch. Both the parser and the dispatch must be added.

### Reference: `cmd_web_ingest` Pattern

`cmd_web_ingest` (lines 974-1058) is the reference for `cmd_chat_ingest`. Key patterns:
1. Validate required args early, exit with message if missing
2. Read env vars with sensible defaults for NEO4J_*, validate GOOGLE_API_KEY and GROQ_API_KEY
3. Import pipeline classes inside the function (lazy import pattern)
4. Construct `ConnectionManager`, `EmbeddingService`, `EntityExtractionService`, `Pipeline`
5. Call `pipeline.ingest(source)` for each unit, print summary

### `cmd_chat_ingest` Implementation Approach

**Input parsing (three modes from CONTEXT.md):**
```python
def _parse_turns_from_file(source_path: str | None) -> list[dict]:
    """Parse JSONL or JSON array from file or stdin."""
    if source_path is None or source_path == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = Path(source_path).read_text().splitlines()

    # Detect JSON array vs JSONL
    stripped = "\n".join(lines).strip()
    if stripped.startswith("["):
        return json.loads(stripped)  # JSON array
    else:
        return [json.loads(line) for line in lines if line.strip()]  # JSONL
```

**Auto-assign turn_index if absent:** Enumerate turns during parsing: if `turn_index` not in turn dict, assign `i` (0-based position in the file).

**Flag overrides:** Apply `--project-id`, `--session-id`, `--source-agent` to each turn if not already present in turn data. Session-id flag OVERRIDES per-turn session_id if both are provided.

**Progress reporting:** Use a simple counter with `print(f"\r{i+1}/{total} turns ingested...", end="", flush=True)`. No external library needed — avoids adding `tqdm` as a dependency for a simple loop. Use `\r` carriage return to update in place.

**Error handling strategy — continue and collect errors:**
```python
errors = []
for i, turn in enumerate(turns):
    try:
        pipeline.ingest(turn)
    except Exception as e:
        errors.append({"turn_index": i, "error": str(e)})
        # Continue processing remaining turns
```
Report all errors in the final summary. Exit code 0 if any turns succeeded, exit code 1 if ALL turns failed. This matches real-world usage where a single malformed turn shouldn't abort a 500-turn import.

**Final summary format:**
```
chat-ingest: Done.
  Turns ingested: 47
  Turns skipped:  3
  Entities extracted: 142
  Duration: 12.4s
  Errors (3):
    Turn 5: ValueError: Unknown role 'human'
    ...
```

**Required flags for `chat-ingest` subparser:**
```python
chat_ingest_parser.add_argument("source", nargs="?", help="Path to JSONL/JSON file (or omit for stdin)")
chat_ingest_parser.add_argument("--project-id", required=True, help="Project ID for all turns")
chat_ingest_parser.add_argument("--session-id", help="Session ID (overrides per-turn session_id if provided)")
chat_ingest_parser.add_argument("--source-agent", help="Source agent (e.g. 'claude')")
```

### `cmd_chat_init` Implementation

```python
def cmd_chat_init(args: argparse.Namespace) -> None:
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    try:
        from codememory.core.connection import ConnectionManager
        conn = ConnectionManager(uri, user, password)
        conn.setup_database()
        conn.driver.close()
        print("chat-init: chat_embeddings vector index ready (768d).")
    except Exception as e:
        print(f"chat-init failed: {e}")
        sys.exit(1)
```

### `cmd_chat_search` Implementation

```python
def cmd_chat_search(args: argparse.Namespace) -> None:
    # args.query, args.project_id (optional), args.limit, args.role (optional)
    # 1. Build pipeline (same as web-ingest pattern)
    # 2. Embed query via pipeline._embedder.embed(query)
    # 3. Run chat_embeddings vector search via conn.session()
    # 4. Print tabular results: session_id, turn_index, role, score, content (truncated)
```

**Tabular output:** Use Python's built-in `str.ljust()` / f-string alignment rather than `tabulate`. Content truncated to 80 chars.

---

## ConversationIngestionPipeline Implementation

### Structural Map (mirror of ResearchIngestionPipeline)

```python
# src/codememory/chat/pipeline.py
register_source("chat_mcp", ["Memory", "Conversation", "Turn"])
register_source("chat_proxy", ["Memory", "Conversation", "Turn"])
register_source("chat_ext", ["Memory", "Conversation", "Turn"])
register_source("chat_cli", ["Memory", "Conversation", "Turn"])

class ConversationIngestionPipeline(BaseIngestionPipeline):
    DOMAIN_LABEL = "Conversation"

    def __init__(self, connection_manager, embedding_service, entity_extractor):
        super().__init__(connection_manager)
        self._embedder = embedding_service
        self._extractor = entity_extractor
        self._writer = GraphWriter(connection_manager)

    def ingest(self, source: dict) -> dict:
        # 1. Validate required fields
        # 2. Validate role
        # 3. Compute content_hash = sha256(f"{session_id}:{turn_index}")
        # 4. Determine if embeddable (role in ["user", "assistant"])
        # 5. If embeddable: extract entities → build_embed_text → embed
        # 6. Build turn props dict
        # 7. write_memory_node(labels, turn_props)
        # 8. write_session_node(session_props)
        # 9. write_has_turn_relationship(session_id, source_key, content_hash, turn_index)
        # 10. write_part_of_turn_relationship(source_key, content_hash, session_id)
        # 11. Wire entity relationships (ABOUT for project, MENTIONS for others)
        # 12. Return summary dict
```

### Content Hash

```python
def _turn_content_hash(self, session_id: str, turn_index: int) -> str:
    """Turn dedup key: session-scoped position, not content."""
    composite = f"{session_id}:{turn_index}"
    return hashlib.sha256(composite.encode()).hexdigest()
```

Note: CONTEXT.md specifies this hash formula. Content is intentionally excluded so re-delivering an updated turn with the same (session_id, turn_index) overwrites in place rather than creating a duplicate.

### Turn Properties Dict

```python
turn_props = {
    "role": role,
    "content": content,
    "embedding": embedding,           # None for system/tool
    "turn_index": turn_index,
    "session_id": session_id,
    "project_id": project_id,
    "source_agent": source.get("source_agent"),
    "model": source.get("model"),
    "tool_name": source.get("tool_name"),
    "tool_call_id": source.get("tool_call_id"),
    "tokens_input": source.get("tokens_input"),
    "tokens_output": source.get("tokens_output"),
    "timestamp": source.get("timestamp") or now,
    "ingested_at": now,
    "ingestion_mode": source.get("ingestion_mode", "active"),
    "embedding_model": "gemini-embedding-2-preview" if embeddable else None,
    "source_key": source_key,
    "source_type": "conversation",
    "content_hash": content_hash,
    "entities": entity_names,      # [] for system/tool
    "entity_types": entity_types,  # [] for system/tool
}
```

### `source_key` Selection

The source_key is passed in the `source` dict or defaults to `"chat_mcp"`. The pipeline itself doesn't hard-code the source_key — it reads from `source.get("source_key", "chat_mcp")`. This allows the same pipeline class to serve MCP, REST, and CLI paths by passing different source_keys.

---

## REST Route Extension

### `src/am_server/routes/conversation.py`

```python
router = APIRouter(dependencies=[Depends(require_auth)])

@router.post("/ingest/conversation", status_code=202)
async def ingest_conversation(body: ConversationIngestRequest) -> dict:
    pipeline = get_conversation_pipeline()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, pipeline.ingest, body.model_dump())
    return {"status": "ok", "result": result}

@router.get("/search/conversations")
async def search_conversations(
    q: str = Query(...),
    project_id: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    role: str | None = Query(None),
) -> dict:
    pipeline = get_conversation_pipeline()
    try:
        conn = pipeline._conn
        loop = asyncio.get_event_loop()
        def _query() -> list:
            with conn.session() as session:
                # Text fallback (same pattern as search_research)
                result = session.run(text_cypher, q=q, project_id=project_id, role=role, limit=limit)
                return [dict(record) for record in result]
        results = await loop.run_in_executor(None, _query)
    except Exception:
        results = []
    return {"results": results}
```

### `src/am_server/models.py` — New Model

```python
class ConversationIngestRequest(BaseModel):
    role: str
    content: str
    session_id: str
    project_id: str
    turn_index: int
    source_agent: str | None = None
    model: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    timestamp: str | None = None
    ingestion_mode: str = "active"
    source_key: str = "chat_proxy"   # REST path default is passive ingest
```

### `src/am_server/dependencies.py` — New Factory

```python
@lru_cache(maxsize=1)
def get_conversation_pipeline() -> ConversationIngestionPipeline:
    conn = ConnectionManager(
        uri=os.environ["NEO4J_URI"],
        user=os.environ["NEO4J_USER"],
        password=os.environ["NEO4J_PASSWORD"],
    )
    embedder = EmbeddingService(provider="gemini", api_key=os.environ["GEMINI_API_KEY"])
    extractor = EntityExtractionService(api_key=os.environ["GROQ_API_KEY"])
    return ConversationIngestionPipeline(conn, embedder, extractor)
```

### `src/am_server/app.py` — Router Registration

```python
from am_server.routes import conversation, ext, health, research

app.include_router(health.router)
app.include_router(research.router)
app.include_router(conversation.router)   # add this
app.include_router(ext.router)
```

**Also add to lifespan:** warm up `get_conversation_pipeline()` alongside `get_pipeline()`.

---

## MCP Tools Extension

### `src/codememory/server/tools.py` — Current State

The current `tools.py` contains the **old-style** `Toolkit` class (lines 1-105 in the file read). It does NOT yet use the Phase 2 decorator pattern (`@mcp.tool()`, `@rate_limit`, `@log_tool_call`) — those were mentioned in CONTEXT.md as a pattern to mirror, but the tools.py file currently contains only the pre-Phase-2 legacy code using `KnowledgeGraphBuilder`.

**The three new MCP tools must be added to the existing `Toolkit` class or the Phase 2 tool registration pattern.** Without seeing the Phase 2 MCP tool additions, the implementer must check whether `search_web_memory`, `memory_ingest_research`, and `brave_search` were added directly to `tools.py` or to a separate file.

**Recommendation:** Add the three conversation MCP tools alongside the existing Phase 2 tools. Use the same `@mcp.tool()` registration approach as Phase 2. The `search_conversations`, `add_message`, and `get_conversation_context` tools delegate to `ConversationIngestionPipeline` (for add_message) and to a vector search function (for search tools).

### MCP Tool Embedding Pattern

For `search_conversations` and `get_conversation_context`, the tool must embed the query before calling the vector search. The pipeline's `_embedder` is accessible if the pipeline is passed to the Toolkit:

```python
# In search_conversations:
pipeline = get_conversation_pipeline()
embedding = pipeline._embedder.embed(query)
# Then run db.index.vector.queryNodes('chat_embeddings', limit, embedding)
```

Or create a standalone `ConversationSearchService` that wraps the conn + embedder without needing the full pipeline. **Simplest approach:** pass `get_conversation_pipeline()` to the MCP search tools and access `_embedder` and `_conn` directly, same way `search_research` accesses `pipeline._conn`.

---

## Test Strategy

### Existing Test Infrastructure

- **Framework:** pytest with `pytest-asyncio` for async tests
- **Mock pattern:** `MagicMock()` for Neo4j connections, `_make_writer()` helper returns `(GraphWriter, mock_conn, mock_session)` — confirmed in `tests/test_web_pipeline.py`
- **Pipeline mock:** `_make_pipeline()` returns `(pipeline, mock_writer)` with `pipeline._writer` replaced by `MagicMock()` after construction
- **am_server pattern:** `TestClient` with `monkeypatch.setattr` to replace pipeline class with mock; `dependencies.get_pipeline.cache_clear()` before creating app
- **conftest.py:** Minimal — only adds `src` to sys.path and registers markers (unit, integration, slow). No shared fixtures beyond that.

### Recommended Test File: `tests/test_chat_pipeline.py`

Mirror `test_web_pipeline.py` structure exactly:

```python
# Helpers
def _make_writer():  # same as test_web_pipeline
def _make_pipeline():
    from codememory.chat.pipeline import ConversationIngestionPipeline
    mock_conn = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768  # 768d not 3072d
    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = [{"name": "TestProject", "type": "project"}]
    pipeline = ConversationIngestionPipeline(mock_conn, mock_embedder, mock_extractor)
    mock_writer = MagicMock()
    pipeline._writer = mock_writer
    return pipeline, mock_writer

def _turn_source(**overrides):
    base = {
        "role": "user",
        "content": "What is the status of the auth module?",
        "session_id": "sess-abc",
        "project_id": "proj-test",
        "turn_index": 0,
    }
    base.update(overrides)
    return base
```

### Minimal Test Plan

| Test Class | Tests | Covers |
|---|---|---|
| `TestGraphWriterSessionNode` | MERGE key is session_id; ON CREATE sets started_at; ON MATCH updates last_turn_index with CASE | GraphWriter.write_session_node |
| `TestGraphWriterHasTurnRelationship` | HAS_TURN written with order=turn_index; MERGE on Session+Turn | GraphWriter.write_has_turn_relationship |
| `TestGraphWriterPartOfTurnRelationship` | PART_OF written Turn→Session | GraphWriter.write_part_of_turn_relationship |
| `TestConversationPipelineContract` | Subclass of BaseIngestionPipeline; DOMAIN_LABEL="Conversation" | class structure |
| `TestConversationPipelineUserTurn` | User turn: embedder.embed called; write_memory_node called with embedding; write_session_node called; HAS_TURN and PART_OF called | happy path |
| `TestConversationPipelineAssistantTurn` | Same as user turn (both roles embedded) | embedding parity |
| `TestConversationPipelineSystemTurn` | System turn: embedder.embed NOT called; embedding=None in props | no-embed for system |
| `TestConversationPipelineToolTurn` | Tool turn: embedder.embed NOT called; embedding=None | no-embed for tool |
| `TestConversationPipelineRoleValidation` | Unknown role raises ValueError | role guard |
| `TestConversationPipelineIdempotency` | content_hash = sha256(f"{session_id}:{turn_index}"), independent of content | dedup key |
| `TestConversationPipelineEntityWiring` | upsert_entity called per entity; write_relationship called ABOUT for project, MENTIONS for others | entity wiring |
| `TestConversationPipelineNoEntityForSystemTool` | extractor.extract NOT called for system/tool turns | efficiency |
| `TestSourceRegistration` | chat_mcp, chat_proxy, chat_ext, chat_cli all in SOURCE_REGISTRY after import | registry |
| `TestVectorIndexDimensions` | setup_database() executed statements contain "768" for research_embeddings and chat_embeddings | bug fix |
| `TestConversationRestIngest` (in test_am_server.py) | POST /ingest/conversation 202 with auth; 403 without auth; pipeline.ingest called with correct payload | REST |
| `TestConversationRestSearch` | GET /search/conversations returns {"results": [...]} | REST |

### Note on `test_connection.py` Regression

The existing `test_setup_database_runs_all_queries` asserts `mock_session.run.call_count == 4`. After fixing the DDL to 768d, this test will still pass (4 statements: code, research, chat, entity_unique). The test also checks for the index names but NOT the dimension values — add a new test `test_vector_index_dimensions_are_768` that inspects the executed Cypher strings for "768".

---

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest (existing, no install needed) |
| Config file | `pytest.ini` or pyproject.toml — check which exists |
| Quick run command | `pytest tests/test_chat_pipeline.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command |
|---|---|---|---|
| CONV-01 | ConversationIngestionPipeline subclasses BaseIngestionPipeline | unit | `pytest tests/test_chat_pipeline.py::TestConversationPipelineContract -x` |
| CONV-02 | User/assistant turns are embedded, system/tool are not | unit | `pytest tests/test_chat_pipeline.py::TestConversationPipelineSystemTurn -x` |
| CONV-03 | MERGE on (session_id, turn_index) — idempotent | unit | `pytest tests/test_chat_pipeline.py::TestConversationPipelineIdempotency -x` |
| CONV-04 | Session node created/updated per turn | unit | `pytest tests/test_chat_pipeline.py::TestGraphWriterSessionNode -x` |
| CONV-05 | last_turn_index tracks max via CASE expression | unit | `pytest tests/test_chat_pipeline.py::TestGraphWriterSessionNode -x` |
| CONV-06 | Vector indexes fixed to 768d | unit | `pytest tests/test_connection.py::test_vector_index_dimensions_are_768 -x` |
| CONV-07 | POST /ingest/conversation 202 with auth | unit | `pytest tests/test_am_server.py -x -k conversation` |
| CONV-08 | GET /search/conversations returns results | unit | `pytest tests/test_am_server.py -x -k search_conversations` |
| CONV-09 | Source keys registered at import time | unit | `pytest tests/test_chat_pipeline.py::TestSourceRegistration -x` |
| CONV-10 | Role validation raises ValueError on unknown | unit | `pytest tests/test_chat_pipeline.py::TestConversationPipelineRoleValidation -x` |

### Sampling Rate

- **Per task commit:** `pytest tests/test_chat_pipeline.py tests/test_connection.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_chat_pipeline.py` — does not exist, create in Wave 1 task (TDD: write tests before implementation)
- [ ] `tests/test_connection.py::test_vector_index_dimensions_are_768` — missing assertion in existing file

*(pytest, pytest-asyncio already installed — no framework install needed)*

---

## Implementation Order

### Recommended Task Sequence

**Wave 1 (foundation — no external dependencies):**
1. **Fix vector index bug** — change `connection.py` lines 63-73 from 3072 to 768 for research_embeddings and chat_embeddings. Update `test_connection.py` to assert "768" appears in executed DDL. This is a one-file fix with a clear test to update.
2. **GraphWriter extensions** — add `write_session_node()`, `write_has_turn_relationship()`, `write_part_of_turn_relationship()` to `graph_writer.py`. Write `TestGraphWriterSessionNode`, `TestGraphWriterHasTurnRelationship`, `TestGraphWriterPartOfTurnRelationship` tests first (TDD).
3. **`ConversationIngestionPipeline`** — create `src/codememory/chat/pipeline.py`. Write `tests/test_chat_pipeline.py` with all unit tests above. Pipeline is pure Python + mocked Neo4j — no integration deps.

**Wave 2 (REST and MCP — depends on pipeline):**
4. **Pydantic model** — add `ConversationIngestRequest` to `src/am_server/models.py`.
5. **Dependency factory** — add `get_conversation_pipeline()` to `src/am_server/dependencies.py`.
6. **REST routes** — create `src/am_server/routes/conversation.py`. Register in `app.py`. Add conversation tests to `test_am_server.py`.
7. **MCP tools** — add `search_conversations`, `add_message`, `get_conversation_context` to `src/codememory/server/tools.py`.

**Wave 3 (CLI — depends on pipeline and REST):**
8. **`cmd_chat_init`** — replace stub in `cli.py`. Register `chat-search` subparser. Add `cmd_chat_search` function.
9. **`cmd_chat_ingest`** — replace stub with full JSONL/JSON/stdin parsing implementation.
10. **`cmd_chat_search`** — implement vector search output.

---

## Open Questions

1. **Phase 2 MCP tools location**
   - What we know: CONTEXT.md describes `@mcp.tool()` pattern for conversation tools, and the current `tools.py` file uses the old-style Toolkit class with `KnowledgeGraphBuilder`. Phase 2 presumably added `search_web_memory`, `memory_ingest_research`, `brave_search` somewhere.
   - What's unclear: Were Phase 2 MCP tools added to `tools.py` alongside the old Toolkit class, or to a new file?
   - Recommendation: Read `src/codememory/server/app.py` and the full `tools.py` at implementation time to see Phase 2 additions before adding conversation tools. The research read of `tools.py` showed only 105 lines — Phase 2 tools may have been added below line 105 but the file wasn't fully read.

2. **`chat-ingest` auto-setup call**
   - CONTEXT.md states: "Running `chat-ingest` should call `setup_database()` automatically if indexes don't exist."
   - What's unclear: Should `chat-ingest` always call `setup_database()` (cheap, idempotent with IF NOT EXISTS) or check first?
   - Recommendation: Always call `setup_database()` at the start of `chat-ingest` — it is cheap (one session, 4 run() calls) and eliminates the user needing to run `chat-init` separately.

3. **`test_setup_database_runs_all_queries` call_count**
   - If the vector index bug fix adds DROP statements before CREATE, the call_count assertion breaks.
   - Recommendation: Keep bug fix as DDL string change only (768d), not as added DROP statements. Keep `setup_database()` at 4 statements. Any migration helper is a separate method not called by `setup_database()`.

---

## Sources

### Primary (HIGH confidence — direct codebase reads)
- `src/codememory/core/connection.py` — confirmed 3072d bug at lines 63-73; exact DDL statements
- `src/codememory/core/graph_writer.py` — all existing methods, MERGE patterns, confirmed `write_relationship()` works for Turn entity wiring
- `src/codememory/web/pipeline.py` — canonical reference implementation, all patterns confirmed
- `src/am_server/routes/research.py` — REST route pattern, inline `_query` closure, text fallback
- `src/am_server/dependencies.py` — `@lru_cache(maxsize=1)` factory pattern confirmed
- `src/am_server/models.py` — Pydantic model pattern for `ResearchIngestRequest`
- `src/am_server/app.py` — router registration pattern, lifespan warm-up
- `src/codememory/cli.py` — chat-init stub (line 1067), chat-ingest stub (line 1073), web-ingest reference (line 974), chat-search missing (confirmed absent)
- `tests/test_web_pipeline.py` — full test patterns, `_make_writer()`, `_make_pipeline()`, fixture helpers
- `tests/test_connection.py` — setup_database test confirms call_count=4 assertion
- `tests/test_am_server.py` — TestClient pattern, `monkeypatch.setattr` pipeline mock, `cache_clear()`
- `.planning/phases/04-conversation-memory-core/04-CONTEXT.md` — all locked decisions

### Secondary (MEDIUM confidence)
- Neo4j documentation behavior: `CREATE VECTOR INDEX IF NOT EXISTS` does not update existing index config — standard DDL behavior confirmed by general Neo4j docs knowledge; if in doubt, test empirically on target Neo4j version before implementing migration path.
