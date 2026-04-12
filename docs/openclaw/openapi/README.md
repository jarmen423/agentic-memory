# OpenClaw OpenAPI Artifact

This directory contains the committed REST contract for the OpenClaw
private-beta surface.

## Artifact

- `D:\code\agentic-memory\docs\openclaw\openapi\agentic-memory-openclaw.openapi.json`

## What The Artifact Includes

- `/health`
- `/metrics`
- all `/openclaw/*` routes that the plugin or operator dashboard uses
- only the schemas referenced by those routes

## Why This Is Filtered

`am-server` exposes more than the OpenClaw beta contract. The private-beta docs
need a stable operator-facing API artifact, not the entire app surface.

Filtering the export keeps this artifact focused on:

- plugin install/setup validation
- OpenClaw memory and context routes
- session/project lifecycle routes
- operator health and metrics checks

## Regeneration Rule

Regenerate from the live FastAPI app whenever the OpenClaw contract changes.

Current verification command:

```bash
python -c "from am_server.app import create_app; spec = create_app().openapi(); assert '/openclaw/memory/search' in spec['paths']; print('openapi ok')"
```

The committed JSON should stay aligned with that live app contract.
