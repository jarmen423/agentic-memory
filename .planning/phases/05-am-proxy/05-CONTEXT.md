# Phase 5: am-proxy (ACP Proxy) — Context

**Gathered:** 2026-03-24
**Status:** Ready for research and planning
**Note:** Context gathered autonomously based on ROADMAP.md Phase 5 spec, prior phase outputs, and codebase scouting.

<domain>
## Phase Boundary

Build `packages/am-proxy/` — a standalone Python package (installable via `pipx install am-proxy`) that transparently proxies stdio between an editor/IDE and any ACP-compliant agent CLI. The proxy silently tees conversation turns to `POST /ingest/conversation` (built in Phase 4) as fire-and-forget HTTP calls. The agent session must have zero measurable latency impact. All failure paths are swallowed silently.

This phase creates the passive capture path for CLI-based agents (Claude Code, Codex, etc.). The browser extension path is Phase 6.

</domain>

<decisions>
## Implementation Decisions

### Package Structure

```
packages/am-proxy/
├── pyproject.toml           ← standalone package, name = "am-proxy"
├── README.md
└── src/
    └── am_proxy/
        ├── __init__.py
        ├── cli.py            ← entry point: am-proxy --agent claude --project <id>
        ├── proxy.py          ← ACPProxy class: async stdio pass-through + ingest
        ├── config.py         ← TOML config loader, defaults
        ├── ingest.py         ← fire-and-forget HTTP ingest client (httpx)
        └── agents.py         ← agent binary name → source_agent mapping
```

**pyproject.toml entry point:**
```toml
[project.scripts]
am-proxy = "am_proxy.cli:main"
```

**Dependencies (minimal):**
- `httpx` — async HTTP for fire-and-forget POSTs to am-server
- `tomllib` (Python 3.11+ stdlib) or `tomli` (Python 3.10 backport) — config parsing
- No other external deps; asyncio, subprocess, json all stdlib

**Python version requirement:** 3.10+ (matches main package). Use `try/import tomllib except ImportError: import tomli as tomllib` for 3.10 compatibility.

---

### TOML Config Location and Schema

Config file: `~/.config/am-proxy/config.toml`

```toml
[am_proxy]
endpoint = "http://localhost:8000"      # am-server base URL
api_key = "your-api-key"               # Bearer token
default_project_id = "default"         # fallback if --project not given
timeout_seconds = 5                    # ingest POST timeout (fire-and-forget)
buffer_ttl_seconds = 300               # tool_call buffer eviction TTL

[agents.claude]
binary = "claude"                      # executable name on PATH

[agents.codex]
binary = "codex"

[agents.gemini]
binary = "gemini"

[agents.opencode]
binary = "opencode"

[agents.kiro]
binary = "kiro"
```

Config loading: `~/.config/am-proxy/config.toml` → merged with hardcoded defaults. Missing file is not an error; all values have defaults. `--project` CLI flag overrides `default_project_id`.

---

### CLI Interface

```
am-proxy --agent <name> [--project <project_id>] [--endpoint <url>] [--api-key <key>]
am-proxy setup
```

**`am-proxy --agent claude --project my-project`:**
1. Load config
2. Look up binary for `claude` agent (from config or default `"claude"`)
3. Spawn subprocess with that binary, passing all remaining args through
4. Run `ACPProxy.run()` — async loop reading stdin→child, child→stdout, tee-ing to ingest
5. Exit when subprocess exits

**`am-proxy setup`:**
- Detect installed agents by checking which binaries are on PATH
- For each detected agent: print the editor config snippet to configure am-proxy as the wrapper
- Example output for Claude Code:
  ```
  Claude Code detected.
  Add to your editor's claude configuration:
    command: am-proxy --agent claude --project <your-project>
  ```
- No config file mutation — just prints instructions

**Windows compatibility:** At `cli.py` entry, set `asyncio.WindowsProactorEventLoopPolicy()` on `sys.platform == "win32"` before `asyncio.run()`. This is required for subprocess streams on Windows.

---

### ACPProxy Class — Core Logic

```python
class ACPProxy:
    def __init__(self, binary: str, args: list[str], config: ProxyConfig):
        self._binary = binary
        self._args = args
        self._config = config
        self._buffer: dict[str, tuple[dict, asyncio.TimerHandle]] = {}  # id → (request, cancel_handle)
        self._session_turn_counts: dict[str, int] = {}  # session_id → next turn_index
        self._ingest_client: IngestClient = IngestClient(config)

    async def run(self) -> int:
        """Spawn subprocess and run bidirectional stdio proxy. Returns exit code."""
        ...
```

**Bidirectional pipe loop:**
- Read lines from `sys.stdin` → write to child `stdin` → also parse as JSON-RPC → filter + ingest
- Read lines from child `stdout` → write to `sys.stdout` → also parse as JSON-RPC → filter + ingest
- `sys.stderr` pass-through directly (no parsing needed)
- Each read/write path is an independent `asyncio.Task` — they run concurrently
- Main loop: `await asyncio.gather(stdin_to_child(), child_to_stdout(), child_stderr_to_stderr())`

---

### ACP Message Routing

ACP messages are newline-delimited JSON-RPC 2.0. The proxy parses each line as JSON (silently ignore non-JSON). Route based on `method` field:

| Method | Direction | Action |
|--------|-----------|--------|
| `threads/create` | stdin→child | Extract `session_id` from params; initialize `_session_turn_counts[session_id] = 0`; skip ingest |
| `threads/message` | stdin→child | POST as user turn |
| `threads/update` | child→stdout | POST as assistant turn (only when `params.done == true` or no `done` field) |
| `threads/tool_call` | child→stdout | Buffer request by `id`; schedule TTL eviction |
| `threads/tool_result` | stdin→child | Match buffer by `id`; POST tool pair (call + result); clear buffer entry |
| `$/progress`, `$/ping`, `$/pong`, notifications | any | Pass through; never ingest |
| All other `$`-prefixed methods | any | Pass through; never ingest |
| Unrecognized methods | any | Pass through; never ingest |

**No `method` field (JSON-RPC response objects):** Pass through silently. Tool results come as requests (with `method`), not bare responses.

---

### Turn Construction from ACP Messages

**`threads/message` (user turn):**
```python
{
    "role": "user",
    "content": params["message"]["content"],   # or str(params["message"])
    "session_id": session_id,
    "project_id": project_id,
    "turn_index": self._next_turn_index(session_id),
    "source_agent": source_agent,     # e.g. "claude_code"
    "ingestion_mode": "passive",
    "source_key": "chat_proxy",
}
```

**`threads/update` (assistant turn, done=true):**
```python
{
    "role": "assistant",
    "content": params.get("message", {}).get("content", str(params)),
    "session_id": session_id,
    "project_id": project_id,
    "turn_index": self._next_turn_index(session_id),
    "source_agent": source_agent,
    "ingestion_mode": "passive",
    "source_key": "chat_proxy",
}
```

**`threads/tool_call` + `threads/tool_result` (tool pair):**
- Buffer tool_call on receipt (don't POST yet)
- On matching tool_result: POST both as two turns in sequence:
  1. `{role: "tool", content: f"{tool_name}({json.dumps(args, default=str)})", tool_name: ..., tool_call_id: id, ...}`
  2. `{role: "tool", content: str(result), tool_name: ..., tool_call_id: id, ...}`

**`_next_turn_index(session_id)`:** Returns `self._session_turn_counts.get(session_id, 0)` then increments.

**Session ID extraction:** From `threads/create` params; or from `threads/message` params if `session_id` field present; or generate `str(uuid4())` once per proxy invocation as fallback (not ideal but silent failure > crash).

---

### Fire-and-Forget Ingest

```python
class IngestClient:
    async def post_turn(self, turn: dict) -> None:
        """POST turn to /ingest/conversation. Never raises. Swallows all errors."""
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                await client.post(
                    f"{self._config.endpoint}/ingest/conversation",
                    json=turn,
                    headers={"Authorization": f"Bearer {self._config.api_key}"},
                )
        except Exception:
            pass   # Silent failure — proxy NEVER surfaces errors to caller
```

**Fire-and-forget pattern:** `asyncio.create_task(self._ingest_client.post_turn(turn))` — do not await. The task runs independently; if it fails, the exception is suppressed. This ensures ingest never adds latency to the main proxy loop.

**Timeout:** 5 seconds (configurable). The timeout ensures a downed am-server is detected quickly and the connection is closed, preventing resource leak.

---

### Buffer TTL for Tool Call Requests

Tool calls may never receive a matching tool_result (e.g., cancelled session, error). The buffer entry must be evicted after TTL to prevent unbounded growth.

```python
def _buffer_tool_call(self, request_id: str, request: dict) -> None:
    # Cancel existing handle if re-buffering same id
    if request_id in self._buffer:
        self._buffer[request_id][1].cancel()
    handle = asyncio.get_event_loop().call_later(
        self._config.buffer_ttl_seconds,
        self._evict_buffer,
        request_id,
    )
    self._buffer[request_id] = (request, handle)

def _evict_buffer(self, request_id: str) -> None:
    self._buffer.pop(request_id, None)
```

---

### Silent Failure Contract

**am-proxy MUST NEVER:**
- Print anything to stdout except what the agent subprocess printed
- Print anything to stderr that reveals internal proxy state
- Crash the agent session due to ingest failure
- Slow down stdin→stdout throughput for ingest calls

**am-proxy MUST:**
- Exit with the same exit code as the agent subprocess
- Pass all stdin/stdout bytes through unmodified
- Swallow all exceptions in ingest paths with bare `except Exception: pass`

---

### Testing Strategy

Since am-proxy has no Neo4j dependency, tests mock only `IngestClient.post_turn()`.

Key test cases:
- `ACPProxy` routes `threads/message` → `post_turn()` called with correct turn dict
- `ACPProxy` does NOT call `post_turn()` for `$/ping`, `$/progress`
- Tool call buffering: `threads/tool_call` buffers; `threads/tool_result` triggers POST of both
- Buffer TTL eviction: buffered entry evicted after TTL with no memory leak
- Ingest failure: `post_turn()` raises → no exception propagates to caller
- Windows event loop policy set on `win32`

---

### Claude's Discretion

- Exact asyncio subprocess stream setup (ProactorEventLoop details, pipe buffering)
- Error handling edge cases in JSON parsing (malformed lines)
- httpx async client reuse strategy (per-call vs persistent session)
- `am-proxy setup` binary detection implementation (shutil.which)
- Exact ACP param structure for content extraction (research may clarify field names)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 4 outputs (this phase posts to these)
- `src/am_server/routes/conversation.py` — `POST /ingest/conversation` endpoint spec
- `src/am_server/models.py` — `ConversationIngestRequest` — exact schema am-proxy must match
- `.planning/phases/04-conversation-memory-core/04-CONTEXT.md` — turn schema decisions

### Planning docs
- `.planning/ROADMAP.md` — Phase 5 spec (lines ~159-188)
- `.planning/codebase/CONVENTIONS.md` — Python conventions (Black, Ruff, MyPy strict)

### New package location
- `packages/am-proxy/` — create this directory tree from scratch

</canonical_refs>

<code_context>
## Existing Code Insights

### Target Endpoint (Phase 4 output)
`POST /ingest/conversation` accepts `ConversationIngestRequest`:
```python
role: str              # "user" | "assistant" | "system" | "tool"
content: str
session_id: str        # REQUIRED — caller-owned
project_id: str
turn_index: int
source_agent: str | None
model: str | None
tool_name: str | None
tool_call_id: str | None
tokens_input: int | None
tokens_output: int | None
timestamp: str | None
ingestion_mode: str = "active"    # am-proxy must send "passive"
source_key: str = "chat_mcp"      # am-proxy must send "chat_proxy"
```

### No Existing Package Template
`packages/` directory does not exist. Must be created from scratch. Follow standard Python src-layout with `pyproject.toml`.

### Key Risk: Windows Asyncio
The main package runs on Windows (user's platform: win32). Subprocess streams on Windows require `asyncio.WindowsProactorEventLoopPolicy`. Must set at `cli.py` entry before `asyncio.run()`.

### Existing Pattern: Silent Failure
The `CircuitBreaker` in `src/codememory/core/base.py` shows the existing error-swallowing pattern. The am-proxy's `IngestClient` takes this further — all exceptions silently discarded.

</code_context>

<specifics>
## Specific Implementation Notes

- **`am-proxy` is a separate installable package** — its own `pyproject.toml`, not added to the main `agentic-memory` package. Users install it with `pipx install am-proxy` or `pip install am-proxy`. It has no import dependency on `codememory`.
- **ACP is JSON-RPC 2.0 over newline-delimited stdio** — each message is one line. Lines that are not valid JSON are silently ignored (pass through unchanged).
- **turn_index is proxy-managed** — the proxy tracks `{session_id: next_index}` in memory. This means a proxy restart resets the counter. Since dedup is `MERGE on (session_id, turn_index)`, a restarted proxy will overwrite early turns from a prior run if the session_id is reused. This is acceptable for v1.
- **`threads/update` streaming:** ACP agents may emit many `threads/update` messages as they stream token-by-token. Only the final message (where `done=true` or where the message is definitively complete) should be ingested. All intermediate updates are passed through but not POSTed.
- **`httpx.AsyncClient` per-call vs persistent:** Use per-call `async with httpx.AsyncClient(...)` for simplicity. Persistent client with keepalive is an optimization for later.
- **`tomllib` vs `tomli`:** Python 3.11+ has `tomllib` in stdlib. For 3.10: `try: import tomllib except ImportError: import tomli as tomllib`. Add `tomli ; python_version < "3.11"` as a conditional dep in pyproject.toml.

</specifics>

<deferred>
## Deferred Ideas

- **Persistent httpx client with connection pooling** — per-call client is fine for v1 fire-and-forget
- **Metrics/telemetry on proxy throughput** — out of scope for v1
- **Multi-agent simultaneous sessions** — v1 tracks one session at a time per proxy invocation
- **ACP spec version negotiation** — hardcode current method names; update when spec changes
- **`am-proxy` PyPI distribution** — packaging/publishing out of scope for this implementation phase
- **Retry logic for ingest failures** — v1 fire-and-forget with no retry; retry logic is future hardening
- **Config file interactive creation** — `am-proxy init` command to create config — future UX improvement

</deferred>

---

*Phase: 05-am-proxy*
*Context gathered: 2026-03-24*
