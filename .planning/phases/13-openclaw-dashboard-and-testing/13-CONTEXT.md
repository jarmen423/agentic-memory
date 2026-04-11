# Phase 13 Context

## Goal

Replace the placeholder desktop shell with a real dashboard and deepen OpenClaw
verification with contract-visible backend read APIs plus E2E, load, and chaos
harnesses.

## Repo Truth Locked For This Phase

- Phase 12 already hardened auth, error envelopes, `/metrics`, SQLite-backed
  product state, OpenClaw contract tests, and minimal TypeScript CI.
- The desktop shell is still the static placeholder under `desktop_shell/static/`.
- There is no `packages/am-dashboard/` workspace yet.
- `src/am_server/routes/` does not yet expose a dashboard-focused read surface
  for summary metrics, agent sessions, detailed health, recent searches, or
  workspace topology.
- OpenClaw does not yet have dedicated E2E, load, or chaos harnesses in
  `tests/e2e/`, `tests/load/`, or `tests/chaos/`.

## Frozen Boundaries

- Keep packaging, npm publish metadata, marketplace submission, Docker release
  work, and GTM collateral out of scope for this phase.
- Do not reopen the Phase 12 foundation contract except where dashboard read
  APIs must consume the already-shipped OpenClaw surfaces.
- Do not resume Phase 10 manual verification or Phase 11 code-graph hardening
  inside this wave.

## Phase Deliverables

- `packages/am-dashboard/` workspace with build/test/typecheck support
- desktop shell serving the built dashboard instead of the placeholder static UI
- authenticated dashboard read APIs for overview, health, search quality, agent
  activity, and workspace topology
- desktop shell proxy routes aligned to the backend dashboard contract
- E2E, load, and chaos harnesses for OpenClaw lifecycle verification
- CI gates for dashboard build/test/typecheck plus the new operational harnesses
