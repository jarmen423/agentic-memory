---
phase: 15-openclaw-docs-and-private-beta
status: active
updated: 2026-04-12T16:20:00Z
summary:
  passed: 0
  pending: 5
  blocked: 0
---

# Phase 15 UAT

## Checks

### Test 1

- name: user-facing install, setup, troubleshooting, and rollback docs match the actual OpenClaw plugin install and backend deployment flow
- status: pending
- method: manual + automated
- evidence:
  - `docs/openclaw/guides/`
  - `docs/INSTALLATION.md`
  - `docs/TROUBLESHOOTING.md`
  - `packages/am-openclaw/README.md`

### Test 2

- name: a committed OpenAPI artifact exists for the OpenClaw backend surface and stays aligned with the FastAPI app contract
- status: pending
- method: automated
- evidence:
  - `docs/openclaw/openapi/`
  - `src/am_server/app.py`
  - `python -c "from am_server.app import create_app; spec = create_app().openapi(); assert '/openclaw/memory/search' in spec['paths']; print('openapi ok')"`

### Test 3

- name: package identity, install command, and marketplace/publish metadata are finalized enough for private-beta distribution
- status: pending
- method: manual + automated
- evidence:
  - `packages/am-openclaw/package.json`
  - `.github/workflows/release.yml`
  - `docs/openclaw/marketplace/`
  - `npm run pack:openclaw`

### Test 4

- name: private-beta onboarding, support, and partner-operations runbooks are sufficient to onboard the first five design partners without inventing missing operator steps
- status: pending
- method: manual
- evidence:
  - `docs/openclaw/beta/`
  - `docs/openclaw/support/`

### Test 5

- name: docs/private-beta work does not regress the existing backend, dashboard, package, and deployment gates
- status: pending
- method: automated
- evidence:
  - `python -m pytest tests/test_am_server.py tests/test_openclaw_contract.py desktop_shell/tests/test_app.py -q`
  - `python -m pytest tests/e2e/test_openclaw_e2e.py tests/load/test_openclaw_load.py tests/chaos/test_openclaw_chaos.py -q`
  - `npm run build`
  - `npm run typecheck`
  - `npm run build:openclaw`
  - `npm run test:openclaw`
  - `npm run typecheck:openclaw`
  - `npm run build --workspace am-dashboard`
  - `npm run test --workspace am-dashboard`
  - `npm run typecheck --workspace am-dashboard`
  - `npm run pack:openclaw`
  - `npm run validate:release-artifacts`
