---
phase: 17-openclaw-hosted-beta-and-dual-mode
status: in_progress
updated: 2026-04-13T22:20:00Z
summary:
  passed: 0
  pending: 5
  blocked: 0
---

# Phase 17 UAT

## Checks

### Test 1

- name: the backend onboarding contract tells the client whether it is managed or self-hosted and which auth/provider-key model applies
- status: pending
- method: automated
- evidence:
  - `src/am_server/models.py`
  - `src/am_server/routes/health.py`

### Test 2

- name: workspace-bound hosted API keys can only act inside their allowed workspace and mismatched workspace requests fail with a stable machine-readable error
- status: pending
- method: automated
- evidence:
  - `src/am_server/auth.py`
  - `src/am_server/routes/openclaw.py`
  - `tests/test_am_server.py`
  - `tests/test_openclaw_contract.py`

### Test 3

- name: setup and doctor explicitly support hosted and self-hosted modes without misleading saved backend defaults
- status: pending
- method: automated + manual
- evidence:
  - `packages/am-openclaw/src/setup.ts`
  - `packages/am-openclaw/src/doctor.ts`
  - `packages/am-openclaw/tests/**`

### Test 4

- name: managed-beta deployment docs and self-hosted runbooks describe separate truthful paths grounded in the current GCP VM setup
- status: pending
- method: manual
- evidence:
  - `docs/openclaw/**`
  - `docs/INSTALLATION.md`
  - `docs/TROUBLESHOOTING.md`
  - `docs/SETUP_FULL_STACK.md`

### Test 5

- name: the widened hosted-beta contract does not regress the backend and plugin verification gates
- status: pending
- method: automated
- evidence:
  - `python -m pytest tests/test_am_server.py tests/test_openclaw_contract.py -q`
  - `npm run build:openclaw`
  - `npm run test:openclaw`
  - `npm run typecheck:openclaw`
