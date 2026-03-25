---
phase: 06-am-ext
plan: 03
subsystem: am-ext
tags:
  - browser-extension
  - popup
  - onboarding
  - chrome-storage
requires:
  - 06-01 extension scaffold and background worker
provides:
  - popup status surface for active platform, capture state, and paused toggle
  - onboarding flow for endpoint, api key, project id, and per-platform settings
affects:
  - packages/am-ext/popup
  - packages/am-ext/onboarding
tech_stack:
  - Manifest V3
  - Chrome extension APIs
  - Vanilla JavaScript
  - HTML/CSS
key_files:
  modified:
    - packages/am-ext/popup/popup.html
    - packages/am-ext/popup/popup.js
    - packages/am-ext/popup/popup.css
    - packages/am-ext/onboarding/onboarding.html
    - packages/am-ext/onboarding/onboarding.js
    - packages/am-ext/onboarding/onboarding.css
decisions:
  - Use active-tab hostname detection in the popup so supported pages resolve locally and unsupported pages degrade cleanly to a neutral state.
  - Keep onboarding writes schema-aligned with background.js, including project_id, paused=false, and per-platform booleans.
  - Treat tab session metadata as best-effort because GET_STATUS is not guaranteed to exist yet; the popup leaves session/turn values as -- when no response arrives.
metrics:
  completed_at: 2026-03-25T17:59:07.8500625-04:00
  duration: "~40m"
  task_count: 2
  file_count: 6
commits:
  - ff6889a
  - df19451
requirements-completed:
  - EXT-07
  - EXT-08
---

# Phase 6 Plan 03: Popup and Onboarding Summary

**Toolbar popup exposes live capture status and pause control while onboarding saves extension config and validates the am-server health endpoint.**

## Completed Work

### Task 1: Popup UI

- Replaced the placeholder popup with a full extension surface showing platform, status badge, session id, and turn count.
- Added `popup.js` to query the active tab, detect supported hostnames, read `chrome.storage.sync`, and compute the required `Capturing` / `Paused` / `Not configured` states.
- Wired the pause button to toggle `paused` immediately in `chrome.storage.sync` and update the badge text without reloading the popup.
- Added a Settings link that opens `onboarding/onboarding.html` in a new extension tab.
- Kept session id and turn count best-effort via `chrome.tabs.sendMessage({ type: "GET_STATUS" })`; when no handler responds, the popup keeps `--` as planned.

### Task 2: Onboarding Page

- Replaced the placeholder onboarding page with a full configuration form for endpoint, API key, project id, and the four supported platform toggles.
- Added `onboarding.js` to prefill existing settings from `chrome.storage.sync`, preserving sensible defaults on first load.
- Implemented the Test Connection flow against `GET /health` with `AbortSignal.timeout(5000)` and green/red status feedback.
- Implemented Save to write the full config schema expected by `background.js`, including `project_id`, `paused: false`, and the `platforms` object.
- Added transient saved-state feedback and responsive styling for the onboarding experience.

## Verification

Executed the plan's automated checks successfully:

```powershell
node -e "const fs = require('fs'); const popup_html = fs.readFileSync('packages/am-ext/popup/popup.html','utf8'); const popup_js = fs.readFileSync('packages/am-ext/popup/popup.js','utf8'); console.assert(popup_html.includes('pause-btn'), 'missing pause button id'); console.assert(popup_html.includes('popup.js'), 'popup.html must load popup.js'); console.assert(popup_js.includes('chrome.storage.sync'), 'missing storage read'); console.assert(popup_js.includes('paused'), 'missing paused state handling'); console.assert(popup_js.includes('Not configured'), 'missing not-configured status'); console.assert(popup_js.includes('Capturing'), 'missing capturing status'); console.assert(popup_js.includes('chrome.tabs.query'), 'missing tab query'); console.assert(fs.existsSync('packages/am-ext/popup/popup.css'), 'missing popup.css'); const onboarding_html = fs.readFileSync('packages/am-ext/onboarding/onboarding.html','utf8'); const onboarding_js = fs.readFileSync('packages/am-ext/onboarding/onboarding.js','utf8'); console.assert(onboarding_html.includes('test-btn'), 'missing test button'); console.assert(onboarding_html.includes('save-btn'), 'missing save button'); console.assert(onboarding_html.includes('cb-chatgpt'), 'missing chatgpt checkbox'); console.assert(onboarding_html.includes('cb-claude'), 'missing claude checkbox'); console.assert(onboarding_html.includes('cb-gemini'), 'missing gemini checkbox'); console.assert(onboarding_html.includes('cb-perplexity'), 'missing perplexity checkbox'); console.assert(onboarding_html.includes('api-key'), 'missing api-key field'); console.assert(onboarding_js.includes('/health'), 'missing health check fetch'); console.assert(onboarding_js.includes('chrome.storage.sync.set'), 'missing storage save'); console.assert(onboarding_js.includes('project_id'), 'missing project_id in saved config'); console.assert(onboarding_js.includes('platforms'), 'missing platforms in saved config'); console.assert(onboarding_js.includes('AbortSignal'), 'missing timeout on health check'); console.assert(fs.existsSync('packages/am-ext/onboarding/onboarding.css'), 'missing css'); console.log('Phase 06-03 checks passed');"
node --check packages/am-ext/popup/popup.js
node --check packages/am-ext/onboarding/onboarding.js
```

Observed results:

- `Phase 06-03 checks passed`
- `node --check packages/am-ext/popup/popup.js` exited successfully
- `node --check packages/am-ext/onboarding/onboarding.js` exited successfully

## Task Commits

- `ff6889a` - `feat(06-am-ext-03): build popup status surface`
- `df19451` - `feat(06-am-ext-03): build onboarding configuration flow`

## Files Modified

- `packages/am-ext/popup/popup.html` - popup structure and extension surface
- `packages/am-ext/popup/popup.js` - popup state, platform detection, and pause/settings behavior
- `packages/am-ext/popup/popup.css` - popup styling and status badge/button states
- `packages/am-ext/onboarding/onboarding.html` - onboarding form markup and platform toggles
- `packages/am-ext/onboarding/onboarding.js` - storage prefill/save logic and `/health` connection test
- `packages/am-ext/onboarding/onboarding.css` - onboarding layout, form, and feedback styling

## Decisions Made

- Use the popup as a passive status surface only; no background fetches or extra permissions were added there.
- Normalize endpoints before testing/saving so `/health` and ingest URLs do not accumulate trailing slashes.
- Preserve the planned best-effort `GET_STATUS` behavior instead of inventing a new content-script contract inside this plan.

## Deviations from Plan

None - plan executed exactly as written.

## User Constraint Overrides

- `.planning/STATE.md` and `.planning/ROADMAP.md` were intentionally left untouched because this execution was explicitly constrained to avoid shared tracking docs.
- No adapter or content-script files were modified; work stayed within the popup/onboarding ownership boundary.

## Known Stubs

None in the files owned by this plan.

## Next Phase Readiness

- Popup and onboarding surfaces are ready for extension loading and manual browser verification.
- Session id and turn count will populate automatically once the content-script side exposes `GET_STATUS`; until then the popup safely shows `--`.

## Self-Check

PASSED

- Found `.planning/phases/06-am-ext/06-03-SUMMARY.md`
- Found commit `ff6889a`
- Found commit `df19451`
