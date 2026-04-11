---
phase: 13-openclaw-dashboard-and-testing
status: active
updated: 2026-04-11T20:50:00Z
summary:
  passed: 0
  pending: 5
  blocked: 0
---

# Phase 13 UAT

## Checks

### Test 1

- name: dashboard backend read APIs expose stable authenticated responses for overview, health, sessions, search quality, and workspaces
- status: pending
- method: automated
- evidence:
  - `src/am_server/routes/dashboard.py`
  - `tests/test_am_server.py`
  - `tests/test_openclaw_contract.py`

### Test 2

- name: the desktop shell serves the built `am-dashboard` SPA instead of the placeholder static bundle
- status: pending
- method: automated
- evidence:
  - `packages/am-dashboard/`
  - `desktop_shell/app.py`
  - `desktop_shell/tests/test_app.py`

### Test 3

- name: dashboard pages render real backend-backed data for overview, agents, memory health, search quality, and workspace views
- status: pending
- method: automated
- evidence:
  - `packages/am-dashboard/`
  - `desktop_shell/tests/test_app.py`

### Test 4

- name: OpenClaw E2E, load, and chaos harnesses cover the full lifecycle without corrupting state
- status: pending
- method: automated
- evidence:
  - `tests/e2e/test_openclaw_e2e.py`
  - `tests/load/test_openclaw_load.py`
  - `tests/chaos/test_openclaw_chaos.py`

### Test 5

- name: dashboard and operational verification merge gates pass together in CI
- status: pending
- method: automated
- evidence:
  - `python -m pytest tests/test_am_server.py tests/test_openclaw_contract.py desktop_shell/tests/test_app.py -q`
  - `python -m pytest tests/e2e/test_openclaw_e2e.py tests/load/test_openclaw_load.py tests/chaos/test_openclaw_chaos.py -q`
  - `npm run build --workspace am-dashboard`
  - `npm run test --workspace am-dashboard`
  - `npm run typecheck --workspace am-dashboard`
