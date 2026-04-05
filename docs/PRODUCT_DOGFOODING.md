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
  - `codememory product-status --json`
  - `GET /product/status`
- Repo registration:
  - `codememory product-repo-add`
  - `POST /product/repos`
- Integration registration:
  - `codememory product-integration-set`
  - `POST /product/integrations`
- Runtime component health:
  - `codememory product-component-set`
  - `POST /product/components/{component}`
- Dogfood event capture:
  - `codememory product-event-record`
  - `POST /product/events`

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
codememory product-status --json

# Register a repo under test
codememory product-repo-add C:\path\to\repo --label "Dogfood Repo" --json

# Mark an integration as configured
codememory product-integration-set ^
  --surface mcp ^
  --target claude_desktop ^
  --status configured ^
  --config-json "{\"command\":\"codememory\"}" ^
  --json

# Mark runtime health
codememory product-component-set ^
  --component server ^
  --status healthy ^
  --details-json "{\"endpoint\":\"http://localhost:8000\"}" ^
  --json

# Record friction or success
codememory product-event-record ^
  --event install_completed ^
  --status ok ^
  --actor dogfood ^
  --details-json "{\"journey\":\"fresh_install\"}" ^
  --json
```

## Release Gate

Do not call a packaging/UI release ready unless all of these pass:

- fresh install completes without manual config editing
- first repo can be added and indexed
- at least one MCP integration works
- at least one passive capture surface works
- server downtime and config drift are recoverable
- uninstall/reinstall leaves the system usable without manual cleanup
