---
phase: 06-am-ext
plan: 02
subsystem: am-ext
tags:
  - browser-extension
  - dom-observation
  - selectors
  - manifest-v3
requires:
  - phase: 06-01
    provides: MV3 extension scaffold, background worker, and placeholder content script
provides:
  - BaseAdapter DOM capture contract with debounced mutation observation
  - ChatGPT, Claude, Gemini, and Perplexity adapter extraction logic
  - Bundled and server-served selector payloads for hotpatching
  - Content-script platform routing with remote selector fallback and SPA restart handling
affects:
  - 06-am-ext
  - am-server selectors hotpatch endpoint
tech-stack:
  added: []
  patterns:
    - Manifest-ordered classic content scripts exposing adapter classes via globalThis
    - 800ms debounced DOM diff capture with per-session turn indexing
    - Remote selector override with bundled fallback for brittle platform DOMs
key-files:
  created:
    - packages/am-ext/adapters/base.js
    - packages/am-ext/adapters/chatgpt.js
    - packages/am-ext/adapters/claude.js
    - packages/am-ext/adapters/gemini.js
    - packages/am-ext/adapters/perplexity.js
    - packages/am-ext/selectors.json
  modified:
    - packages/am-ext/content.js
    - packages/am-ext/manifest.json
    - src/am_server/data/selectors.json
key-decisions:
  - Expose adapter classes on globalThis so MV3 content scripts can stay buildless while still loading in manifest order before content.js.
  - Duplicate the selector payload into both the extension bundle and am-server data so the hotpatch endpoint can override selectors without an extension release.
  - Preserve the Phase 06-01 ChatGPT hostname compatibility fix by supporting both chat.openai.com and chatgpt.com in platform detection and selector metadata.
patterns-established:
  - "Platform adapters own DOM extraction; content.js owns routing, remote config, and SPA restart behavior."
  - "Selector config is identical between extension and server to keep hotpatch behavior deterministic."
requirements-completed:
  - EXT-03
  - EXT-04
  - EXT-05
duration: 4m
completed: 2026-03-25
---

# Phase 6 Plan 02: DOM Observation Layer Summary

**Cross-platform DOM capture for ChatGPT, Claude, Gemini, and Perplexity with manifest-ordered adapters, remote selector hotpatch fallback, and SPA-safe session resets**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-25T21:53:11Z
- **Completed:** 2026-03-25T21:57:16Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- Implemented `BaseAdapter` with the required debounce, diffing, session extraction, and silent message handoff contract.
- Added platform-specific extraction for ChatGPT, Claude, Gemini custom elements, and Perplexity substring-class selectors.
- Wired `content.js` to choose the correct adapter, fetch `/ext/selectors.json` with bundled fallback, and restart cleanly on SPA navigation with the required 200ms delay.

## Task Commits

1. **Task 1: BaseAdapter + four platform adapters + selectors.json** - `975959b` (`feat`)
2. **Task 2: content.js platform router, remote selector fetch, SPA navigation** - `ff4a932` (`feat`)

## Files Created/Modified

- `packages/am-ext/adapters/base.js` - Shared DOM capture contract used by all platform adapters.
- `packages/am-ext/adapters/chatgpt.js` - ChatGPT turn extraction using verified author-role selectors.
- `packages/am-ext/adapters/claude.js` - Claude turn extraction using `data-testid` and class fallback selectors.
- `packages/am-ext/adapters/gemini.js` - Gemini custom-element extraction for `user-query` and `model-response`.
- `packages/am-ext/adapters/perplexity.js` - Perplexity turn extraction using low-confidence substring class selectors.
- `packages/am-ext/selectors.json` - Bundled selector payload shipped with the extension.
- `src/am_server/data/selectors.json` - Server-side selector payload used by `GET /ext/selectors.json`.
- `packages/am-ext/content.js` - Platform detection, remote selector fallback, adapter startup, and SPA reset logic.
- `packages/am-ext/manifest.json` - Ordered content script loading so adapters exist before content bootstrap.

## Decisions Made

- Used global classic-script classes instead of dynamic imports because MV3 content scripts need buildless, manifest-declared execution.
- Kept selector payloads byte-for-byte aligned between the extension and server copies so hotpatches cannot drift from bundled defaults.
- Retained both ChatGPT hostnames in runtime detection because the current product hostname differs from older plan context and dropping either would break capture coverage.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Preserved current ChatGPT hostname compatibility**
- **Found during:** Task 1 and Task 2
- **Issue:** Plan context still mapped ChatGPT to `chat.openai.com` only, but Phase 06-01 had already expanded manifest coverage to `chatgpt.com`. Restricting selectors and routing back to the legacy hostname would have broken capture on the current site.
- **Fix:** Added `chatgpt.com` alongside `chat.openai.com` in selector metadata and runtime platform detection while keeping the legacy hostname supported.
- **Files modified:** `packages/am-ext/selectors.json`, `src/am_server/data/selectors.json`, `packages/am-ext/content.js`
- **Verification:** Phase 06-02 node assertions passed; manifest ordering remained valid and the runtime detection now matches both supported ChatGPT hosts.
- **Committed in:** `975959b`, `ff4a932`

---

**Total deviations:** 1 auto-fixed (1 Rule 2)
**Impact on plan:** The adjustment preserved correctness without expanding scope. All planned behaviors still landed exactly as specified.

## Issues Encountered

None.

## User Setup Required

None.

## Next Phase Readiness

- Popup and onboarding work in 06-03 can rely on a real content capture layer instead of the 06-01 placeholder.
- The am-server selector hotpatch endpoint is now populated with live platform data and ready for runtime overrides.
- `.planning/STATE.md` and `.planning/ROADMAP.md` were intentionally left untouched because this execution was explicitly constrained to avoid shared tracking docs.

## Self-Check

PASSED

- Found `.planning/phases/06-am-ext/06-02-SUMMARY.md`
- Found commit `975959b`
- Found commit `ff4a932`

---
*Phase: 06-am-ext*
*Completed: 2026-03-25*
