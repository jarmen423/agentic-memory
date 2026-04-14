# OpenClaw Private Beta Docs

This directory is the operator-facing documentation bundle for the current
OpenClaw private beta.

Use this index when you need to answer one of these questions quickly:

- how do I install and configure the OpenClaw plugin?
- how do I deploy the Agentic Memory backend that the plugin talks to?
- where is the committed API contract for the OpenClaw beta surface?
- how do we onboard, support, and track the first design partners?

## Locked Product Identity

- npm package name: `agentic-memory-openclaw`
- install command: `openclaw plugin install agentic-memory-openclaw`
- runtime OpenClaw plugin id: `agentic-memory`
- doctor command: `openclaw agentic-memory doctor`
- setup command: `openclaw agentic-memory setup`

The npm artifact is the OpenClaw plugin package. Operators still provision or
connect to a separate Agentic Memory backend.

Important host-version note:

- some OpenClaw hosts expose `openclaw plugins install ...`
- others expose `openclaw plugin install ...`

This docs bundle uses the singular form because that is the locked contract we
are targeting, but beta operators should verify the host-specific command shape
if install output differs.

## Recommended Reading Order

1. `docs/openclaw/guides/PRIVATE_BETA_QUICKSTART.md`
   - shortest supported path from install to doctor, setup, and first validation
2. `docs/openclaw/DEPLOYMENT_RUNBOOK.md`
   - backend deployment, health checks, and rollback steps
3. `docs/openclaw/openapi/README.md`
   - committed REST contract for the OpenClaw beta routes
4. `docs/openclaw/beta/README.md`
   - onboarding and partner-operations docs for the first design partners
5. `docs/openclaw/support/README.md`
   - support runbooks for the most likely beta failures
6. `docs/openclaw/marketplace/PUBLISHING_CHECKLIST.md`
   - listing and publish prerequisites for the plugin package

## Directory Map

### `docs/openclaw/guides/`

- `PRIVATE_BETA_QUICKSTART.md`
  - install, setup, verification, and rollback for beta operators

### `docs/openclaw/openapi/`

- `README.md`
  - explains the OpenClaw-filtered API artifact
- `agentic-memory-openclaw.openapi.json`
  - committed OpenAPI export for `/health`, `/metrics`, and `/openclaw/*`

### `docs/openclaw/beta/`

- `README.md`
  - overview of the private beta program
- `ONBOARDING_RUNBOOK.md`
  - intake, provisioning, install, and first-session checklist
- `PARTNER_OPERATIONS.md`
  - design-partner tracking, cadence, and success criteria

### `docs/openclaw/support/`

- `README.md`
  - support index
- `SUPPORT_RUNBOOK.md`
  - triage routing for the top beta failure modes
- `RB-001_PROVISION_ENVIRONMENT.md`
- `RB-002_ROTATE_API_KEYS.md`
- `RB-003_NEO4J_BACKUP_RESTORE.md`
- `RB-004_CAPACITY_AND_BACKLOG.md`
- `RB-005_API_ERRORS_AND_EMPTY_RESULTS.md`
- `RB-006_EMBEDDING_PROVIDER_OUTAGE.md`

### `docs/openclaw/marketplace/`

- `OPENCLAW_PLUGIN_LISTING.md`
  - listing copy draft for the plugin package
- `PUBLISHING_CHECKLIST.md`
  - publish-time readiness checklist

## Current Beta Boundaries

This doc set assumes:

- managed hosted beta or self-hosted backend deployment
- authenticated `/metrics` and `/openclaw/*` routes already exist
- the plugin package is ready for controlled beta distribution
- the runtime plugin id remains stable as `agentic-memory`
- setup should validate `/health/onboarding` before it claims success

This doc set does not claim:

- hosted multi-tenant control plane
- public beta or GA rollout
- marketplace approval already completed
- one-click local backend provisioning from the plugin package alone
