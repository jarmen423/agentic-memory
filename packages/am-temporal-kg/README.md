# am-temporal-kg

SpacetimeDB TypeScript module for Phase 8 temporal maintenance in Agentic Memory.

## Scope

- Temporal edge ingest with interval-aware identity
- Evidence linking and lightweight contradiction tracking
- Scheduled decay, archival, and MDL-lite pruning
- Deterministic temporal PPR retrieval procedure
- Public sync-facing tables for the Phase 8 shadow-mode Neo4j mirror

## Publish

```bash
npm install
npm run publish:local --workspace am-temporal-kg
```

This script explicitly targets the saved `local` SpacetimeDB server and publishes the
database as `agentic-memory-temporal`.

For local development it also accepts the 1.x -> 2.x upgrade prompt and replaces any
stale local data from older test publishes so the module can be republished cleanly.

## Generate Client Bindings

Generate bindings after publishing and point the sync worker at the emitted module entry:

```bash
npm run generate:bindings --workspace am-temporal-kg
```

Equivalent direct CLI invocation:

```bash
spacetime generate agentic-memory-temporal --lang typescript --out-dir ./generated-bindings --module-path .
```

Recommended environment for the sync worker:

```bash
STDB_BINDINGS_MODULE=D:\code\agentic-memory\packages\am-temporal-kg\generated-bindings\index.ts
STDB_URI=http://127.0.0.1:3000
STDB_MODULE_NAME=agentic-memory-temporal
```

## Shadow Mode Notes

- `node`, `edge`, `evidence`, `edge_evidence`, and `edge_archive` are public so the internal sync worker can subscribe to them.
- `edge_stats` and `maintenance_job` stay internal to the module.
- Retrieval cutover is deferred; Phase 8 only maintains and mirrors the temporal graph.
