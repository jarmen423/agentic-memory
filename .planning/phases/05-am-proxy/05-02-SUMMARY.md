---
phase: "05"
plan: "02"
subsystem: "am-proxy"
tags: ["asyncio", "fire-and-forget", "stdio-proxy", "httpx", "acp"]
dependency_graph:
  requires: ["05-01"]
  provides: ["IngestClient", "ACPProxy"]
  affects: ["05-03"]
tech_stack:
  added: ["httpx async client per-call pattern", "asyncio.TimerHandle buffer TTL"]
  patterns: ["fire-and-forget with _pending set (GC-safe Python 3.12+)", "silent failure contract"]
key_files:
  created:
    - packages/am-proxy/src/am_proxy/ingest.py
    - packages/am-proxy/src/am_proxy/proxy.py
    - packages/am-proxy/tests/test_ingest.py
    - packages/am-proxy/tests/test_proxy.py
  modified:
    - .planning/phases/05-am-proxy/05-02-PLAN.md
decisions:
  - "Used asyncio.get_event_loop().call_later() for buffer TTL as specified in CONTEXT.md"
  - "fire_and_forget uses _pending set to hold strong references — prevents GC on Python 3.12+ (CPython #117379)"
  - "_handle_line wrapped in try/except Exception to ensure routing errors never surface"
  - "threads/update ingests unless explicitly done=False (default True = ingest)"
  - "tool_call id extracted from msg.get('id') first, params.get('id') as fallback"
metrics:
  duration: "~15 minutes"
  completed: "2026-03-25T04:13:00Z"
  tasks_completed: 3
  files_created: 4
---

# Phase 05 Plan 02: IngestClient + ACPProxy Core + Tests Summary

## One-liner

Fire-and-forget HTTP ingest client with GC-safe task retention plus full ACP routing proxy with buffer TTL eviction, implemented with 22 passing unit tests.

## What Was Built

### `packages/am-proxy/src/am_proxy/ingest.py` — IngestClient

`IngestClient` posts conversation turns to `POST /ingest/conversation` as non-blocking fire-and-forget tasks. Key design: `_pending: set[asyncio.Task[None]]` holds strong references to in-flight tasks, preventing Python 3.12+ GC from collecting tasks before they complete (CPython issue #117379). The `done_callback` discards each task from `_pending` once complete. All exceptions in `_post()` are swallowed with bare `except Exception: pass` — ingest failure never affects the agent session.

### `packages/am-proxy/src/am_proxy/proxy.py` — ACPProxy

`ACPProxy` implements bidirectional ACP stdio proxying with full message routing per the CONTEXT.md routing table:

- `threads/create` — initializes `_session_turn_counts[session_id] = 0`, no ingest
- `threads/message` — posts user turn with `role="user"`, `source_key="chat_proxy"`, `ingestion_mode="passive"`
- `threads/update` — posts assistant turn only when `params.get("done", True)` is not False
- `threads/tool_call` — buffers by JSON-RPC `id`, schedules TTL eviction via `asyncio.get_event_loop().call_later()`
- `threads/tool_result` — matches buffer by id, POSTs tool_call + tool_result as two turns, cancels TTL handle
- `$`-prefixed methods — silently skipped, never ingested
- Unrecognized methods — pass-through only

The `run()` method spawns a subprocess and runs three concurrent tasks via `asyncio.gather()`: stdin forwarding via `loop.run_in_executor()`, stdout pass-through, and stderr pass-through.

### Test Coverage

**`test_ingest.py`** (5 tests):
- Task added to `_pending` immediately on `fire_and_forget()`
- Task removed from `_pending` after completion
- `_post()` sends correct JSON payload + Bearer auth header
- HTTP exceptions swallowed silently
- Timeouts swallowed silently

**`test_proxy.py`** (17 tests):
- `threads/message` routes to `fire_and_forget` with correct turn fields
- Turn index increments per session
- `$/ping` and `$/progress` not ingested
- Unknown methods not ingested
- `threads/update` with `done=True` ingested, `done=False` skipped, missing `done` ingested
- `threads/tool_call` buffered but not posted
- `threads/tool_result` triggers exactly 2 posts, clears buffer
- Orphaned tool results ignored
- Buffer TTL evicts entry after 50ms
- TTL cancelled when result arrives before TTL fires
- Non-JSON lines, empty lines, JSON-RPC responses — all handled without exception
- `threads/create` initializes session turn counter

## Test Results

```
packages/am-proxy: 22 passed in ~0.5s
main test suite:   218 passed, 2 skipped (Neo4j unavailable — expected)
```

## Deviations from Plan

None — plan executed exactly as written. All implementation details from the plan spec were followed verbatim including the exact method signatures, `_pending` set pattern, `asyncio.get_event_loop().call_later()` for TTL, and the `try/except Exception: pass` routing guard.

## Known Stubs

None. Both modules are fully wired. `ingest.py` makes real HTTP calls (mocked in tests). `proxy.py` runs real subprocesses in `run()` (not tested at unit level — subprocess integration is deferred to plan 05-03 cli tests).

## Self-Check: PASSED

Files created:
- FOUND: packages/am-proxy/src/am_proxy/ingest.py
- FOUND: packages/am-proxy/src/am_proxy/proxy.py
- FOUND: packages/am-proxy/tests/test_ingest.py
- FOUND: packages/am-proxy/tests/test_proxy.py

Commit: 8e29888 — verified in git log.
