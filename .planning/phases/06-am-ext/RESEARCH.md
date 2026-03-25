# Phase 6: am-ext (Browser Extension) - Research

**Researched:** 2026-03-25
**Domain:** Chrome/Firefox Manifest V3 Browser Extension — DOM observation, message passing, passive conversation capture
**Confidence:** HIGH (most critical facts verified against official MDN and Chrome developer docs)

---

## Summary

Phase 6 builds a Manifest V3 browser extension that passively captures AI chat conversations from claude.ai, chatgpt.com, perplexity.ai, and gemini.google.com, then ships them to the am-server `POST /ingest/conversation` endpoint. The CONTEXT.md design is technically sound and follows established MV3 patterns.

The most significant research finding is a **Firefox background script incompatibility**: Firefox does not support the `"service_worker"` key in the `background` manifest section (bug 1573659 is still open as of this research). The fix is simple — include both `"scripts"` (for Firefox) and `"service_worker"` (for Chrome) in the background manifest block. Chrome ignores `scripts` in MV3; Firefox ignores `service_worker`. This single-manifest approach covers both browsers without a polyfill.

DOM selectors were verified against the `revivalstack/ai-chat-exporter` repository (active maintenance, last updated 2025). The selectors in CONTEXT.md are directionally correct for ChatGPT and Claude, with corrections and additions for Gemini (uses custom web components: `user-query`, `model-response`) and refinements for Claude and Perplexity.

Service worker keepalive via `chrome.alarms` with `periodInMinutes: 0.5` (30 seconds minimum, Chrome 120+) is the official approach and is sufficient for this use case. Alarms wake a terminated service worker before processing the next turn, so no turns are lost even if the worker was killed between conversations.

**Primary recommendation:** Build exactly as CONTEXT.md specifies; apply the Firefox background manifest fix; use the verified DOM selectors below to populate `selectors.json`.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Pure vanilla JS — no TypeScript, no webpack, no build step
- MV3 extension (Chrome primary, Firefox secondary)
- Package structure: `packages/am-ext/` with adapters/, popup/, onboarding/, icons/
- `chrome.storage.sync` for config (not local) — synced across signed-in Chrome instances
- 800ms MutationObserver debounce for streaming detection
- BaseAdapter pattern: each platform has an Adapter class extending BaseAdapter
- `selectors.json` externalized (both bundled and remotely fetchable from `GET /ext/selectors.json`)
- Background service worker handles all fetch() calls; content scripts do NOT make cross-origin requests
- `chrome.alarms` keepalive with `periodInMinutes: 0.5`
- `chrome.runtime.sendMessage` from content to background (Promise-based in MV3, `.catch(() => {})` to suppress connection errors)
- Silent failure on all fetch paths — `.catch(() => {})` everywhere
- `ingestion_mode: "passive"`, `source_key: "browser_ext_{platform}"` on all payloads
- Session ID extracted from platform conversation URL (not generated)
- `_lastTurnCount` diff approach (count elements, not hash content)
- SPA navigation handled by MutationObserver on `document.body` watching for URL changes
- Testing: Node.js `node --test` for pure JS utility functions + manual checklist; no Playwright
- Onboarding page opened on first install via `chrome.runtime.onInstalled`
- No OAuth, no login scraping — passive DOM observation only
- `project_id` stored in `chrome.storage.sync`, default: `"browser"`

### Claude's Discretion
- Exact CSS selector values (research agent will verify current platform DOM)
- Icon implementation (SVG data URIs or simple solid-color PNGs)
- Exact onboarding/popup HTML layout and styling
- Session ID fallback behavior for conversations that don't yet have a URL session ID

### Deferred Ideas (OUT OF SCOPE)
- Webpack/TypeScript build pipeline
- Automated browser tests with Playwright
- Additional platforms (Grok, Mistral, etc.)
- Image capture from multimodal conversations
- Conversation export button
- Firefox-specific packaging (.xpi format, AMO submission)
- `project_id` per-platform configuration (v1 uses single global project_id)
</user_constraints>

---

## Standard Stack

### Core
| Component | Version / Spec | Purpose | Why Standard |
|-----------|---------------|---------|--------------|
| Manifest V3 | MV3 spec (Chrome 88+, Firefox 109+) | Extension packaging and permissions | Current required spec; MV2 deprecated |
| Vanilla JS (ES2020+) | No framework | All extension code | No build step required; decision locked |
| `chrome.*` APIs | Chrome Extension API | storage, alarms, tabs, runtime, scripting | Universal — Firefox maps chrome.* in MV3 |
| MutationObserver | Web API (all browsers) | DOM change detection | Only correct tool for streaming UI observation |
| `node:test` | Node 18+ built-in | Unit tests for utility functions | Zero dependencies; locked decision |

### Supporting
| Component | Version | Purpose | When to Use |
|-----------|---------|---------|-------------|
| `chrome.storage.sync` | MV3 API | Config persistence across devices | User settings (endpoint, api_key, paused, project_id) |
| `chrome.alarms` | MV3 API | Service worker keepalive | Background.js — prevents 30s idle termination |
| `chrome.runtime.sendMessage` | MV3 API | Content script → background IPC | Every detected turn event |
| `chrome.tabs.sendMessage` | MV3 API | Background/popup → content script IPC | Popup querying turn count from active tab |
| `chrome.runtime.onInstalled` | MV3 API | First-run detection | Opening onboarding on initial install |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `chrome.alarms` keepalive | WebSocket keepalive (Chrome 116+) | Alarms simpler, no server-side component needed |
| `chrome.storage.sync` | `chrome.storage.local` | sync cross-device at cost of 102KB quota; config is tiny (~200 bytes) |
| Vanilla JS | TypeScript | TS adds build step (deferred); plain JS is fine for this scope |
| `node:test` | Jest | Jest needs install; `node:test` is zero-dep for simple utility functions |

**Installation:** No npm packages. The extension is loaded unpacked from the filesystem during development.

---

## Architecture Patterns

### Recommended Project Structure
```
packages/am-ext/
├── manifest.json               - MV3 manifest (Chrome + Firefox compatible)
├── background.js               - Service worker: receives NEW_TURN, POSTs to am-server
├── content.js                  - Content script: loads platform adapter, coordinates observation
├── adapters/
│   ├── base.js                 - BaseAdapter class with shared debounce + diff logic
│   ├── chatgpt.js              - chat.openai.com
│   ├── claude.js               - claude.ai
│   ├── perplexity.js           - perplexity.ai
│   └── gemini.js               - gemini.google.com
├── popup/
│   ├── popup.html
│   ├── popup.js
│   └── popup.css
├── onboarding/
│   ├── onboarding.html
│   ├── onboarding.js
│   └── onboarding.css
├── icons/
│   ├── icon16.png
│   ├── icon48.png
│   └── icon128.png
├── selectors.json              - Bundled default selectors
├── tests/
│   └── utils.test.js           - node:test unit tests for utility functions
├── TESTING.md                  - Manual acceptance test checklist
└── README.md
```

### Pattern 1: Firefox + Chrome Cross-Browser Background Manifest

**What:** The manifest background block must include BOTH `service_worker` (for Chrome) and `scripts` (for Firefox). Firefox bug 1573659 means `service_worker` is not supported in Firefox; Chrome ignores `scripts` in MV3.

**When to use:** Always — this is the only correct approach for Chrome+Firefox dual support without a polyfill.

```json
// Source: MDN WebExtensions/manifest.json/background (verified 2026-03-25)
{
  "background": {
    "scripts": ["background.js"],
    "service_worker": "background.js"
  }
}
```

**NOTE:** CONTEXT.md shows only `"service_worker": "background.js"`. The `scripts` fallback must be added for Firefox support.

### Pattern 2: Service Worker Keepalive via chrome.alarms

**What:** Chrome terminates extension service workers after 30 seconds of idle time. `chrome.alarms` wakes the worker on a schedule, preventing termination between conversation turns.

**When to use:** background.js — always. The alarm listener must be registered at the top level (not inside another listener) to fire reliably on worker wake.

```javascript
// Source: Chrome developer docs — extension service worker lifecycle (verified 2026-03-25)
// Minimum alarm period since Chrome 120: 30 seconds (periodInMinutes: 0.5)
chrome.alarms.create("keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => {}); // no-op — waking up is sufficient
```

**Key insight:** The service worker may be killed between turns. When the next `chrome.runtime.onMessage` fires (from content script), Chrome wakes the service worker. The alarm is a secondary guarantee that the worker doesn't go cold for more than 30 seconds, which ensures `chrome.storage.sync.get` calls in `handleTurn()` are fast.

### Pattern 3: Content Script Cross-Origin Fetch Prohibition

**What:** Content scripts in MV3 CANNOT make cross-origin fetch requests directly. They run in the context of the web page's origin and are subject to that page's CORS policy. The background service worker CAN fetch any URL declared in `host_permissions`.

**When to use:** This is why the architecture routes all fetch() calls through the background. Content scripts only use `chrome.runtime.sendMessage` to hand off turn data.

```javascript
// Source: Chrome developer docs — network requests (verified 2026-03-25)
// content.js — CORRECT: relay to background, no direct fetch
chrome.runtime.sendMessage({ type: "NEW_TURN", payload: {...} }).catch(() => {});

// background.js — CORRECT: background can fetch with host_permissions
fetch(`${cfg.endpoint}/ingest/conversation`, { method: "POST", ... }).catch(() => {});
```

**host_permissions for localhost:** Use `"http://localhost/*"` and optionally `"http://127.0.0.1/*"` in `host_permissions` for the default am-server endpoint. Users running am-server on a non-default port need the wildcard to cover any port.

### Pattern 4: MutationObserver Debounce for Streaming UIs

**What:** AI chat UIs update the DOM token-by-token during streaming. Observing at `childList: true, subtree: true` fires the callback dozens of times per second. A 800ms debounce collapses all mutations from a single streaming response into one event.

**When to use:** BaseAdapter._onMutation() — the 800ms debounce fires only after streaming stops, ensuring `_extractAllTurns()` captures the complete response.

```javascript
// Source: CONTEXT.md design + verified MDN MutationObserver docs
this._observer = new MutationObserver(() => {
  clearTimeout(this._debounceTimer);
  this._debounceTimer = setTimeout(() => this._captureNewTurns(), 800);
});
this._observer.observe(container, { childList: true, subtree: true });
```

**Subtree vs childList only:** `subtree: true` is required — streaming responses update deeply nested elements, not just direct children of the container.

### Pattern 5: SPA Navigation Detection

**What:** All 4 supported platforms (ChatGPT, Claude, Gemini, Perplexity) are SPAs. Navigation between conversations changes `window.location.href` without a page reload, so content scripts are NOT re-injected. The adapter must detect URL changes and restart.

**When to use:** content.js — observe `document.body` for any DOM mutation and compare `window.location.href` to `lastUrl`.

```javascript
// Source: CONTEXT.md design (verified pattern — SPAs don't trigger content script re-injection)
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
}).observe(document.body, { subtree: true, childList: true });
```

**Caveat:** Observing `document.body` with `subtree: true` is expensive. Performance acceptable here because (a) it's a no-op if URL hasn't changed, (b) the four supported platforms have fast UIs.

### Pattern 6: chrome.runtime.sendMessage Fire-and-Forget

**What:** `chrome.runtime.sendMessage` returns a Promise in MV3. When the background service worker is sleeping, the call rejects with "Could not establish connection. Receiving end does not exist." This must be suppressed silently.

**When to use:** Every `_sendTurn()` call in BaseAdapter — use `.catch(() => {})` to swallow connection errors.

```javascript
// Source: Chrome developer docs — messaging (verified 2026-03-25)
chrome.runtime.sendMessage({ type: "NEW_TURN", payload: { ... } })
  .catch(() => {}); // suppress "receiving end does not exist" when SW is sleeping
```

**Important:** When the background worker is sleeping and a message arrives, Chrome wakes the worker and processes it. The connection error only occurs in a narrow race condition; `.catch(() => {})` handles it.

### Anti-Patterns to Avoid

- **Direct fetch() from content scripts:** Cross-origin requests are blocked in MV3 content scripts. Always route through background via sendMessage.
- **`persistent: true` in background:** Not supported in MV3; Chrome ignores it.
- **Global variables in service worker for state:** Service worker may be killed; use `chrome.storage` for any state that must survive across invocations. (Turn count lives in content script, not background — this is correct.)
- **`setInterval` keepalive in service worker:** Only allowed for enterprise/education managed devices. Not acceptable for Web Store submission.
- **Observing DOM before `document_idle`:** Content scripts with `run_at: "document_idle"` are guaranteed to run after DOM is complete — do not add `DOMContentLoaded` listeners.
- **Synchronously loading adapters with `<script>` tags:** MV3 content scripts cannot use dynamic `<script>` injection in the page context. All adapter code must be in a single content script or declared in the manifest.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service worker keepalive | Custom WebSocket ping | `chrome.alarms` API | Official API; zero server component; wakes SW reliably |
| Config storage | `localStorage`, cookies, IndexedDB | `chrome.storage.sync` | Only storage accessible from content script + background + popup simultaneously |
| Cross-origin fetch from content | Content-script fetch with headers | Route through background service worker | MV3 security model blocks content script cross-origin requests |
| Extension popup → content comms | Custom event dispatching | `chrome.tabs.sendMessage` | Correct MV3 pattern for extension → content IPC |
| Message schema validation | Manual type checks | Pydantic (server-side, already in am-server) | Client extension is fire-and-forget; server validates |

**Key insight:** The extension is thin by design. All the heavy lifting (embedding, entity extraction, graph writes) happens server-side. The extension's job is observation and relay — resist adding complexity here.

---

## Verified DOM Selectors

Verified against `revivalstack/ai-chat-exporter` (active as of 2025) and cross-referenced with CONTEXT.md proposals.

### ChatGPT (chat.openai.com)

| Element | Selector | Status |
|---------|---------|--------|
| Conversation turns | `section[data-testid^='conversation-turn-']` | VERIFIED — each turn is its own `<section>` |
| User messages | `[data-message-author-role='user']` | VERIFIED — still present 2025 |
| Assistant messages | `[data-message-author-role='assistant']` | VERIFIED |
| Message content | `.markdown, .whitespace-pre-wrap` | VERIFIED |
| Session ID source | URL path `/c/{uuid}` | VERIFIED |

**Refinement from CONTEXT.md:** `messages_container` in CONTEXT.md uses `[data-testid='conversation-turns']` (a wrapper). The per-turn selector `section[data-testid^='conversation-turn-']` directly identifies individual turns without needing a container. The container approach also works for MutationObserver — use `[data-testid='conversation-turns']` as the observer target.

### Claude.ai

| Element | Selector | Status |
|---------|---------|--------|
| User messages | `[data-testid='user-message']` | VERIFIED |
| Assistant messages | `.font-claude-response` | VERIFIED (also seen as `.font-claude-message` in some versions) |
| Message actions (for role detection) | `[role='group'][aria-label='Message actions']` | VERIFIED — alternative approach |
| Assistant detection | Presence of `button[aria-label='Give positive feedback']` | VERIFIED — only on assistant turns |
| Conversation container | `[data-testid='conversation']` | Likely valid; needs visual verification |
| Session ID source | URL path `/chat/{uuid}` | VERIFIED |

**Key finding:** Claude does NOT use a single reliable container selector with stable class names. The most robust selector strategy is `[data-testid='user-message']` for user turns and `.font-claude-response` (or `.font-claude-message` as fallback) for assistant turns. The CONTEXT.md `.human-turn` / `.assistant-turn` selectors may be outdated — prefer `data-testid` over class names.

**Revised selectors.json for claude:**
```json
{
  "user_message": "[data-testid='user-message']",
  "assistant_message": ".font-claude-response, .font-claude-message, [data-testid='assistant-message']"
}
```

### Gemini (gemini.google.com)

| Element | Selector | Status |
|---------|---------|--------|
| User messages | `user-query` (custom element) | VERIFIED |
| User message content | `user-query > div.query-content` | VERIFIED |
| Assistant messages | `model-response` (custom element) | VERIFIED |
| Assistant content | `model-response > message-content` | VERIFIED |
| Chat container | `chat-window` | Likely valid (from CONTEXT.md) |
| Session ID source | URL path `/app/{id}` | VERIFIED |

**Key finding:** Gemini uses custom HTML elements (`user-query`, `model-response`), not CSS classes. These are part of Gemini's Angular/Web Components architecture and have been stable. The CONTEXT.md selectors are correct. The adapter must use `innerText` or `.textContent` on `query-content` and `message-content` children.

### Perplexity (perplexity.ai)

| Element | Selector | Status |
|---------|---------|--------|
| User messages | `[class*='UserMessage']` | MEDIUM confidence |
| Assistant messages | `[class*='AnswerSection']` | MEDIUM confidence |
| Session ID source | URL path `/search/{id}` | VERIFIED |

**Note:** Perplexity's DOM is the least stable of the four platforms — it uses Tailwind/CSS-in-JS with generated class names. The `[class*='UserMessage']` substring match is the most resilient approach. The CONTEXT.md selectors are reasonable but should be considered LOW confidence pending real browser inspection. The remote selectors hotpatch mechanism is most critical for Perplexity.

---

## Common Pitfalls

### Pitfall 1: Firefox Ignores `service_worker` in Manifest Background

**What goes wrong:** Extension loads in Chrome, but Firefox either fails to register a background script or uses an empty event page with no listeners.

**Why it happens:** Firefox bug 1573659 — `service_worker` key in `background` is not supported in Firefox MV3 (as of 2026-03-25). Firefox requires `scripts` array.

**How to avoid:** Include both keys:
```json
"background": {
  "scripts": ["background.js"],
  "service_worker": "background.js"
}
```

**Warning signs:** Extension installs in Firefox but no turns are ingested; no console errors in content script.

### Pitfall 2: Service Worker Terminated Between Long Conversations

**What goes wrong:** User opens a long conversation. After ~30 seconds of reading without DOM mutations, the service worker is killed. The next turn fires `sendMessage` which wakes the SW, but there's a brief race condition window.

**Why it happens:** Chrome kills idle extension service workers after 30 seconds.

**How to avoid:** `chrome.alarms` with `periodInMinutes: 0.5` wakes the SW every 30 seconds. The listener must be at the top level of background.js (not inside another callback) to fire reliably on SW wake.

**Warning signs:** First turn of a resumed conversation silently fails; subsequent turns succeed.

### Pitfall 3: chrome.storage.sync Quota on Write-Heavy Patterns

**What goes wrong:** Writes to `chrome.storage.sync` fail silently if quota is exceeded or if more than 120 writes/minute occur.

**Why it happens:** Sync storage has 102KB total, 8KB per item, 120 operations/minute limit.

**How to avoid:** Config object fits well within limits (~200 bytes). Never write to sync storage per-turn — only write on config changes (pause toggle, settings save). Turn state (count, session ID) lives only in the adapter's in-memory state, never in storage.

**Warning signs:** `chrome.runtime.lastError` set after storage.set() in onboarding; settings not persisting.

### Pitfall 4: Adapter `_lastTurnCount` Reset on SPA Navigation Race

**What goes wrong:** URL changes while streaming is in progress. The adapter restarts with `_lastTurnCount = 0` and re-captures all visible turns including in-progress ones, producing duplicate entries in Neo4j.

**Why it happens:** The URL MutationObserver fires immediately on navigation, before the old content has been replaced with the new conversation.

**How to avoid:** On URL change, wait for the container to be replaced before restarting the adapter. A 200ms delay after URL change before calling `adapter.start()` is sufficient for all four platforms. The dedup MERGE key `(session_id, turn_index)` on the server provides a safety net — duplicate posts with the same session_id + turn_index are idempotent.

**Warning signs:** Duplicate turns appearing in Neo4j after SPA navigation.

### Pitfall 5: Content Script `fetch()` to am-server Silently Fails

**What goes wrong:** Developer removes the background relay and tries to call `fetch()` from content.js directly. It works locally but fails on production sites with strict CSP.

**Why it happens:** Content scripts run in the page's origin context. Sites like claude.ai have CSP that blocks outbound connections to non-allowlisted origins.

**How to avoid:** Never fetch from content scripts. All network calls go through background.js. This is already the locked design.

**Warning signs:** Console error in content script: "Refused to connect to 'http://localhost:8000/' because it violates the following Content Security Policy directive".

### Pitfall 6: `all_frames: true` Not Set for Embedded Chat

**What goes wrong:** Chat interface loads in an iframe (less common but possible in some platform embeds). Content script only injects into the top-level frame and misses the conversation.

**Why it happens:** Default content script injection targets top-level frames only.

**How to avoid:** For v1, the four platforms all render chat in the main frame — no `all_frames` needed. Document this assumption.

### Pitfall 7: Streaming Detection Fires Before Response Completes

**What goes wrong:** 800ms debounce fires, but the assistant response was taking longer than 800ms between token batches (e.g., long tool use). The adapter captures a partial response.

**Why it happens:** Very slow streaming or tool-use pauses can exceed the debounce window.

**How to avoid:** The server-side dedup key is `(session_id, turn_index)`. If a partial response is ingested first, a subsequent capture of the completed response with the same turn_index will MERGE and overwrite the content property. The `_lastTurnCount` diff approach means the completed turn is not sent again as a new turn — BUT if the content changes, the MERGE won't update it (Neo4j MERGE only creates, not updates). For v1, document this as acceptable — long tool-use turns may be captured at partial completion.

---

## Code Examples

### Verified Pattern: Chrome + Firefox Compatible Manifest Background

```json
// Source: MDN WebExtensions/manifest.json/background (verified 2026-03-25)
{
  "manifest_version": 3,
  "background": {
    "scripts": ["background.js"],
    "service_worker": "background.js"
  }
}
```

### Verified Pattern: chrome.storage.sync Access in Content Script

```javascript
// Source: Chrome developer docs (verified — storage.sync accessible from content scripts by default)
const config = await chrome.storage.sync.get(["endpoint", "platforms", "paused"]);
// config.endpoint, config.platforms, config.paused all available
```

### Verified Pattern: Fire-and-Forget Message with Error Suppression

```javascript
// Source: Chrome developer docs — messaging (verified 2026-03-25)
// MV3: sendMessage returns a Promise. Catch suppresses "receiving end does not exist".
chrome.runtime.sendMessage({ type: "NEW_TURN", payload: payload })
  .catch(() => {});
```

### Verified Pattern: node:test Unit Test with Chrome API Mock

```javascript
// Source: node:test built-in + Chrome unit testing docs (verified 2026-03-25)
// tests/utils.test.js — no npm dependencies
import { test } from 'node:test';
import assert from 'node:assert/strict';

// Manual chrome API mock for the test scope
globalThis.chrome = {
  storage: { sync: { get: async () => ({}) } },
  runtime: { sendMessage: async () => {} },
};

test('extractSessionId extracts UUID from claude.ai URL', () => {
  const path = '/chat/abc123-def456';
  const match = path.match(/\/chat\/([a-z0-9-]+)/);
  assert.equal(match?.[1], 'abc123-def456');
});
```

### Verified Pattern: Gemini Custom Element Content Extraction

```javascript
// Source: revivalstack/ai-chat-exporter (verified 2025 — Gemini uses web components)
function extractGeminiTurns() {
  const userTurns = [...document.querySelectorAll('user-query')];
  const assistantTurns = [...document.querySelectorAll('model-response')];
  // interleave by DOM order
  const allTurns = [...document.querySelectorAll('user-query, model-response')];
  return allTurns.map(el => ({
    role: el.tagName.toLowerCase() === 'user-query' ? 'user' : 'assistant',
    content: el.querySelector('div.query-content, message-content')?.innerText?.trim() || '',
  }));
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| MV2 background page (persistent) | MV3 service worker (ephemeral) | Chrome 88+, mandatory ~2023 | Service workers get killed; need keepalive strategy |
| `chrome.alarms` min 1 minute | `chrome.alarms` min 30 seconds | Chrome 120 (Dec 2023) | `periodInMinutes: 0.5` now valid |
| Content script fetch for cross-origin | Background service worker relay | MV3 (enforced) | Content scripts can no longer make cross-origin requests reliably |
| `background.scripts` array | `background.service_worker` string | MV3 | Firefox still requires `scripts` (see pitfall 1) |

**Deprecated/outdated:**
- `chrome.browserAction` / `chrome.pageAction`: Unified into `chrome.action` in MV3
- MV2 `permissions` containing host patterns: Now in separate `host_permissions` key
- Persistent background pages (`persistent: true`): Not supported in MV3

---

## Open Questions

1. **Claude.ai `.font-claude-response` vs `.font-claude-message`**
   - What we know: Both class names have been observed in the wild; the exporter tools use `.font-claude-response`
   - What's unclear: Which is current as of 2026-03-25 (requires live browser inspection)
   - Recommendation: Use comma-separated fallback — `.font-claude-response, .font-claude-message` — and verify by loading claude.ai and inspecting DOM before writing the adapter

2. **Perplexity DOM stability**
   - What we know: Perplexity uses Next.js/Tailwind with generated class names; substring selectors like `[class*='UserMessage']` have been used in community tools
   - What's unclear: Whether these substring selectors survive frequent UI updates
   - Recommendation: Treat Perplexity selectors as LOW confidence; implement the adapter but prioritize the remote selectors hotpatch mechanism so Perplexity can be fixed without an extension release

3. **claude.ai conversation container selector**
   - What we know: The chat exporter tools bypass the container and target messages directly
   - What's unclear: Whether `[data-testid='conversation']` is a valid MutationObserver target
   - Recommendation: Fall back to `document.body` as the observer target if no container is found — less efficient but guaranteed to work

4. **Firefox `chrome.alarms` keepalive behavior**
   - What we know: Firefox MV3 uses event pages (not service workers), which are not killed on idle in the same way Chrome service workers are
   - What's unclear: Whether `chrome.alarms` is needed at all for Firefox (event pages may persist by default)
   - Recommendation: Keep the alarms code — it's harmless on Firefox and required on Chrome

---

## Environment Availability

> Phase 6 creates a new package from scratch (no external runtime dependencies beyond a browser). No server-side dependencies are new.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Chrome browser (dev) | Extension development/testing | Assumed | — | Firefox |
| am-server (local) | Integration testing | Assumed running from Phase 4/5 | — | Manual payload inspection |
| Node.js | `node --test` unit tests | Assumed | 18+ | — |

**Missing dependencies with no fallback:** None — this is a browser extension with no new server-side requirements.

---

## Validation Architecture

> `workflow.nyquist_validation: true` in config.json — this section is required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `node:test` (Node.js 18+ built-in) |
| Config file | None — no configuration file needed |
| Quick run command | `node --test packages/am-ext/tests/` |
| Full suite command | `node --test packages/am-ext/tests/` (same — no integration tests in v1) |

### Phase Requirements → Test Map

| Behavior | Test Type | Automated Command | Notes |
|----------|-----------|-------------------|-------|
| Session ID regex extraction (all 4 platforms) | unit | `node --test packages/am-ext/tests/utils.test.js` | Pure function, fully testable |
| Debounce timer logic (800ms fires once) | unit | `node --test packages/am-ext/tests/utils.test.js` | Use `node:test` mock timers |
| Multi-selector fallback (`_queryFirst`) | unit | `node --test packages/am-ext/tests/utils.test.js` | No DOM needed — test the logic |
| chrome.storage.sync read in content script | unit | `node --test packages/am-ext/tests/utils.test.js` | Mock chrome API |
| ChatGPT turn capture (live) | manual | TESTING.md | Requires browser |
| Claude turn capture (live) | manual | TESTING.md | Requires browser |
| Debounce fires once per streaming response | manual | TESTING.md | Requires live streaming |
| Pause toggle stops ingest | manual | TESTING.md | Requires popup interaction |
| Server unreachable — no visible error | manual | TESTING.md | Kill am-server, verify UX |
| Selector hotpatch from remote endpoint | manual | TESTING.md | Update selectors.json, reload |
| Onboarding flow completes in < 2 minutes | manual | TESTING.md | First-install simulation |

### Wave 0 Gaps

- [ ] `packages/am-ext/tests/utils.test.js` — session ID regex, debounce, _queryFirst tests
- [ ] `packages/am-ext/TESTING.md` — manual acceptance checklist

*(No test framework install needed — `node:test` is built into Node 18+)*

---

## Sources

### Primary (HIGH confidence)
- [Chrome Extension Service Worker Lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle) — termination conditions, alarms minimum period
- [Chrome Extension Network Requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests) — content script cross-origin prohibition
- [Chrome Extension Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/messaging) — sendMessage promise return, fire-and-forget pattern
- [Chrome Extension Storage API](https://developer.chrome.com/docs/extensions/reference/api/storage) — sync quota limits (102KB, 8KB/item, 120 ops/min)
- [MDN WebExtensions background manifest](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/background) — Firefox service_worker not supported (bug 1573659), scripts+service_worker dual pattern
- [Chrome Extension Unit Testing](https://developer.chrome.com/docs/extensions/mv3/unit-testing/) — Jest recommendation, chrome API mock pattern
- [revivalstack/ai-chat-exporter](https://raw.githubusercontent.com/revivalstack/ai-chat-exporter/main/ai-chat-exporter.user.js) — verified DOM selectors for ChatGPT, Claude, Gemini (2025)

### Secondary (MEDIUM confidence)
- [Firefox MV3 Migration Guide](https://extensionworkshop.com/documentation/develop/manifest-v3-migration-guide/) — chrome.* namespace support, CSP differences
- [agarwalvishal/claude-chat-exporter](https://github.com/agarwalvishal/claude-chat-exporter) — Claude selector pattern using feedback button for role detection
- [victoronsoftware.com unit test guide](https://victoronsoftware.com/posts/add-unit-tests-to-chrome-extension/) — Jest + custom chrome mock setup pattern

### Tertiary (LOW confidence, flag for validation)
- Perplexity.ai DOM selectors — no authoritative source; inferred from community tools using `[class*='UserMessage']`
- Claude.ai `.font-claude-response` vs `.font-claude-message` — two different class names observed in different tools; requires live DOM inspection to confirm current name

---

## Project Constraints (from CONVENTIONS.md)

CONVENTIONS.md applies to Python code. The extension is **vanilla JS** and explicitly exempt from:
- Black formatter (Python only)
- Ruff linter (Python only)
- MyPy (Python only)

**JS conventions that apply by analogy:**
- Snake_case for JS variables and functions (matches Python convention throughout project)
- Private methods/properties prefixed with `_` (as established in BaseAdapter design)
- Silent failure pattern (`.catch(() => {})`) consistent with am-proxy Phase 5 pattern
- No bare `catch:` clauses — use `.catch(() => {})` for intentional suppression

---

## Metadata

**Confidence breakdown:**
- Chrome MV3 APIs (storage, alarms, messaging, service worker lifecycle): HIGH — verified against official Chrome developer docs
- Firefox compatibility (background manifest dual-key pattern): HIGH — verified against MDN with specific bug reference
- DOM selectors (ChatGPT, Gemini): HIGH — verified against actively maintained community exporter (2025)
- DOM selectors (Claude.ai): MEDIUM — verified class name exists but `.font-claude-response` vs `.font-claude-message` ambiguity requires live inspection
- DOM selectors (Perplexity): LOW — inferred from community patterns, not verified against live DOM
- Testing approach (`node:test`): HIGH — built-in Node 18+, zero dependencies, locked decision

**Research date:** 2026-03-25
**Valid until:** 2026-06-25 for Chrome/Firefox APIs (stable); 2026-04-25 for DOM selectors (sites change frequently)
