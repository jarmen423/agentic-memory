# Phase 17 Context

## Goal

Make Agentic Memory credible as a managed hosted beta product without losing
the self-hosted escape hatch that bootstrap-stage delivery still needs.

Phase 16 fixed whole-stack onboarding honesty for the current operator-managed
path. Phase 17 exists because product direction is now sharper:

- normal users should connect to a managed backend, not reason about local infra
- self-hosted should remain supported, but it is a full-stack operator path
- hosted mode needs real auth and usage boundaries, not one shared generic API key
- the backend must tell the client whether it is managed or self-hosted

## Repo Truth Locked For This Phase

- The published OpenClaw npm package is `agentic-memory-openclaw`.
- The runtime plugin id remains `agentic-memory`.
- The current production-like deployment path is documented in:
  - `docs/openclaw/DEPLOYMENT_RUNBOOK.md`
  - `docker-compose.prod.yml`
- The current plugin setup and doctor flows live in:
  - `packages/am-openclaw/src/setup.ts`
  - `packages/am-openclaw/src/doctor.ts`
- The current backend onboarding and auth seams live in:
  - `src/am_server/auth.py`
  - `src/am_server/models.py`
  - `src/am_server/routes/health.py`
  - `src/am_server/routes/openclaw.py`
- The current local control-plane store lives in:
  - `src/agentic_memory/product/state.py`

## Product Assumptions Frozen For This Phase

- Managed hosted beta uses the current GCP VM as the first real target.
- Managed beta keeps one shared backend/data stack with strict workspace scoping.
- Managed beta uses backend-owned provider keys for embeddings/reranking.
- Usage is metered now; customer-facing billing is deferred.
- Self-hosted remains a supported full-stack mode.
- Mixed mode (hosted API + customer-managed databases) stays out of scope.
- SpacetimeDB is not a required part of the hosted beta footprint.

## User Pain This Phase Must Remove

The stack still lacks a coherent answer to:

- what happens when the user is connecting to a hosted backend instead of localhost?
- how is hosted auth scoped so one workspace cannot act as another?
- how will the product meter hosted usage without forcing beta users to bring their own keys?
- how does setup distinguish saved local defaults from the current backend truth?

## Frozen Boundaries

- No public signup flow or automated customer provisioning in this phase.
- No customer-facing billing UI in this phase.
- No BYOK in hosted beta.
- No attempt to support the mixed hosted-API / customer-managed-database mode as a first-class path.
- Do not regress the Phase 16 doctor-first onboarding contract while widening it.

## Phase Deliverables

- a widened onboarding contract that exposes deployment mode, auth strategy, and provider-key ownership
- workspace-bound hosted API keys plus backend-side workspace enforcement
- metering hooks for the core OpenClaw operations in the local control-plane store
- explicit hosted vs self-hosted setup/doctor UX in the plugin
- docs/runbooks that explain managed beta vs self-hosted cleanly
