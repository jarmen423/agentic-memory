---
phase: 02-web-research-core
plan: 03
subsystem: web-research
tags: [mcp-tools, cli, brave-search, vector-search, ingestion, tdd]
dependency_graph:
  requires:
    - src/codememory/web/pipeline.py
    - src/codememory/core/connection.py
    - src/codememory/core/embedding.py
    - src/codememory/core/entity_extraction.py
    - src/codememory/web/crawler.py
  provides:
    - memory_ingest_research MCP tool
    - search_web_memory MCP tool
    - brave_search MCP tool
    - cmd_web_init (functional)
    - cmd_web_ingest (functional, PDF detection)
    - cmd_web_search (stub)
  affects:
    - REST API (02-04)
    - Agent research sessions (live)
tech_stack:
  added:
    - httpx (sync HTTP client for Brave Search API)
  patterns:
    - TDD red-green
    - Lazy singleton pattern for research pipeline
    - Local imports inside CLI functions (avoids top-level circular imports)
    - Patch at source module path (not at CLI import path) for unit testing
key_files:
  created:
    - tests/test_web_tools.py
  modified:
    - src/codememory/server/app.py
    - src/codememory/cli.py
    - tests/test_cli.py
decisions:
  - "All 3 MCP tools use sync def matching existing codebase pattern (confirmed rate_limit/log_tool_call are sync wrappers)"
  - "_get_research_pipeline() lazy singleton avoids re-creating connections on every tool call"
  - "brave_search has no auto-ingest — results go to agent context only, never touch Neo4j"
  - "CLI uses local imports inside function bodies to avoid top-level circular import issues"
  - "Test mocking patches source module paths (codememory.core.connection.ConnectionManager) not CLI import paths (codememory.cli.ConnectionManager) because imports are local to function bodies"
  - "Pre-existing test isolation failure in SOURCE_REGISTRY (full suite only) logged to deferred-items.md — not caused by this plan"
metrics:
  duration_minutes: 25
  completed_date: 2026-03-21
  tasks_completed: 2
  files_changed: 4
---

# Phase 02 Plan 03: MCP Tools and CLI Commands Summary

Three MCP tools (memory_ingest_research, search_web_memory, brave_search) and functional CLI commands (web-init, web-ingest with PDF detection) wiring ResearchIngestionPipeline to agents and users.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for MCP web tools | f84d95c | tests/test_web_tools.py |
| 1 (GREEN) | MCP tools implementation | 5537577 | src/codememory/server/app.py |
| 2 (RED) | Failing tests for web CLI commands | 77aff19 | tests/test_cli.py |
| 2 (GREEN) | web-init, web-ingest, web-search implementation | a656ee0 | src/codememory/cli.py, tests/test_cli.py |

## What Was Built

### MCP Tools (src/codememory/server/app.py)

**`_get_research_pipeline()`** — lazy singleton that initializes `ConnectionManager`, `EmbeddingService`, `EntityExtractionService`, and `ResearchIngestionPipeline` on first call. Returns `None` if `GOOGLE_API_KEY` or `GROQ_API_KEY` not set. Stored in module-level `_research_pipeline` global.

**`memory_ingest_research`** — primary agent write path. Accepts type, content, project_id, session_id, source_agent, plus optional title, research_question, confidence, findings, citations. Routes to `pipeline.ingest()` with ingestion_mode="active". Returns JSON string with `{"status": "ok", ...result fields}`. Docstring starts with "ALWAYS call this tool..." for reliable agent invocation. Handles missing pipeline and ingest exceptions with descriptive error strings.

**`search_web_memory`** — vector similarity search over `:Memory:Research` nodes. Embeds query via `pipeline._embedder.embed()`, runs `db.index.vector.queryNodes('research_embeddings', ...)` Cypher, formats results with node type (Finding/Chunk/Research), score, source_agent, and text snippet. Returns "No relevant research found." on empty results.

**`brave_search`** — Brave Search API tool. Guards on `BRAVE_SEARCH_API_KEY` env var. Uses `httpx.Client` (sync, not async) for `GET https://api.search.brave.com/res/v1/web/search` with `X-Subscription-Token` header. Returns formatted results. Zero interaction with Neo4j or ResearchIngestionPipeline — results go to agent context only.

All three tools use synchronous `def` matching the existing `search_codebase` pattern with `@mcp.tool()`, `@rate_limit`, `@log_tool_call` decorators.

### CLI Commands (src/codememory/cli.py)

**`cmd_web_init`** — creates `ConnectionManager` from env vars, calls `conn.setup_database()` to create `research_embeddings` vector index, closes driver, prints "research_embeddings vector index ready." Exits 1 on connection failure.

**`cmd_web_ingest`** — validates `GOOGLE_API_KEY` and `GROQ_API_KEY` (exits 1 if missing). PDF detection: if `url.lower().endswith(".pdf")` or `os.path.isfile(url)` → format="pdf", skips crawl_url. Local PDFs pass path directly; remote PDFs are downloaded with httpx to a temp file. Non-PDF URLs crawled via `asyncio.run(crawl_url(url))` → format="markdown". Builds source dict with `ingestion_mode="manual"` and `session_id=f"web-ingest-{url}"` for dedup. Calls `pipeline.ingest(source)`.

**`cmd_web_search`** — stub prints "web-search: Not yet implemented." and exits 0.

### Tests (tests/test_web_tools.py, tests/test_cli.py)

**test_web_tools.py** — 15 tests covering all 3 MCP tools. Key testing decisions:
- Mock `_get_research_pipeline` directly via `monkeypatch.setattr` for tool tests
- For `brave_search`, patch `codememory.server.app.httpx` module-level to intercept `httpx.Client`
- `test_brave_search_does_not_touch_neo4j` asserts `_get_research_pipeline` never called

**test_cli.py additions** — 6 new tests for web CLI. Key discovery: CLI uses local imports inside function bodies, so `patch("codememory.cli.ConnectionManager")` does NOT work. Must patch at source module path: `patch("codememory.core.connection.ConnectionManager")`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed 3 pre-existing stub tests that asserted old placeholder behavior**
- **Found during:** Task 2 (GREEN run)
- **Issue:** `test_web_init_prints_not_implemented_and_exits_zero` and 2 related tests expected "Not yet implemented" / exit 0, but implementations now call real code
- **Fix:** Updated tests to reflect real implementations (setup_database call, URL required error, stub message)
- **Files modified:** tests/test_cli.py
- **Commit:** a656ee0

**2. [Rule 1 - Bug] Fixed test_stub_commands_are_registered_in_parser**
- **Found during:** Task 2 (GREEN run)
- **Issue:** Test asserted `exit code == 0` for all stub commands, but `web-init` now succeeds without raising SystemExit when mocked
- **Fix:** Changed assertion to `exit code != 2` (argparse unknown command) and wrapped in try/except to handle both success and failure exits
- **Files modified:** tests/test_cli.py
- **Commit:** a656ee0

### Deferred Items

Pre-existing test isolation failure in `test_source_registration` and `test_ingest_finding_flow` when full suite runs — `SOURCE_REGISTRY` global cleared by another test. Exists before this plan. Logged to `.planning/phases/02-web-research-core/deferred-items.md`.

## Self-Check: PASSED

Files exist:
- FOUND: src/codememory/server/app.py (with memory_ingest_research, search_web_memory, brave_search)
- FOUND: src/codememory/cli.py (with cmd_web_init, cmd_web_ingest real implementations)
- FOUND: tests/test_web_tools.py
- FOUND: tests/test_cli.py (with new web tests)

Commits exist:
- FOUND: f84d95c (RED tests for MCP tools)
- FOUND: 5537577 (GREEN MCP tools implementation)
- FOUND: 77aff19 (RED tests for CLI commands)
- FOUND: a656ee0 (GREEN CLI implementation)

Test results:
- tests/test_web_tools.py: 15 passed
- tests/test_cli.py (web tests): 30 passed (all CLI tests)
- tests/test_web_pipeline.py + test_web_tools.py + test_cli.py combined: 76 passed
