# SpacetimeDB Operations

This document covers the local operational path for the temporal sidecar used by Phase 8 and Phase 9, and still relevant to Phase 10 fallback and unified-search verification.

## Components

- `packages/am-temporal-kg`
  SpacetimeDB module for temporal ingest, maintenance, and retrieval

- `packages/am-sync-neo4j`
  Shadow sync worker that mirrors curated temporal rows into Neo4j

## Standard local environment

Required:

- `STDB_URI`
- `STDB_MODULE_NAME`
- `STDB_BINDINGS_MODULE`

Common values:

```text
STDB_URI=http://127.0.0.1:3001
STDB_MODULE_NAME=agentic-memory-temporal
STDB_BINDINGS_MODULE=D:\code\agentic-memory\packages\am-temporal-kg\generated-bindings\index.ts
```

Pick the real SpacetimeDB port in your environment and set `STDB_URI`
explicitly everywhere. Do not rely on a saved `local` alias and do not assume
`3000` is available.

## Start the server

Example:

```bash
spacetime start --listen-addr 127.0.0.1:3001
```

Then export:

```powershell
$env:STDB_URI="http://127.0.0.1:3001"
```

## Publish the module

```bash
$env:STDB_URI="http://127.0.0.1:3001"
npm run publish:local --workspace am-temporal-kg
```

This command now publishes directly to `STDB_URI`; it no longer relies on a
saved `local` server alias.

## Generate bindings

```bash
$env:STDB_URI="http://127.0.0.1:3001"
npm run generate:bindings --workspace am-temporal-kg
```

The wrapper temporarily points the SpacetimeDB CLI at `STDB_URI` before it
runs `spacetime generate`, then restores the previous default server.

## Run the sync worker

From the repo root:

```powershell
$env:STDB_URI="http://127.0.0.1:3001"
$env:STDB_MODULE_NAME="agentic-memory-temporal"
$env:STDB_BINDINGS_MODULE="D:\code\agentic-memory\packages\am-temporal-kg\generated-bindings\index.ts"
npm run start --workspace am-sync-neo4j
```

## Troubleshooting

- `module not found` or binding import failures
  Regenerate bindings and verify `STDB_BINDINGS_MODULE`.

- retrieval or sync appears stale
  Republish the module and restart the worker.

- server reachable on the wrong port
  Align `STDB_URI` with the port used by `spacetime start`.

- Neo4j does not reflect temporal rows
  Confirm `am-sync-neo4j` is running and its Neo4j credentials are valid.

## Relationship to current retrieval

- research and conversation search can use the temporal bridge directly
- Neo4j shadow sync is still useful for inspection and for explicitly non-primary/internal verification paths
- hosted/public research and conversation retrieval are now temporal-first contracts; if the temporal bridge is unavailable those surfaces should fail closed instead of silently degrading to baseline-only results
