# 📚 Full Podcast‑to‑Markdown Outline (≈ 40 min)

---

## 0:00 – 0:02 Intro & Premise
- **Hook:** Warehouse inventory vs. AI “semantic muddy waters”.
- **Goal:** Build a **retrieval system** for an AI‑startup’s **Agentic Memory** that is both **high‑recall** and **high‑precision** while staying **safe** for high‑stakes domains.

## 0:02 – 0:07 Why Exact Retrieval Matters
- **Hallucination control** → force the model to use a **single approved vector path**.
- **Side‑effect:** Retrieval becomes **rigid** → fails on exact‑line code or factual queries.
- **Architectural crisis:** code search needs *exact* matches, not a “box of nails”.

## 0:07 – 0:15 Two‑Stage Retrieval Architecture

### 0:07 – 0:10 Stage 1 – Candidate Generation (Recall‑Focused)
| Component | Purpose | Typical Settings |
|-----------|---------|------------------|
| **Lexical BM25** | Exact term match, O(1) lookup via inverted index. | `top_k_bm25 = 30`, stop‑word removal, n‑gram = 1‑3. |
| **Dense Vector Search** | Semantic similarity for paraphrases. | `embedding_model = text‑embedding‑ada‑002`, `faiss_index = IVF‑PQ`, `top_k_dense = 30`. |
| **Ensemble Merge** | Union of both result sets → **candidate pool K** (40‑80). | Deduplicate by doc‑ID, preserve order of higher‑scoring source. |
| **Latency Goal** | < 100 ms total for both calls (parallel async). | Use separate thread pools for BM25 & FAISS. |

### 0:10 – 0:15 Stage 2 – Re‑ranking (Precision‑Focused)
- **Cross‑Encoder (BERT‑style)** receives **[CLS] query [SEP] document [SEP]**.
- **Cross‑attention** evaluates token‑to‑token relationships → **reading‑comprehension** style verification.
- **Scoring:** sigmoid(logits) → relevance probability used to sort candidates.
- **Implementation:**
  - **Off‑the‑shelf:** `cross‑encoder/ms‑marco‑MiniLM‑L‑6‑v2` via HuggingFace Inference API.
  - **Future:** fine‑tune on **domain‑specific** data (code, legal, medical).
- **Batch size:** 16‑32 for GPU inference; fallback to CPU for low‑traffic periods.

## 0:15 – 0:22 Concrete Example – Authentication Payload Query

| Phase | Action | Result |
|------|--------|--------|
| **Query** | “How is the user authentication payload encrypted?” | – |
| **BM25** | Returns 12 docs containing the word *encrypted*. | High recall, many false positives. |
| **Dense** | Returns 18 semantically similar docs (auth, crypto). | Overlap with BM25, adds broader context. |
| **Union (K = 40)** | Mixed list includes a large legacy file where *encrypted* appears only in a comment. | True implementation doc at rank 27. |
| **Cross‑Encoder** | Computes cross‑attention; detects that *encrypted* token is unrelated to *payload* token in the legacy file. | Score for that doc drops; true implementation doc rises to rank 2. |
| **Final Top‑3** | 1️⃣ `auth_payload.py` (actual encryption routine) <br> 2️⃣ `auth_interface.py` (interface only) <br> 3️⃣ `legacy_notes.txt` (irrelevant) | User receives the correct code snippet. |

## 0:22 – 0:28 System Design & Roadmap

- **Modular API (`retrieval_service.py`)** – pluggable vector store (`Voyage`, `Cohere`, `FAISS`).
- **Configuration (`config.yaml`)**
  ```yaml
  candidate:
    bm25_top: 30
    dense_top: 30
    merge: union
  reranker:
    model: cross-encoder/ms-marco-MiniLM-L-6-v2
    batch: 16
    device: cuda
  ```
- **Phase 1 (MVP)** – hosted cross‑encoder via HuggingFace Inference API; fallback to bi‑encoder if latency > 200 ms.
- **Phase 2 (Series B)** – train a **domain‑specific cross‑encoder** on internal codebase using **hard negative mining** (randomly sampled non‑relevant docs).
- **Extensibility:** add new encoders, swap vector store, plug in **RAG** generation for non‑code queries.

## 0:28 – 0:35 Evaluation – “Holy Trinity” Metrics

| Metric | What It Measures | Formula (simplified) | Example |
|--------|------------------|----------------------|---------|
| **Recall @ K** | % of queries where the *ground‑truth* doc appears in the top‑K candidates (Stage 1). | `Recall@K = (relevant in top K) / (total queries)` | `Recall@40 = 0.78` → 78 % coverage. |
| **MRR @ 10** | Mean Reciprocal Rank of the *first* relevant result after re‑ranking. | `MRR = (1/rank₁ + 1/rank₂ + …) / N` | `MRR = 0.78` → average first‑hit at rank ≈ 1.3. |
| **NDCG @ 10** | Normalized Discounted Cumulative Gain; rewards multiple relevant docs and penalizes lower ranks. | `NDCG = DCG / IDCG`, `DCG = Σ (2^{rel‑1}) / log₂(rank+1)` | `NDCG = 0.85` → strong overall ranking quality. |

- **Team translation:**
  - *Recall* = “Did we even look at the right file?”
  - *MRR* = “How fast did the user see a correct answer?”
  - *NDCG* = “Is the whole list useful, not just the top hit?”
- **A/B test plan:** compare baseline BM25‑only vs. two‑stage on a 5 k query set (real support tickets).

## 0:35 – 0:38 Safety & Compliance in High‑Stakes Domains

| Layer | Function | Example |
|-------|----------|---------|
| **Metadata Filter** | Deterministic pre‑filter based on tags (jurisdiction, regulation, data‑sensitivity). | Query “California patient medication dosage” → drop all docs `state:NY`. |
| **Policy Engine** | Rule‑based exclusion (e.g., “no medical advice for minors”). | Block any doc lacking `FDA_approved = true`. |
| **Cross‑Encoder** | Still respects policy; masked docs receive score = 0. | Even if a legal case is semantically similar, it is filtered out. |
| **Human‑in‑the‑Loop** | Manual review of top‑N results for regulated sectors (law, healthcare). | Lawyer reviews top‑3 legal citations before presenting to user. |

- **Risk mitigation:** high‑confidence, well‑formatted answers can mislead lay users; deterministic filters guarantee **regulatory compliance** before any neural scoring.

## 0:38 – 0:40 Closing & Next Steps
- **Recap:** two‑stage pipeline, evaluation metrics, safety stack.
- **Call‑to‑action:** GitHub repo `agentic-memory-retrieval`; submit queries for live demo.
- **Teaser:** next episode on **fine‑tuning a domain‑specific cross‑encoder** and **continuous evaluation pipelines**.

---
