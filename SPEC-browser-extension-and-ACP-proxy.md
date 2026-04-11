---

# SPEC: ACP Proxy (`am-proxy`)

## Overview

A standalone binary that wraps any ACP-compliant agent CLI. Sits transparently between an editor or terminal and the agent process via stdio pass-through. Tees the JSON-RPC stream to the memory server REST API asynchronously. The agent and editor are completely unaware of its presence. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/collection_33a3b366-1b2c-43cf-9623-fc7cc27b838d/cedbbfa6-f872-4249-8be9-d3fbb45c3d39/take-a-look-at-my-jarmen423-ag-_0IAxC5GQla4lI4LTLkgUw.md)

## Transport Layer

ACP is JSON-RPC 2.0 over stdio. Every message is a newline-delimited JSON object. The proxy reads from stdin, writes to the agent's stdin; reads from the agent's stdout, writes to stdout. Two concurrent async loops — one per direction. The critical invariant: **pass through first, ingest after**. The proxy never buffers, never delays, never modifies the stream.

```
[Editor/Terminal]
    │  stdin  ▲ stdout
    ▼         │
 [am-proxy]  ──── async fire-and-forget ────▶ [Memory Server REST API]
    │  stdin  ▲ stdout
    ▼         │
 [agent CLI: claude/codex/gemini/etc]
```

## Core Architecture

```python
# packages/am-proxy/src/am_proxy/proxy.py

INGEST_METHODS = {
    "threads/create",
    "threads/message",      # user prompt + agent response
    "threads/tool_call",    # tool invoked
    "threads/tool_result",  # tool result returned
    "threads/update",       # agent state update
}

SKIP_METHODS = {
    "ping", "pong", "$/cancelRequest",
    "window/logMessage",    # IDE housekeeping
    "$/progress",           # progress pings
}

class ACPProxy:
    def __init__(self, agent_cmd: list[str], memory_endpoint: str, 
                 project_id: str, api_key: str):
        self.agent_cmd = agent_cmd
        self.memory_endpoint = memory_endpoint
        self.project_id = project_id
        self.session_id = str(uuid4())
        self.http = httpx.AsyncClient(timeout=5.0)
        self._buffer: dict[str, dict] = {}  # request_id → request, for pairing

    async def run(self):
        agent = await asyncio.create_subprocess_exec(
            *self.agent_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        await asyncio.gather(
            self._pipe(sys.stdin.buffer, agent.stdin, "inbound"),
            self._pipe(agent.stdout, sys.stdout.buffer, "outbound"),
        )

    async def _pipe(self, reader, writer, direction: str):
        async for line in reader:
            # PASS THROUGH FIRST — zero latency impact
            writer.write(line)
            await writer.drain()
            # INGEST ASYNC — never blocks the stream
            asyncio.create_task(self._maybe_ingest(line, direction))

    async def _maybe_ingest(self, raw: bytes, direction: str):
        try:
            msg = json.loads(raw)
            method = msg.get("method", "")
            if method in SKIP_METHODS or method not in INGEST_METHODS:
                return
            # pair request/response by id for full context
            if "id" in msg and "params" in msg:
                self._buffer[str(msg["id"])] = msg
            elif "id" in msg and "result" in msg:
                request = self._buffer.pop(str(msg["id"]), None)
                msg["_request"] = request  # attach original request to response
            await self.http.post(
                f"{self.memory_endpoint}/ingest/conversation",
                json={
                    "message": msg,
                    "direction": direction,
                    "session_id": self.session_id,
                    "project_id": self.project_id,
                    "source_agent": self._detect_agent(),
                    "ingestion_mode": "passive",
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except Exception:
            pass  # NEVER surface to agent or editor
```

## Message Filtering

Only ingest messages with semantic value. Protocol noise is discarded:

| Method | Ingest? | What it contains |
|---|---|---|
| `threads/create` | ✅ | New thread, title, project path |
| `threads/message` | ✅ | Full user prompt + agent response |
| `threads/tool_call` | ✅ | Tool name, arguments (file reads, shell cmds, edits) |
| `threads/tool_result` | ✅ | Tool output — actual file content, command output |
| `threads/update` | ✅ | Agent reasoning/thought steps |
| `ping/pong` | ❌ | Protocol heartbeat |
| `$/progress` | ❌ | Spinner updates |
| `window/logMessage` | ❌ | IDE housekeeping |

## Request/Response Pairing

ACP is async — requests and responses share an `id` but may not arrive consecutively. The proxy maintains a `_buffer` dict keyed on request `id`. When a response arrives, it looks up its matching request and attaches it. This gives the ingestion pipeline full context — what was asked AND what was answered — in one payload.

## Agent Detection

```python
def _detect_agent(self) -> str:
    binary = Path(self.agent_cmd[0]).name
    return {
        "claude": "claude_code",
        "codex": "codex",
        "gemini": "gemini_cli",
        "opencode": "opencode",
        "kiro": "kiro",
    }.get(binary, binary)
```

## Configuration

```toml
# ~/.config/am-proxy/config.toml
[proxy]
memory_endpoint = "http://localhost:8000"
api_key = "am_..."
default_project_id = "default"

[agents.claude]
binary = "/usr/local/bin/claude"
args = ["--acp"]

[agents.codex]
binary = "/usr/local/bin/codex"
# Current OpenAI Codex CLI: use App Server stdio (e.g. `app-server`), not a literal `--acp` flag.
# See docs/AM_PROXY_CODEX.md and packages/am-proxy — `am-proxy --agent codex` defaults to `codex app-server`.
args = ["app-server"]

# For interactive terminal `codex` (TUI), `am-proxy` does not apply — use `am-codex-watch` to tail
# `~/.codex/sessions/**/*.jsonl` into POST /ingest/conversation. See docs/AM_PROXY_CODEX.md and
# docs/CODEX_ROLLOUT_JSONL.md. OpenClaw uses packages/am-openclaw (native hooks), not this proxy.

[agents.gemini]
binary = "/usr/local/bin/gemini"
args = ["--acp"]
```

## CLI Interface

```bash
# Direct invocation — user sets this as their agent binary path in editor
am-proxy --agent claude --project my-saas-project

# Or with explicit binary override
am-proxy --binary /usr/local/bin/claude --args "--acp" --project my-saas-project

# Setup helper — auto-detects installed agents and outputs config snippets
am-proxy setup
# → Detected: claude (/usr/local/bin/claude)
# → Detected: codex (/home/user/.npm/bin/codex)  
# → Zed config: { "agent": { "binary": "am-proxy", "args": ["--agent", "claude"] } }
# → VS Code config: { "agent.binary": "am-proxy --agent claude" }
```

## Failure Modes

| Failure | Behavior |
|---|---|
| Memory server unreachable | Swallow silently. Agent session continues unaffected. |
| Memory server slow (>5s) | httpx timeout fires, task cancelled, session unaffected. |
| JSON parse error on line | Skip that line, continue. |
| Agent process dies | Proxy exits with same exit code. |
| Proxy crashes | Agent process is already running independently — user loses ingestion for that session only. |

## Package Structure

```
packages/am-proxy/
├── src/am_proxy/
│   ├── __main__.py       # entry point, argparse
│   ├── proxy.py          # ACPProxy class
│   ├── config.py         # TOML config loader
│   ├── filter.py         # INGEST_METHODS, SKIP_METHODS, message classifier
│   ├── client.py         # httpx async client wrapper with retry
│   └── setup.py          # am-proxy setup command — auto-detect agents
├── pyproject.toml
└── README.md
```

Distributed as a standalone binary via `pipx install am-proxy` or as a pre-built binary via GitHub releases for users who don't have Python.

***

# SPEC: Browser Extension (`am-ext`)

## Overview

A Chrome/Firefox extension that passively observes AI chat web UIs and ingests conversations into the user's memory server. User grants explicit consent at install — per-platform toggles in onboarding. Runs invisibly from that point forward. Data routes to the user's own memory server endpoint only. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/collection_33a3b366-1b2c-43cf-9623-fc7cc27b838d/cedbbfa6-f872-4249-8be9-d3fbb45c3d39/take-a-look-at-my-jarmen423-ag-_0IAxC5GQla4lI4LTLkgUw.md)

## Supported Platforms

- `chat.openai.com` — ChatGPT
- `claude.ai` — Claude
- `perplexity.ai` — Perplexity
- `gemini.google.com` — Gemini
- (extensible — each platform is a module with a DOM adapter)

## Architecture

```
[Browser Tab: chat.openai.com]
    │
    ▼
[Content Script: chatgpt-adapter.js]
    │  MutationObserver watching message list
    │  Fires on new assistant message (turn complete)
    ▼
[Background Service Worker: background.js]
    │  Receives message event from content script
    │  Checks: is this platform enabled for this user?
    │  Batches if needed (rapid sequential messages)
    ▼
[Memory Server REST API: POST /ingest/conversation]
    │  User's own endpoint (localhost or cloud)
    ▼
[Neo4j Memory Graph]
```

## Manifest V3 Structure

```json
{
  "manifest_version": 3,
  "name": "Agentic Memory",
  "version": "1.0.0",
  "permissions": ["storage", "alarms"],
  "host_permissions": [
    "https://chat.openai.com/*",
    "https://claude.ai/*",
    "https://perplexity.ai/*",
    "https://gemini.google.com/*"
  ],
  "background": { "service_worker": "background.js" },
  "content_scripts": [
    {
      "matches": ["https://chat.openai.com/*"],
      "js": ["adapters/chatgpt.js"],
      "run_at": "document_idle"
    },
    {
      "matches": ["https://claude.ai/*"],
      "js": ["adapters/claude.js"],
      "run_at": "document_idle"
    },
    {
      "matches": ["https://perplexity.ai/*"],
      "js": ["adapters/perplexity.js"],
      "run_at": "document_idle"
    },
    {
      "matches": ["https://gemini.google.com/*"],
      "js": ["adapters/gemini.js"],
      "run_at": "document_idle"
    }
  ],
  "action": { "default_popup": "popup.html" }
}
```

## Platform Adapters

Each platform has its own adapter — a content script that knows the platform's specific DOM structure. All adapters emit the same normalized event shape to the background worker.

```javascript
// adapters/chatgpt.js
const SELECTORS = {
  messageList: '[data-testid="conversation-turn"]',
  userMessage: '[data-message-author-role="user"]',
  assistantMessage: '[data-message-author-role="assistant"]',
  markdownContent: '.markdown',
};

function extractTurn(node) {
  const role = node.querySelector('[data-message-author-role]')
    ?.dataset?.messageAuthorRole;
  const text = node.querySelector(SELECTORS.markdownContent)?.innerText?.trim();
  if (!role || !text) return null;
  return { role, text };
}

// Only fire after assistant message is fully rendered (turn complete)
// Debounce handles streaming token-by-token updates
let debounceTimer;
const observer = new MutationObserver((mutations) => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    const turns = document.querySelectorAll(SELECTORS.messageList);
    const lastTurn = turns[turns.length - 1];
    const extracted = extractTurn(lastTurn);
    if (extracted?.role === "assistant") {
      chrome.runtime.sendMessage({
        type: "NEW_TURN",
        platform: "chatgpt",
        url: location.href,
        conversationId: extractConversationId(location.pathname),
        turn: extracted,
        capturedAt: new Date().toISOString(),
      });
    }
  }, 800); // wait 800ms after last DOM mutation — streaming complete
});

observer.observe(document.body, { childList: true, subtree: true });
```

The 800ms debounce is critical — streaming responses cause hundreds of DOM mutations per turn. Without it the ingestion fires dozens of times on partial text.

## Background Service Worker

```javascript
// background.js
chrome.runtime.onMessage.addListener(async (msg) => {
  if (msg.type !== "NEW_TURN") return;
  
  const config = await chrome.storage.sync.get([
    "memoryEndpoint", "apiKey", "enabledPlatforms"
  ]);
  
  if (!config.enabledPlatforms?.[msg.platform]) return; // platform disabled
  
  await fetch(`${config.memoryEndpoint}/ingest/conversation`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({
      session_id: msg.conversationId,
      project_id: config.defaultProjectId ?? "default",
      source_agent: msg.platform,
      source_key: `browser_ext_${msg.platform}`,
      ingestion_mode: "passive",
      turn: msg.turn,
      captured_at: msg.capturedAt,
      url: msg.url,
    }),
  }).catch(() => {}); // never throw — silent failure
});
```

## Onboarding Flow

On first install, the extension opens an onboarding page:

```
Welcome to Agentic Memory
─────────────────────────
Your AI conversations, saved to your own database.

Memory Server Endpoint: [http://localhost:8000    ]
API Key:               [am_...                    ]

Enable memory collection for:
  ☑ ChatGPT      (chat.openai.com)
  ☑ Claude       (claude.ai)
  ☑ Perplexity   (perplexity.ai)
  ☐ Gemini       (gemini.google.com)

[Test Connection]  →  ✅ Connected to memory server

[Save & Start Collecting]
```

After save — done. Extension runs silently forever. No further interaction needed.

## Popup (Extension Icon Click)

The toolbar popup shows live status — gives the user awareness without interrupting workflow:

```
Agentic Memory         ●  Active
──────────────────────────────────
This session
  Platform:    ChatGPT
  Turns saved: 7
  Session ID:  abc123...

[Pause Collection]  [Open Dashboard]
```

## Conversation Stitching

The extension captures individual turns, not full conversations. The memory server stitches them into a coherent conversation node using the `session_id` (which maps to the platform's conversation ID extracted from the URL). Each turn is a separate POST — the server groups them by `session_id` and `project_id` using the same composite MERGE key established in the deduplication spec.

## DOM Selector Maintenance

Platform DOM structures change with frontend deploys. This is the primary maintenance burden. Mitigations:

- **Selectors are extracted into a `selectors.json` config file** — can be hotpatched without a full extension release
- **The extension checks a remote selectors endpoint on startup** — `GET https://your-server.com/ext/selectors.json` — allowing selector updates without going through the Chrome Store review cycle
- **Fallback selectors** — each adapter has 2-3 alternative selectors tried in sequence if the primary fails

## Package Structure

```
packages/am-ext/
├── manifest.json
├── background.js
├── onboarding.html / onboarding.js
├── popup.html / popup.js
├── adapters/
│   ├── chatgpt.js
│   ├── claude.js
│   ├── perplexity.js
│   └── gemini.js
├── selectors.json          # per-platform DOM selectors, remotely updatable
└── README.md
```

## Key Constraints Shared By Both

| Constraint | ACP Proxy | Browser Extension |
|---|---|---|
| Failure must be silent | ✅ `pass` on all exceptions | ✅ `.catch(() => {})` on all fetches |
| Data only to user's own endpoint | ✅ Config-specified | ✅ User-set in onboarding |
| `ingestion_mode` | `"passive"` | `"passive"` |
| Session ID source | Generated UUID per proxy run | Platform conversation ID from URL |
| Agent/source identification | Binary name detection | Hardcoded per adapter |
| Zero latency on hot path | ✅ Pass-through first | ✅ DOM observer never blocks rendering |