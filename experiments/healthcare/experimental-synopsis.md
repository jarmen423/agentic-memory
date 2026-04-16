Experiment 1 — Temporal Decay for Clinical Relevance
What it tests: Whether SpacetimeDB's time-aware scoring (personalized PageRank with exponential decay on claim age) actually helps retrieval return the currently relevant clinical fact, vs a vanilla vector search that treats all dates equally.

Why it matters: A patient with ten years of medical history has many "hypertension diagnosed" records. The useful one for today's query is the most recent active one. A flat vector store retrieves by semantic similarity alone — it has no reason to prefer recent over old. Temporal decay is the feature that should fix this.

Setup:

Ground truth comes straight from CSV joins (no LLM judging). Example QA: "What is patient X's most recent active condition as of 2017-01-01?" → the condition with the latest START and no STOP in conditions.csv.
Three decay half-lives tested: 24h, 168h (1 week), 720h (30 days), plus a decay OFF baseline.
Each QA pair scored under all four conditions.
Metrics: MRR, Hits@1, Hits@3 — comparing decay ON (each half-life) vs decay OFF.

Success criterion: Decay ON beats decay OFF on MRR, and the optimal half-life is non-trivial (i.e., results actually depend on the half-life, proving the mechanism is doing work rather than just adding noise).

Experiment 2 — Multi-hop Clinical Reasoning
What it tests: Whether answering questions that require following relationships across the graph is materially better with Cypher traversal than with flat vector similarity, on the same corpus.

Why it matters: Questions like "Which providers treated patients who had hypertension AND were prescribed metoprolol?" require three hops: patient → condition, patient → medication, patient → encounter → provider. A vector store returns documents that look similar to the query string — it cannot actually follow the relationships. If the graph doesn't help here, it doesn't help anywhere.

Setup:

Ground truth computed in pure Python by joining CSV tables (conditions ∩ medications ∩ encounters → providers). Deterministic, exact, no LLM.
Two retrieval systems compared on identical queries:
Cypher multi-hop: structured traversal across DIAGNOSED_WITH, PRESCRIBED, HAD_ENCOUNTER, TREATED_BY edges.
Vector-only baseline: top-k nearest neighbors on the query embedding, returning whatever patient/provider nodes appear.
Metrics: Precision, Recall, F1 per cohort query, aggregated across the query set.

Success criterion: Cypher dominates vector-only, especially on recall. Vector-only is expected to occasionally get lucky on simple intersections but collapse on queries requiring ≥2 hops.

Shared infrastructure
Both experiments run against the same ingested corpus:

Neo4j on the Hetzner CPX52 (graph + vector index for the baseline)
SpacetimeDB Maincloud (temporal claims feeding Exp 1's decay scorer)
Embeddings generated on Colab Pro G4, written via Tailscale to Neo4j
Synthea CSV format (first tarball), tiers at 2K / 20K / 200K patients
What varies between tiers is not the experiments — it's the ecological validity of the results. A 2K smoke run proves the code path works. A 20K run produces statistically meaningful numbers. A 200K run tells you whether the architecture degrades at hospital scale.