# Phase 8 Summary: SpacetimeDB Maintenance Layer

**Date:** 2026-03-26  
**Status:** Complete

## Delivered

- Root TypeScript workspace scaffold:
  - `package.json`
  - `tsconfig.base.json`
- New SpacetimeDB module package:
  - `packages/am-temporal-kg/`
  - Temporal tables for nodes, evidence, edges, edge stats, archive rows, and maintenance jobs
  - Reducers for node upsert, temporal edge ingest, claim ingest, maintenance seeding, decay, archival, and MDL-lite pruning
  - Deterministic `temporal_ppr_retrieve` procedure
  - Public `module_health` view
- New Neo4j sync worker package:
  - `packages/am-sync-neo4j/`
  - Dynamic generated-bindings loader
  - SpacetimeDB subscriptions for `node`, `edge`, `evidence`, `edge_evidence`, `edge_archive`
  - Idempotent Neo4j mirror with checkpoint file persistence
  - Shadow edge-node pattern so evidence can attach cleanly in Neo4j

## Architectural Notes

- Phase 8 remains **shadow mode only**. Retrieval cutover is deferred to Phase 9.
- Sync-facing SpacetimeDB tables are public because the current client subscription model is table-based and public-table oriented.
- Neo4j mirrors both:
  - direct temporal relationships for analytics/fallback traversal
  - `:TemporalEdge` shadow nodes so `:TemporalEvidence` can attach with `:SUPPORTS`

## Runtime Prerequisites

1. Install Node dependencies for the new workspaces.
2. Publish `packages/am-temporal-kg` to a local SpacetimeDB instance.
3. Generate TypeScript bindings for the published module.
4. Start `packages/am-sync-neo4j` with:
   - `STDB_BINDINGS_MODULE`
   - `STDB_URI`
   - `STDB_MODULE_NAME`
   - `NEO4J_URI`
   - `NEO4J_USER`
   - `NEO4J_PASSWORD`

## Verification

Runtime verification completed on the local development stack:

- `npm install`
- `npm run typecheck --workspace am-temporal-kg`
- `npm run typecheck --workspace am-sync-neo4j`
- `npm run build --workspace am-temporal-kg`
- `npm run build --workspace am-sync-neo4j`
- local `spacetime publish` against the standalone server
- local bindings generation via `spacetime generate ... --module-path .`
- live sync worker startup with subscription applied
- seeded temporal claim mirrored into Neo4j as `:TemporalNode`, `SYNCS_TO`, and `:TemporalEvidence`

## Follow-On

- Local debug seed data was cleared after verification.
- Phase 9 is the next GSD step: temporal PPR retrieval cutover and benchmark harness.
