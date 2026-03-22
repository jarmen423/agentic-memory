---
phase: 04-conversation-memory-core
plan: "03"
subsystem: api
tags: [fastapi, mcp, fastmcp, neo4j, conversation, vector-search, pydantic]

# Dependency graph
requires:
  - phase: 04-02
    provides: ConversationIngestionPipeline with ingest() method
  - phase: 02-04
    provides: am-server FastAPI app factory, auth middleware, REST pattern

provides:
  - POST /ingest/conversation REST endpoint (202, Bearer auth)
  - GET /search/conversations REST endpoint (vector + text fallback, Bearer auth)
  - ConversationIngestRequest Pydantic model in am_server/models.py
  - get_conversation_pipeline() @lru_cache factory in am_server/dependencies.py
  - search_conversations MCP tool (semantic search over chat_embeddings)
  - get_conversation_context MCP tool (vector search with +/-1 surrounding turn context window)
  - add_message MCP tool (explicit turn write, hardcoded source_key='chat_mcp')

affects:
  - 05-am-proxy
  - 06-am-ext
  - any client that POSTs conversation turns to am-server

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "REST conversation router follows same pattern as research.py: APIRouter(dependencies=[Depends(require_auth)])"
    - "get_conversation_pipeline() uses @lru_cache(maxsize=1) — independent singleton from get_pipeline()"
    - "MCP conversation tools wrapped in register_conversation_tools(mcp) to avoid circular imports with app.py"
    - "search_conversations vector first, text CONTAINS fallback if embedding fails"
    - "get_conversation_context fetches prev_index=t_idx-1 and next_index=t_idx+1 per match; prev_index=-1 when t_idx=0 never matches any node"

key-files:
  created:
    - src/am_server/routes/conversation.py
  modified:
    - src/am_server/models.py
    - src/am_server/dependencies.py
    - src/am_server/app.py
    - src/codememory/server/tools.py
    - src/codememory/server/app.py

key-decisions:
  - "register_conversation_tools(mcp) function pattern in tools.py avoids circular import: tools.py cannot import mcp from app.py since app.py imports tools.py"
  - "register_conversation_tools called at module level in app.py after mcp instance creation — tools registered at import time"
  - "MCP tools are async; existing code-memory tools in app.py are sync — both patterns supported by FastMCP"
  - "Existing Toolkit class in tools.py left unchanged; new tools added via register_conversation_tools() at end of file"

patterns-established:
  - "Conversation REST endpoint pattern: asyncio.get_event_loop().run_in_executor() for sync pipeline.ingest() calls"
  - "Vector search with project_id/role WHERE clause post-YIELD filtering"
  - "Text fallback wrapped in nested try/except returning empty list on double-failure"

requirements-completed: []

# Metrics
duration: 7min
completed: 2026-03-22
---

# Phase 4 Plan 03: am-server Conversation Endpoints + MCP Tools Summary

**REST endpoints POST /ingest/conversation and GET /search/conversations wired to ConversationIngestionPipeline; three MCP tools (search_conversations, get_conversation_context, add_message) registered on FastMCP server via circular-import-safe register_conversation_tools() pattern**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-22T16:19:47Z
- **Completed:** 2026-03-22T16:26:04Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Conversation REST API layer complete: POST /ingest/conversation (202) and GET /search/conversations (vector + text fallback), both requiring Bearer auth
- Three MCP conversation tools registered on FastMCP: semantic search, context retrieval with surrounding turns, and explicit message write
- Lifespan warm-up extended to include conversation pipeline alongside research pipeline; all 11 existing am-server tests still pass

## Task Commits

1. **Task 1: Pydantic model + dependency factory + REST router** - `e8d6734` (feat)
2. **Task 2: MCP tools in tools.py** - `a0a2d02` (feat)

**Plan metadata:** (this commit — docs)

## Files Created/Modified

- `src/am_server/routes/conversation.py` — Created: POST /ingest/conversation + GET /search/conversations with vector/text fallback
- `src/am_server/models.py` — Added ConversationIngestRequest with all turn schema fields
- `src/am_server/dependencies.py` — Added get_conversation_pipeline() @lru_cache factory; added ConversationIngestionPipeline import
- `src/am_server/app.py` — Added conversation router registration; added conversation pipeline lifespan warm-up
- `src/codememory/server/tools.py` — Added _get_mcp_conversation_pipeline() factory, register_conversation_tools() with 3 async MCP tools
- `src/codememory/server/app.py` — Added register_conversation_tools(mcp) call at module level

## Decisions Made

- Used `register_conversation_tools(mcp)` function pattern instead of direct `@mcp.tool()` decorators at module level in tools.py — avoids circular import since app.py would need to import tools.py and tools.py would need to import mcp from app.py
- Called `register_conversation_tools(mcp)` at module level in app.py (not inside a startup function) so tools are registered at import time, consistent with how existing inline tools in app.py are registered
- MCP conversation tools are async (per plan spec); existing code-memory tools in app.py are sync — FastMCP handles both

## Deviations from Plan

None — plan executed exactly as written. The `register_conversation_tools(mcp)` pattern was explicitly documented as the correct approach for the circular import scenario, and the plan's note confirmed this was the right choice for the existing codebase structure.

## Issues Encountered

None. Import verification, route registration check, and full test suite all passed on first attempt.

## User Setup Required

None — no external service configuration required. Uses existing NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GEMINI_API_KEY, GROQ_API_KEY, and AM_SERVER_API_KEY env vars from prior phases.

## Next Phase Readiness

- am-server conversation API is complete and ready for am-proxy (Phase 5) to POST to /ingest/conversation with source_key="chat_proxy"
- am-ext (Phase 6) can POST to /ingest/conversation with source_key="chat_ext"
- MCP tools search_conversations, get_conversation_context, add_message available to any MCP client
- Phase 4 has one remaining plan (04-04 CLI commands) before phase is complete

## Self-Check: PASSED

- src/am_server/routes/conversation.py: FOUND
- src/am_server/models.py: FOUND
- src/codememory/server/tools.py: FOUND
- Commit e8d6734 (Task 1): FOUND
- Commit a0a2d02 (Task 2): FOUND

---
*Phase: 04-conversation-memory-core*
*Completed: 2026-03-22*
