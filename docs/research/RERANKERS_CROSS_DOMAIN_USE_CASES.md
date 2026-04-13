# Rerankers Across Domains

## Status

- Research date: 2026-04-12
- Scope: broader reranker use cases beyond code retrieval
- Related docs:
  - [Rerankers Primer](RERANKERS_PRIMER.md)
  - [Code Retrieval Reranking Decision Memo](RERANKING_DECISION_MEMO.md)

## Why This Exists

The decision memo in this repo is intentionally centered on Agentic Memory's
current code retrieval path. That is the most concrete product decision in this
project today.

Rerankers themselves are much broader than code search. This document explains
where rerankers fit in other domains, especially legal and healthcare, where the
cost of retrieval mistakes is higher and the retrieval problem is more than
"find something on the same topic."

## General Rule

Rerankers are broadly useful anywhere:

1. first-stage retrieval must be fast and high-recall
2. the final top results need to be much more precise

That pattern appears in:

- enterprise search
- customer support
- legal research
- healthcare retrieval
- finance and compliance
- long-document RAG
- code retrieval

The architecture is the same in all of them:

1. retrieve candidates with lexical, dense, hybrid, or graph retrieval
2. rerank those candidates for final relevance
3. return the best few results downstream

## Enterprise Search

Typical tasks:

- search across policies, internal docs, tickets, and wikis
- find the most relevant operating procedure
- surface the best troubleshooting document for a support question

Why rerankers help:

- internal corpora often contain near-duplicate pages
- titles can be similar while actual relevance differs sharply
- exact terms and concept-level similarity both matter

Typical pattern:

- lexical + dense retrieval
- rerank top `20-50`
- return top `5-10`

## Legal Use Cases

Legal retrieval is a strong reranker use case because legal corpora are full of:

- long documents
- dense jargon
- many near-neighbor passages that are topically related but not equally relevant
- subtle distinctions that materially change whether a document is actually useful

Typical legal retrieval tasks:

- finding the most relevant case for a legal question
- finding the right statute or regulation section
- ranking contract clauses by fit to an issue
- surfacing the best precedent language
- retrieving passages for litigation, diligence, or research workflows

Why rerankers help in legal:

- broad topical similarity is not enough
- exact question-to-passage fit matters
- the top few results matter a lot because review time is expensive
- long documents create many plausible but not equally useful candidates

What makes legal retrieval hard:

- jurisdiction matters
- date and version matter
- procedural posture matters
- wording differences can change meaning

That means a strong legal retrieval system usually needs:

- lexical retrieval for citations, names, clauses, and exact terms
- dense retrieval for semantic recall
- reranking for final question-passage fit
- metadata filters for jurisdiction, date, source, and document type

Important caveat:

Reranking does not establish legal validity. It does not tell you whether a case
is binding, current, applicable in the right jurisdiction, or safe to rely on
without review. It improves the ordering of candidate material.

Relevant published evidence:

- Voyage's legal retrieval work argues that general-purpose embedding models
  struggle in law and shows gains from legal-specific retrieval models.
- Voyage's rerank evaluation includes law datasets and reports that reranking
  improves first-stage retrieval across that domain.
- Harvey's public write-up with Voyage describes legal retrieval as a domain
  where standard embeddings struggle to disambiguate relevant text cleanly.

## Healthcare Use Cases

Healthcare is another strong reranker domain because the retrieval problem is
rarely just "find something related." The real question is usually "find the
most applicable evidence, protocol, or guideline for this task."

Typical healthcare retrieval tasks:

- surfacing the right guideline section for a condition or workflow
- retrieving relevant evidence from medical literature
- ranking chart-note or discharge-summary passages for a downstream assistant
- finding the best internal protocol text
- triaging medical QA corpora for staff-facing tools

Why rerankers help in healthcare:

- terminology is specialized and abbreviation-heavy
- many passages are broadly related but only one is operationally or clinically on-point
- long documents and semi-structured records are common
- weakly relevant top results are costly in high-stakes settings

What makes healthcare retrieval hard:

- source authority matters
- recency matters
- guideline versioning matters
- patient context matters
- unsupported extrapolation is dangerous

That means a strong healthcare retrieval system usually needs:

- source filtering and provenance
- temporal or version-aware retrieval
- lexical retrieval for exact terms, drug names, and codes
- dense retrieval for concept-level recall
- reranking for final question-evidence fit
- human review or strong abstention behavior where stakes are high

Important caveat:

Reranking does not establish medical correctness, clinical appropriateness, or
regulatory sufficiency. It is one retrieval quality layer, not a safety layer by
itself.

Relevant published evidence:

- Voyage's published cross-domain retrieval evaluations include medical-style
  datasets such as medical QA and instruction corpora, which is direct evidence
  that retrieval and reranking quality are being tested outside code and generic
  web text.

## Finance and Compliance

Typical tasks:

- rank the most relevant filing passage for a finance question
- surface the best compliance policy section
- find the best match for an audit or control query

Why rerankers help:

- corpora often contain many similar disclosures
- exact section fit matters more than broad topical overlap
- long, semi-structured documents are common

The operating lesson is the same:

- rerankers help with final relevance
- metadata and source controls still matter

## Long Documents and Semi-Structured Data

Rerankers are especially useful when:

- documents are long
- candidate passages are serialized from structured records
- the answer-relevant fields are sparse relative to total document length

This is why vendor docs increasingly emphasize:

- larger reranker context windows
- support for YAML or JSON-like candidate formatting
- evaluation on long-document and semi-structured retrieval tasks

## High-Stakes Domains Need More Than Better Ranking

Legal and healthcare illustrate a broader system rule:

- the higher the stakes, the less useful "better semantic relevance" is on its own

In high-stakes domains, a strong retrieval stack usually combines:

- metadata filtering
- lexical retrieval
- dense retrieval
- reranking
- provenance
- temporal awareness when versions matter
- fallback or abstention rules
- human review where appropriate

Rerankers help with relevance. They do not replace these controls.

## Practical Takeaway

If you are building:

- a code assistant
- a legal research assistant
- a healthcare retrieval assistant
- an enterprise knowledge search system

the core architecture is still the same:

1. build a strong candidate generator
2. use reranking for final precision
3. add domain-specific controls for authority, freshness, filtering, and safety

## Sources

- Voyage legal retrieval article:
  https://blog.voyageai.com/2024/04/15/domain-specific-embeddings-and-retrieval-legal-edition-voyage-law-2/
- Harvey + Voyage legal retrieval article:
  https://blog.voyageai.com/2024/07/31/harvey-partners-with-voyage-to-build-custom-legal-embeddings/
- Voyage rerank-2 evaluation article:
  https://blog.voyageai.com/2024/09/30/rerank-2/
- Voyage reranker docs:
  https://docs.voyageai.com/docs/reranker
- Cohere advanced retrieval launch note:
  https://docs.cohere.com/changelog/advanced-retrieval-launch
- Cohere rerank overview:
  https://docs.cohere.com/docs/rerank-overview
- Cohere Rerank 4.0 release note:
  https://docs.cohere.com/changelog/rerank-v4.0
