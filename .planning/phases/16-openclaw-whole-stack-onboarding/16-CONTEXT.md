# Phase 16 Context

## Goal

Make the OpenClaw stack genuinely onboardable as a whole system instead of
merely documented as private-beta-ready.

This phase exists because real dogfooding exposed a gap between the current
repo state and the intended user experience:

- plugin setup can persist config without proving the stack is actually usable
- local stack docs still leak operator-only assumptions about ports, aliases,
  and temporal wiring
- temporal scripts and docs still assume `STDB_URI=http://127.0.0.1:3000` or a
  working saved `local` alias even when other services legitimately own that port

## Repo Truth Locked For This Phase

- Phase 15 completed docs, OpenAPI, marketplace prep, and beta runbooks.
- The OpenClaw npm package identity is locked to `agentic-memory-openclaw`.
- The runtime OpenClaw plugin id remains `agentic-memory`.
- The current deployment path is still operator-managed:
  - `docs/openclaw/DEPLOYMENT_RUNBOOK.md`
  - `docker-compose.prod.yml`
- The current plugin setup path lives in:
  - `packages/am-openclaw/src/setup.ts`
- Temporal local-stack pain points are repo-grounded in:
  - `packages/am-temporal-kg/package.json`
  - `packages/am-temporal-kg/README.md`
  - `packages/am-temporal-kg/scripts/query_temporal.ts`
  - `docs/SPACETIMEDB_OPERATIONS.md`
  - `docs/SETUP_FULL_STACK.md`

## User Pain That Triggered This Phase

The current stack still allows or requires:

- saved SpacetimeDB aliases that silently point at the wrong service
- hardcoded or stale local port defaults
- separate reasoning about Grafana, SpacetimeDB, Neo4j, and backend health
- manual inference about which services are required vs optional
- a setup command that can look complete before the backing services are verified

That is not a credible private-beta onboarding experience.

## Frozen Boundaries

- Public beta rollout, GA launch, multi-tenant hosted auth, SSO, and enterprise
  packaging stay out of scope for this phase.
- Do not reopen GTM collateral or marketplace copy except where onboarding docs
  must be corrected to reflect the supported path.
- Do not treat SpacetimeDB as the only issue. The phase is about the whole local
  stack and the truthfulness of the default onboarding path.

## Phase Deliverables

- a locked onboarding contract for required vs optional services plus how setup,
  doctor, and shell bootstrap should report readiness
- plugin-side doctor/preflight UX that validates the backend path before
  declaring success
- local stack/bootstrap cleanup that removes hidden reliance on saved temporal
  aliases and stale port assumptions
- rewritten install and troubleshooting docs that match the supported path
- execution truth updated so the completed Phase 15 wave remains archived and
  resumable while Phase 16 becomes the active track
