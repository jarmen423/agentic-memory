---
phase: 16-openclaw-whole-stack-onboarding
status: complete
updated: 2026-04-13T15:20:00Z
summary:
  passed: 5
  pending: 0
  blocked: 0
---

# Phase 16 UAT

## Checks

### Test 1

- name: the onboarding flow explicitly distinguishes required services, optional temporal services, and unsupported/missing dependencies before setup claims success
- status: complete
- method: automated + manual
- evidence:
  - `packages/am-openclaw/src/setup.ts`
  - `src/am_server/routes/health.py`
  - `desktop_shell/app.py`

### Test 2

- name: plugin-side doctor or preflight validation surfaces actionable failures for wrong backend targets, auth problems, and missing stack services
- status: complete
- method: automated
- evidence:
  - `packages/am-openclaw/**`
  - `tests/test_openclaw_contract.py`

### Test 3

- name: the local bootstrap path and temporal tooling no longer depend on saved `local` aliases or stale `STDB_URI` defaults that conflict with other services
- status: complete
- method: automated + manual
- evidence:
  - `packages/am-temporal-kg/**`
  - `packages/am-sync-neo4j/**`
  - `docker-compose.prod.yml`
  - `docs/SPACETIMEDB_OPERATIONS.md`

### Test 4

- name: installation, setup, troubleshooting, and whole-stack onboarding docs describe one supported path that matches the actual validated implementation
- status: complete
- method: manual
- evidence:
  - `docs/openclaw/**`
  - `docs/INSTALLATION.md`
  - `docs/TROUBLESHOOTING.md`
  - `docs/SETUP_FULL_STACK.md`

### Test 5

- name: onboarding changes do not regress the backend, plugin, dashboard, temporal package, or release validation gates
- status: complete
- method: automated
- evidence:
  - `python -m pytest tests/test_am_server.py tests/test_openclaw_contract.py desktop_shell/tests/test_app.py -q`
  - `npm run build`
  - `npm run typecheck`
  - `npm run build:openclaw`
  - `npm run test:openclaw`
  - `npm run typecheck:openclaw`
  - `npm run build --workspace am-dashboard`
  - `npm run test --workspace am-dashboard`
  - `npm run typecheck --workspace am-dashboard`
  - `npm run build --workspace am-temporal-kg`
  - `npm run typecheck --workspace am-temporal-kg`
  - `npm run build --workspace am-sync-neo4j`
  - `npm run typecheck --workspace am-sync-neo4j`
  - `npm run pack:openclaw`
  - `npm run validate:release-artifacts`
