# Phase 15 Context

## Goal

Make OpenClaw ready for a controlled private beta by finishing the parts of the
GTM plan that sit on top of the completed engineering foundation:

- final install/setup docs
- committed OpenAPI output
- marketplace/publish preparation
- partner onboarding and support runbooks

## Repo Truth Locked For This Phase

- Phase 12 delivered the OpenClaw backend foundation.
- Phase 13 delivered the dashboard plus E2E/load/chaos coverage.
- Phase 14 delivered scaling/package/deployment work:
  - backend observability and scale-path hardening
  - distribution-ready `packages/am-openclaw` artifacts
  - `docker-compose.prod.yml`
  - `.github/workflows/release.yml`
  - `docs/openclaw/` deployment/runbook scaffolding
- The execution registry for `w14-openclaw-scaling-and-packaging` is complete
  and archived.
- The remaining package-name decision is now a documentation, marketplace, and
  publish-surface blocker rather than an engineering-foundation blocker.

## Frozen Boundaries

- Public beta, GA launch, hosted multi-tenant auth, SSO, and enterprise
  packaging stay out of scope for this phase.
- Do not reopen Phase 14 backend scale-path work unless a docs/private-beta task
  reveals a concrete contract gap.
- Do not resume Phase 10 manual verification or Phase 11 code-graph work inside
  this wave.

## Phase Deliverables

- user-facing install, setup, troubleshooting, and rollback docs aligned to the
  actual OpenClaw plugin install flow
- committed OpenAPI artifact for the OpenClaw backend surface
- package identity decision plus marketplace/listing preparation artifacts
- private-beta onboarding, support, and partner-operations runbooks for the
  first 5 design partners
- planning and execution truth updated so the completed Phase 14 wave remains
  resumable from archive while Phase 15 becomes the active track
