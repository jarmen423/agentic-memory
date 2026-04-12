# Phase 14 Context

## Goal

Make OpenClaw ready for controlled beta rollout by closing the gap between
internal functionality and distributable, operationally supportable delivery.

## Repo Truth Locked For This Phase

- Phase 12 delivered the backend foundation: multi-key auth, normalized error
  envelopes, authenticated metrics, SQLite-backed product state, OpenClaw
  contract tests, and minimal TypeScript CI.
- Phase 13 delivered the dashboard, desktop shell replacement, and E2E/load/
  chaos harnesses.
- `packages/am-openclaw/package.json` is still marked `private: true`, which
  blocks an actual distribution-ready packaging pass.
- The GTM reference plan still calls for a scaling and packaging wave before
  docs, private beta, public beta, and GA.
- The current local worktree already contains uncommitted MCP surface changes in
  `src/am_server/app.py`, `src/am_server/auth.py`, and
  `tests/test_am_server.py`. Phase 14 backend work must merge with those
  changes instead of assuming a clean pre-refactor baseline.

## Frozen Boundaries

- Marketplace submission, hosted multi-tenant auth, public internet rate
  limiting, final GTM collateral, and GA readiness stay out of scope for this
  phase.
- Do not reopen dashboard product design or desktop shell implementation except
  where packaging or release validation needs existing artifacts to build.
- Do not resume Phase 10 manual verification or Phase 11 code-graph hardening
  inside this wave.

## Phase Deliverables

- backend scale-path hardening for OpenClaw request flow, MCP surface exposure,
  and observability
- `packages/am-openclaw/` package metadata, docs, and artifact checks suitable
  for controlled distribution
- production deployment artifacts such as `docker-compose.prod.yml`, release
  workflow scaffolding, and ops-facing setup/runbook documentation
- CI and merge gates that validate backend regressions, plugin packaging, and
  deployment configuration together
