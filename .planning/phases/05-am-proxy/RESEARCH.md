# Phase 5: am-proxy — Research

**Researched:** 2026-03-24
**Domain:** Python asyncio subprocess proxy + ACP JSON-RPC protocol + fire-and-forget HTTP
**Confidence:** MEDIUM (ACP param structures inferred; core Python patterns HIGH)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Package Structure:**
```
packages/am-proxy/
├── pyproject.toml           ← standalone package, name = "am-proxy"
├── README.md
└── src/
    └── am_proxy/
        ├── __init__.py
        ├── cli.py            ← entry point
        ├── proxy.py          ← ACPProxy class
        ├── config.py         ← TOML config loader, defaults
        ├── ingest.py         ← fire-and-forget HTTP ingest client
        └── agents.py         ← agent binary → source_agent mapping
```

**pyproject.toml entry point:** `am-proxy = "am_proxy.cli:main"`

**Dependencies:** `httpx`, `tomli ; python_version < "3.11"`. No other external deps.

**Python version:** 3.10+ (use `try: import tomllib except ImportError: import tomli as tomllib`)

**Config file location:** `~/.config/am-proxy/config.toml`

**CLI interface:** `am-proxy --agent <name> [--project <id>] [--endpoint <url>] [--api-key <key>]` and `am-proxy setup`

**Windows:** Set `asyncio.WindowsProactorEventLoopPolicy()` at cli.py entry on `sys.platform == "win32"` before `asyncio.run()`.

**ACP message routing table (locked method names):**
- `threads/create` → extract session_id, initialize turn counter, skip ingest
- `threads/message` → POST as user turn
- `threads/update` → POST as assistant turn only when `params.done == true` or no `done` field
- `threads/tool_call` → buffer by `id`; schedule TTL eviction
- `threads/tool_result` → match buffer, POST tool pair (call + result)
- `$/progress`, `$/ping`, `$/pong`, notifications → pass-through only

**Turn field access patterns (best-effort from CONTEXT.md):**
- `threads/message` content: `params["message"]["content"]` or `str(params["message"])`
- `threads/update` content: `params.get("message", {}).get("content", str(params))`
- `threads/tool_call`: buffer by JSON-RPC `id` field; tool_name/args in params
- Source fields: `source_key = "chat_proxy"`, `ingestion_mode = "passive"`

**Fire-and-forget pattern:** `asyncio.create_task(ingest_client.post_turn(turn))` — do not await.

**IngestClient:** Per-call `async with httpx.AsyncClient(timeout=...)` — no persistent session in v1.

**Buffer TTL:** `asyncio.get_event_loop().call_later(ttl, self._evict_buffer, request_id)`

**Silent failure contract:** am-proxy MUST NEVER print to stdout except agent output, MUST swallow all ingest exceptions.

**Packages directory does not exist** — must be created from scratch.

### Claude's Discretion

- Exact asyncio subprocess stream setup (ProactorEventLoop details, pipe buffering)
- Error handling edge cases in JSON parsing (malformed lines)
- httpx async client reuse strategy (per-call vs persistent session)
- `am-proxy setup` binary detection implementation (shutil.which)
- Exact ACP param structure for content extraction (research may clarify field names)

### Deferred Ideas (OUT OF SCOPE)

- Persistent httpx client with connection pooling
- Metrics/telemetry on proxy throughput
- Multi-agent simultaneous sessions
- ACP spec version negotiation
- `am-proxy` PyPI distribution
- Retry logic for ingest failures
- Config file interactive creation (`am-proxy init`)
</user_constraints>

---

## Summary

Phase 5 builds a pure-Python asyncio stdio proxy that intercepts newline-delimited JSON-RPC 2.0 messages between an editor and any ACP-compliant agent CLI. The proxy passes all bytes through unmodified while asynchronously tee-ing conversation turns to `POST /ingest/conversation` as fire-and-forget tasks.

The implementation has two areas of genuine uncertainty: (1) the exact field names inside ACP `params` objects — the protocol has evolved and different agents use slightly different shapes; and (2) the asyncio stdin-wrapping pattern on Windows, which requires `ProactorEventLoop` and the `connect_read_pipe` API. Both are addressable: the ACP field access should use defensive `.get()` chains with fallbacks, and the Windows stdin pattern has a verified implementation path.

**Primary recommendation:** Build defensively around ACP field access using `.get()` chains with `str(params)` fallbacks. The proxy should never crash on unexpected message shapes — silent pass-through is always the correct fallback behavior.

---

## ACP Protocol Structure

### Confirmed: ACP is Agent Client Protocol (not IBM ACP)

The relevant ACP is the **Agent Client Protocol** at `agentclientprotocol.com` — the LSP-for-agents standard used by Zed, JetBrains AI Assistant, Kiro, GitHub Copilot CLI, and community Claude Code bridges. It is JSON-RPC 2.0 over newline-delimited stdio (NDJSON). This matches the CONTEXT.md description precisely.

**Confidence: HIGH** — verified via official spec, Kiro docs, GitHub Copilot docs, and multiple SDK implementations.

### Method Names: DISCREPANCY FOUND

**Critical finding:** The official ACP spec uses `session/`-prefixed methods (`session/new`, `session/prompt`, `session/update`), NOT `threads/`-prefixed methods. The `threads/` naming in CONTEXT.md appears to be an older or agent-specific variant.

| CONTEXT.md method | Official ACP equivalent | Notes |
|-------------------|------------------------|-------|
| `threads/create` | `session/new` | Returns `sessionId` in result |
| `threads/message` | `session/prompt` | User sends content blocks |
| `threads/update` | `session/update` (notification) | Agent streams chunks |
| `threads/tool_call` | `session/update` with `sessionUpdate: "tool_call"` | Part of update stream |
| `threads/tool_result` | Response to `session/request_permission` | JSON-RPC response object |

**Research verdict:** The CONTEXT.md `threads/` method names are LOCKED by the decision section and must be used as-is. The proxy routes on whatever `method` field appears in each line. If real agents use `session/` methods, the proxy will simply pass those through without ingesting (which is the correct fallback behavior). The planner should implement the routing table exactly as specified in CONTEXT.md, with the understanding that real-world ACP traffic may use `session/` prefixes.

**Recommendation for the planner:** The routing table is correct as locked. To capture `session/`-prefixed traffic in a future version, the developer would add `session/prompt`, `session/update`, and `session/new` to the routing table alongside the `threads/` methods. For v1, implement exactly what CONTEXT.md specifies.

### Confirmed ACP Message Shapes (official spec, HIGH confidence)

**`session/new` (≈ `threads/create`) — client→agent:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "session/new",
  "params": {
    "cwd": "/path/to/project",
    "mcpServers": []
  }
}
```
Response: `{"result": {"sessionId": "sess_abc123"}}`

**`session/prompt` (≈ `threads/message`) — client→agent:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/prompt",
  "params": {
    "sessionId": "sess_abc123",
    "content": [{"type": "text", "text": "User message here"}]
  }
}
```

**`session/update` (≈ `threads/update`) — agent→client notification:**
```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "sess_abc123",
    "update": {
      "sessionUpdate": "agent_message_chunk",
      "content": {"type": "text", "text": "The capital of France is Paris."}
    }
  }
}
```

Streaming completion: agent responds to the original `session/prompt` request (matching `id`) with `{"result": {"stopReason": "end_turn"}}`. There is no explicit `done` field in the notification stream.

**`session/update` with tool call:**
```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "sess_abc123",
    "update": {
      "sessionUpdate": "tool_call",
      "toolCallId": "call_001",
      "title": "Reading file",
      "kind": "read",
      "status": "pending"
    }
  }
}
```

### Inferred `threads/` Method Shapes (LOW confidence — no spec found)

No authoritative spec for `threads/`-prefixed methods was found. The CONTEXT.md field access patterns are best-effort inferences. Based on JSON-RPC 2.0 conventions and the `session/` shapes above, the most likely structures are:

**`threads/message` params (inferred):**
```json
{
  "session_id": "...",
  "message": {"role": "user", "content": "user text here"}
}
```
Access: `params["message"]["content"]` — use `str(params.get("message", params))` as fallback.

**`threads/update` params (inferred):**
```json
{
  "session_id": "...",
  "message": {"role": "assistant", "content": "agent response text"},
  "done": true
}
```
Access: `params.get("message", {}).get("content", str(params))`. The `done` flag is the CONTEXT.md-specified completion indicator.

**`threads/tool_call` params (inferred):**
```json
{
  "session_id": "...",
  "tool_name": "read_file",
  "args": {"path": "/foo/bar"},
  "id": "call_001"
}
```
Note: JSON-RPC 2.0 `id` is on the top-level message object, not in `params`. The proxy should extract `id` from `msg["id"]` not `params["id"]`. CONTEXT.md buffers by `id` — treat this as the top-level JSON-RPC `id` field.

**`threads/create` params (inferred):**
```json
{
  "session_id": "generated-uuid-or-similar"
}
```

**Implementation guidance for defensive access:**
```python
def _extract_content(params: dict, fallback: str = "") -> str:
    """Defensive content extraction with multiple fallback paths."""
    msg = params.get("message", params)
    if isinstance(msg, dict):
        return msg.get("content") or msg.get("text") or str(msg)
    return str(msg) if msg else fallback
```

---

## Python Package Structure

### Build Backend: hatchling (HIGH confidence)

The main `pyproject.toml` uses `hatchling`. The `packages/am-proxy/` package MUST also use hatchling for consistency.

**Verified `pyproject.toml` pattern for am-proxy:**
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "am-proxy"
version = "0.1.0"
description = "Transparent ACP stdio proxy with passive conversation ingestion"
requires-python = ">=3.10"
dependencies = [
    "httpx>=0.27.0",
    "tomli>=2.0.0 ; python_version < '3.11'",
]

[project.scripts]
am-proxy = "am_proxy.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/am_proxy"]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-mock>=3.10.0",
    "ruff>=0.1.0",
    "black>=23.0.0",
    "mypy>=1.0.0",
]
```

### tomllib/tomli Import Pattern (HIGH confidence)

Python 3.11+ has `tomllib` in stdlib. The current environment runs Python 3.13 (confirmed), but the package targets Python 3.10+.

```python
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
```

pyproject.toml conditional dep: `"tomli>=2.0.0 ; python_version < '3.11'"`

### Tests Directory

The standalone package should have its own `tests/` subdirectory at `packages/am-proxy/tests/`. Tests in the main repo's `tests/` directory cannot import from `am_proxy` without installing the package. The planner should create `packages/am-proxy/tests/` with its own `conftest.py`.

**Alternatively:** A separate `pytest.ini` or `pyproject.toml` section in `packages/am-proxy/pyproject.toml` pointing `testpaths = ["tests"]`.

---

## asyncio Subprocess + stdin Bridging on Windows

### Event Loop Policy (HIGH confidence)

Confirmed: the current dev environment is `win32` and already uses `WindowsProactorEventLoopPolicy` by default on Python 3.13. However, the code must set it explicitly for compatibility with Python 3.10/3.11 where it may not be the default:

```python
# cli.py — at top of main(), before asyncio.run()
import sys
import asyncio

def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_async_main())
```

**Why required:** `SelectorEventLoop` (the other option) has no subprocess support on Windows. `ProactorEventLoop` is required for `asyncio.create_subprocess_exec()` to work on Windows.

### Subprocess Stdin/Stdout Pipes (HIGH confidence)

Source: official Python docs (`asyncio-subprocess.html`)

```python
import asyncio

proc = await asyncio.create_subprocess_exec(
    binary, *args,
    stdin=asyncio.subprocess.PIPE,   # -> Process.stdin: StreamWriter
    stdout=asyncio.subprocess.PIPE,  # -> Process.stdout: StreamReader
    stderr=asyncio.subprocess.PIPE,  # -> Process.stderr: StreamReader
)
# proc.stdin  — StreamWriter (write to child's stdin)
# proc.stdout — StreamReader (read from child's stdout)
# proc.stderr — StreamReader (read from child's stderr)
```

**Reading lines from subprocess stdout:**
```python
async def child_to_stdout() -> None:
    assert proc.stdout is not None
    async for line in proc.stdout:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
        _maybe_ingest(line, direction="child_out")
```

**Note:** Use `proc.stdout` as an async iterable — it yields bytes including the newline. Do NOT use `communicate()` for a proxy since that reads everything until EOF, blocking the pass-through loop.

### Wrapping sys.stdin as asyncio StreamReader (MEDIUM confidence)

The `loop.connect_read_pipe()` API is the correct approach for wrapping `sys.stdin`:

```python
async def _wrap_stdin() -> asyncio.StreamReader:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
    return reader
```

**Windows note:** `connect_read_pipe` on Windows requires `ProactorEventLoop` (same as subprocesses). With the policy set at entry, this works. `sys.stdin.buffer` (bytes) must be passed, not `sys.stdin` (text).

**Alternative simpler pattern** using `asyncio.get_event_loop().run_in_executor` for stdin reads:
```python
async def stdin_to_child() -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
        if not line:
            break
        proc.stdin.write(line)
        await proc.stdin.drain()
        _maybe_ingest(line, direction="stdin_in")
```

**Recommendation:** Use `run_in_executor` for stdin reads. It is simpler, avoids the `connect_read_pipe` protocol wiring, and works reliably on Windows. The executor thread blocks on `readline()` while the asyncio loop runs other tasks. This is the correct approach when stdin is the proxy's own stdin (not a subprocess pipe).

### Complete Bidirectional Loop Pattern

```python
async def run(self) -> int:
    proc = await asyncio.create_subprocess_exec(
        self._binary, *self._args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def stdin_to_child() -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
            if not line:
                break
            assert proc.stdin is not None
            proc.stdin.write(line)
            await proc.stdin.drain()
            self._handle_line(line, direction="in")
        proc.stdin.close()

    async def child_to_stdout() -> None:
        assert proc.stdout is not None
        async for line in proc.stdout:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            self._handle_line(line, direction="out")

    async def child_stderr_passthrough() -> None:
        assert proc.stderr is not None
        async for chunk in proc.stderr:
            sys.stderr.buffer.write(chunk)
            sys.stderr.buffer.flush()

    await asyncio.gather(
        stdin_to_child(),
        child_to_stdout(),
        child_stderr_passthrough(),
    )
    return await proc.wait()
```

---

## Fire-and-Forget httpx Pattern

### Task Garbage Collection Problem (HIGH confidence)

**Critical:** In Python 3.12+, `asyncio.create_task()` holds only a weak reference to the task. If no strong reference is kept, the task may be garbage-collected before it completes. This was confirmed as a CPython issue (issue #117379) and affects Python 3.12+.

The dev environment is Python 3.13, so this is active.

**Correct pattern — retain strong references:**
```python
class IngestClient:
    def __init__(self, config: ProxyConfig) -> None:
        self._config = config
        self._pending: set[asyncio.Task[None]] = set()  # Strong references

    def fire_and_forget(self, turn: dict) -> None:
        """Schedule a POST without awaiting. Safe on Python 3.12+."""
        task = asyncio.create_task(self._post(turn))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _post(self, turn: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                await client.post(
                    f"{self._config.endpoint}/ingest/conversation",
                    json=turn,
                    headers={"Authorization": f"Bearer {self._config.api_key}"},
                )
        except Exception:
            pass  # Silent failure — never surfaces to caller
```

**Why per-call `AsyncClient`:** The CONTEXT.md decision to use per-call `async with httpx.AsyncClient(...)` is correct for fire-and-forget. A persistent client with keepalive would complicate lifecycle management (cleanup on exit). Per-call has marginal overhead but is safe and simple.

### httpx Timeout Configuration (HIGH confidence)

`httpx.AsyncClient(timeout=5.0)` sets a 5-second total timeout. This is the CONTEXT.md default. The `timeout` parameter accepts `float` (seconds) or `httpx.Timeout` object.

---

## Test Infrastructure

### pytest-asyncio Availability (HIGH confidence)

`pytest-asyncio>=0.21.0` is in the main `pyproject.toml` dev dependencies. The package is installed in the dev environment.

**Current mode:** No `asyncio_mode` is configured in `pyproject.toml` `[tool.pytest.ini_options]`. pytest-asyncio 0.21+ defaults to **strict** mode, requiring `@pytest.mark.asyncio` on every async test function.

**Existing async test pattern** (from `tests/test_web_pipeline.py`):
```python
@pytest.mark.asyncio
async def test_crawl_url_success(self):
    mock_crawler_instance = AsyncMock()
    mock_crawler_instance.__aenter__ = AsyncMock(return_value=mock_crawler_instance)
    mock_crawler_instance.__aexit__ = AsyncMock(return_value=False)
    with patch("codememory.web.crawler.AsyncWebCrawler", return_value=mock_crawler_instance):
        result = await crawl_url("https://example.com")
    assert result == "..."
```

**Test pattern for am-proxy** — mock `IngestClient.post_turn` / `IngestClient.fire_and_forget`:
```python
@pytest.mark.asyncio
async def test_threads_message_routes_to_ingest():
    from unittest.mock import AsyncMock, patch
    with patch.object(IngestClient, "_post", new_callable=AsyncMock) as mock_post:
        proxy = ACPProxy(binary="echo", args=[], config=make_test_config())
        await proxy._handle_line(
            b'{"jsonrpc":"2.0","method":"threads/message","params":{"message":{"content":"hello"}}}\n',
            direction="in"
        )
        mock_post.assert_awaited_once()
```

**am-proxy tests location:** `packages/am-proxy/tests/` with its own `conftest.py`. The main repo's `tests/` is for `codememory` and `am_server`. The am-proxy package is standalone and must be tested in isolation.

**Recommendation for the am-proxy `pyproject.toml`:** Add `asyncio_mode = "auto"` to `[tool.pytest.ini_options]` within the am-proxy package's own `pyproject.toml`. This avoids the need to decorate every async test:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## Setup Command Implementation

### `shutil.which()` Behavior (HIGH confidence)

Confirmed via direct Python execution on this machine:
- `shutil.which("python")` returns `"C:\\Python313\\python.EXE"` (full path)
- `shutil.which("nonexistent_binary_xyz")` returns `None`

**Pattern for binary detection:**
```python
import shutil

KNOWN_AGENTS: dict[str, str] = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "opencode": "opencode",
    "kiro": "kiro",
}

def detect_installed_agents() -> list[str]:
    """Return list of agent names whose binaries are on PATH."""
    return [name for name, binary in KNOWN_AGENTS.items() if shutil.which(binary) is not None]
```

**`am-proxy setup` output pattern:**
```python
def cmd_setup() -> None:
    detected = detect_installed_agents()
    if not detected:
        print("No supported agents found on PATH.")
        print("Supported agents: claude, codex, gemini, opencode, kiro")
        return
    for agent in detected:
        print(f"\n{agent.title()} detected.")
        print(f"Add to your editor's {agent} configuration:")
        print(f"  command: am-proxy --agent {agent} --project <your-project>")
```

---

## Implementation Order

Recommended task breakdown for the planner:

### Wave 1: Package scaffold + config
1. Create `packages/am-proxy/` directory tree (pyproject.toml, src/am_proxy/__init__.py)
2. Implement `config.py` — TOML loading, `ProxyConfig` dataclass, defaults
3. Implement `agents.py` — binary name mapping, `detect_installed_agents()`
4. Write tests: config loading with missing file, agent detection mock

### Wave 2: Ingest client
5. Implement `ingest.py` — `IngestClient` with `fire_and_forget()` and `_post()`
6. Write tests: `_post()` called with correct payload, exception swallowed, task retained

### Wave 3: Core proxy logic
7. Implement `proxy.py` — `ACPProxy` class with `_handle_line()`, `_build_turn()`, `_buffer_tool_call()`, `_evict_buffer()`, `_next_turn_index()`
8. Write tests: routing table (message→ingest, ping→skip, tool buffering, TTL eviction)

### Wave 4: Subprocess loop
9. Implement `proxy.py run()` — bidirectional asyncio loop, stdin reader via executor, subprocess pipes
10. Write tests: subprocess exits → proxy exits with same code; child stdout passes through

### Wave 5: CLI entry point
11. Implement `cli.py` — argparse, Windows policy, agent lookup, `main()` entry
12. Implement `cmd_setup()` — binary detection, print instructions
13. Write tests: Windows event loop policy set on win32, setup prints instructions for detected agents

---

## Open Questions

### 1. Actual `threads/` Method Names in Production Agents

**What we know:** Official ACP spec uses `session/`-prefixed methods. The `threads/` names in CONTEXT.md are either (a) from an older ACP spec version, (b) agent-specific extensions, or (c) a custom naming convention the user has observed.

**What's unclear:** Which actual method names `claude`, `codex`, `kiro`, etc. emit on the wire. No spec doc was found that defines `threads/message`.

**Recommendation:** Implement the routing table exactly as specified in CONTEXT.md (threads/ prefixed). The proxy's pass-through behavior means unmatched methods are safely forwarded. When the user first runs am-proxy against a real agent, they can add a debug mode (`--debug`) that logs method names to stderr to discover what the agent actually sends.

### 2. `threads/tool_call` id Field Location

**What we know:** JSON-RPC 2.0 spec puts `id` at the top level of a request object (not inside `params`). CONTEXT.md says "Buffer request by `id`".

**What's unclear:** Does `threads/tool_call` use JSON-RPC request `id` for correlation with `threads/tool_result`, or does it use a separate `id` field inside `params`?

**Recommendation:** Buffer on `msg.get("id") or params.get("id")` — check both locations. This covers both conventions silently.

### 3. `threads/update` `done` Field

**What we know:** CONTEXT.md says "only when `params.done == true` or no `done` field". Official ACP uses a `stopReason` in the JSON-RPC result response, not a `done` flag in notification params.

**What's unclear:** Whether real agents using `threads/update` include a `done` field in params, or use a separate mechanism.

**Recommendation:** Implement exactly as CONTEXT.md specifies: `if not params.get("done", True):` skip ingest. This means "ingest unless explicitly told done=false". For agents that don't use this pattern, all `threads/update` messages will be ingested (slightly noisy but not harmful).

### 4. Session ID in `threads/message`

**What we know:** CONTEXT.md says "extract `session_id` from `threads/message` params if `session_id` field present". This is a fallback path.

**What's unclear:** Whether the `session_id` field in `threads/message` params is at `params["session_id"]` or nested inside `params["message"]["session_id"]`.

**Recommendation:** Try `params.get("session_id")` first, then fall back to the proxy-level UUID.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 (confirmed on this machine) | Async HTTP POST to am-server | Already in main package deps; async-native |
| tomllib (stdlib) | 3.11+ builtin | TOML config parsing | Zero deps on Python 3.11+ |
| tomli | 2.0+ | tomllib backport for Python 3.10 | Official backport, tiny |
| asyncio | stdlib | Subprocess management, event loop | Zero deps |
| hatchling | — | Build backend | Matches main package convention |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-asyncio | 0.21.0+ | Async test support | Required for testing coroutines |
| pytest-mock | 3.10.0+ | Mock fixtures | `mocker` fixture for patching |

---

## Project Constraints (from CLAUDE.md)

No `CLAUDE.md` was found in the repository root. Conventions are documented in `.planning/codebase/CONVENTIONS.md`:

- **Formatter:** Black, line length 100
- **Linter:** Ruff with E, F, I, N, W, UP, B, C4, SIM rules
- **Type checking:** MyPy strict (`disallow_untyped_defs = true`, etc.)
- **Docstrings:** Google-style
- **Naming:** snake_case functions/variables, PascalCase classes, UPPER_CASE constants
- **Private methods:** underscore prefix (`_handle_line`, `_build_turn`)
- **Error handling:** Never bare `except:` — use `except Exception:` for the silent-failure contract
- **Logging:** `logger = logging.getLogger(__name__)`, but am-proxy must NOT log to stderr in normal operation (would pollute the agent's stderr stream). All internal logging should be suppressed or written to a log file, never stderr.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | Package runtime | ✓ | 3.13.12 | — |
| httpx | IngestClient | ✓ | 0.28.1 | — |
| asyncio | Subprocess proxy | ✓ | stdlib | — |
| tomllib | Config parsing | ✓ | stdlib (3.11+) | tomli |
| pytest-asyncio | Tests | ✓ | in dev deps | — |
| hatchling | Build | ✓ | in main pyproject | — |
| WindowsProactorEventLoopPolicy | Windows subprocess | ✓ | stdlib win32 | — (not needed on Linux/Mac) |

**Missing dependencies with no fallback:** None.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest with pytest-asyncio 0.21+ |
| Config file | `packages/am-proxy/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd packages/am-proxy && pytest tests/ -x -q` |
| Full suite command | `cd packages/am-proxy && pytest tests/ -v` |

### Phase Requirements → Test Map
| Behavior | Test Type | Automated Command | File |
|----------|-----------|-------------------|------|
| `threads/message` → `post_turn()` with correct dict | unit | `pytest tests/test_proxy.py::test_message_routing -x` | Wave 1 |
| `$/ping` → `post_turn()` NOT called | unit | `pytest tests/test_proxy.py::test_ping_skipped -x` | Wave 1 |
| `threads/tool_call` buffers; `threads/tool_result` triggers POST of both | unit | `pytest tests/test_proxy.py::test_tool_buffering -x` | Wave 1 |
| Buffer TTL eviction — no memory leak | unit | `pytest tests/test_proxy.py::test_ttl_eviction -x` | Wave 1 |
| `post_turn()` raises → no exception propagates | unit | `pytest tests/test_ingest.py::test_silent_failure -x` | Wave 1 |
| Windows event loop policy set on win32 | unit | `pytest tests/test_cli.py::test_windows_policy -x` | Wave 2 |
| Task retained in `_pending` set (GC safety) | unit | `pytest tests/test_ingest.py::test_task_retained -x` | Wave 1 |
| `threads/update` only ingested when `done=true` | unit | `pytest tests/test_proxy.py::test_update_filtering -x` | Wave 1 |

### Wave 0 Gaps
- [ ] `packages/am-proxy/tests/__init__.py`
- [ ] `packages/am-proxy/tests/conftest.py` — shared `ProxyConfig` fixture
- [ ] `packages/am-proxy/tests/test_proxy.py` — ACPProxy routing tests
- [ ] `packages/am-proxy/tests/test_ingest.py` — IngestClient fire-and-forget tests
- [ ] `packages/am-proxy/tests/test_cli.py` — CLI entry / setup command tests

---

## Sources

### Primary (HIGH confidence)
- Python docs `asyncio-subprocess.html` — subprocess PIPE, StreamReader, ProactorEventLoop requirement on Windows
- Python docs `asyncio-eventloop.html#connect_read_pipe` — `connect_read_pipe` API + `StreamReaderProtocol` pattern
- Python docs `asyncio-task.html` — `create_task` weak reference GC issue (3.12+)
- CPython issue #117379 — confirms task GC in 3.12+
- `D:/code/agentic-memory/pyproject.toml` — build backend (hatchling), pytest-asyncio version
- Direct `python3 -c` execution — confirmed win32, WindowsProactorEventLoopPolicy default, shutil.which behavior, Python 3.13.12

### Secondary (MEDIUM confidence)
- `agentclientprotocol.com` official docs — `session/new`, `session/prompt`, `session/update` message shapes
- `agentclientprotocol.com/protocol/session-setup` — `session/new` returns `{"result": {"sessionId": "..."}}`
- `agentclientprotocol.com/protocol/tool-calls.md` — tool call via `sessionUpdate: "tool_call"`, `toolCallId` field
- ACP schema.json (raw GitHub) — all method names confirmed, `session/` prefix confirmed
- Kiro ACP docs — `session/update` notification structure, `sessionUpdate` discriminator field

### Tertiary (LOW confidence)
- CONTEXT.md `threads/` method names — no spec found; treated as locked decisions per upstream author
- `threads/message` `params.message.content` field path — inferred from `session/prompt` content block pattern

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (ACP spec stable; Python asyncio patterns stable)
