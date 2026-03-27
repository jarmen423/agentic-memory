# 09-02 Summary: Temporal-First Retrieval Cutover with Fallback

**Date:** 2026-03-26  
**Status:** Complete

## Delivered

- Added `src/codememory/temporal/seeds.py`
  - `collect_seed_entities`
  - `extract_query_seed_entities`
  - `parse_as_of_to_micros`
  - `parse_conversation_source_id`
- Updated `src/codememory/server/tools.py`
  - shared temporal-first conversation search helpers
  - `get_conversation_context` now uses temporal PPR when project scope + seeds + bridge data are available
  - deterministic fallback to current vector/text behavior remains in place
- Updated `src/codememory/server/app.py`
  - `search_web_memory` is now temporal-first when seeds and a dominant project id are available
  - preserves the existing string-style MCP response contract
- Updated `src/am_server/routes/conversation.py`
  - added `as_of`
  - `/search/conversations` now uses the temporal-first helper path while preserving `{"results": [...]}` output

## Behavior

- Seed discovery is shared instead of duplicated across MCP and REST entry points.
- Invalid `as_of` values no longer crash the temporal path.
- Temporal conversation evidence is hydrated back to the existing Neo4j turn nodes by `session_id + turn_index`.
- Temporal search failures, empty temporal results, or missing seeds fall back to the prior baseline behavior with server-side logging.

## Verification

- `python -m pytest tests/test_server.py -x -q`
- `python -m pytest tests/test_web_tools.py -x -q`
- `python -m pytest tests/test_am_server.py -x -q`
- `python -m pytest tests/test_scheduler.py -x -q`
- `python -c "from codememory.temporal.seeds import collect_seed_entities, parse_as_of_to_micros; print('seed helpers ok')"`

All passed.
