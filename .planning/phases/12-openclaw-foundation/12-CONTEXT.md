# Phase 12 Context

## Goal

Stabilize the existing OpenClaw integration without widening scope into dashboard,
packaging, marketplace, or hosted multi-tenant work.

## Repo Truth Locked For This Phase

- The OpenClaw plugin already exists at `packages/am-openclaw/`.
- The backend already exposes `/openclaw/*` routes from `src/am_server/routes/openclaw.py`.
- The current backend auth path is single-key only in `src/am_server/auth.py`.
- Local product state is still stored as a single JSON document in `src/agentic_memory/product/state.py`.
- CI in `.github/workflows/ci.yml` is Python-only and still targets stale coverage package names.
- `desktop_shell/static/**` exists but is explicitly out of scope for this phase.

## Frozen Boundaries

- Keep the current `/openclaw/*` route set.
- Do not add dashboard APIs or `packages/am-dashboard`.
- Do not change the OpenClaw setup config schema.
- Do not resume Phase 10 or Phase 11 work inside this wave.

## Phase Deliverables

- multi-key backend auth with backward compatibility
- machine-readable error envelope with request id
- authenticated `/metrics`
- SQLite-backed product-state persistence behind the same `ProductStateStore` API
- plugin transport retries and package-local tests
- OpenClaw contract tests and minimal TypeScript CI gates
