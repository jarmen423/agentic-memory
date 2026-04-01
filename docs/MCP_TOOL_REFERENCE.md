# MCP Tool Reference

This document describes the primary MCP surfaces exposed by the current server implementation.

## Core code-memory tools

- `search_codebase(query, limit=5, domain="code")`
  Searches code or git-aware memory depending on `domain`.

- `get_file_dependencies(file_path, domain="code")`
  Returns imports and dependents for a file.

- `identify_impact(file_path, max_depth=3, domain="code")`
  Returns transitive impact information for a file.

- `get_file_info(file_path, domain="code")`
  Returns structure and metadata for a file.

## Research-memory tools

- `memory_ingest_research(...)`
  Stores research reports or findings into research memory.

- `search_web_memory(query, limit=5, as_of=None)`
  Searches research memory. Uses temporal retrieval when the bridge is available and seeded; otherwise falls back to the baseline path.

- `brave_search(query, count=5, freshness=None)`
  Executes Brave Search without ingesting by default.

## Conversation-memory tools

- `search_conversations(query, project_id=None, role=None, limit=10, as_of=None)`
  Searches conversation memory with temporal-first behavior and deterministic fallback.

- `get_conversation_context(session_id, turn_index, as_of=None)`
  Returns the local context window around a turn.

- `add_message(...)`
  Ingests a conversation turn directly through the MCP layer.

## Unified Phase 10 tool

- `search_all_memory(query, limit=10, project_id=None, as_of=None, modules=None)`
  Runs unified cross-module retrieval across:
  - code
  - web research
  - conversation

### Normal behavior

- code results come from the existing code graph search
- web and conversation results keep their temporal-first behavior
- one module can fail without suppressing healthy modules

### `modules` filter

Optional comma-separated subset:

- `code`
- `web`
- `conversation`

Examples:

- `modules="code,web"`
- `modules="conversation"`

### Fallback behavior

- if the temporal bridge is unavailable, baseline results are still returned
- if temporal retrieval fails, the API contract stays stable and results fall back deterministically
- partial failures are returned as warnings or `errors`, not as a global hard failure

## REST parity

Phase 10 added REST parity for unified search:

- `GET /search/all`

This endpoint mirrors the unified normalized result contract used by `search_all_memory`.

## Request correlation

`am-server` now emits an `X-Request-ID` header. That request id is also propagated into structured fallback logs for the REST path.
