# Phase 9: Temporal PPR Retrieval + Benchmark - Research

**Date:** 2026-03-26  
**Status:** Ready for planning  
**Primary sources:** local repo code and prior phase artifacts

## Executive Summary

Phase 9 is not an algorithm-invention phase. The core temporal retrieval procedure already exists in
`packages/am-temporal-kg/src/procedures/retrieve.ts`. The real work is integration:

1. introduce a runtime bridge from the Python retrieval surfaces into the existing TypeScript
   SpacetimeDB bindings,
2. derive temporal seed nodes from the current Neo4j/vector path,
3. preserve vector/text fallback behavior,
4. benchmark the new path on replayed real traces.

The main non-obvious repo finding is this:

- **Phase 8 delivered the SpacetimeDB module and sync worker, but the Python ingestion/runtime code
  does not currently write conversation or research data into SpacetimeDB.**

That means Phase 9 planning must not assume the hot temporal graph is already populated by normal
runtime traffic. The phase either needs a minimal shadow-write path for live retrieval, or it must
scope the benchmark harness as the only population mechanism until that write-through exists.

## Key Findings

### 1. Public retrieval is still entirely Neo4j/vector-based

**Confidence:** High

- `src/codememory/server/tools.py`
  - `search_conversations(...)`
  - `get_conversation_context(...)`
- `src/codememory/server/app.py`
  - `search_web_memory(...)`
- `src/am_server/routes/conversation.py`
  - `GET /search/conversations`

All of those paths embed a query, run a Neo4j vector search, and optionally do text fallback. `as_of`
is currently only a Python-side cutoff on `ingested_at`, not a graph-native temporal retrieval
boundary.

### 2. `temporal_ppr_retrieve` is already implemented and usable

**Confidence:** High

- `packages/am-temporal-kg/src/procedures/retrieve.ts`

What already exists:
- bounded neighborhood collection
- temporal weighting using half-life decay
- personalized PageRank over a local subgraph
- ranked edge return set with interval metadata and evidence ids

What does not exist yet:
- a public Python caller
- evidence hydration into current MCP/REST response shapes
- seed resolution from current memory hits into temporal node ids

### 3. The only real SpacetimeDB client in-repo is TypeScript

**Confidence:** High

- `packages/am-sync-neo4j/src/stdb_client.ts`
- `packages/am-sync-neo4j/src/config.ts`
- `packages/am-temporal-kg/generated-bindings/index.ts`

The repo has a working TypeScript bindings/runtime path and no Python SpacetimeDB integration. The
lowest-risk Phase 9 route is to reuse the generated TypeScript bindings instead of introducing a new
Python client stack.

### 4. Phase 8 did not wire live Python ingestion into SpacetimeDB

**Confidence:** High

Repo search found no SpacetimeDB calls from:
- `src/`
- `packages/am-proxy/`
- `packages/am-ext/`

So today:
- conversation and research ingests still write only to Neo4j
- SpacetimeDB can be populated manually or by dedicated TS code
- the sync worker mirrors SpacetimeDB into Neo4j, but nothing in the shipping Python runtime feeds
  SpacetimeDB yet

This is the biggest planning trap for Phase 9.

### 5. The current memory nodes already carry enough metadata to derive temporal seeds

**Confidence:** Medium-High

Conversation turns and research nodes already persist entity metadata:

- `src/codememory/chat/pipeline.py`
  - stores `entities` and `entity_types`
- `src/codememory/web/pipeline.py`
  - stores `entities` and `entity_types`

That means the first PPR rollout does not need a second semantic stack. It can:

1. run the current vector search,
2. collect entity candidates from the matched memory nodes,
3. resolve those entities to temporal node ids,
4. call `temporal_ppr_retrieve(...)`.

The current search queries do not always return the entity metadata yet, so Phase 9 should expose it
on the seed-discovery path.

### 6. Existing token counting is heuristic, and that is acceptable for the first benchmark pass

**Confidence:** High

- `src/codememory/chat/pipeline.py`
  - `tokens_approx = int(len(content.split()) * 1.3)`
- `src/codememory/web/chunker.py`
  - `_token_count(text)`

There is no dedicated exact tokenizer benchmark utility in the repo today. For Phase 9, use the
existing approximation consistently across baseline and temporal paths so the comparison is fair.
Exact tokenizer integration can be deferred unless benchmark fidelity becomes a blocker.

## Standard Stack

Use this stack for Phase 9 planning and implementation.

### Runtime retrieval integration

- Python remains the public API orchestrator.
  - `src/codememory/server/tools.py`
  - `src/codememory/server/app.py`
  - `src/am_server/routes/conversation.py`
- Add a Python bridge manager for temporal retrieval.
  - recommended location: `src/codememory/temporal/bridge.py`
- Reuse the existing generated TypeScript bindings through a long-lived Node helper process.
  - recommended location: `packages/am-temporal-kg/scripts/query_temporal.ts`
- Configure that helper using the same SpacetimeDB env contract already used by the sync worker:
  - `STDB_URI`
  - `STDB_MODULE_NAME`
  - `STDB_BINDINGS_MODULE`
  - optional `STDB_TOKEN`
  - optional `STDB_CONFIRMED_READS`

### Seed discovery

- Keep Neo4j vector search for seed discovery.
- Extend the vector-search projections to include:
  - `entities`
  - `entity_types`
  - stable source identity fields needed for fallback and hydration

### Benchmark

- Add benchmark scripts under `bench/`.
- Use TypeScript for replay/build/query/report scripts so they can call the bindings directly.
- Use existing repo token heuristics for the first benchmark pass.

## Architecture Patterns

## 1. Vector For Seeds, PPR For Final Ranking

Do not replace the current vector path with raw temporal traversal in one jump.

Recommended pattern:
- vector search finds semantically relevant memory items
- entity mentions from those items become seed candidates
- temporal PPR reranks the local temporal graph around those seeds
- fallback returns the original vector result set if anything in the temporal path fails

This preserves compatibility while making the temporal graph additive instead of all-or-nothing.

## 2. Entity-First Seed Resolution, Not Turn-Id Or Chunk-Id Resolution

The temporal graph is entity/claim oriented. The vector baseline returns memory nodes such as:
- conversation turns
- research chunks
- findings

Those are not the same thing as SpacetimeDB `node` rows.

Recommended seed path:
- collect `(entity_name, entity_type)` pairs from top vector hits
- if the hit list has no usable entities, run the existing entity extractor on the query text
- let the Node helper resolve those entity names/types into temporal node ids

That avoids inventing a brittle direct mapping from Neo4j memory-node ids to SpacetimeDB node ids.

## 3. Long-Lived Bridge, Not Per-Request Process Spawn

Do not shell out to a fresh Node process on every query. That adds avoidable cold-start cost and
will work against the Phase 9 latency target.

Recommended pattern:
- Python process owns a cached bridge singleton
- bridge launches one long-lived Node helper
- requests are exchanged over JSON lines on stdin/stdout
- helper keeps its SpacetimeDB connection warm

This is materially simpler than adding a full new HTTP service, while still avoiding per-request
startup cost.

## 4. Bridge Enrichment Before Python Response Formatting

`temporal_ppr_retrieve(...)` currently returns edge ids, node ids, interval metadata, and evidence
ids. That is not enough for the existing public MCP/REST response shapes.

The Node helper should enrich the raw procedure result before returning to Python:
- resolve `subjId` and `objId` into node names/kinds
- resolve `evidenceIds` into evidence rows
- return a compact JSON payload Python can reshape into:
  - conversation context bundles
  - web research result strings
  - REST `results`

Do not force Python to reproduce SpacetimeDB table access logic after the procedure call.

## 5. Replay-Driven Benchmark Population

Because live Python ingestion does not yet populate SpacetimeDB, the benchmark harness must replay
captured traces into the temporal module directly.

That makes the benchmark independent of live cutover and gives deterministic test data.

## 6. Minimal Shadow-Write Hook Is A Practical Prerequisite For Live Cutover

If Phase 9 truly updates the public retrieval surfaces, then live requests need live temporal data.

So planning should include one of these:
- a small shadow-write hook from Python ingestion into the Node helper / SpacetimeDB reducers, or
- an explicit statement that public cutover is benchmark-only until runtime write-through lands

The first option is the better match for the roadmap’s Phase 9 goal.

## Data Contract Recommendations

These contracts are not fully locked elsewhere, but Phase 9 needs them.

### Evidence source contract

Standardize `Evidence.sourceKind` and `Evidence.sourceId` so Python can hydrate baseline memory rows
from temporal evidence:

- `conversation_turn`
  - `sourceId = "{session_id}:{turn_index}"`
- `research_chunk`
  - `sourceId = "{source_key}:{content_hash}"`
- `research_finding`
  - `sourceId = "{source_key}:{content_hash}"`

`rawExcerpt` should carry the excerpt actually used as evidence. This lets temporal retrieval remain
useful even if Neo4j hydration is partial.

### Seed request contract

Python should send the Node helper:

```json
{
  "projectId": "browser",
  "query": "what did we conclude about selectors",
  "asOfUs": 1764201600000000,
  "seedEntities": [
    {"kind": "project", "name": "ChatGPT"},
    {"kind": "topic", "name": "selectors.json"}
  ],
  "maxEdges": 24,
  "maxHops": 2,
  "alpha": 0.2,
  "halfLifeHours": 72,
  "minRelevance": 0.05
}
```

The helper should be responsible for:
- normalizing names
- resolving names to node ids
- dropping unresolved seeds
- calling `temporal_ppr_retrieve(...)`
- hydrating evidence and node labels

### Seed scoring contract

For the first rollout, keep seed scoring simple:

- gather top vector hits
- sum hit scores per `(entity_name, entity_type)` pair
- take top N distinct entity seeds
- if that set is empty, use query-extracted entities
- if it is still empty, fallback immediately to baseline vector retrieval

Do not add a second reranker before temporal PPR.

## Don't Hand-Roll

## 1. Do Not Reimplement PPR In Python

The procedure already exists in `packages/am-temporal-kg/src/procedures/retrieve.ts`. Phase 9
should consume it, not port it.

## 2. Do Not Invent A New Python SpacetimeDB Client Layer In This Phase

The repo already has a working TypeScript bindings path and no Python SpacetimeDB stack. A new
Python client is extra surface area with no Phase 9 benefit.

## 3. Do Not Use A Fresh Node Subprocess Per Request

That will turn the bridge into the latency bottleneck.

## 4. Do Not Treat Turn Or Chunk Hits As Temporal Node Ids

Temporal nodes are hashed entity rows, not raw memory-node ids. The first correct bridge is
entity-first.

## 5. Do Not Break Existing MCP Or REST Response Shapes

Callers should still receive the same top-level shape. Change ranking internals, not external
contracts.

## 6. Do Not Benchmark Only Edge Counts

Measure:
- retrieval latency
- returned evidence count
- token footprint of the final context payload
- temporal consistency against known `as_of`

Edge counts alone are not the user-facing outcome.

## 7. Do Not Assume Phase 8 Already Provides Live Runtime Population

It does not. Planning must account for the missing write-through path.

## Common Pitfalls

## 1. Forgetting To Return Entity Metadata From Seed-Discovery Queries

`search_web_memory(...)` currently does not return `entities` or `entity_types`, and
`get_conversation_context(...)` currently does not project them either. Without that, seed
resolution becomes guessy and weak.

## 2. Keeping `as_of` As A Post-Filter

The temporal boundary belongs in the SpacetimeDB procedure call via `asOfUs`, not only in Python
filtering after vector search.

## 3. Empty Seed Sets Falling Through Silently

If vector hits produce no seed entities, the system should log why and explicitly fallback. Silent
empty temporal results will look like broken relevance.

## 4. Returning Raw Edge Rows To The User-Facing Tools

MCP `get_conversation_context` and `search_web_memory` need evidence-oriented output, not raw graph
internals.

## 5. Mixing Benchmark Population With Live Retrieval Assumptions

The benchmark harness can replay traces and work immediately. Live cutover needs real runtime
population. Keep those two truths separate in planning.

## 6. Measuring Latency Without Stage Breakdown

Split latency into:
- vector seed discovery
- temporal bridge/procedure time
- evidence hydration/formatting

Otherwise you will not know what to tune.

## 7. Using Synthetic Temporal Data Only

The roadmap explicitly wants validation on real conversation and research traces. Synthetic data is
fine for smoke tests, not for benchmark conclusions.

## 8. Overbuilding The Bridge Into A New Permanent Service

Phase 9 needs a reliable bridge, not a major new deployment topology.

## Benchmark Design

Recommended benchmark shape:

1. `bench/build_temporal_kg.ts`
   - replays captured conversation/research traces
   - writes temporal claims/edges into SpacetimeDB
   - makes the benchmark reproducible without live runtime hooks

2. `bench/run_queries.ts`
   - runs the same query set against:
     - baseline vector retrieval
     - temporal seed + PPR retrieval
   - records per-stage latency

3. `bench/measure_tokens.ts`
   - measures token footprint of the final context payload using the repo’s current approximation

4. `bench/report_results.ts`
   - emits Markdown and machine-readable JSON

Benchmark report should include at least:
- query id
- domain: conversation or research
- baseline latency
- temporal latency
- baseline token estimate
- temporal token estimate
- token delta %
- evidence count
- temporal consistency verdict
- fallback used: yes/no

## Code Examples

### Python orchestration shape

```python
baseline_hits = neo4j_seed_search(query, project_id, limit=8)
seed_entities = collect_seed_entities(baseline_hits)

if not seed_entities:
    seed_entities = extract_seed_entities_from_query(query)

if not seed_entities:
    return baseline_response(baseline_hits)

temporal = temporal_bridge.retrieve(
    project_id=project_id,
    query=query,
    as_of_us=as_of_us,
    seed_entities=seed_entities,
)

if not temporal["results"]:
    return baseline_response(baseline_hits)

return format_temporal_results(temporal, fallback_hits=baseline_hits)
```

### Seed-discovery query additions

Conversation and research seed-discovery queries should project entity metadata:

```cypher
RETURN
    node.session_id   AS session_id,
    node.turn_index   AS turn_index,
    node.content      AS content,
    node.entities     AS entities,
    node.entity_types AS entity_types,
    score
```

### Node helper responsibilities

```ts
const resolvedSeedIds = await resolveSeedEntities(projectId, seedEntities);
if (resolvedSeedIds.length === 0) return { results: [] };

const edges = await callTemporalPprRetrieve({
  projectId,
  seedNodeIds: resolvedSeedIds,
  asOfUs,
  maxEdges,
  maxHops,
  alpha,
  halfLifeHours,
  minRelevance,
});

return await hydrateEdgesAndEvidence(edges);
```

## Recommended Plan Split

Phase 9 should likely plan into three slices:

1. **Bridge + runtime data contract**
   - Node helper
   - Python bridge manager
   - seed contract
   - evidence contract
   - minimal live shadow-write path if live cutover is required

2. **Public retrieval cutover**
   - `get_conversation_context`
   - `search_web_memory`
   - `GET /search/conversations`
   - stable fallback behavior
   - response-shape preservation

3. **Benchmark harness**
   - replay build
   - baseline vs temporal query runner
   - token measurement
   - Markdown report

## Confidence Notes

- **High confidence:** public retrieval is still Neo4j/vector only.
- **High confidence:** `temporal_ppr_retrieve` should be consumed, not rebuilt.
- **High confidence:** a TypeScript bridge is lower-risk than a new Python SpacetimeDB client.
- **High confidence:** benchmark replay is required because live runtime population is not wired.
- **Medium confidence:** entity-first seeding is the best first rollout. It fits current data
  shapes well, but Phase 9 implementation may still need small query/result-shape adjustments.

## References

- `.planning/ROADMAP.md`
- `.planning/prd-spacetimedb-tgrag.md`
- `.planning/phases/08-spacetimedb-maintenance-layer/08-CONTEXT.md`
- `.planning/phases/08-spacetimedb-maintenance-layer/08-SUMMARY.md`
- `.planning/phases/09-temporal-ppr-retrieval-benchmark/09-CONTEXT.md`
- `src/codememory/server/tools.py`
- `src/codememory/server/app.py`
- `src/am_server/routes/conversation.py`
- `src/codememory/chat/pipeline.py`
- `src/codememory/web/pipeline.py`
- `src/codememory/web/chunker.py`
- `packages/am-temporal-kg/src/procedures/retrieve.ts`
- `packages/am-temporal-kg/src/reducers/ingest.ts`
- `packages/am-temporal-kg/generated-bindings/index.ts`
- `packages/am-sync-neo4j/src/stdb_client.ts`
