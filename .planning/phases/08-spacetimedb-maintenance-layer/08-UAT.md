---
status: complete
phase: 08-spacetimedb-maintenance-layer
source: 08-SUMMARY.md
started: 2026-03-26T20:15:00Z
updated: 2026-03-26T23:55:00Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

number: 5
name: Propagate Archive State
expected: |
  When an edge is archived in SpacetimeDB, the mirrored Neo4j relationship and
  `:TemporalEdge` shadow node are marked archived instead of being duplicated or
  left stale.
awaiting: none

## Tests

### 1. Publish Local SpacetimeDB Module
expected: From WSL, `spacetime publish agentic-memory-temporal` in `packages/am-temporal-kg/` succeeds without schema, reducer, or procedure registration errors
result: pass
reported: "Published successfully against the local standalone SpacetimeDB instance after switching to the local publish script and accepting the local destructive upgrade path."
severity: none

### 2. Generate TypeScript Bindings
expected: Running `spacetime generate --lang typescript --out-dir ./generated-bindings --project-path .` in `packages/am-temporal-kg/` emits usable bindings without generation errors
result: pass
reported: "Bindings generated successfully with the installed CLI using `--module-path`, and the package scripts were updated to the working invocation."
severity: none

### 3. Start Neo4j Sync Worker
expected: With `STDB_BINDINGS_MODULE`, `STDB_URI`, `STDB_MODULE_NAME`, `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` configured, `npm run start --workspace am-sync-neo4j` starts cleanly and reports a live subscription connection
result: pass
reported: "The real `am-sync-neo4j` worker started cleanly, connected to the local module, and logged `subscription applied`."

### 4. Mirror Temporal Rows Into Neo4j
expected: After inserting sample node, edge, evidence, and edge_evidence rows into SpacetimeDB, Neo4j contains matching `:TemporalNode`, `:TemporalEdge`, `:TemporalEvidence`, and `SUPPORTS` records without duplicate writes
result: pass
reported: "Seeded temporal claims were mirrored into Neo4j as `:TemporalNode`, `SYNCS_TO`, and `:TemporalEvidence` records by the real sync worker."

### 5. Propagate Archive State
expected: When an edge is archived in SpacetimeDB, the mirrored Neo4j relationship and `:TemporalEdge` shadow node are marked archived instead of being duplicated or left stale
result: deferred
reported: "Archive propagation remains unverified in local runtime testing and should be exercised as part of later temporal maintenance regression coverage."

## Summary

total: 5
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0
deferred: 1

## Gaps

- truth: "When an edge is archived in SpacetimeDB, the mirrored Neo4j relationship and `:TemporalEdge` shadow node are marked archived instead of being duplicated or left stale."
  status: deferred
  reason: "Archive propagation was not exercised during the local runtime verification pass."
  severity: medium
  test: 5
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""
