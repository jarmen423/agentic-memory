---
phase: 01-foundation
plan: 04
subsystem: ingestion
tags: [neo4j, knowledge-graph, treesitter, cli, docker, abc, registry]

# Dependency graph
requires:
  - phase: 01-03
    provides: BaseIngestionPipeline ABC, ConnectionManager, SOURCE_REGISTRY
  - phase: 01-01
    provides: ConnectionManager, register_source
  - phase: 01-02
    provides: EmbeddingService, EntityExtractionService
provides:
  - KnowledgeGraphBuilder subclassing BaseIngestionPipeline with DOMAIN_LABEL="Code"
  - code_treesitter registered in SOURCE_REGISTRY at import time
  - src/codememory/web/__init__.py stub package
  - src/codememory/chat/__init__.py stub package
  - 5 new CLI stub commands (web-init, web-ingest, web-search, chat-init, chat-ingest)
  - docker-compose.yml updated with single-instance design documentation
affects: [02-web-research, 04-conversation-memory, 05-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Backward-compatible super().__init__() bridge: ConnectionManager created internally, self.driver = self._conn.driver preserves existing call sites"
    - "Module-level register_source() call at import time auto-populates SOURCE_REGISTRY"
    - "Stub CLI commands: print 'Not yet implemented' + sys.exit(0) as Phase N placeholder pattern"

key-files:
  created:
    - src/codememory/web/__init__.py
    - src/codememory/chat/__init__.py
  modified:
    - src/codememory/ingestion/graph.py
    - src/codememory/cli.py
    - docker-compose.yml
    - tests/test_cli.py

key-decisions:
  - "KnowledgeGraphBuilder.__init__ creates ConnectionManager internally and calls super().__init__(conn) to satisfy ABC — preserves (uri, user, password, openai_key, ...) signature for all existing callers"
  - "self.driver = self._conn.driver keeps all 300+ internal method references intact without touching them"
  - "ingest() wraps run_pipeline() as thin ABC compliance shim — does not replace the existing pipeline orchestration"
  - "docker-compose.yml already had single Neo4j instance on 7474/7687 — only comment updated to document the multi-index design"

patterns-established:
  - "ABC bridge pattern: subclass creates dependency internally, exposes it via _conn, mirrors via self.driver for backward compat"
  - "Stub command pattern: cmd_X prints 'Not yet implemented. Coming in Phase N.' and sys.exit(0)"

requirements-completed: [FOUND-KGB-ADOPTION, FOUND-DOCKER, FOUND-CLI-SCAFFOLD, FOUND-BACKWARD-COMPAT]

# Metrics
duration: 8min
completed: 2026-03-21
---

# Phase 1 Plan 04: Foundation Integration Summary

**KnowledgeGraphBuilder wired into BaseIngestionPipeline ABC with backward-compatible bridge; 5 CLI stub commands and web/chat stub packages scaffolded for Phases 2 and 4**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-21T07:00:00Z
- **Completed:** 2026-03-21T07:05:31Z
- **Tasks:** 2
- **Files modified:** 4 (modified) + 2 (created)

## Accomplishments

- KnowledgeGraphBuilder now subclasses BaseIngestionPipeline with DOMAIN_LABEL="Code"; constructor signature unchanged
- SOURCE_REGISTRY populated with `code_treesitter -> ["Memory", "Code", "Chunk"]` at module import time
- ingest() method added to satisfy ABC — delegates to existing run_pipeline()
- 5 stub CLI commands registered, dispatched, and tested: web-init, web-ingest, web-search, chat-init, chat-ingest
- web/ and chat/ stub packages created as landing zones for Phases 2 and 4
- Full test suite (117 tests) passes; no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Adopt BaseIngestionPipeline in KnowledgeGraphBuilder** - `e7e4216` (feat)
2. **Task 2: Scaffold CLI commands and update Docker Compose** - `7d2d6aa` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/codememory/ingestion/graph.py` - Added BaseIngestionPipeline subclassing, DOMAIN_LABEL, ConnectionManager bridge, register_source call, ingest() method
- `src/codememory/web/__init__.py` - Phase 2 stub package (created)
- `src/codememory/chat/__init__.py` - Phase 4 stub package (created)
- `src/codememory/cli.py` - 5 new stub cmd_* functions, 5 subparsers, 5 dispatch branches
- `docker-compose.yml` - Updated header comment to document single-instance multi-index design
- `tests/test_cli.py` - 6 new tests for stub commands and parser registration

## Decisions Made

- **ConnectionManager bridge:** `__init__` creates `ConnectionManager(uri, user, password)` and calls `super().__init__(conn)`. Then `self.driver = self._conn.driver` keeps all 300+ internal method references working without modification. This was the cleanest backward-compatible approach.
- **ingest() as thin wrapper:** The existing `run_pipeline()` is the multi-pass orchestrator. `ingest()` simply calls it, returning a minimal status dict. This satisfies the ABC without disrupting the existing pipeline model.
- **docker-compose.yml unchanged structurally:** The existing file already had a single Neo4j instance on 7474/7687, which matches the CONTEXT.md single-DB decision. Only the header comment was updated to document the multi-index design intent.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 1 foundation is complete: registry, connection manager, embedding service, entity extraction, base pipeline ABC, graph writer, config validator, and KGB adoption are all in place.
- Phase 2 (Web Research Core) can begin: `codememory/web/__init__.py` stub is the landing zone; BaseIngestionPipeline ABC is ready for WebResearchPipeline subclassing; SOURCE_REGISTRY pattern established for `web_crawl4ai` source.
- Phase 4 (Conversation Memory) stub is in place at `codememory/chat/__init__.py`.

---
*Phase: 01-foundation*
*Completed: 2026-03-21*
