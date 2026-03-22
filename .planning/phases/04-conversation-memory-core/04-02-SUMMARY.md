---
phase: 04-conversation-memory-core
plan: "02"
subsystem: ingestion
tags: [neo4j, conversation, chat, pipeline, embedding, entity-extraction, pytest]

# Dependency graph
requires:
  - phase: 04-01
    provides: write_session_node, write_has_turn_relationship, write_part_of_turn_relationship on GraphWriter
  - phase: 01-03
    provides: BaseIngestionPipeline ABC, GraphWriter base, EmbeddingService, EntityExtractionService
provides:
  - ConversationIngestionPipeline in src/codememory/chat/pipeline.py
  - All four chat source keys registered in SOURCE_REGISTRY (chat_mcp, chat_proxy, chat_ext, chat_cli)
  - 22 unit tests covering all turn roles, content_hash behavior, entity wiring
affects: [04-03, 04-04, am-server-conversation-routes, am-proxy, am-ext]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Role-conditional embedding: EMBEDDABLE_ROLES frozenset gates embedding and entity extraction"
    - "Session-scoped content_hash: sha256(session_id:turn_index) excludes content for in-place updates"
    - "Module-level register_source() calls trigger at import time for all domain sources"
    - "Mock writer injection: pipeline._writer = MagicMock() for graph call inspection in tests"

key-files:
  created:
    - src/codememory/chat/pipeline.py
    - tests/test_conversation_pipeline.py
  modified:
    - src/codememory/chat/__init__.py

key-decisions:
  - "EMBEDDABLE_ROLES = frozenset({'user', 'assistant'}) — system and tool turns stored without embedding or entities"
  - "content_hash = sha256(session_id:turn_index) — session-scoped, content-excluded MERGE key enables in-place updates"
  - "source_key defaults to chat_mcp if not specified in source dict"
  - "tokens_approx = int(len(content.split()) * 1.3) — consistent with chunker approximation, no tiktoken"
  - "entity relationship rel_type: ABOUT for project-type entities, MENTIONS for all others"

patterns-established:
  - "ConversationIngestionPipeline mirrors ResearchIngestionPipeline layout exactly (imports, module docstring, register_source calls, class, ingest(), private helpers)"
  - "Test file mirrors test_web_pipeline.py structure with _make_pipeline() and _turn_source() factory helpers"

requirements-completed: []

# Metrics
duration: 7min
completed: "2026-03-22"
---

# Phase 4 Plan 02: ConversationIngestionPipeline Summary

**Turn-by-turn conversation ingestion pipeline with role-conditional embedding, session upsert, and entity wiring — all four chat source keys registered and 22 unit tests green.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-22T16:13:50Z
- **Completed:** 2026-03-22T16:20:45Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Implemented `ConversationIngestionPipeline` in `src/codememory/chat/pipeline.py` as a full `BaseIngestionPipeline` subclass with role-conditional embedding, entity extraction, session upsert, and relationship wiring
- Registered all four chat source keys at module import time: `chat_mcp`, `chat_proxy`, `chat_ext`, `chat_cli` — each mapping to `["Memory", "Conversation", "Turn"]`
- Created 22 unit tests covering subclass contract, role validation, embeddable/non-embeddable flows, content_hash determinism and session-scoping, and source registration — all pass alongside 43 regression tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement src/codememory/chat/pipeline.py** - `a6b46b4` (feat)
2. **Task 2: Populate chat __init__.py + unit tests** - `738ff8f` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/codememory/chat/pipeline.py` - ConversationIngestionPipeline with full ingest() implementation, _ingest_turn(), _turn_content_hash(), _now() helpers
- `src/codememory/chat/__init__.py` - Replaced stub; exports ConversationIngestionPipeline, triggers source registration on import
- `tests/test_conversation_pipeline.py` - 22 tests across 5 test classes: subclass contract, embeddable flow, non-embeddable flow, content hash, source registration

## Decisions Made

None - plan executed exactly as specified. All key decisions were pre-locked in the plan frontmatter and CONTEXT.md.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `ConversationIngestionPipeline` is ready for import in 04-03 (am-server `/ingest/conversation` route) and 04-04 (CLI commands)
- All four chat source keys in `SOURCE_REGISTRY` — downstream routes can use any of `chat_mcp`, `chat_proxy`, `chat_ext`, `chat_cli` as `source_key`
- No blockers or concerns

---
*Phase: 04-conversation-memory-core*
*Completed: 2026-03-22*
