# Phase 6: am-ext (Browser Extension) — Context

**Gathered:** 2026-03-24
**Status:** Ready for research and planning
**Note:** Context gathered autonomously based on ROADMAP.md Phase 6 spec, prior phase outputs, and codebase scouting.

<domain>
## Phase Boundary

Build `packages/am-ext/` — a Chrome/Firefox Manifest V3 browser extension that passively captures AI chat conversations from web UIs and silently ships them to `POST /ingest/conversation`. Install once, capture forever with zero friction. Also populate `src/am_server/data/selectors.json` with real platform DOM selectors to activate the `GET /ext/selectors.json` endpoint built in Phase 2.

</domain>

<decisions>
## Implementation Decisions

### Package Structure

Pure vanilla JS — no TypeScript, no webpack, no build step. MV3 extension loaded directly from the filesystem for development, packed as `.zip` for distribution.

```
packages/am-ext/
├── manifest.json               ← MV3 manifest (Chrome + Firefox compatible)
├── background.js               ← Service worker: receives NEW_TURN, POSTs to am-server
├── content.js                  ← Content script: loads platform adapter, coordinates observation
├── adapters/
│   ├── base.js                 ← BaseAdapter class with shared debounce + diff logic
│   ├── chatgpt.js              ← chat.openai.com
│   ├── claude.js               ← claude.ai
│   ├── perplexity.js           ← perplexity.ai
│   └── gemini.js               ← gemini.google.com
├── popup/
│   ├── popup.html
│   ├── popup.js
│   └── popup.css
├── onboarding/
│   ├── onboarding.html
│   ├── onboarding.js
│   └── onboarding.css
├── icons/
│   ├── icon16.png              ← placeholder SVG-based icon (no design tools needed)
│   ├── icon48.png
│   └── icon128.png
└── selectors.json              ← bundled default selectors (same schema as am-server data)
```

---

### Manifest V3

```json
{
  "manifest_version": 3,
  "name": "am-ext",
  "version": "0.1.0",
  "description": "Passive conversation capture for agentic memory",
  "permissions": ["storage", "alarms"],
  "host_permissions": [
    "https://chat.openai.com/*",
    "https://claude.ai/*",
    "https://perplexity.ai/*",
    "https://gemini.google.com/*"
  ],
  "background": {
    "service_worker": "background.js"
  },
  "content_scripts": [{
    "matches": [
      "https://chat.openai.com/*",
      "https://claude.ai/*",
      "https://perplexity.ai/*",
      "https://gemini.google.com/*"
    ],
    "js": ["content.js"],
    "run_at": "document_idle"
  }],
  "action": {
    "default_popup": "popup/popup.html",
    "default_icon": {"16": "icons/icon16.png", "48": "icons/icon48.png"}
  }
}
```

**Firefox compatibility:** MV3 is supported in Firefox 109+. Use `chrome.*` APIs — Firefox MV3 maps these automatically. No webextension-polyfill needed for the API surface used here.

---

### Message Flow

```
Platform webpage DOM
    ↓  MutationObserver + 800ms debounce
Content script (content.js + adapter)
    ↓  chrome.runtime.sendMessage({type: "NEW_TURN", payload: {...}})
Background service worker (background.js)
    ↓  fetch POST /ingest/conversation (fire-and-forget, .catch(() => {}))
am-server
    ↓  ConversationIngestionPipeline
Neo4j
```

---

### Config Storage

`chrome.storage.sync` (synced across user's signed-in Chrome instances):

```js
{
  endpoint: "http://localhost:8000",     // am-server base URL
  api_key: "",                           // Bearer token
  paused: false,                         // global pause toggle from popup
  platforms: {
    chatgpt: true,
    claude: true,
    perplexity: true,
    gemini: true,
  }
}
```

Default: all platforms enabled, no endpoint/api_key (onboarding required before ingest works).

---

### selectors.json Schema

Same schema used both in `packages/am-ext/selectors.json` (bundled) and `src/am_server/data/selectors.json` (served via `GET /ext/selectors.json`). The content script fetches remote selectors at startup and merges with bundled fallback.

```json
{
  "version": 1,
  "platforms": {
    "chatgpt": {
      "url_pattern": "chat.openai.com",
      "session_id_regex": "/c/([a-z0-9-]+)",
      "messages_container": "[data-testid='conversation-turns']",
      "user_message": "[data-message-author-role='user']",
      "assistant_message": "[data-message-author-role='assistant']",
      "message_content": ".whitespace-pre-wrap, .markdown"
    },
    "claude": {
      "url_pattern": "claude.ai",
      "session_id_regex": "/chat/([a-z0-9-]+)",
      "messages_container": ".conversation-content, [data-testid='conversation']",
      "user_message": "[data-testid='user-message'], .human-turn",
      "assistant_message": ".font-claude-message, .assistant-turn, [data-testid='assistant-message']",
      "message_content": null
    },
    "perplexity": {
      "url_pattern": "perplexity.ai",
      "session_id_regex": "/search/([a-z0-9-]+)",
      "messages_container": ".prose, [class*='ConversationMessage']",
      "user_message": "[class*='UserMessage'], [class*='user-message']",
      "assistant_message": "[class*='AssistantMessage'], [class*='answer']",
      "message_content": null
    },
    "gemini": {
      "url_pattern": "gemini.google.com",
      "session_id_regex": "/app/([a-z0-9]+)",
      "messages_container": "chat-window, .conversation-container",
      "user_message": "user-query, [class*='user-query']",
      "assistant_message": "model-response, [class*='model-response']",
      "message_content": ".response-content, p"
    }
  }
}
```

**Multi-selector fallback:** All selector values support comma-separated alternatives (tried in order). The adapter tries each and uses the first that matches. This gives resilience against platform DOM updates.

---

### BaseAdapter — Shared DOM Capture Logic

```js
class BaseAdapter {
  constructor(platform, selectors) {
    this.platform = platform;
    this.selectors = selectors;
    this._debounceTimer = null;
    this._lastTurnCount = 0;
    this._sessionId = null;
    this._turnIndex = 0;
    this._observer = null;
  }

  start() {
    // 1. Extract session ID from URL
    this._sessionId = this._extractSessionId();
    // 2. Find messages container (try each selector, first match wins)
    const container = this._queryFirst(this.selectors.messages_container);
    if (!container) return;  // silent if container not found
    // 3. Observe mutations with 800ms debounce
    this._observer = new MutationObserver(() => this._onMutation());
    this._observer.observe(container, {childList: true, subtree: true});
    // 4. Capture any existing turns immediately
    this._captureNewTurns();
  }

  _onMutation() {
    clearTimeout(this._debounceTimer);
    this._debounceTimer = setTimeout(() => this._captureNewTurns(), 800);
  }

  _captureNewTurns() {
    const turns = this._extractAllTurns();
    const newTurns = turns.slice(this._lastTurnCount);
    newTurns.forEach(turn => this._sendTurn(turn));
    this._lastTurnCount = turns.length;
  }

  _sendTurn(turn) {
    chrome.runtime.sendMessage({
      type: "NEW_TURN",
      payload: {
        role: turn.role,
        content: turn.content,
        session_id: this._sessionId,
        platform: this.platform,
        turn_index: this._turnIndex++,
      }
    }).catch(() => {});  // silent failure
  }

  _extractSessionId() {
    const match = window.location.pathname.match(
      new RegExp(this.selectors.session_id_regex)
    );
    return match ? match[1] : `fallback-${Date.now()}`;
  }

  _queryFirst(selectorList) {
    // Try comma-separated selectors, return first match
    return selectorList.split(",").map(s => document.querySelector(s.trim()))
      .find(el => el != null) || null;
  }
}
```

---

### content.js — Platform Routing

```js
// content.js — injected on all matched pages
(async () => {
  const platform = detectPlatform(window.location.hostname);
  if (!platform) return;

  // Fetch remote selectors (fallback to bundled)
  const config = await chrome.storage.sync.get(["endpoint", "platforms", "paused"]);
  if (config.paused) return;
  if (!config.platforms?.[platform]) return;  // platform disabled

  let selectors = BUNDLED_SELECTORS.platforms[platform];
  try {
    const res = await fetch(`${config.endpoint || "http://localhost:8000"}/ext/selectors.json`);
    const remote = await res.json();
    if (remote.platforms?.[platform]) selectors = remote.platforms[platform];
  } catch {}  // use bundled on failure

  // Load and start platform adapter
  const AdapterClass = ADAPTERS[platform];
  const adapter = new AdapterClass(platform, selectors);
  adapter.start();

  // Re-start on SPA navigation (URL change without page reload)
  let lastUrl = window.location.href;
  new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      adapter.stop?.();
      adapter._sessionId = adapter._extractSessionId();
      adapter._lastTurnCount = 0;
      adapter._turnIndex = 0;
      adapter.start();
    }
  }).observe(document.body, {subtree: true, childList: true});
})();
```

---

### background.js — Service Worker

```js
// Keepalive alarm — prevents MV3 service worker from being killed
chrome.alarms.create("keepalive", {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(() => {});  // no-op listener keeps worker alive

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type !== "NEW_TURN") return;
  handleTurn(msg.payload);
  return false;  // sync response
});

async function handleTurn(payload) {
  try {
    const cfg = await chrome.storage.sync.get(["endpoint", "api_key", "paused", "platforms"]);
    if (cfg.paused) return;
    if (!cfg.platforms?.[payload.platform]) return;
    if (!cfg.api_key) return;  // not configured

    const body = {
      role: payload.role,
      content: payload.content,
      session_id: payload.session_id,
      project_id: cfg.project_id || "browser",
      turn_index: payload.turn_index,
      source_agent: payload.platform,
      ingestion_mode: "passive",
      source_key: `browser_ext_${payload.platform}`,
    };

    fetch(`${cfg.endpoint}/ingest/conversation`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${cfg.api_key}`,
      },
      body: JSON.stringify(body),
    }).catch(() => {});  // silent failure — NEVER surface errors
  } catch {}  // outer catch for storage errors
}
```

---

### Onboarding Page

Opened on first install via `chrome.runtime.onInstalled` listener in background.js.

Fields:
- **am-server URL** — text input, placeholder `http://localhost:8000`
- **API Key** — password input
- **Per-platform toggles** — checkbox for each of 4 platforms (all enabled by default)
- **Test Connection** — button that GETs `{endpoint}/health`, shows green/red indicator
- **Save** — stores to `chrome.storage.sync`, closes tab

---

### Popup

Activated by clicking extension icon.

Shows:
- **Current platform** (detected from active tab hostname) or "Not on a supported page"
- **Status** — Capturing / Paused / Not configured
- **Turns this session** — count from content script (via `chrome.tabs.sendMessage`)
- **Session ID** — truncated for display
- **Pause/Resume toggle** — writes `paused` to `chrome.storage.sync`
- **Settings link** — opens onboarding page

---

### Testing Strategy

Browser extensions cannot be unit tested with a standard Python test runner. For v1, testing is:

1. **Pure JS unit tests** — Test isolated utility functions (session ID extraction regex, debounce timing, selector query logic) using Node.js with `node --test` (Node 18+ built-in test runner, no jest dependency). These go in `packages/am-ext/tests/`.

2. **Manual test checklist** — Documented acceptance tests in `packages/am-ext/TESTING.md` covering: install flow, onboarding, ChatGPT capture, debounce timing, pause toggle, server downtime.

No full browser automation (Playwright) for v1 — overhead is too high. The manual checklist covers success criteria.

---

### am-server selectors.json Update

`src/am_server/data/selectors.json` must be updated with real platform selectors. This is part of Phase 6 delivery — the same selector data as in `packages/am-ext/selectors.json` is written here so the hotpatch endpoint works.

---

### Claude's Discretion

- Exact CSS selector values (research agent will verify current platform DOM)
- Icon implementation (SVG data URIs or simple solid-color PNGs)
- Exact onboarding/popup HTML layout and styling
- Session ID fallback behavior for conversations that don't yet have a URL session ID

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 4 output (this phase posts to this)
- `src/am_server/routes/conversation.py` — `POST /ingest/conversation` endpoint
- `src/am_server/models.py` — `ConversationIngestRequest` — exact schema to match
- `src/am_server/routes/ext.py` — `GET /ext/selectors.json` endpoint (returns selectors.json)
- `src/am_server/data/selectors.json` — **must be populated in Phase 6**

### Prior context
- `.planning/phases/04-conversation-memory-core/04-CONTEXT.md` — source_key and ingestion_mode decisions
- `.planning/phases/05-am-proxy/05-CONTEXT.md` — silent failure contract pattern (same applies here)

### New package location
- `packages/am-ext/` — create from scratch

### Conventions
- `.planning/codebase/CONVENTIONS.md` — Python conventions (JS files exempt from Black/Ruff/MyPy)

</canonical_refs>

<code_context>
## Existing Code Insights

### Target Endpoints (Phase 4 outputs)
- `POST /ingest/conversation` — accepts `ConversationIngestRequest`, Bearer auth required
- `GET /ext/selectors.json` — unauthenticated, returns `src/am_server/data/selectors.json`
- `GET /health` — unauthenticated, useful for onboarding connection test

### selectors.json Stub
`src/am_server/data/selectors.json` currently contains `{"version": 1, "platforms": {}}` — it's a stub waiting for real selectors from Phase 6.

### source_key Convention (Phase 4)
Phase 4 registered `chat_ext` as a source key. The actual `source_key` per payload is `browser_ext_{platform}` (e.g. `browser_ext_chatgpt`) per ROADMAP.md. These do NOT need to be pre-registered in the Python source registry — they're stored as metadata on Turn nodes. Only the Python pipeline source registry needs pre-registration, not the values stored in the graph.

### am-proxy Pattern
`packages/am-proxy/` (Phase 5) established the standalone package pattern. Follow the same layout: `packages/am-ext/` with its own `README.md`.

</code_context>

<specifics>
## Specific Implementation Notes

- **SPA navigation:** All 4 platforms are SPAs. URL changes happen without page reload. The `MutationObserver` on `document.body` watching for URL change (comparing `window.location.href`) handles this. On URL change: reset `_lastTurnCount`, generate new session ID, restart adapter.
- **`_lastTurnCount` diff approach:** Rather than tracking message hashes, count visible turn elements. Simpler, handles the 800ms debounce window (streaming completes before count is taken). A turn is counted once the element appears and debounce fires.
- **project_id in extension:** Store `project_id` in `chrome.storage.sync` (editable in onboarding). Default value: `"browser"`. Users can set this to match their am-server project.
- **turn_index in content script:** Tracked in `BaseAdapter._turnIndex`, incremented per sent turn. Resets on SPA navigation. Since dedup MERGE key is `(session_id, turn_index)`, consistent ordering within a session is sufficient.
- **`chrome.runtime.sendMessage` from content to background:** Returns a Promise in MV3. Use `.catch(() => {})` to suppress "Could not establish connection" errors when background is asleep.
- **chrome.alarms permission:** Required for keepalive. Already in manifest permissions.
- **`source_key` not in Python registry:** The `chat_ext` entry in the Python `SOURCE_REGISTRY` was registered in Phase 4. Extension payloads send `browser_ext_chatgpt` etc. — these are node metadata values, not registry keys. The graph still works correctly; the Python registry only controls label generation in the pipeline, not what values are stored in node properties.

</specifics>

<deferred>
## Deferred Ideas

- **Webpack/TypeScript build pipeline** — pure JS is sufficient for v1; build tooling adds complexity
- **Automated browser tests with Playwright** — manual checklist covers v1 acceptance criteria
- **Additional platforms** (Grok, Mistral, etc.) — add adapters in post-v1 without extension release (remote selectors hotpatch)
- **Image capture from multimodal conversations** — screenshots of image turns — future enhancement
- **Conversation export button** — export current session as JSON — future UX feature
- **Firefox-specific packaging** — `.xpi` format, AMO submission — distribution is post-v1
- **`project_id` per-platform configuration** — v1 uses single global project_id; per-platform override is future

</deferred>

---

*Phase: 06-am-ext*
*Context gathered: 2026-03-24*
