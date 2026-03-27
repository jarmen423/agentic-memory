# Phase 8: SpacetimeDB Maintenance Layer - Research

**Date:** 2026-03-25
**Primary sources:** official SpacetimeDB docs and `.planning/PRD-SpacetimeDB-TGRAG.md`

## Key Findings

### 1. TypeScript server modules are first-class
- Current SpacetimeDB docs support TypeScript server modules and client bindings.
- The current client package is `spacetimedb`; the older `@clockworklabs/spacetimedb-sdk`
  package is deprecated as of SpacetimeDB 1.4.0+.
- Module-specific client bindings are generated with:
  `spacetime generate --lang typescript --out-dir <dir> --project-path <module-dir>`

**Implication for this repo:** use a TypeScript server module in `packages/am-temporal-kg/`
and a separate TypeScript worker in `packages/am-sync-neo4j/`.

### 2. Procedures are valid but still beta
- Procedures can perform logic reducers cannot, but they do not get `ctx.db` directly.
- Procedure reads and writes must occur inside `ctx.withTx(...)`.
- The function passed into `withTx(...)` may run multiple times and must remain deterministic.

**Implication for this repo:** temporal retrieval should be implemented as a deterministic
procedure with explicit transaction scope and no external network calls.

### 3. Reducers remain the correct write path
- Reducers are the canonical mutation path in SpacetimeDB.
- Scheduled work is driven by scheduled rows and reducer dispatch, which fits nightly decay,
  archival, and pruning jobs.

**Implication for this repo:** edge ingest, contradiction tracking, stats updates, and
maintenance should live in reducers, not external cron jobs.

### 4. Subscriptions are the right sync primitive
- Client bindings expose generated table accessors and row callbacks for insert, update, and
  delete events.
- Subscription SQL is intentionally constrained, so replication should subscribe to relevant
  tables separately instead of expecting arbitrary join queries.

**Implication for this repo:** the Neo4j sync worker should subscribe to `node`, `edge`,
`evidence`, `edge_evidence`, and `edge_archive` independently and map them into Cypher writes.

### 5. Generated bindings should not be assumed in-repo
- SpacetimeDB bindings are generated from a published module or module project path.
- This repo does not currently include generated TypeScript bindings or an existing JS/TS
  workspace.

**Implication for this repo:** the sync worker should load generated bindings dynamically from
an environment-configured path instead of using a hard-coded import.

## Repo-Specific Constraints

- The current repo is Python-first and has no root TypeScript workspace.
- `packages/` already exists and is the least disruptive place to add TypeScript deliverables.
- Neo4j temporal relationship semantics are already fixed by Phase 7 and must remain compatible.

## Recommended Build Shape

1. Add a minimal root JS workspace (`package.json` + `tsconfig.base.json`) for the new packages.
2. Implement `packages/am-temporal-kg/` as the SpacetimeDB TypeScript module:
   - schema tables
   - reducers for ingest and maintenance
   - deterministic retrieval procedure
   - README and publish/codegen instructions
3. Implement `packages/am-sync-neo4j/` as a standalone worker:
   - dynamic bindings loader
   - subscription registration
   - checkpoint store
   - Neo4j MERGE writer
4. Keep the worker and module decoupled from the existing Python runtime so shadow mode can be
   adopted incrementally.

## Open Technical Choices Left to Implementation

- Exact MDL-lite heuristics and default thresholds.
- Whether archived Neo4j relationships are deleted or relabeled during sync.
- How much relation-type normalization to do in the worker vs upstream extraction.

## References

- `.planning/PRD-SpacetimeDB-TGRAG.md`
- `.planning/ROADMAP.md`
- `.planning/phases/07-temporal-schema/07-CONTEXT.md`

