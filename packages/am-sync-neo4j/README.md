# am-sync-neo4j

Shadow-mode worker that mirrors the Phase 8 SpacetimeDB temporal graph into Neo4j.

## Responsibilities

- Connect to the published `am-temporal-kg` database using generated TypeScript bindings
- Subscribe to `node`, `edge`, `evidence`, `edge_evidence`, and `edge_archive`
- Apply idempotent Neo4j upserts for temporal nodes, shadow edge nodes, relationships, and evidence
- Track replay checkpoints locally so reconnects do not re-emit unchanged rows

## Environment

```bash
STDB_URI=http://127.0.0.1:3001
STDB_MODULE_NAME=agentic-memory-temporal
STDB_BINDINGS_MODULE=/absolute/path/to/repo/packages/am-temporal-kg/generated-bindings/index.ts
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
AM_SYNC_CHECKPOINT_PATH=/absolute/path/to/repo/.cache/am-sync-neo4j/checkpoints.json
```

Optional:

```bash
STDB_TOKEN=<owner-or-service-token>
STDB_CONFIRMED_READS=true
```

`STDB_URI` is now required. The sync worker no longer silently assumes
`http://127.0.0.1:3000`, because that port may belong to a different local
service in a real development stack.

## Run

```bash
npm install
npm run start --workspace am-sync-neo4j
```

This worker is intentionally shadow-only in Phase 8. It does not change the existing retrieval path.
