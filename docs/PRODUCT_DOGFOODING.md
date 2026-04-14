# Product Dogfooding Loop

This document turns the packaging/UI/UX plan into a repeatable local validation loop.

## Goal

Validate Agentic Memory in the same shape future users should run it:

- local app / local services
- optional cloud account later
- one-click or guided integrations
- repeated install, uninstall, patch, repair, and reconnect cycles

The target is not just "the repo works." The target is:

- setup is easy
- integrations are legible
- failures are recoverable
- first useful value happens quickly

## Core Artifacts

- Local product state:
  - `agentic-memory product-status --json`
  - `GET /product/status`
- Repo registration:
  - `agentic-memory product-repo-add`
  - `POST /product/repos`
- Integration registration:
  - `agentic-memory product-integration-set`
  - `POST /product/integrations`
- Runtime component health:
  - `agentic-memory product-component-set`
  - `POST /product/components/{component}`
- Dogfood event capture:
  - `agentic-memory product-event-record`
  - `POST /product/events`
- Desktop shell:
  - `python -m am_server.server`
  - `python -m desktop_shell --backend-url http://127.0.0.1:8765`

## Required Journeys

Run these as the primary UI/UX validation suite for packaging work:

1. Fresh install
2. First-run onboarding
3. Add first repo
4. Connect first MCP client
5. Connect first browser extension surface
6. Connect first proxy/ACP surface
7. Break local runtime and repair it
8. Uninstall and reinstall cleanly
9. Upgrade over an existing install

## Metrics To Capture

For every journey, record:

- completion status
- elapsed time
- number of manual steps
- number of retries
- terminal interventions required
- docs lookups required
- failure point
- repair success

## Suggested CLI Flow During Dogfooding

```bash
# Inspect the local control-plane state
agentic-memory product-status --json

# Register a repo under test
agentic-memory product-repo-add C:\path\to\repo --label "Dogfood Repo" --json

# Mark an integration as configured
agentic-memory product-integration-set ^
  --surface mcp ^
  --target claude_desktop ^
  --status configured ^
  --config-json "{\"command\":\"agentic-memory\"}" ^
  --json

# Mark runtime health
agentic-memory product-component-set ^
  --component server ^
  --status healthy ^
  --details-json "{\"endpoint\":\"http://localhost:8000\"}" ^
  --json

# Record friction or success
agentic-memory product-event-record ^
  --event install_completed ^
  --status ok ^
  --actor dogfood ^
  --details-json "{\"journey\":\"fresh_install\"}" ^
  --json
```

## Running The Core Code-Memory Loop On This Repo

If the dogfood target is this repository itself, it is already initialized via:

- `D:\code\agentic-memory\.codememory\config.json`

Use this local Windows sequence first:

```powershell
cd D:\code\agentic-memory
docker compose up -d neo4j
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli status --json
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli index --json
```

Important notes:

- `agentic-memory` may not be on `PATH` locally, so prefer the explicit venv
  Python command shown above
- `status` is the quick liveness/state check
- `index` is the one-time ingest pass and can take materially longer
- `watch` is a foreground long-running observer and should be treated as a
  deliberate step, not the default first command

## Release Gate

Do not call a packaging/UI release ready unless all of these pass:

- fresh install completes without manual config editing
- first repo can be added and indexed
- at least one MCP integration works
- at least one passive capture surface works
- server downtime and config drift are recoverable
- uninstall/reinstall leaves the system usable without manual cleanup
- the browser-based `desktop_shell` view can load the local product status endpoint
