# Phase 8: SpacetimeDB Maintenance Layer - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning and implementation
**Source:** `.planning/PRD-SpacetimeDB-TGRAG.md`

<domain>
## Phase Boundary

Add a hot temporal maintenance layer in SpacetimeDB that runs alongside the existing
Neo4j-backed memory system. This phase introduces a SpacetimeDB module that owns temporal
edge maintenance, contradiction tracking, decay, pruning, and archival, plus a sync worker
that mirrors curated rows into Neo4j in shadow mode. Retrieval cutover stays out of scope
until Phase 9.

</domain>

<decisions>
## Implementation Decisions

### Hot/Cold Topology
- **D-01:** Use a hot/cold hybrid: SpacetimeDB is the authoritative temporal maintenance layer,
  while Neo4j remains the cold analytical graph and fallback exploration surface.
- **D-02:** Phase 8 runs in shadow mode only. Existing Python ingestion and Neo4j retrieval paths
  remain intact while SpacetimeDB tables and sync replication are introduced in parallel.

### SpacetimeDB Module Shape
- **D-03:** Implement the SpacetimeDB server module in TypeScript under `packages/am-temporal-kg/`.
- **D-04:** Use first-class temporal edges with interval-bearing identity: edge ids are derived
  from `(project_id, subj_id, pred, obj_id, valid_from_us, valid_to_us)`.
- **D-05:** Represent time in microseconds since epoch (`bigint`) throughout the module to avoid
  timezone ambiguity and to align with scheduled maintenance.

### Maintenance and Pruning
- **D-06:** Keep maintenance in-database using scheduled rows that dispatch reducer work for
  nightly decay, expiry archival, and MDL-lite pruning.
- **D-07:** Archive instead of hard-delete when suppressing expired or low-quality temporal edges.
- **D-08:** Track contradiction and support signals structurally on edges and edge stats tables,
  not in LLM-side adjudication.

### Procedures and Determinism
- **D-09:** Use reducers for ingestion and maintenance; use procedures only for parameterized,
  deterministic read flows such as bounded temporal retrieval.
- **D-10:** Procedure code must avoid external I/O and rely on `withTx(...)` only, because
  SpacetimeDB procedures are transactional only inside an explicit transaction scope.

### Sync Worker
- **D-11:** Implement the Neo4j sync worker in TypeScript under `packages/am-sync-neo4j/`.
- **D-12:** The worker loads generated SpacetimeDB bindings at runtime from a configured path
  instead of importing checked-in generated code. This keeps the repo shippable before a database
  is published.
- **D-13:** Sync is idempotent. Neo4j relationships are merged by stable `edge_id`, and worker
  replay protection is handled with a local checkpoint store.

### ACP-first Ingestion Compatibility
- **D-14:** Preserve the Phase 5 ACP proxy and Phase 4 conversation ingest contract unchanged.
  Phase 8 only changes downstream temporal maintenance and replication.

### the agent's Discretion
- MDL-lite thresholds, decay constants, and retention defaults.
- Exact workspace scripts and package-manager commands.
- Whether archived Neo4j relationships are deleted or relabeled during sync.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Scope and Architecture
- `.planning/ROADMAP.md` - Phase 8 goal, deliverables, success criteria, and dependency chain.
- `.planning/PRD-SpacetimeDB-TGRAG.md` - Primary implementation spec for the SpacetimeDB temporal KG layer.

### Upstream Temporal Work
- `.planning/phases/07-temporal-schema/07-CONTEXT.md` - Locked temporal edge semantics added in Phase 7.
- `src/codememory/core/graph_writer.py` - Existing Neo4j temporal relationship write contract that Phase 8 must mirror.

### Existing Passive Ingestion Path
- `packages/am-proxy/src/am_proxy/proxy.py` - ACP proxy behavior already shipping in Phase 5.
- `src/am_server/routes/conversation.py` - Current passive conversation ingest endpoint that remains the upstream source.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/codememory/core/connection.py`: Existing Neo4j connection configuration and pool settings worth mirroring in the sync worker.
- `src/codememory/core/graph_writer.py`: Canonical relationship property names and MERGE semantics for the cold graph.
- `packages/am-proxy/`: Existing `packages/` subtree pattern for adding non-Python deliverables without disturbing the main Python package.

### Established Patterns
- Python remains the primary runtime for ingestion and REST APIs; the new TypeScript packages must be additive and isolated.
- The repo currently has no JS/TS workspace at the root, so Phase 8 must establish one without interfering with `pyproject.toml`.
- Temporal metadata is already standardized in Neo4j (`valid_from`, `valid_to`, `confidence`, `support_count`, `contradiction_count`).

### Integration Points
- SpacetimeDB ingest outputs ultimately need to map back onto the Neo4j node and relationship surface used by the existing MCP tools.
- The sync worker must translate SpacetimeDB temporal rows into Neo4j nodes and relationships compatible with the current cold graph.

</code_context>

<specifics>
## Specific Ideas

- Runtime-loaded SpacetimeDB bindings avoid checking generated client code into the repo.
- Keep retrieval cutover out of Phase 8. This phase introduces the data plane and maintenance layer only.
- Use archive tables plus replay-safe checkpoints so the worker can be restarted without duplicating writes.

</specifics>

<deferred>
## Deferred Ideas

- Temporal PPR retrieval cutover and benchmark-driven token-reduction validation belong to Phase 9.
- Unified cross-module ranking and MCP search aggregation belong to Phase 10.

</deferred>

---

*Phase: 08-spacetimedb-maintenance-layer*
*Context gathered: 2026-03-25*
