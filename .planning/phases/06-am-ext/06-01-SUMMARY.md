---
phase: 06-am-ext
plan: 01
subsystem: am-ext
tags:
  - browser-extension
  - manifest-v3
  - background-worker
requires: []
provides:
  - MV3 extension scaffold under packages/am-ext
  - cross-browser background manifest wiring
  - silent background ingestion worker for /ingest/conversation
affects:
  - packages/am-ext
tech_stack:
  - Manifest V3
  - Chrome extension APIs
  - Firefox WebExtension compatibility keys
  - Vanilla JavaScript
  - Node.js
key_files:
  created:
    - packages/am-ext/manifest.json
    - packages/am-ext/background.js
    - packages/am-ext/icons/icon16.png
    - packages/am-ext/icons/icon48.png
    - packages/am-ext/icons/icon128.png
    - packages/am-ext/content.js
    - packages/am-ext/popup/popup.html
    - packages/am-ext/onboarding/onboarding.html
decisions:
  - Use a dual-key background block (`scripts` + `service_worker`) so one manifest works in Chrome and Firefox.
  - Keep all outbound HTTP in background.js and swallow failures on every fetch path.
  - Add minimal placeholder package resources so the extension can load cleanly before plans 06-02 and 06-03 fill them in.
metrics:
  completed_at: 2026-03-25T17:46:02.8093191-04:00
  duration: "~15m"
  task_count: 2
  file_count: 8
commits:
  - 817adff
  - 10fde82
---

# Phase 6 Plan 01: Browser Extension Bootstrap Summary

Bootstrap the `am-ext` browser extension package with a loadable MV3 manifest, valid toolbar icons, and a background service worker that silently relays `NEW_TURN` payloads to `POST /ingest/conversation`.

## Completed Work

### Task 1: Package scaffold + manifest + icons

- Created `packages/am-ext/` scaffold with `icons/`, `adapters/`, `popup/`, `onboarding/`, and `tests/` directories.
- Added `packages/am-ext/manifest.json` with MV3 metadata, `storage` and `alarms` permissions, localhost host permissions, dual background keys, content script registration, popup wiring, and icon wiring.
- Generated valid PNG icon assets at 16px, 48px, and 128px using a pure Node.js PNG writer.
- Added minimal placeholder `content.js`, `popup/popup.html`, and `onboarding/onboarding.html` so the extension package resolves its manifest references and can load before later plans implement those surfaces.

### Task 2: background.js

- Added top-level `chrome.alarms` keepalive registration with `periodInMinutes: 0.5`.
- Added a `chrome.runtime.onMessage` listener for `NEW_TURN` that delegates to `handle_turn(payload)` and returns `false`.
- Implemented `handle_turn(payload)` to read `endpoint`, `api_key`, `paused`, `platforms`, and `project_id` from `chrome.storage.sync`, enforce the required guards, build the required passive ingestion body, and POST it with bearer auth.
- Added an `onInstalled` handler that opens `onboarding/onboarding.html` on first install.

## Verification

Executed the plan's automated checks successfully:

```powershell
node -e "const m = JSON.parse(require('fs').readFileSync('packages/am-ext/manifest.json','utf8')); console.assert(m.manifest_version===3,'mv3'); console.assert(m.background.scripts,'firefox scripts key missing'); console.assert(m.background.service_worker,'chrome sw key missing'); console.assert(m.host_permissions.includes('http://localhost/*'),'localhost missing'); console.log('manifest OK')"
node -e "const fs=require('fs'); ['icon16','icon48','icon128'].forEach(n=>{const b=fs.readFileSync('packages/am-ext/icons/'+n+'.png'); console.assert(b[0]===0x89&&b[1]===0x50,'invalid PNG: '+n)}); console.log('icons OK')"
node -e "const src = require('fs').readFileSync('packages/am-ext/background.js','utf8'); console.assert(src.includes('periodInMinutes'),'missing alarms keepalive'); console.assert(src.includes('NEW_TURN'),'missing NEW_TURN handler'); console.assert(src.includes('ingest/conversation'),'missing fetch to ingest'); console.assert(src.includes('ingestion_mode'),'missing ingestion_mode field'); console.assert(src.includes('onInstalled'),'missing onInstalled'); console.assert(src.includes('.catch(() => {})'), 'missing silent catch'); console.log('background.js OK')"
node --check packages/am-ext/background.js
node -e "const fs=require('fs'); ['packages/am-ext/content.js','packages/am-ext/popup/popup.html','packages/am-ext/onboarding/onboarding.html'].forEach((p)=>console.assert(fs.existsSync(p), 'missing '+p)); console.log('scaffold OK')"
```

Observed results:

- `manifest OK`
- `icons OK`
- `background.js OK`
- `node --check` exited successfully
- `scaffold OK`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Critical loadability] Added minimal manifest target files**
- **Found during:** Task 1
- **Issue:** The plan required `content.js`, `popup/popup.html`, and `onboarding/onboarding.html` to be referenced immediately, but did not create them in 06-01. Leaving those files absent would make the extension package incomplete before 06-02 and 06-03 land.
- **Fix:** Added minimal placeholder versions of those files so the package can load cleanly and the install hook has a real onboarding page target.
- **Files modified:** `packages/am-ext/content.js`, `packages/am-ext/popup/popup.html`, `packages/am-ext/onboarding/onboarding.html`
- **Commit:** `817adff`

**2. [Rule 2 - Current hostname compatibility] Included the current ChatGPT hostname**
- **Found during:** Task 1
- **Issue:** The phase context still listed `chat.openai.com`, while the current product hostname is `chatgpt.com`.
- **Fix:** Included both `https://chat.openai.com/*` and `https://chatgpt.com/*` in `host_permissions` and `content_scripts.matches` to preserve backward compatibility while covering the current hostname.
- **Files modified:** `packages/am-ext/manifest.json`
- **Commit:** `817adff`

### User Constraint Overrides

- `.planning/STATE.md` and `.planning/ROADMAP.md` were intentionally left untouched because this execution was explicitly constrained to avoid orchestrator-owned tracking docs.

## Known Stubs

- `packages/am-ext/content.js:2` — placeholder content script retained only so the MV3 package loads before plan 06-02 implements DOM observation.
- `packages/am-ext/popup/popup.html:11` — placeholder popup copy retained until plan 06-03 builds the actual popup UI.
- `packages/am-ext/onboarding/onboarding.html:11` — placeholder onboarding copy retained until plan 06-03 builds the configuration form.

## Self-Check

PASSED

- Found `.planning/phases/06-am-ext/06-01-SUMMARY.md`
- Found commit `817adff`
- Found commit `10fde82`
