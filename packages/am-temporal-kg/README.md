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
STDB_URI=http://127.0.0.1:3001
npm run publish:local --workspace am-temporal-kg
```

`publish:local` no longer relies on a saved `local` alias. It requires
`STDB_URI` and publishes directly to that explicit SpacetimeDB target.

That matters because other local services, such as Grafana, often own port
`3000`, and a stale saved alias can silently point at the wrong host.

## Generate Client Bindings

Generate bindings after publishing and point the sync worker at the emitted module entry:

```bash
STDB_URI=http://127.0.0.1:3001
npm run generate:bindings --workspace am-temporal-kg
```

The wrapper script temporarily points the SpacetimeDB CLI at the explicit
`STDB_URI` target before it runs `spacetime generate`, then restores the
previous default server afterward.

Recommended environment for the sync worker:

```bash
STDB_BINDINGS_MODULE=D:\code\agentic-memory\packages\am-temporal-kg\generated-bindings\index.ts
STDB_URI=http://127.0.0.1:3001
STDB_MODULE_NAME=agentic-memory-temporal
```

## Shadow Mode Notes

- `node`, `edge`, `evidence`, `edge_evidence`, and `edge_archive` are public so the internal sync worker can subscribe to them.
- `edge_stats` and `maintenance_job` stay internal to the module.
- Retrieval cutover is deferred; Phase 8 only maintains and mirrors the temporal graph.
