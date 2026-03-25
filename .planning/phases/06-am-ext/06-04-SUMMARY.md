---
phase: 06-am-ext
plan: 04
subsystem: testing
tags: [node:test, browser-extension, chrome, firefox, docs]
requires:
  - phase: 06-01
    provides: "Manifest, background worker, and content script scaffold for am-ext"
  - phase: 06-02
    provides: "BaseAdapter utility behavior and platform selector contracts"
  - phase: 06-03
    provides: "Popup and onboarding UI flows referenced by the docs and checklist"
provides:
  - "Self-contained node:test coverage for session ID extraction, debounce timing, and selector lookup helpers"
  - "Manual acceptance checklist for install, onboarding, capture, pause, server downtime, hotpatch, and SPA navigation"
  - "Developer README for loading, configuring, and understanding am-ext"
affects: [06-am-ext, verification, onboarding, browser-capture]
tech-stack:
  added: []
  patterns: ["DOM-independent utility coverage via node:test", "Docs assertions verified with Node file reads"]
key-files:
  created:
    - packages/am-ext/tests/utils.test.js
    - packages/am-ext/TESTING.md
    - packages/am-ext/README.md
  modified:
    - .planning/phases/06-am-ext/06-04-SUMMARY.md
key-decisions:
  - "Kept the utility coverage self-contained instead of importing browser-global adapter code into Node tests."
  - "Documented the verified glob-based node --test command because a directory target failed on the current Node/Windows environment."
patterns-established:
  - "Mirror pure MV3 helper logic into node:test files when direct imports depend on browser globals."
  - "Pair extension docs with both automated Node assertions and browser-only acceptance steps."
requirements-completed: [EXT-09, EXT-10]
duration: 6min
completed: 2026-03-25
---

# Phase 6 Plan 04: am-ext Summary

**Node-based coverage for BaseAdapter utility behavior with verified am-ext install and acceptance documentation**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-25T22:06:30Z
- **Completed:** 2026-03-25T22:12:50Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added a self-contained `node:test` suite covering all four session ID URL patterns, fallback behavior, 800ms debounce timing, and comma-separated selector lookup.
- Wrote `TESTING.md` with the eight manual acceptance sections required to verify the browser-dependent Phase 6 flows.
- Wrote `README.md` covering load-unpacked installation, onboarding/configuration, platform support, selector hotpatching, testing, and architecture.

## Task Commits

1. **Task 1: Unit tests — session ID extraction, debounce, _queryFirst** - `65df2d6` (test, RED), `a07dd98` (test, GREEN)
2. **Task 2: TESTING.md manual checklist + README.md** - `8c13adb` (chore)

## Files Created/Modified

- `packages/am-ext/tests/utils.test.js` - Pure utility coverage for session ID extraction, debounce timing, and selector lookup.
- `packages/am-ext/TESTING.md` - Manual acceptance checklist for install, onboarding, capture, pause, downtime, hotpatch, and SPA navigation.
- `packages/am-ext/README.md` - Development install guide, configuration reference, platform table, testing notes, and relay architecture summary.
- `.planning/phases/06-am-ext/06-04-SUMMARY.md` - Execution summary for plan 06-04.

## Decisions Made

- Kept the unit tests independent from `adapters/base.js` imports because the shipped adapter file depends on browser globals and is not directly runnable under Node without additional harness code.
- Used a minimal document mock for selector coverage so the test file stays dependency-free and does not require jsdom.
- Updated the README to the verified `node --test packages/am-ext/tests/*.test.js` form because the planned directory target failed on this environment.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected the README test invocation**
- **Found during:** Task 2 (TESTING.md manual checklist + README.md)
- **Issue:** `node --test packages/am-ext/tests/` failed on the current Node 25 / Windows setup because the directory target was treated as a module path instead of a runnable test set.
- **Fix:** Updated the README to use `node --test packages/am-ext/tests/*.test.js`, then re-ran the package test command successfully.
- **Files modified:** `packages/am-ext/README.md`
- **Verification:** `node --test packages/am-ext/tests/*.test.js`
- **Committed in:** `8c13adb`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The fix kept the documentation accurate without changing the extension implementation or test coverage scope.

## Issues Encountered

- The planned directory-based `node --test` invocation was not portable to this environment; the verified glob form resolved it cleanly.

## User Setup Required

None - no external service configuration required beyond the existing am-server endpoint and API key already described in the package docs.

## Next Phase Readiness

- `packages/am-ext/` now has both automated utility coverage and manual acceptance guidance.
- Shared tracking docs were intentionally left untouched in this workspace because this execution was constrained to owned files only.

## Self-Check: PASSED

- Found `.planning/phases/06-am-ext/06-04-SUMMARY.md`.
- Verified task commits `65df2d6`, `a07dd98`, and `8c13adb` exist in git history.
