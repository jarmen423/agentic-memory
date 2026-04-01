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
STDB_URI=http://127.0.0.1:3000
STDB_MODULE_NAME=agentic-memory-temporal
STDB_BINDINGS_MODULE=D:\code\agentic-memory\packages\am-temporal-kg\generated-bindings\index.ts
```

If you start SpacetimeDB on `3333`, set `STDB_URI=http://127.0.0.1:3333` everywhere.

## Start the server

Default:

```bash
spacetime start
```

Custom port:

```bash
spacetime start --listen-addr 127.0.0.1:3333
```

## Publish the module

Default local server:

```bash
npm run publish:local --workspace am-temporal-kg
```

Custom server:

```bash
cd packages/am-temporal-kg
spacetime publish --server http://127.0.0.1:3333 --yes --delete-data --module-path . agentic-memory-temporal
```

## Generate bindings

Default:

```bash
npm run generate:bindings --workspace am-temporal-kg
```

Custom server:

```bash
cd packages/am-temporal-kg
spacetime generate agentic-memory-temporal --server http://127.0.0.1:3333 --lang typescript --out-dir ./generated-bindings --module-path .
```

## Run the sync worker

From the repo root:

```powershell
$env:STDB_URI="http://127.0.0.1:3000"
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
- Neo4j shadow sync is still useful for inspection and some fallback-oriented verification
- the temporal sidecar remains additive; baseline retrieval still matters and is still tested
