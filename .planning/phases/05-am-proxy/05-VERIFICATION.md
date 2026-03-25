---
phase: 05-am-proxy
verified: 2026-03-25T00:00:00Z
status: passed
score: 6/6 success criteria verified
---

# Phase 5: am-proxy — Verification Report

**Phase Goal:** Build `packages/am-proxy/` — a standalone Python package that transparently proxies stdio between an editor and an ACP-compliant agent CLI, silently tees conversation turns to `POST /ingest/conversation`, and never impacts agent session latency.

**Verified:** 2026-03-25
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Success Criteria

### SC-1: `am-proxy --agent claude --project test` starts cleanly and passes stdin/stdout transparently

**Status: VERIFIED**

Evidence:
- `packages/am-proxy/pyproject.toml` line 16: entry point `am-proxy = "am_proxy.cli:main"` wired correctly
- `cli.py` lines 108-141: `main()` parses `--agent` and `--project`, calls `asyncio.run(_run_proxy(...))`
- `proxy.py` lines 253-292: `ACPProxy.run()` spawns subprocess via `asyncio.create_subprocess_exec`, pipes stdin/stdout/stderr using three concurrent asyncio tasks via `asyncio.gather()`
- `cli.py` lines 119-122: `parse_known_args()` captures all unrecognized flags into `agent_args` and passes them through to the subprocess
- Test `test_main_passes_agent_args_through` (test_cli.py line 197) confirms passthrough behavior
- 41/41 tests pass (`python -m pytest tests/ -q --tb=short`)

### SC-2: Agent session runs with zero measurable latency overhead (fire-and-forget confirmed)

**Status: VERIFIED**

Evidence:
- `ingest.py` line 43: `task = asyncio.create_task(self._post(turn))` — task is scheduled without awaiting
- `proxy.py` line 164: `self._ingest_client.fire_and_forget(turn)` — called synchronously in `_handle_line`, which itself is called after the pass-through write has already happened (proxy.py lines 268-270: write, drain, then handle)
- `proxy.py` lines 277-279: child→stdout path writes and flushes before calling `_handle_line` — the agent's output reaches the editor before any ingest processing begins
- `ingest.py` lines 35-45: `_pending` set holds strong references to in-flight tasks (GC-safe on Python 3.12+, CPython issue #117379)
- The ingest path is entirely decoupled from the stdio pass-through path — no `await` on ingest calls in either direction

### SC-3: `threads/message` turns are POSTed to `/ingest/conversation` (implementation confirmed in code)

**Status: VERIFIED**

Evidence:
- `proxy.py` lines 152-164: `threads/message` handler constructs a turn dict with `role="user"`, `ingestion_mode="passive"`, `source_key="chat_proxy"`, `session_id`, `project_id`, `turn_index`, `source_agent`, then calls `fire_and_forget(turn)`
- `ingest.py` lines 47-61: `_post()` sends `POST` to `f"{self._config.endpoint}/ingest/conversation"` with the turn as JSON body and `Authorization: Bearer {api_key}` header
- Turn schema matches `ConversationIngestRequest` from Phase 4 (`role`, `content`, `session_id`, `project_id`, `turn_index`, `source_agent`, `ingestion_mode`, `source_key` all present)
- Test `test_threads_message_calls_fire_and_forget` (test_proxy.py line 31) verifies `role=="user"`, `source_key=="chat_proxy"`, `ingestion_mode=="passive"`, `project_id=="test-proj"`, `turn_index==0`
- Test `test_post_sends_correct_payload` (test_ingest.py line 39) verifies the HTTP POST targets `/ingest/conversation` with correct JSON and Bearer header

### SC-4: Protocol noise (ping/pong, $/progress) is never forwarded to the memory server

**Status: VERIFIED**

Evidence:
- `proxy.py` lines 144-146: `if method.startswith("$"): return` — all `$`-prefixed methods are skipped before any ingest action
- This covers `$/ping`, `$/pong`, `$/progress`, and any other `$`-prefixed protocol messages
- `proxy.py` lines 138-139: JSON-RPC response objects (no `method` field) also return early — no ingest
- Test `test_dollar_ping_not_ingested` (test_proxy.py line 71): confirms `$/ping` produces no `fire_and_forget` call
- Test `test_dollar_progress_not_ingested` (test_proxy.py line 78): confirms `$/progress` produces no `fire_and_forget` call
- Test `test_unknown_method_not_ingested` (test_proxy.py line 85): confirms unrecognized methods are not ingested
- Test `test_jsonrpc_response_no_method_not_ingested` (test_proxy.py line 277): confirms response objects with no method field are not ingested

### SC-5: Memory server downtime (5s timeout) is swallowed silently — agent session unaffected

**Status: VERIFIED**

Evidence:
- `config.py` line 33: `timeout_seconds: float = 5.0` — default timeout is 5 seconds
- `ingest.py` line 54: `async with httpx.AsyncClient(timeout=self._config.timeout_seconds)` — timeout applied to each POST
- `ingest.py` lines 53-61: full `try/except Exception: pass` wrapping the HTTP call — all exceptions including `httpx.TimeoutException` and `ConnectionRefusedError` are silently discarded
- `proxy.py` line 239-240: `_handle_line` is itself wrapped in `except Exception: pass` — routing errors cannot surface either
- Test `test_post_swallows_http_exception` (test_ingest.py line 63): verifies `Exception("connection refused")` does not propagate
- Test `test_post_swallows_network_timeout` (test_ingest.py line 75): verifies `httpx.TimeoutException` does not propagate
- Because ingest tasks run via `asyncio.create_task()`, a timeout or failure in `_post` does not affect the main proxy loop's stdin/stdout throughput

### SC-6: Buffer TTL: unbuffered requests are evicted after 300s with no memory leak

**Status: VERIFIED**

Evidence:
- `config.py` line 34: `buffer_ttl_seconds: float = 300.0` — default TTL is 300 seconds
- `proxy.py` lines 98-113: `_buffer_tool_call()` calls `asyncio.get_event_loop().call_later(self._config.buffer_ttl_seconds, self._evict_buffer, request_id)` — schedules eviction
- `proxy.py` lines 115-121: `_evict_buffer()` calls `self._buffer.pop(request_id, None)` — removes the entry cleanly with no exception on missing key
- `proxy.py` lines 106-107: if the same `request_id` is re-buffered, the existing `call_later` handle is cancelled before creating a new one — no duplicate timers
- `proxy.py` lines 193-194: on matching `tool_result`, the cancel handle is explicitly cancelled and the entry is popped — no TTL fires after result
- Test `test_buffer_ttl_evicts_entry` (test_proxy.py line 204): uses 50ms TTL, confirms entry present after buffering and absent after `asyncio.sleep(0.1)`
- Test `test_buffer_ttl_cancelled_on_result` (test_proxy.py line 228): confirms TTL handle is cancelled when `tool_result` arrives, no leak after TTL window passes
- Test `test_tool_call_buffered_not_ingested` (test_proxy.py line 141): confirms `tool_call` is buffered (not immediately posted) and `"call-1"` key present in `_buffer`

---

## Artifact Summary

| Artifact | Status | Evidence |
| -------- | ------ | -------- |
| `packages/am-proxy/pyproject.toml` | VERIFIED | Entry point, deps (httpx, tomli conditional), hatchling build, dev extras |
| `packages/am-proxy/src/am_proxy/proxy.py` | VERIFIED | ACPProxy class, full ACP routing table, buffer TTL, turn construction, 293 lines |
| `packages/am-proxy/src/am_proxy/ingest.py` | VERIFIED | IngestClient, fire_and_forget, GC-safe _pending set, silent failure, 61 lines |
| `packages/am-proxy/src/am_proxy/cli.py` | VERIFIED | main(), argparse, Windows ProactorEventLoop policy, setup subcommand, 141 lines |
| `packages/am-proxy/src/am_proxy/config.py` | VERIFIED | ProxyConfig dataclass, load_config(), TOML loading with defaults, 67 lines |
| `packages/am-proxy/src/am_proxy/agents.py` | VERIFIED | AGENT_CONFIGS (claude/codex/gemini/opencode/kiro), get_agent_config(), detect_installed_agents() |
| `packages/am-proxy/tests/test_proxy.py` | VERIFIED | 22 tests covering all ACP routing paths and buffer TTL |
| `packages/am-proxy/tests/test_ingest.py` | VERIFIED | 5 tests covering fire-and-forget, GC safety, payload, silent failure |
| `packages/am-proxy/tests/test_cli.py` | VERIFIED | 14 tests covering arg parsing, setup subcommand, Windows policy, exit codes |

---

## Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `cli.py:main()` | `proxy.py:ACPProxy.run()` | `asyncio.run(_run_proxy(...))` | VERIFIED |
| `proxy.py:_handle_line()` | `ingest.py:IngestClient.fire_and_forget()` | direct call, no await | VERIFIED |
| `ingest.py:_post()` | `POST /ingest/conversation` | `httpx.AsyncClient.post()` | VERIFIED |
| `proxy.py:_buffer_tool_call()` | `proxy.py:_evict_buffer()` | `asyncio.call_later(ttl, ...)` | VERIFIED |
| `cli.py:main()` | `asyncio.WindowsProactorEventLoopPolicy` | `if sys.platform == "win32"` | VERIFIED |

---

## Test Results

```
41 passed in 0.66s
```

All 41 tests pass across `test_proxy.py` (22 tests), `test_ingest.py` (5 tests), and `test_cli.py` (14 tests).

---

## Anti-Patterns Scan

No blockers or warnings found:
- No TODO/FIXME/placeholder comments in source files
- No `return null` or empty stub implementations
- All exception handlers are intentional silent-failure contracts per spec (documented in docstrings and inline comments)
- `except Exception: pass` in `_handle_line` (proxy.py line 239) and `_post` (ingest.py line 60) are correct per the silent failure contract — not accidental swallows
- Hardcoded `_fallback_session_id = str(uuid4())` (proxy.py line 56) is intentional per spec: "generate str(uuid4()) once per proxy invocation as fallback"

---

## Human Verification Required

### 1. End-to-end stdio passthrough with a real agent

**Test:** Install am-proxy (`pip install -e packages/am-proxy`), run `am-proxy --agent claude --project test` in a terminal where `claude` is on PATH, send an ACP message via stdin, confirm the message appears on stdout unchanged.

**Expected:** Identical bytes in and out; no proxy artifacts on stdout; ingest POST fires asynchronously to am-server.

**Why human:** Cannot test subprocess stdin/stdout passthrough with real agent binary programmatically without a running agent.

### 2. am-proxy setup output in an editor context

**Test:** Run `am-proxy setup` on a machine where `claude` (or another supported agent) is on PATH.

**Expected:** Prints the correct editor config snippet for each detected agent.

**Why human:** `detect_installed_agents()` uses `shutil.which()` which depends on actual PATH state; test suite mocks this.

---

## Summary

Phase 5 goal is fully achieved. The `packages/am-proxy/` package is a complete, standalone, installable Python package that:

1. Provides a working CLI entry point (`am-proxy`) with correct pyproject.toml wiring
2. Proxies ACP stdio transparently with Windows ProactorEventLoop compatibility
3. Routes all six ACP message types (`threads/create`, `threads/message`, `threads/update`, `threads/tool_call`, `threads/tool_result`, and `$`-prefixed noise) correctly
4. Fires ingest POSTs as non-blocking asyncio tasks with GC-safe task retention
5. Enforces silent failure at every error boundary (routing, HTTP, timeout)
6. Evicts unmatched tool_call buffer entries after configurable TTL (default 300s) with no memory leak
7. Passes 41 unit tests covering all success criteria

---

_Verified: 2026-03-25_
_Verifier: Claude (gsd-verifier)_
