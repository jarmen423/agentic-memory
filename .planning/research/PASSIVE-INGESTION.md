# Passive Ingestion Architecture

**Captured:** 2026-03-21
**Source:** SPEC-browser-extension-and-ACP-proxy.md

## Overview

Two passive ingestion connectors sit on top of the REST API server (`am-server`). Both use `ingestion_mode: "passive"` and POST to `POST /ingest/conversation`. Neither requires OAuth or prompt engineering.

| Connector | Target | Transport | Session ID |
|---|---|---|---|
| am-proxy | ACP CLI agents (claude, codex, gemini, opencode, kiro) | stdio JSON-RPC tee | Generated UUID per proxy run |
| am-ext | Web UI agents (ChatGPT, Claude.ai, Perplexity, Gemini) | DOM MutationObserver | Platform conversation ID from URL |

## am-proxy Critical Design Decisions

### Buffer TTL (fixed from original spec)
The `_buffer` dict for request/response pairing uses `asyncio.call_later` per-entry TTL handles, NOT an unbounded dict. This prevents memory leaks when requests never receive a response (agent crash, cancelled requests).

```python
BUFFER_TTL = 300  # 5 minutes

def _store_request(self, request_id: str, msg: dict) -> None:
    if request_id in self._buffer:
        self._buffer[request_id][1].cancel()
    handle = asyncio.get_event_loop().call_later(BUFFER_TTL, self._evict, request_id)
    self._buffer[request_id] = (msg, handle)

def _pop_request(self, request_id: str) -> dict | None:
    entry = self._buffer.pop(request_id, None)
    if entry is None:
        return None
    msg, handle = entry
    handle.cancel()  # Response arrived — cancel TTL
    return msg

def _evict(self, request_id: str) -> None:
    self._buffer.pop(request_id, None)  # TTL fired, no response ever arrived
```

### Message Filtering
Ingest only: `threads/create`, `threads/message`, `threads/tool_call`, `threads/tool_result`, `threads/update`
Skip: `ping`, `pong`, `$/cancelRequest`, `window/logMessage`, `$/progress`

### Pass-through invariant
Pass through FIRST, ingest async AFTER. The proxy never buffers, never delays, never modifies the stream.

### Source registry entries (register in Phase 5)
```python
register_source("acp_proxy_claude", ["Memory", "Conversation", "ACPProxy"])
register_source("acp_proxy_codex",  ["Memory", "Conversation", "ACPProxy"])
register_source("acp_proxy_gemini", ["Memory", "Conversation", "ACPProxy"])
```

## am-ext Critical Design Decisions

### 800ms debounce
Streaming responses cause hundreds of DOM mutations per turn. The MutationObserver fires a debounced callback 800ms after the last mutation — this reliably indicates streaming is complete.

### Remote selectors
Platform DOM structures change with frontend deploys. `selectors.json` is fetched from `GET {memory_endpoint}/ext/selectors.json` at startup, allowing selector updates without Chrome Store review.

### Session ID
Uses platform conversation ID extracted from URL path (e.g., `/c/abc123` on chat.openai.com), not a generated UUID. This enables conversation stitching — turns from the same conversation share a session_id even across browser sessions.

### Source registry entries (register in Phase 6)
```python
register_source("browser_ext_chatgpt",    ["Memory", "Conversation", "BrowserExt"])
register_source("browser_ext_claude",     ["Memory", "Conversation", "BrowserExt"])
register_source("browser_ext_perplexity", ["Memory", "Conversation", "BrowserExt"])
register_source("browser_ext_gemini",     ["Memory", "Conversation", "BrowserExt"])
```

## REST API Requirement

Both connectors POST to `POST /ingest/conversation`. This endpoint must exist before either connector can be deployed.

**`am-server` REST API is split across two phases:**
- **Phase 2 (02-04-PLAN)** — FastAPI foundation: `POST /ingest/research`, `GET /search/research`, Bearer token auth middleware, `GET /ext/selectors.json` for am-ext hotpatching
- **Phase 4** — Extends `am-server` with conversation endpoints: `POST /ingest/conversation`, `GET /search/conversations`

Phases 5 (am-proxy) and 6 (am-ext) depend on Phase 4 for `/ingest/conversation`. The server infrastructure and auth middleware are already available after Phase 2.

Payload shape (both connectors):
```json
{
  "session_id": "...",
  "project_id": "...",
  "source_agent": "claude_code|chatgpt|perplexity|...",
  "source_key": "acp_proxy_claude|browser_ext_chatgpt|...",
  "ingestion_mode": "passive",
  "turn": { "role": "user|assistant", "text": "..." },
  "captured_at": "2026-03-21T18:00:00Z"
}
```

## Failure Modes (both connectors)

| Failure | Behavior |
|---|---|
| Memory server unreachable | Swallow silently. Session continues unaffected. |
| Server slow (>5s timeout) | httpx/fetch timeout fires, swallowed silently. |
| JSON parse error | Skip that message/turn, continue. |
| Proxy/extension crash | Agent/browser session continues independently — ingestion lost for that session only. |
