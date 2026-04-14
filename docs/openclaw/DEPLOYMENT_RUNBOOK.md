# OpenClaw Deployment Runbook

This runbook explains how to stand up the Agentic Memory backend that the
OpenClaw plugin uses during the controlled beta phase.

Phase 17 introduces two explicit modes:

- managed hosted beta
  - this runbook's primary path
  - the current GCP VM is the first real target
- self-hosted full stack
  - still supported, but covered by `D:\code\agentic-memory\docs\SETUP_FULL_STACK.md`

The managed deployment shape in this phase is intentionally simple:

- one `am-server` instance
- one Neo4j instance
- one shared hosted data plane with strict workspace scoping
- optional hosted-MCP keys
- optional temporal bridge configuration

This is a bootstrap-stage managed beta scaffold, not a hosted multi-tenant GA architecture.

## What This Stack Serves

The OpenClaw plugin talks to `am-server` over the `/openclaw/*` routes that
were built in Phases 12 and 13.

That backend handles:

- session registration
- memory search
- turn ingest
- context resolution
- per-session project activation/deactivation
- authenticated health and metrics

## Files Used In This Runbook

- `D:\code\agentic-memory\docker-compose.prod.yml`
- `D:\code\agentic-memory\.github\workflows\release.yml`

## Prerequisites

- Docker with Compose support
- a checked-out repo revision you intend to run for beta
- at least one valid embedding/extraction provider configuration
- a real operator/admin `AM_SERVER_API_KEYS` value
- an explicit deployment mode env value for the hosted backend

## 1. Create A Production Environment File

Create a local file such as `.env.production` next to the repo checkout.

Minimum example:

```dotenv
NEO4J_USER=neo4j
NEO4J_PASSWORD=replace-with-real-password

AM_SERVER_API_KEYS=replace-with-real-rest-key
AGENTIC_MEMORY_DEPLOYMENT_MODE=managed
AGENTIC_MEMORY_HOSTED_BASE_URL=https://your-managed-hostname.example.com

# Use at least one provider path that matches the workloads you want.
GOOGLE_API_KEY=replace-with-real-key
# OPENAI_API_KEY=
# GEMINI_API_KEY=

# Optional hosted-MCP surface keys
AM_SERVER_PUBLIC_MCP_API_KEYS=
AM_SERVER_INTERNAL_MCP_API_KEYS=

# Optional temporal bridge wiring
STDB_URI=
STDB_MODULE_NAME=agentic-memory-temporal
STDB_BINDINGS_MODULE=

# Optional bind overrides
AM_SERVER_EXTERNAL_PORT=8765
AM_SERVER_BIND_ADDRESS=0.0.0.0
NEO4J_HTTP_BIND_ADDRESS=127.0.0.1
NEO4J_BOLT_BIND_ADDRESS=127.0.0.1
```

Why these values matter:

- `AM_SERVER_API_KEYS`
  - operator/admin bearer key surface for the managed backend
- `AGENTIC_MEMORY_DEPLOYMENT_MODE=managed`
  - makes `/health/onboarding` and auth surfaces identify this backend as the hosted path
- `AGENTIC_MEMORY_HOSTED_BASE_URL`
  - gives setup/doctor/docs one canonical hosted URL to point at
- provider keys
  - search, ingest, and context resolution can depend on them
- Neo4j credentials
  - `am-server` will not warm its pipelines without a working graph connection

## 2. Render The Compose File Before You Deploy

Run this first so environment interpolation mistakes are visible before
containers start:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production config
```

If this output looks correct, continue.

Treat that rendered output as sensitive material. `docker compose config`
expands the actual environment values that Compose sees, so API keys and
passwords can appear in the rendered file or terminal output.

## 3. Start The Backend Stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Expected services:

- `neo4j`
- `am-server`

## 4. Check Health

Basic backend health:

```bash
curl http://127.0.0.1:8765/health
```

Detailed OpenClaw-facing health:

```bash
curl \
  -H "Authorization: Bearer replace-with-real-rest-key" \
  http://127.0.0.1:8765/openclaw/health/detailed
```

Authenticated metrics:

```bash
curl \
  -H "Authorization: Bearer replace-with-real-rest-key" \
  http://127.0.0.1:8765/metrics
```

Whole-stack onboarding contract:

```bash
curl http://127.0.0.1:8765/health/onboarding
```

What to look for:

- `server`, `mcp`, `openclaw_memory`, and `openclaw_context_engine` components
  should report sane statuses
- request-id-bearing errors should come back in the shared error envelope if a
  dependency is missing
- `/health/onboarding` should truthfully distinguish:
  - backend merely reachable
  - setup-ready
  - capture-only-ready
  - augment-context-ready

## 5. Install The OpenClaw Plugin

The operator install flow is:

```bash
openclaw plugin install agentic-memory-openclaw
```

Then configure it against the deployed backend:

```bash
openclaw agentic-memory doctor --hosted --backend-url http://127.0.0.1:8765
openclaw agentic-memory setup --hosted --backend-url http://127.0.0.1:8765
```

`doctor` should pass before `setup` is considered the supported path. `setup`
now validates the backend onboarding contract before it writes config.

The setup command should then record:

- backend URL
- API key template or literal value
- workspace identity
- device identity
- agent identity
- selected mode (`capture_only` or `augment_context`)

## 6. Smoke Test The OpenClaw Flow

After setup, validate the operator path from OpenClaw:

```bash
openclaw agentic-memory project status
```

Then exercise the integration with a short session and confirm:

- `/openclaw/session/register` is hit
- `/openclaw/memory/search` returns results
- `/openclaw/memory/ingest-turn` records new turns
- `/openclaw/context/resolve` works when context augmentation is enabled

## 7. Roll Back Safely

To stop the stack:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production down
```

To keep data but restart containers later, keep the named Docker volumes.

To fully reset beta data, remove the named volumes only when you explicitly
intend to wipe:

- `neo4j_data`
- `neo4j_logs`
- `neo4j_plugins`
- `agentic_memory_state`

## Operational Notes

- This compose file keeps Neo4j bound to loopback by default so the graph is
  not exposed broadly unless the operator opts in.
- Hosted-MCP surface keys are optional in this beta scaffold. The OpenClaw REST
  key path is the required one.
- Temporal bridge settings are carried through as optional environment
  variables, but the beta compose file does not attempt to provision
  SpacetimeDB or `am-sync-neo4j`.
