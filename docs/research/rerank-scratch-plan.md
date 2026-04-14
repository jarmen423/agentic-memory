# Reranking & retrieval — scratch plan

## Candidate generation

- **Hybrid retrieval:** BM25 + dense vector search → deduplication by `docId`
- **Merge policy:** Preserve order of the higher-scoring source
- **Concurrency:** Separate thread pools for each retrieval path

## Reranking

- **Model class:** Cross-attention (cross-encoder)
- **Now:** Hosted — Cohere Rerank 4 and Rerank 4 Fast
- **Later:** Train a domain-specific cross-encoder

## Evaluation metrics

### Recall @ K

- Share of queries where the **ground-truth document** appears in the top-*k* candidates.
- Formula (coverage-style):  
  `recall@k = (# queries with relevant doc in top K) / (total queries)`
- Example: `recall@40 = 0.78` → ~78% of queries have the right doc somewhere in the top 40.

### MRR @ 10

**Mean Reciprocal Rank** of the **first relevant** result after re-ranking.

- `MRR = (1/rank₁ + 1/rank₂ + …) / N` over queries (using reciprocal rank of first hit per query).
- Example: `MRR = 0.78` → on average the first relevant hit sits near rank ~1.3.

### NDCG @ 10

**Normalized Discounted Cumulative Gain** — rewards multiple relevant docs and penalizes lower ranks.

- `ndcg = dcg / idcg`
- `dcg` sums graded relevance with position discount, e.g. terms like `(2^rel − 1) / log₂(rank + 1)` in standard formulations.
- Example: `ndcg = 0.85` → strong overall ranking quality in the top 10.

---

## Podcast / host outline — strategic & technical notes

*Outline of recommendations for upgrading an agentic memory retrieval stack.*

### I. Architectural pivot: two-stage retrieval

Move off a single monolithic vector search toward **candidate generation → re-ranking**. Four-step engineering story:

1. **True hybrid candidate generation** — Run lexical search (e.g. BM25) **in parallel** with dense retrieval; merge and **deduplicate** so exact tokens (variables, version strings) are not dropped.
2. **Optional graph-aware enrichment** — Keep personalized PageRank (or similar) as a **tie-breaker** on structural importance of files.
3. **Learned re-ranking** — Cross-encoder scores the **pre-filtered** candidate set.
   - *Sub-point:* Avoid feeding whole raw files to the cross-encoder (“token dilution”, context limits). Prefer **candidate serialization**: compact “cards” (symbol type, name, signature, short snippet).
4. **Final output** — Return re-sorted top results to the UI / downstream agent.

### II. Go-to-market and infrastructure

- **Start with hosted APIs** — e.g. Voyage AI or Cohere for the cross-encoder at launch: less MLOps, batching, and ops risk; often larger context windows.
- **Plan for a local model later** — Phase 2 for cost at scale and for **air-gapped / enterprise** buyers (banks, defense) who cannot send code to third-party APIs.

### III. Rigorous evaluation

- **Adversarial prompts** — Test on hard, realistic queries, not only easy keyword lookups.
- **“Holy trinity” metrics:**
  - **Recall @ K** — Did stage-1 retrieval include the right doc?
  - **MRR @ 10** — Is the **first** relevant hit near the top after re-ranking?
  - **NDCG @ 10** — Quality across the **whole** top 10 when multiple answers matter.

### IV. High-stakes domains (law, healthcare)

Golden rule: **“Reranking improves ordering, not truth.”** Pair retrieval with deterministic controls:

| Control | Role |
|--------|------|
| **Metadata filtering** | Drop wrong jurisdiction, stale corpuses, etc. *before* scoring. |
| **Provenance & time** | Show source authority and document dates prominently. |
| **Abstention** | If confidence is low, refuse to answer rather than guess. |
| **Human review** | UI assumes professional judgment; rerankers are **not** a safety layer. |
