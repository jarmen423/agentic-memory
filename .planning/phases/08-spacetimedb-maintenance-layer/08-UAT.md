---
status: testing
phase: 08-spacetimedb-maintenance-layer
source: 08-SUMMARY.md
started: 2026-03-26T20:15:00Z
updated: 2026-03-26T21:10:00Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

number: 3
name: Start Neo4j Sync Worker
expected: |
  With `STDB_BINDINGS_MODULE`, `STDB_URI`, `STDB_MODULE_NAME`, `NEO4J_URI`,
  `NEO4J_USER`, and `NEO4J_PASSWORD` configured, `npm run start --workspace am-sync-neo4j`
  should start cleanly and report a live subscription connection.
awaiting: user response

## Tests

### 1. Publish Local SpacetimeDB Module
expected: From WSL, `spacetime publish agentic-memory-temporal` in `packages/am-temporal-kg/` succeeds without schema, reducer, or procedure registration errors
result: issue
reported: "Published to maincloud.spacetimedb.com instead of a local standalone instance after reboot, and the CLI warned that `tsc` was not found in node_modules."
severity: major

### 2. Generate TypeScript Bindings
expected: Running `spacetime generate --lang typescript --out-dir ./generated-bindings --project-path .` in `packages/am-temporal-kg/` emits usable bindings without generation errors
result: issue
reported: "The installed SpacetimeDB CLI rejects `--project-path` and reports that a similar argument is `--uproject-dir`; `spacetime generate --help` shows the current module flag is `--module-path`."
severity: major

### 3. Start Neo4j Sync Worker
expected: With `STDB_BINDINGS_MODULE`, `STDB_URI`, `STDB_MODULE_NAME`, `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` configured, `npm run start --workspace am-sync-neo4j` starts cleanly and reports a live subscription connection
result: [pending]

### 4. Mirror Temporal Rows Into Neo4j
expected: After inserting sample node, edge, evidence, and edge_evidence rows into SpacetimeDB, Neo4j contains matching `:TemporalNode`, `:TemporalEdge`, `:TemporalEvidence`, and `SUPPORTS` records without duplicate writes
result: [pending]

### 5. Propagate Archive State
expected: When an edge is archived in SpacetimeDB, the mirrored Neo4j relationship and `:TemporalEdge` shadow node are marked archived instead of being duplicated or left stale
result: [pending]

## Summary

total: 5
passed: 0
issues: 2
pending: 3
skipped: 0
blocked: 0

## Gaps

- truth: "From WSL, `spacetime publish agentic-memory-temporal` in `packages/am-temporal-kg/` succeeds against a local standalone SpacetimeDB instance without schema, reducer, or procedure registration errors."
  status: failed
  reason: "User reported: Published to maincloud.spacetimedb.com instead of a local standalone instance after reboot, and the CLI warned that `tsc` was not found in node_modules."
  severity: major
  test: 1
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""
- truth: "Running `spacetime generate --lang typescript --out-dir ./generated-bindings --project-path .` in `packages/am-temporal-kg/` emits usable bindings without generation errors."
  status: failed
  reason: "User reported: The installed SpacetimeDB CLI rejects `--project-path` and `spacetime generate --help` shows the current module flag is `--module-path`."
  severity: major
  test: 2
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""
