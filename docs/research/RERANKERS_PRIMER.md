# Rerankers Primer

## Status

- Research date: 2026-04-12
- Scope: retrieval systems, RAG, code search, and the role of rerankers
- Audience: engineers designing Agentic Memory retrieval

## Executive Summary

Rerankers are second-stage retrieval models. They do not search the whole
corpus. They take a small candidate set returned by first-stage retrieval and
reorder it more accurately.

In practice:

- lexical retrieval is good at exact terms
- dense retrieval is good at semantic similarity
- graph retrieval is good at structure
- rerankers are good at final query-document relevance

The most common reranker architecture is a cross-encoder. That distinction
matters:

- a reranker is the job
- a cross-encoder is one common way to do the job

For code retrieval, rerankers are useful because they can read the query and the
candidate snippet together and decide whether the candidate actually answers the
question. They are not a replacement for good candidate generation.

## What Is a Reranker?

A reranker:

1. receives a query
2. receives a small list of candidate documents or passages
3. scores each candidate for relevance to that query
4. returns a better final ordering

The standard pattern is:

1. retrieve broadly and cheaply
2. rerank narrowly and accurately

## Why Rerankers Exist

First-stage retrieval has to be cheap enough to search large corpora.

That usually means:

- BM25 or full-text search
- vector search over precomputed embeddings
- hybrid lexical plus dense retrieval

These methods are strong, but they are optimized for recall and speed. They are
not always the best final judge of relevance. A reranker adds that final judge.

## Retrieval Background

### Lexical Retrieval

Lexical retrieval matches literal terms.

Strengths:

- identifiers
- file paths
- API names
- error strings
- dates and version numbers

Weaknesses:

- poor on paraphrases and synonyms

### Dense Retrieval

Dense retrieval encodes the query and documents separately into vectors and then
compares those vectors.

Strengths:

- semantic similarity
- paraphrases
- concept-level matching

Weaknesses:

- ANN search is approximate
- exact token matching is not guaranteed
- vector similarity is not the same as final task relevance

### Hybrid Retrieval

Hybrid retrieval combines lexical and dense retrieval.

Strength:

- usually better candidate recall than either one alone

### Graph Retrieval or Graph Reranking

Graph-based retrieval uses structure such as:

- imports
- containment
- ownership
- call paths

This is useful when the relationships themselves carry meaning. It is different
from learned reranking because it is not usually a learned query-document
scoring model.

## What Is a Cross-Encoder?

A cross-encoder jointly processes a query and a candidate document in one model
pass and emits one relevance score.

Instead of computing:

- `embedding(query)`
- `embedding(document)`

separately, it computes something closer to:

- `score(query, document)`

That joint processing is why cross-encoders are usually stronger rerankers than
bi-encoder retrieval alone.

## Mechanistic Explanation

At a high level, a cross-encoder reranker does this:

1. tokenize the query
2. tokenize one candidate document
3. concatenate them into one input pair
4. run the pair through a transformer together
5. emit one scalar relevance score
6. repeat for each candidate
7. sort by score

Conceptually the input looks like:

```text
[CLS] query [SEP] candidate [SEP]
```

The important property is that the query tokens and candidate tokens are in the
same transformer context. That lets the model use cross-attention between them.

This gives it much finer judgment than independent vector similarity.

It can learn patterns like:

- this symbol directly answers the question
- this snippet mentions the same API, but in the wrong context
- this file is nearby in meaning, but the symbol type is wrong
- this result matches exact terms and the surrounding semantics

## Bi-Encoder vs Cross-Encoder

### Bi-Encoder

Bi-encoders encode queries and documents separately. That makes them indexable
and scalable.

Good for:

- millions of documents
- fast first-stage retrieval

### Cross-Encoder

Cross-encoders score one query-document pair at a time.

Good for:

- tens of candidates
- strong final ranking

Bad for:

- searching the entire corpus directly

That is why production systems usually use both.

## Why Rerankers Improve Results

Rerankers often fix first-stage errors such as:

- semantically close but task-irrelevant passages
- exact-token matches in the wrong context
- broad file matches instead of the exact symbol
- structurally related nodes that do not actually answer the query

Official Sentence Transformers guidance explicitly recommends "retrieve and
rerank": retrieve a larger candidate set, then use a cross-encoder for better
final ranking.

## What Rerankers Cannot Fix

Rerankers cannot recover candidates that were never retrieved.

If the right answer is missing from the candidate set, reranking cannot help.

This leads to the most important design rule:

- candidate generation quality still matters more than reranker quality

Common failure cases rerankers cannot repair:

- ANN search missed the answer
- lexical search was never consulted for exact identifiers
- chunking hid the relevant evidence
- the candidate text omitted the most informative fields

## Rerankers for Code Retrieval

Code retrieval depends on mixed signals:

- exact identifiers and paths
- natural-language descriptions
- symbol kind: file vs class vs function
- structural location in the codebase

That usually argues for:

- hybrid candidate retrieval
- structured candidate serialization
- reranking over symbol-level or chunk-level candidates

For code retrieval, a compact candidate card is often better than a raw whole
file.

Example:

```yaml
kind: function
name: authenticate_user
signature: src/auth/service.py:AuthService.authenticate_user
path: src/auth/service.py
docstring: Validate credentials and return a session token.
snippet: |
  def authenticate_user(self, email: str, password: str) -> Session:
      ...
```

## Common Reranker Options

### Local Cross-Encoders

Pros:

- private
- no per-query API cost

Cons:

- local model serving complexity
- CPU or GPU tuning
- often smaller context windows than hosted APIs

### Hosted Rerank APIs

Pros:

- easier integration
- no local inference stack
- often larger context windows and strong retrieval quality

Cons:

- network latency
- provider cost
- privacy and governance concerns

## Latency and Context Tradeoffs

Rerankers are pairwise scorers. If you rerank 40 candidates, you pay for 40
query-document comparisons.

Practical rules:

- keep candidate sets bounded
- keep candidates compact
- rerank only top `k`

Typical interactive pattern:

- retrieve `20-100`
- rerank `20-40`
- return `5-10`

## Evaluation

Do not judge rerankers only by intuition.

Measure:

- `Recall@k` for candidate generation
- `MRR@10`
- `NDCG@10`
- realistic task success
- latency and cost

Use query sets that include:

- conceptual code questions
- exact symbol lookup
- exact path lookup
- debugging and "where is this enforced?" questions

## Practical Design Rules

1. Treat reranking as second-stage ranking, not the primary search engine.
2. Improve candidate generation first if recall is weak.
3. Use hybrid retrieval when exact tokens matter.
4. Serialize candidates compactly and consistently.
5. Keep reranking optional behind an interface.
6. Measure quality and latency before making it default.

## References

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
- Neo4j vector index documentation:
  https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- Neo4j GraphRAG retriever docs:
  https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html
- Neo4j hybrid retrieval article:
  https://neo4j.com/blog/developer/hybrid-retrieval-graphrag-python-package/
- Voyage reranker docs:
  https://docs.voyageai.com/docs/reranker
- Voyage rerank-2 evaluation article:
  https://blog.voyageai.com/2024/09/30/rerank-2/
- Cohere rerank overview:
  https://docs.cohere.com/docs/rerank-overview
- Cohere Rerank 4.0 release note:
  https://docs.cohere.com/changelog/rerank-v4.0

## Related Internal Document

- [Code Retrieval Reranking Decision Memo](RERANKING_DECISION_MEMO.md)
