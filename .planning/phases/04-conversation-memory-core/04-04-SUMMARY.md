---
phase: 04-conversation-memory-core
plan: "04"
subsystem: cli
tags: [cli, argparse, neo4j, gemini, conversation, chat]

# Dependency graph
requires:
  - phase: 04-01
    provides: fix_vector_index_dimensions() on ConnectionManager
  - phase: 04-02
    provides: ConversationIngestionPipeline with ingest() method

provides:
  - chat-init CLI command (setup_database + fix_vector_index_dimensions)
  - chat-ingest CLI command (JSONL/JSON array/stdin ingestion)
  - chat-search CLI command (semantic vector search over chat_embeddings)

affects:
  - 04-03 (MCP tools reference same pipeline pattern)
  - 05-am-proxy (will POST to REST instead of CLI, but same pipeline)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Local imports inside cmd_ functions to avoid circular deps and lazy-load heavy deps"
    - "getattr(args, flag, default) pattern for optional argparse flags"
    - "Auto-initialize indexes in chat-ingest (idempotent setup_database call)"
    - "Continue-on-error per-turn ingestion with final skipped count report"

key-files:
  created: []
  modified:
    - src/codememory/cli.py

key-decisions:
  - "chat-ingest --project-id is required flag (not optional) to ensure all turns are project-scoped"
  - "chat-ingest calls setup_database() automatically so users don't need chat-init first"
  - "--session-id flag overrides per-turn session_id (flag wins over data)"
  - "turn_index auto-assigned from 0-based loop position if absent in turn data"
  - "source_key defaults to chat_cli for CLI ingestion path"
  - "ingestion_mode defaults to manual for CLI-ingested turns"
  - "ValueError from pipeline.ingest() is caught and turn is skipped, not fatal"
  - "chat-search content truncated to 120 chars for display; --json flag for machine-readable output"

patterns-established:
  - "3-part change for new CLI command: function + subparser + dispatch branch (all in one commit)"

requirements-completed: []

# Metrics
duration: 3min
completed: "2026-03-22"
---

# Phase 4 Plan 04: CLI Commands (chat-init, chat-ingest, chat-search) Summary

**Three chat CLI commands replacing stubs: chat-init runs DB migration, chat-ingest ingests JSONL/JSON/stdin with per-turn error recovery, chat-search does semantic vector search over chat_embeddings via Gemini embeddings**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-22T16:19:44Z
- **Completed:** 2026-03-22T16:22:33Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Replaced `cmd_chat_init` stub: now calls `conn.setup_database()` then `conn.fix_vector_index_dimensions()` with confirmation messages for each step
- Replaced `cmd_chat_ingest` stub: handles JSONL file, JSON array file, and stdin JSONL; auto-assigns turn_index; `--session-id` flag overrides per-turn values; continues on per-turn errors; reports final `turns_ingested/turns_skipped/entities_extracted/duration_s`
- Added `cmd_chat_search`: embeds query via Gemini, queries `chat_embeddings` vector index, outputs formatted table (or JSON with `--json`), content truncated to 120 chars
- Added `--project-id` (required), `--session-id`, `--source-agent` flags to `chat_ingest_parser`
- Added `chat-search` subparser with `query`, `--project-id`, `--role`, `--limit`, `--json` flags
- Added `elif args.command == "chat-search": cmd_chat_search(args)` dispatch branch

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement cmd_chat_init and cmd_chat_ingest** - `c5d77ac` (feat)
2. **Task 2: Add cmd_chat_search + subparser + dispatch** - `b2b5be5` (feat)

## Files Created/Modified

- `src/codememory/cli.py` - Replaced two stubs, added cmd_chat_search function, updated chat_ingest_parser with flags, added chat-search subparser and dispatch branch

## Decisions Made

- `--project-id` is a `required=True` flag on `chat-ingest` (not optional) — ensures all CLI-ingested turns are project-scoped; matches CONTEXT.md requirement
- `chat-ingest` calls `conn.setup_database()` before pipeline construction so users don't need to run `chat-init` separately
- `--session-id` flag assignment uses direct `turn["session_id"] = session_id_flag` (overrides existing value) per key decision in plan
- `source_key` defaults to `"chat_cli"` via `turn.setdefault()` — per-turn data can still override
- `ingestion_mode` defaults to `"manual"` for CLI-sourced turns (vs. `"active"` for MCP writes)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - both tasks executed cleanly. All three `--help` outputs verified before committing.

## User Setup Required

None - no external service configuration required. (Neo4j and GEMINI_API_KEY env vars must already be configured from prior phases.)

## Next Phase Readiness

- All three chat CLI commands operational and verified via `--help` output
- `chat-ingest` and `chat-search` will work end-to-end once Neo4j is running with `chat-init` run first
- Phase 4 plans 04-01 through 04-04 complete — conversation memory CLI layer is done
- Phase 5 (am-proxy) and Phase 6 (am-ext) unblocked — they POST to REST endpoints, not CLI

---
*Phase: 04-conversation-memory-core*
*Completed: 2026-03-22*
