# Code Retrieval Reranking Decision Memo

## Status

- Date: 2026-04-12
- Decision state: recommended architecture direction
- Scope: code retrieval in Agentic Memory
- Related primer: [Rerankers Primer](RERANKERS_PRIMER.md)

## Decision

Agentic Memory should add a learned reranking stage for code retrieval, but it
should not add it as a replacement for the current stack.

The recommended direction is:

1. make normal code candidate generation truly hybrid: lexical plus dense
2. keep the current structural graph reranking path
3. add a learned reranker over the top `20-40` candidates
4. make the reranker pluggable
5. ship a hosted rerank backend first
6. add a local cross-encoder later as the optional privacy or offline path

In short:

- yes, add reranking
- no, do not make a local cross-encoder the first default

## Current System: Relevant Pieces

### Code Search Is Vector-First

`KnowledgeGraphBuilder.semantic_search()` in
[`src/agentic_memory/ingestion/graph.py`](../src/agentic_memory/ingestion/graph.py)
embeds the query, calls Neo4j's `code_embeddings` vector index, and uses
`candidate_limit=max(limit * 8, limit)`.

That means the normal code path is ANN vector retrieval over chunk embeddings.

### A Full-Text Index Exists, But Normal Search Does Not Use It as a Peer

`KnowledgeGraphBuilder.setup_database()` creates:

- `code_embeddings`
- `entity_text_search`

But `semantic_search()` only uses `entity_text_search` as a fallback when the
query vector is invalid. So the current system has lexical capability, but not
true hybrid code retrieval in the normal path.

### There Is Already a Structural Reranker

[`src/agentic_memory/server/code_search.py`](../src/agentic_memory/server/code_search.py)
implements graph-aware reranking with Personalized PageRank.

Important details:

- it uses `IMPORTS`, `DEFINES`, and `HAS_METHOD`
- it explicitly excludes `CALLS` from ranking
- it carries retrieval provenance forward to agent-facing surfaces

This is useful, but it is structural reranking, not learned query-document
reranking.

### Public Surfaces Default to the Conservative Path

The MCP tool layer and unified search favor `SAFE_RETRIEVAL_POLICY`, which
means the product default is intentionally conservative and does not currently
include a learned reranker.

## Current Strengths

The existing design already has strong building blocks:

- repo-scoped graph entities
- vector retrieval over code chunks
- a full-text index
- graph-based reranking
- provenance surfaced to the agent
- conservative exclusion of low-trust `CALLS` edges

The question is not whether retrieval exists. The question is how to improve the
final ordering of code results.

## Current Gaps

### Gap 1: Normal Code Search Is Not Truly Hybrid

Because lexical search is fallback-only in the normal path, the system remains
weaker than it should be on:

- exact identifiers
- paths
- API names
- error strings
- dates and version numbers

### Gap 2: No Learned Query-Candidate Relevance Model

The system can currently say:

- this result is semantically similar
- this result is structurally connected

It cannot yet say:

- after reading the query and this candidate together, this is clearly the best answer

That missing layer is what rerankers are for.

### Gap 3: Vector Search Is Approximate

Neo4j vector search is ANN search. That is the right scaling tradeoff, but it
reinforces the need for better candidate generation and better final ranking.

## Decision Criteria

The decision should optimize for:

1. better relevance on real code questions
2. preserved candidate recall
3. interactive latency suitable for MCP-style use
4. low operational burden
5. compatibility with hosted product surfaces
6. an eventual privacy or offline path

## Options Considered

### Option A: Do Nothing

Keep:

- vector retrieval
- optional graph reranking
- full-text fallback only

Result:

- not recommended

It leaves a known final-ranking quality gap and continues to underuse the
existing full-text index.

### Option B: Make a Local Cross-Encoder the Default

Pros:

- private
- no per-query API cost

Cons:

- adds local inference and packaging complexity
- adds platform variability and model-serving work
- is a larger first rollout than needed

Result:

- useful later
- not recommended as the first default

### Option C: Add a Hosted Rerank API First

Pros:

- fastest path to strong quality
- lower integration risk
- strong fit for hosted MCP and product surfaces
- avoids forcing a local model stack into every environment

Cons:

- network latency
- provider cost
- privacy concerns for some users

Result:

- recommended as the first learned reranker backend

### Option D: Improve Candidate Generation to Hybrid Retrieval, Then Add Learned Reranking

Pros:

- addresses recall and ranking together
- better fit for code-specific exact-token questions
- matches the system's current weakness

Cons:

- more work than only bolting on a reranker

Result:

- strongly recommended

## Recommendation

### Primary Recommendation

Agentic Memory should add a learned reranking stage for code retrieval.

### Architecture Recommendation

Target pipeline:

1. lexical plus dense candidate generation
2. optional graph-aware enrichment or structural reranking
3. learned reranking on the bounded candidate set
4. final top `n` results returned to MCP and unified search

### Backend Recommendation

Add a narrow interface with backends:

- `none`
- `voyage`
- `cohere`
- `local_cross_encoder`

The first default backend should be a hosted rerank API. A local cross-encoder
should be added later as an opt-in backend.

## Why Hosted First Is the Right Move

### Lower Integration Risk

Agentic Memory already uses provider-backed embeddings. Adding a hosted rerank
primitive is less disruptive than introducing a mandatory local inference stack.

### Better Match for Hosted Surfaces

Hosted public MCP surfaces need predictable operations more than they need zero
external dependencies.

### Larger Context Windows

Modern hosted rerank APIs expose larger context windows than many older
open-source passage rerankers. That makes them easier to use for code candidate
cards without overly aggressive truncation.

### Faster Path to Evidence

The first goal should be to prove that learned reranking materially improves the
query set. Hosted rerank APIs are the shortest path to that proof.

## Why Local Cross-Encoder Still Matters Later

It is still worth supporting because:

- some teams will not send code-derived text to a third party
- some operators need local-only cost control
- some deployments will be offline or restricted
- a code-specific fine-tuned reranker may later outperform general-purpose APIs

That is an argument for a second backend, not for the first default.

## Candidate Generation Comes First

Rerankers cannot recover missing candidates.

Because the current normal code path is vector-first with full-text only as
fallback, the first quality improvement should be true hybrid candidate
generation:

- vector search
- full-text search
- normalize and merge candidates
- dedupe by source identifier
- then rerank

Without that step, a learned reranker will still help, but it will be capped by
the candidate set.

## Proposed Retrieval Pipeline

### Phase 1: Candidate Retrieval

Retrieve from:

- `code_embeddings`
- `entity_text_search`

Suggested initial bounds:

- vector `top_k`: 20-30
- lexical `top_k`: 20-30
- merged rerank set: 20-40

### Phase 2: Candidate Serialization

Serialize each candidate into a compact card with fields such as:

- kind
- name
- signature
- path
- docstring or summary
- short code snippet
- maybe owning class or a tiny amount of structural context

Avoid whole-file payloads by default.

### Phase 3: Learned Reranking

Rerank the merged top set and keep baseline, structural, and reranker scores in
provenance.

## Evaluation Plan

Do not make reranking default-on until it wins on repo-grounded evaluation.

Measure:

- `Recall@k` for candidate generation
- `MRR@10`
- `NDCG@10`
- task success on realistic code search prompts
- median and `p95` latency
- per-query cost

Use prompts such as:

- "where is auth enforced"
- "what code creates the session token"
- exact symbol lookup
- exact path lookup
- exact error-string lookup
- ambiguous conceptual queries

## Final Answer

Should Agentic Memory add reranking?

- yes

Should the first implementation be a local cross-encoder default?

- no

What should it do instead?

- make code retrieval truly hybrid
- keep graph-aware retrieval
- add a learned reranker on top
- ship that reranker first as a hosted backend behind a pluggable interface
- support a local cross-encoder later as an optional backend

## Sources

### Internal Code References

- [`src/agentic_memory/ingestion/graph.py`](../src/agentic_memory/ingestion/graph.py)
- [`src/agentic_memory/server/code_search.py`](../src/agentic_memory/server/code_search.py)
- [`src/agentic_memory/server/tools.py`](../src/agentic_memory/server/tools.py)
- [`src/agentic_memory/server/app.py`](../src/agentic_memory/server/app.py)
- [`src/agentic_memory/server/unified_search.py`](../src/agentic_memory/server/unified_search.py)
- [`src/agentic_memory/config.py`](../src/agentic_memory/config.py)
- [`README.md`](../README.md)
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)

### External References

- Sentence Transformers cross-encoder usage:
  https://sbert.net/docs/cross_encoder/usage/usage.html
- Sentence Transformers retrieve-and-rerank guide:
  https://www.sbert.net/examples/applications/retrieve_rerank/README.html
- Sentence-BERT paper:
  https://arxiv.org/abs/1908.10084
- Passage Re-ranking with BERT:
  https://arxiv.org/abs/1901.04085
- MS MARCO cross-encoder models:
  https://www.sbert.net/docs/pretrained-models/ce-msmarco.html
- Cross-encoder inference optimization:
  https://www.sbert.net/docs/cross_encoder/usage/efficiency.html
- Neo4j vector index docs:
  https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- Neo4j GraphRAG retriever docs:
  https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html
- Neo4j hybrid retrieval article:
  https://neo4j.com/blog/developer/hybrid-retrieval-graphrag-python-package/
- Voyage reranker docs:
  https://docs.voyageai.com/docs/reranker
- Voyage rerank-2 evaluation post:
  https://blog.voyageai.com/2024/09/30/rerank-2/
- Cohere rerank overview:
  https://docs.cohere.com/docs/rerank-overview
- Cohere Rerank 4.0 release note:
  https://docs.cohere.com/changelog/rerank-v4.0
