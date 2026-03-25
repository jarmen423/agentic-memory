# am-ext

`am-ext` is the browser extension for Agentic Memory’s passive conversation capture flow. It watches supported AI chat web apps, extracts completed turns from the DOM, and relays them to `am-server` so the conversation memory pipeline can ingest them without manual export steps.

## Requirements

- Chrome 120+ for the 30-second `chrome.alarms` keepalive interval used by the MV3 background worker
- Firefox 109+ for MV3 support
- A running `am-server` instance from Phase 4, reachable at `http://localhost:8000` by default
- A valid am-server API key for `POST /ingest/conversation`
- Node 18+ if you want to run the package unit tests

## Install (Development)

1. Open `chrome://extensions`.
2. Enable the **Developer mode** toggle in the top-right corner.
3. Click **Load unpacked**.
4. Select the `packages/am-ext/` directory from this repository.
5. Confirm the extension icon appears in the toolbar.
6. Wait for the onboarding tab to open automatically on first install.

This load unpacked flow is the intended development install path for the package as it exists today.

## Configuration

The onboarding page stores configuration in `chrome.storage.sync` and exposes these fields:

- **am-server URL**: Base server endpoint. Defaults to `http://localhost:8000`.
- **API key**: Bearer token used by the background worker when it posts captured turns.
- **Project ID**: Stored with each conversation payload. Defaults to `browser`.
- **Platform toggles**: Enable or disable ChatGPT, Claude, Gemini, and Perplexity independently.

On the first run, all four platform toggles are enabled by default. The onboarding page also includes a **Test Connection** button that calls `GET /health` and shows a success or failure status before you save.

The popup gives you a quick status view for the active tab:

- current supported platform
- capturing or paused status
- current session ID
- turns seen in the current session
- global pause and resume control
- link back to the onboarding page

## Supported Platforms

| Platform | URLs | Selector confidence |
| --- | --- | --- |
| ChatGPT | `https://chatgpt.com/*`, `https://chat.openai.com/*` | High |
| Claude | `https://claude.ai/*` | Medium |
| Gemini | `https://gemini.google.com/*` | High |
| Perplexity | `https://perplexity.ai/*` | Low |

Perplexity is intentionally marked low-confidence because its DOM is less stable. The remote selector hotpatch path exists so you can update selectors without shipping a new extension build.

## Selector Hotpatch

At startup, the content script loads bundled selectors and then attempts to fetch a fresher selector set from `GET /ext/selectors.json` on the configured am-server. The effective behavior is:

1. Keep `packages/am-ext/selectors.json` as the extension’s bundled fallback.
2. Update `src/am_server/data/selectors.json` when a platform DOM changes.
3. Keep am-server running so `GET /ext/selectors.json` serves the new selector payload.
4. Navigate away from and back to a supported chat page, or reload the page, so the content script starts again and fetches the updated selectors.

That means selector hotpatch changes can take effect without rebuilding or reinstalling the extension.

## Testing

Run the package unit tests with:

```bash
node --test packages/am-ext/tests/*.test.js
```

No npm install is required for this test command. Manual browser acceptance coverage lives in [TESTING.md](./TESTING.md). Use that checklist for install flow, onboarding, ChatGPT capture, debounce behavior, pause controls, server downtime handling, selector hotpatch validation, and SPA navigation.

## Architecture

The extension uses a thin browser relay architecture:

1. `content.js` detects the current platform and loads the matching adapter.
2. `adapters/base.js` observes the chat DOM, extracts new turns, and debounces streaming updates so a long response is emitted once after it settles.
3. The content script sends normalized turn payloads to `background.js` via `chrome.runtime.sendMessage`.
4. `background.js` reads synced config and forwards the payload to `POST /ingest/conversation`.
5. `am-server` handles authentication, ingestion, and downstream graph writes.

The network hop lives in the background worker so the page context does not need direct cross-origin access to the memory server.
