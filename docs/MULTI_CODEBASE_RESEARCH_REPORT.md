# Multi-Codebase GraphRAG Research Report

## Executive Summary

This report distills findings from an exported research session focused on multi-codebase GraphRAG architecture for CodeMemory.

Top conclusion: start with a **single Neo4j graph plus `repo_id` partitioning** (Pattern A), then add a migration path toward stronger isolation if scale or tenancy requirements demand it.

A critical practical finding from live probing: retrieval quality is currently harmed more by **duplicate indexed worktree paths** than by multi-repo architecture limits.

## Scope and Method

The source session synthesized:

- 22 sources across academia, vendor documentation, and large-scale industry implementations
- comparative architecture analysis for multi-tenancy and multi-corpus GraphRAG
- live Aura capability probing on the active environment
- feasibility testing of graph-enriched retrieval in pure Cypher

## Research Findings

### 1. Microsoft GraphRAG Baseline

- Microsoft GraphRAG core paper (arXiv:2404.16130) describes hierarchical community summaries, primarily for a single corpus.
- Open discussions indicate no official merged multi-corpus indexing solution; per-corpus pipelines remain common.
- Example discussion: https://github.com/microsoft/graphrag/discussions/1635

**Takeaway:** per-corpus indexing + query-time federation remains the de facto pattern.

### 2. Academic Consensus

- Recent surveys and system papers characterize GraphRAG as a pipeline of graph indexing, graph retrieval, and graph-informed generation.
- Multi-tenant/multi-corpus handling is acknowledged as important but not standardized.

**Takeaway:** there is no dominant canonical architecture for multi-corpus GraphRAG yet.

### 3. Enterprise Knowledge Graph Patterns

- Enterprise systems commonly keep a **shared graph substrate** with domain/type-based partitioning.
- Federation layers are added for cross-domain querying and governance at scale.

**Takeaway:** large organizations often favor one graph with logical partitioning before physical separation.

### 4. Neo4j Multi-Tenancy Patterns

- Official patterns support federation/sharding with constraints.
- Cross-database relationships are limited in federated setups.
- Third-party guidance highlights tradeoffs:
  - label/property partitioning: flexible but leakage/complexity risk
  - separate instances: strongest isolation, highest operational overhead
  - multi-database: practical middle ground for moderate tenant counts

**Takeaway:** architecture should keep an explicit escalation path from logical to physical isolation.

### 5. Vector-DB Maturity vs Graph-Layer Gap

- Qdrant, Weaviate, Pinecone have mature tenant partitioning constructs.
- PropertyGraphIndex ecosystems usually leave multi-tenancy policy to application/graph design.

**Takeaway:** vector partitioning is mostly solved; graph partitioning still requires custom design decisions.

### 6. Code Intelligence Signals

- Google/Kythe and Sourcegraph/SCIP patterns validate graph-driven code retrieval at very large scale.
- A practical reference model is **per-repo indexing with stable cross-repo identifiers**.

**Takeaway:** cross-repo symbol identity should be first-class even if storage starts unified.

### 7. GraphRAG Algorithmic Variants

- HippoRAG-style Personalized PageRank (PPR) offers a principled way to localize retrieval in mixed graphs while preserving cross-repo traversal when structurally justified.

**Takeaway:** PPR is a strong medium-term upgrade path for relevance and dilution control.

## Architecture Options for CodeMemory

| Pattern | Description | Best Fit | Tradeoffs |
|---|---|---|---|
| A. Single Graph + `repo_id` | One Neo4j database with logical partitioning | Small to medium repo counts | Easiest to implement; requires strict filtering and governance |
| B. Database per Repo + Federation | Separate DB per repo with federated queries | Larger installations with stronger isolation requirements | Better isolation; added complexity and cross-DB relationship limits |
| C. Hybrid Escalation | Start A, promote heavy repos to dedicated DBs | Mixed workloads over time | Operational flexibility; migration complexity |

**Recommended starting point:** Pattern A with explicit migration hooks toward Pattern C/B.

## Dilution and Relevance Strategy

A layered strategy emerged from the session:

1. **Pre-filter at retrieval time** when available.
2. **Over-fetch + post-filter** as fallback (`k * multiplier` then filter).
3. **Graph-structural re-ranking** using topology signals.
4. **PPR-based ranking** where Graph Data Science is available.
5. **Cross-encoder re-ranking** only for a small final candidate set when high precision is needed.

Example composite score:

`final_score = α*vector_sim + β*structural_proximity + γ*co_change + δ*recency`

## Aura Capability Probe Results (from session)

### Confirmed Available

- Neo4j Aura Enterprise: `5.27-aura`
- Cypher versions: default Cypher 5, Cypher 25 available
- Vector indexes present (`code_embeddings`, `memory_embeddings`)
- Post-`YIELD` filtering in vector queries works
- `vector.similarity.cosine()` available
- `db.index.vector.queryRelationships` available
- `genai.vector.encodeBatch` available (config-dependent)

### Available but Blocked by Configuration

- GDS algorithms (PageRank/Leiden/ArticleRank) discovered but gated by Aura API credentials for projection workflows.

### Not Available in Current Environment

- Composite database/fabric workflows
- Additional tenant databases (only `neo4j` and `system` observed)

## Critical Issues Identified

1. **Worktree pollution in indexed paths**
- Duplicate code from worktree directories appears in top retrieval hits.
- This currently causes major relevance degradation, independent of multi-repo design.

2. **Semantic search under-enriched by default**
- Current response shape is mostly vector hit metadata and snippet.
- Missing default structural context (file, callers/callees, sibling symbols, imports).

3. **Memory retrieval asymmetry**
- Outgoing relationship enrichment exists; incoming/contextual edges are limited.

4. **CALLS edge property sparsity**
- No useful relationship properties currently available for weighting (e.g., frequency/strength).

## Feasible Immediate Upgrade (No GDS Required)

The session validated a pure-Cypher enriched retrieval pattern:

- vector seed (`db.index.vector.queryNodes`)
- `Chunk -> DESCRIBES -> entity`
- recover containing file via `DEFINES`/`CONTAINS`
- collect `CALLS` (outgoing and incoming)
- include class methods (`HAS_METHOD`)
- include file dependencies (`IMPORTS`)
- include sibling functions via file-level `DEFINES`

This supports out-of-the-box graph-enriched answers without additional infrastructure.

## Prioritized Recommendations

### Immediate (before multi-repo expansion)

1. Exclude transient worktree paths from ingestion/indexing.
2. Make semantic search graph-enriched by default.
3. Expand memory search to include incoming and richer neighborhood context.

### Multi-Repo Enablement

4. Add `repo_id` to all relevant node/edge types.
5. Enforce repo-scoped retrieval via post-`YIELD` filtering and over-fetch fallback.
6. Add structural re-ranking features (same-file, call distance, import path, co-change, recency).

### Advanced Phase

7. Configure Aura API credentials for GDS projection functions.
8. Evaluate Leiden/PPR-based retrieval for module-aware ranking.
9. Consider optional cross-encoder final-stage reranking for high-precision workflows.

## Decision

Proceed with:

- **Pattern A** (single graph + `repo_id`) as the default architecture
- mandatory ingestion hygiene (remove worktree duplication)
- graph-enriched retrieval as the default response mode
- an explicit migration path toward hybrid/physical isolation when scale requires it

## Notes

- This report is a transformation of the exported session log in `RESEARCH-SESSION.txt`.
- It intentionally preserves conclusions and validated capability findings while removing chat/tool noise.
