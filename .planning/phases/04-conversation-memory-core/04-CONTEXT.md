# Phase 4: Conversation Memory Core — Context

**Gathered:** 2026-03-22
**Status:** Ready for research and planning
**Note:** Context gathered autonomously (user unavailable) based on prior phase outputs and codebase scouting.

<domain>
## Phase Boundary

Build the `ConversationIngestionPipeline`, extend `am-server` REST API with `/ingest/conversation` and `/search/conversations`, add three MCP tools (`search_conversations`, `add_message`, `get_conversation_context`), and implement CLI commands (`chat-init`, `chat-ingest`, `chat-search`). This phase creates the conversation memory foundation that am-proxy (Phase 5) and am-ext (Phase 6) will write to passively.

</domain>

<decisions>
## Implementation Decisions

### Turn Payload Schema

The conversation turn is the atomic unit. Both REST ingest and MCP `add_message` accept this shape:

```python
# Required fields
role: str           # "user" | "assistant" | "system" | "tool"
content: str        # turn text (required; tool turns may include structured JSON as string)
session_id: str     # caller-owned conversation boundary — NEVER server-generated
project_id: str     # explicit project anchor (first-class per Phase 1)
turn_index: int     # 0-based position within session — MERGE key with session_id

# Optional fields
source_agent: str | None     # "claude" | "chatgpt" | "gemini" | "custom" — which AI produced this
model: str | None            # specific model name (e.g. "claude-opus-4-6")
tool_name: str | None        # for role="tool": the tool that was called
tool_call_id: str | None     # for request/response pairing in tool turns
tokens_input: int | None     # input token count if available
tokens_output: int | None    # output token count if available
timestamp: str | None        # ISO-8601 turn timestamp (if not provided, ingested_at used)
ingestion_mode: str          # "active" | "passive" | "manual" (default: "active")
```

**Dedup key:** MERGE on `(session_id, turn_index)` — append-only, idempotent. Same turn re-delivered is a no-op (properties overwritten, no duplicate node created).

**Embedding:** Only `role = "user"` and `role = "assistant"` turns are embedded. `role = "system"` and `role = "tool"` are stored as metadata (no embedding, no vector index entry). This keeps the chat_embeddings index focused on semantically meaningful content.

**Entity extraction:** Extract entities per-turn on user and assistant turns only. Tool turns are too structured for meaningful NER. One LLM call per turn (not per session) — keeps call sizes manageable and enables per-turn entity tagging.

---

### Graph Schema: Conversation Layer

```
// Turn node — core unit, embedded for user/assistant roles
(:Memory:Conversation:Turn {
    role,                          ← "user" | "assistant" | "system" | "tool"
    content,                       ← turn text
    embedding,                     ← null for system/tool turns; gemini-embedding-2-preview for user/assistant
    turn_index,                    ← 0-based position
    session_id, project_id,
    source_agent,                  ← which AI produced this (e.g. "claude")
    model,                         ← specific model variant (e.g. "claude-opus-4-6")
    tool_name, tool_call_id,       ← tool turn metadata
    tokens_input, tokens_output,   ← token counts if known
    timestamp,                     ← original turn time or ingested_at
    ingested_at,
    ingestion_mode,                ← "active" | "passive" | "manual"
    embedding_model,               ← "gemini-embedding-2-preview" or null
    source_key,                    ← "chat_mcp" | "chat_proxy" | "chat_ext" | "chat_cli"
    source_type: "conversation",
    entities, entity_types         ← denormalized entity arrays
})

// Session grouping — lightweight metadata node
(:Memory:Conversation:Session {
    session_id,
    project_id,
    source_agent,
    started_at,           ← timestamp of first turn ingested
    last_turn_index,      ← tracks append position for incremental writes
    turn_count
})

// Relationships
(:Memory:Conversation:Session)-[:HAS_TURN {order: turn_index}]->(:Memory:Conversation:Turn)
(:Memory:Conversation:Turn)-[:PART_OF]->(:Memory:Conversation:Session)
(:Memory:Conversation:Turn)-[:ABOUT]->(:Entity:Project)
(:Memory:Conversation:Turn)-[:MENTIONS]->(:Entity:*)
```

**Source registry entries:**
- `register_source("chat_mcp", ["Memory", "Conversation", "Turn"])` — explicit MCP writes
- `register_source("chat_proxy", ["Memory", "Conversation", "Turn"])` — am-proxy passive ingest
- `register_source("chat_ext", ["Memory", "Conversation", "Turn"])` — am-ext passive ingest
- `register_source("chat_cli", ["Memory", "Conversation", "Turn"])` — CLI import

**`chat_embeddings` vector index bug fix:** The index is currently created at 3072d in `connection.py` (same as code_embeddings). It MUST be corrected to 768d to match Gemini output. Same bug applies to `research_embeddings`. Both need to be fixed in this phase.

---

### `search_conversations` MCP Tool — Semantic Search

General-purpose semantic search across all embedded conversation turns:

```python
@mcp.tool(description="Search past conversations for relevant exchanges. Use when you need to find prior context, check what was discussed about a topic, or retrieve conversation history by semantic similarity.")
async def search_conversations(
    query: str,
    project_id: str | None,      # optional project filter
    role: str | None,             # optional role filter ("user" | "assistant")
    limit: int = 10,
) -> list[dict]: ...
```

Returns: `[{session_id, turn_index, role, content, source_agent, timestamp, score, entities}]`

Behavior: Pure vector search over `chat_embeddings` index. Filter by `project_id` and/or `role` if provided. No recency weighting — pure cosine similarity.

---

### `get_conversation_context` MCP Tool — LLM Context Retrieval

Optimized for feeding relevant past conversation context into an LLM prompt:

```python
@mcp.tool(description="Retrieve the most relevant past conversation context for a given query or task. Returns a compact, structured bundle of prior exchanges ranked by relevance. Use this to ground responses in prior conversation history before answering a user's question.")
async def get_conversation_context(
    query: str,
    project_id: str,             # required — context is always project-scoped
    limit: int = 5,              # number of turns to return (keep small for context window)
    include_session_context: bool = True,  # whether to fetch surrounding turns (±1) for each match
) -> dict: ...
```

Returns: `{query, turns: [{session_id, turn_index, role, content, score, context_window: [±1 turns]}]}`

Behavior: Vector search over `chat_embeddings` filtered to `project_id`. If `include_session_context=True`, for each matching turn, fetch the previous and next turn from the same session to provide conversational framing. Returns a structured dict formatted for direct LLM injection.

**Distinction from `search_conversations`:**
- `search_conversations` → discovery, debugging, broad retrieval (returns many results, raw format)
- `get_conversation_context` → LLM grounding, context injection (returns few results, structured for prompting, includes surrounding context)

---

### `add_message` MCP Tool — Explicit Turn Write

```python
@mcp.tool(description="Explicitly save a conversation turn to memory. Use this when you want to ensure a specific message is persisted, or when passive capture is not configured. Provide turn_index=0 for single messages; use sequential indexes for multi-turn writes.")
async def add_message(
    role: str,
    content: str,
    session_id: str,
    project_id: str,
    turn_index: int = 0,
    source_agent: str | None = None,
    **optional_fields,
) -> dict: ...
```

`source_key` is always `"chat_mcp"` for this path. `ingestion_mode` defaults to `"active"`.

---

### REST Endpoints: Extend `am-server`

Add two new routes in `src/am_server/routes/conversation.py`:

```python
POST /ingest/conversation   ← accepts ConversationIngestRequest body
GET  /search/conversations  ← query param: q, project_id, limit, role
```

`ConversationIngestRequest` mirrors the turn schema above. The REST endpoint is the target for am-proxy and am-ext — they POST to `am-server`, not directly to Neo4j.

**Dependency injection:** Add `get_conversation_pipeline()` factory in `dependencies.py` using same `@lru_cache(maxsize=1)` pattern as `get_pipeline()`. Conversation pipeline is independent of research pipeline.

---

### `ConversationIngestionPipeline`

Subclasses `BaseIngestionPipeline` with `DOMAIN_LABEL = "Conversation"`.

```python
class ConversationIngestionPipeline(BaseIngestionPipeline):
    def ingest(self, source: dict) -> dict:
        # 1. Validate required fields (role, content, session_id, project_id, turn_index)
        # 2. Determine if turn should be embedded (user/assistant roles only)
        # 3. If embeddable: extract entities → build_embed_text → embed
        # 4. Write :Memory:Conversation:Turn node via write_memory_node()
        # 5. Upsert :Memory:Conversation:Session node (MERGE on session_id)
        # 6. Wire HAS_TURN and PART_OF relationships
        # 7. Wire entity relationships (:ABOUT for project, :MENTIONS for others)
```

Content hash for turn MERGE: `sha256(f"{session_id}:{turn_index}")` — session-scoped identity key. Content itself is not part of the hash so that re-ingestion of an updated turn overwrites in place.

**Batch ingest:** The pipeline `ingest()` handles one turn at a time. The `chat-ingest` CLI loops over turns and calls `ingest()` per turn.

---

### `chat-ingest` CLI

**Input formats accepted:**
1. JSONL file — each line is a turn object (flexible, no wrapper)
2. JSON file — array of turn objects
3. Stdin — pipe JSONL lines

**Required flags:**
- `--project-id` — applied to all turns in the file if not in the turn data itself
- `--session-id` — applied to all turns if not in turn data (overrides per-turn session_id if provided as flag)
- `--source-agent` — optional, e.g. "claude" — applied if not in turn data

**Turn schema for import files:**
Minimum required per line: `{role, content}`. If `turn_index` is absent, auto-assigned based on line position (0-based). `session_id` and `project_id` from flags if not in the line.

**Output:** progress bar (per-turn), final summary: `{turns_ingested, turns_skipped, entities_extracted, duration_s}`.

---

### `chat-init` CLI

Runs `connection_manager.setup_database()` (already creates `chat_embeddings` index) — but the bug-fixed version. Prints confirmation of index creation.

---

### `chat-search` CLI

Semantic search via the same vector search as `search_conversations`. Flags: `--query`, `--project-id`, `--limit`, `--role`. Outputs tabular results.

---

### Claude's Discretion

- Exact Cypher for Session MERGE and last_turn_index tracking
- GraphWriter new methods needed for conversation (write_session_node, write_has_turn_relationship)
- Token counting approximation (same as chunker: `len(text.split()) * 1.3`)
- Unit test fixtures and mock strategy
- CLI output formatting (tabulate or manual)
- Whether to embed system prompts (default: no — decision locked above)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 + 2 outputs (extend these)
- `src/codememory/core/base.py` — `BaseIngestionPipeline` ABC to subclass
- `src/codememory/core/embedding.py` — `EmbeddingService` with `gemini-embedding-2-preview` provider
- `src/codememory/core/entity_extraction.py` — `EntityExtractionService`, `build_embed_text`
- `src/codememory/core/graph_writer.py` — `GraphWriter` methods (write_memory_node, upsert_entity, write_relationship)
- `src/codememory/core/connection.py` — `ConnectionManager` — **BUG: chat_embeddings and research_embeddings are 3072d, must be corrected to 768d**
- `src/codememory/core/registry.py` — `register_source()`
- `src/codememory/chat/__init__.py` — stub, implement ConversationIngestionPipeline here
- `src/codememory/cli.py` — chat-init, chat-ingest, chat-search stub commands to implement
- `src/am_server/app.py` — FastAPI app factory, add conversation router here
- `src/am_server/routes/research.py` — **reference implementation** for new conversation routes
- `src/am_server/models.py` — add ConversationIngestRequest (mirror ResearchIngestRequest pattern)
- `src/am_server/dependencies.py` — add get_conversation_pipeline() factory
- `src/am_server/auth.py` — Bearer auth middleware, reuse unchanged

### Phase 2 Context
- `.planning/phases/02-web-research-core/02-CONTEXT.md` — full reference for patterns to mirror

### Planning docs
- `.planning/ROADMAP.md` — phase boundary for Phase 4
- `.planning/phases/01-foundation/01-CONTEXT.md` — base graph schema, metadata fields, entity extraction flow
- `.planning/codebase/CONVENTIONS.md` — Black, Ruff, MyPy strict, Google docstrings

</canonical_refs>

<code_context>
## Existing Code Insights

### Bug to Fix: Vector Index Dimensions
`connection.py:setup_database()` creates `research_embeddings` and `chat_embeddings` at 3072d (same as code_embeddings). Both must be 768d to match Gemini embedding output. This must be corrected in Phase 4 as part of chat module init work. Fix: change the DDL statements for these two indexes.

### Pattern to Mirror: `ResearchIngestionPipeline`
`src/codememory/web/pipeline.py` is the canonical reference. `ConversationIngestionPipeline` follows the same structure:
- Constructor takes `ConnectionManager`, `EmbeddingService`, `EntityExtractionService`
- `ingest(source: dict) -> dict`
- Uses `self._writer`, `self._embedder`, `self._extractor`
- `register_source()` calls at module import time

### Pattern to Mirror: `am_server/routes/research.py`
```python
router = APIRouter(dependencies=[Depends(require_auth)])

@router.post("/ingest/conversation", status_code=202)
async def ingest_conversation(body: ConversationIngestRequest) -> dict:
    pipeline = get_conversation_pipeline()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, pipeline.ingest, body.model_dump())
    return {"status": "ok", "result": result}
```

### Pattern to Mirror: `am_server/dependencies.py`
```python
@lru_cache(maxsize=1)
def get_conversation_pipeline() -> ConversationIngestionPipeline:
    conn = ConnectionManager(...)
    embedder = EmbeddingService(provider="gemini", api_key=os.environ["GEMINI_API_KEY"])
    extractor = EntityExtractionService(api_key=os.environ["GROQ_API_KEY"])
    return ConversationIngestionPipeline(conn, embedder, extractor)
```

### MCP Tool Pattern: `src/codememory/server/tools.py`
```python
class Toolkit:
    @mcp.tool()
    @rate_limit(calls_per_minute=60)
    @log_tool_call
    async def search_conversations(...):
        result = await self._search_conversations(...)
        return validate_tool_output(result)
```

### GraphWriter Extension Points
The planner must add new methods to `GraphWriter`:
- `write_session_node(props: dict)` — MERGE on session_id
- `write_has_turn_relationship(session_id, turn_source_key, turn_content_hash, order)` — Session → Turn
- `write_part_of_turn_relationship(turn_source_key, turn_content_hash, session_id)` — Turn → Session
- Vector search method for conversations (or extend existing search pattern)

</code_context>

<specifics>
## Specific Implementation Notes

- **Embedding only user/assistant turns** — system and tool turns stored without embedding. Keeps vector index focused on semantically searchable content. Tool call data is often too structured (JSON) to be useful for semantic search.
- **Session node dedup:** MERGE on `session_id` — update `last_turn_index = max(existing, new)` and `turn_count` on each write.
- **`get_conversation_context` surrounding turns:** when `include_session_context=True`, for each vector-matched turn fetch the previous and next turn in the same session. This requires a Cypher lookup by `(session_id, turn_index ± 1)`. Provides LLMs with conversational framing (knowing what prompted a response or what followed from a user message).
- **REST ingest is the primary passive path** — am-proxy and am-ext POST to `/ingest/conversation`. The MCP `add_message` tool is for explicit agent writes. Both hit `ConversationIngestionPipeline.ingest()` identically; `ingestion_mode` in the payload distinguishes them.
- **`chat-ingest` CLI auto-indexes:** Running `chat-ingest` should call `setup_database()` automatically if indexes don't exist, so users don't need to run `chat-init` first.
- **Token count approximation:** `int(len(content.split()) * 1.3)` — same pattern as the chunker. No tiktoken dependency needed.
- **Role validation:** accept `["user", "assistant", "system", "tool"]` only. Raise ValueError on unknown roles rather than silently storing.

</specifics>

<deferred>
## Deferred Ideas

- **Conversation analytics** (sentiment, topic modeling, speaker stats) — out of scope for v1; mentioned in PROJECT.md Out of Scope
- **Streaming ingest** (Server-Sent Events or WebSocket for real-time turn appending) — batch REST POST is sufficient for v1; streaming is future
- **Session summarization** — generate a summary node for long sessions — future improvement
- **Cross-session conversation threads** — linking related sessions by topic or entity — Phase 7 (Cross-Module Integration)
- **Provider-specific import adapters** (Claude Code export format, ChatGPT export JSON, etc.) — v1 uses generic JSONL; provider adapters are a future quality-of-life improvement
- **Confidence-weighted search** using `confidence` field — not applicable to conversation turns (no confidence score), skip
- **Retroactive re-embedding** of system/tool turns if embedding strategy changes — low priority, skip for now

</deferred>

---

*Phase: 04-conversation-memory-core*
*Context gathered: 2026-03-22*
