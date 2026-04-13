# Agentic Memory OpenClaw Listing Draft

## Package Identity

- npm package: `agentic-memory-openclaw`
- install command: `openclaw plugin install agentic-memory-openclaw`
- OpenClaw plugin id after install: `agentic-memory`
- doctor command after install: `openclaw agentic-memory doctor`
- setup command after install: `openclaw agentic-memory setup`

## Short Description

Agentic Memory adds persistent memory search, turn capture, project scoping,
and optional context augmentation to OpenClaw through a backend-connected
plugin.

## Operator Value

- capture OpenClaw turns into Agentic Memory automatically
- search prior memory from inside the OpenClaw memory slot
- optionally assemble backend-driven context on each turn
- scope work to session-level projects without rewriting install-time config

## Required External Dependency

This plugin is not a self-contained backend. Operators still need an Agentic
Memory backend reachable at the configured `backendUrl`.

Minimum operator story:

1. deploy or reach an Agentic Memory backend
2. install the OpenClaw plugin package
3. run `openclaw agentic-memory doctor`
4. run `openclaw agentic-memory setup`
5. validate search, ingest, and project commands from OpenClaw

## Supported Modes

- `capture_only`
  - capture turns and serve memory search
  - do not inject custom context blocks
- `augment_context`
  - capture turns and serve memory search
  - also resolve Agentic Memory context blocks per turn

## Notes For Listing Copy

- keep "OpenClaw plugin" language in the listing so operators do not confuse
  the npm package with the Python backend
- keep "Agentic Memory" language in the title/summary so the broader product
  brand remains visible
- call out that the supported operator path is `install -> doctor -> setup`,
  not install straight into saved config
- call out that the plugin id stays `agentic-memory` after install because
  OpenClaw config and slot wiring use that stable id
