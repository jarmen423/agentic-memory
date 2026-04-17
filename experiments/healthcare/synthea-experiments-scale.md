# Healthcare Experiments Plan — Scale Validity (Plan B)

**Companion document to `synthea-experiments.md`.** Where the original plan
tests *whether the architectural ideas work at all* (algorithm validity),
this plan tests *whether they keep working at hospital scale* (scale
validity). Both plans run the same two experiments — temporal decay
retrieval and multi-hop cohort reasoning — just at very different N.

---

## 1. Why we need two plans

Scale introduces failure modes that a 2,000-patient dataset cannot reveal:

1. **Index density.** With 50× more vectors in the haystack, the "nearest"
   neighbours to a query get more crowded. An answer at rank 1 in a 2K
   corpus can sit at rank 47 in a 1M corpus. This is the single biggest
   ecological-validity concern for Experiment 1.
2. **Distractor density.** "Patients with hypertension AND lisinopril"
   returns ~50 people at 2K. At 1M it returns ~50,000. Experiment 2 now
   has to rank the *right* ones, not just *some* of them.
3. **Query latency.** Cypher multi-hop over 25M nodes is a different animal
   from over 50K nodes.
4. **Effect-size of temporal decay.** Real patients have decades of
   records; a thin synthetic timeline of 20 conditions makes decay look
   less impactful than it would in a real EHR.

Plan A establishes directional findings. Plan B stress-tests them and
produces a *scale-sensitivity curve* we can publish or hand to a research
partner. The curve is the deliverable, not a single number at full N.

---

## 2. Architectural reframe — split compute from storage

Plan A assumes one host does everything: ingestion, embedding, Neo4j, and
retrieval. That breaks down at scale because the three workloads have
very different resource profiles.

Plan B splits them explicitly:

```
  G:/Drive                Colab Pro (G4 GPU)             Host VM / Research VM
  Synthea FHIR tarball ▶  Stream + parse FHIR            Neo4j (Memory + Entity)
                          Nemotron embed on GPU           SpacetimeDB → Maincloud
                          Checkpoint to Drive
                          Resume on restart
                          │
                          ▼ (HTTP / bolt)
                          Already-embedded batches
```

- **Colab Pro** is the **embedding factory**: GPU-heavy, stateless, cheap.
  It never hosts the graph.
- **Host VM** is the **graph host**: disk-heavy, long-lived, where Neo4j
  actually lives.
- **SpacetimeDB Maincloud (free tier)** handles all temporal claims for
  every tier, including the 1M-patient tier. Claims are small rows with
  short strings and timestamps; the free tier can carry millions of them
  without trouble.

This split means we can *independently* scale compute (burst Colab G4 for
an afternoon) and storage (bigger Neo4j when credits arrive) without
re-architecting anything.

---

## 3. The scale ladder

| Tier | Patients | Purpose | Neo4j disk | Host | Embedding budget |
|---|---|---|---|---|---|
| Smoke | 2K | Plan A overlap; algorithm works at all | ~1 GB | Current VM | ~0.1 compute units |
| Mid | 20K | First directional confirmation; any performance cliffs? | ~10 GB | Current VM | ~0.5 units |
| Scale | 200K | Hospital-adjacent density; degradation trend visible | ~100 GB | Current VM (fits) or research-credit VM | ~3 units |
| Full | 1M | Only if trend demands it; "real hospital scale" claim | ~500 GB | Research-credit VM or partner infra — **deferred** | ~17 units |

All compute-unit estimates are G4 time on Colab Pro, including I/O
overhead. Total embedding compute across every tier is ~20 units, out of
your 180 available. Compute is not the bottleneck; storage is.

### What each tier answers

- **2K** — "Does decay beat flat?" "Does Cypher beat vector on AND
  queries?" Yes/no, directional.
- **20K** — "Does the 2K result hold when the index is 10× denser?"
  First confidence interval on the effect size.
- **200K** — "How does the metric degrade with N?" Slopes become
  estimable; gives a real scale curve.
- **1M** — "Does the architecture survive a full hospital-scale corpus?"
  This is the tier we defer unless the 200K curve makes it necessary.

### What the scale curve looks like

For Exp 1 (temporal decay), plot MRR-at-K vs N on a log-x axis for each
half-life variant. The publishable claim is the *shape* of the curve:
"decay maintains a positive delta over flat across three orders of
magnitude of corpus size" is a stronger claim than "decay was 0.08 MRR
better at N=2000."

For Exp 2, plot F1 vs N for both Cypher and vector-only retrieval across
each cohort query. The Cypher-vs-vector gap should widen with N because
vector search degrades faster under distractor pressure.

---

## 4. Four design decisions that make this feasible

These are not optional; each is what turns a "we can't afford this"
problem into a "we can do this on Colab Pro" problem.

### 4.1 Query-first ingestion

Instead of ingesting everything and hoping questions hit relevant
patients, we **generate QA tasks first** from the raw FHIR (streaming, no
DB) and only ingest patients that the tasks reference, plus a controlled
number of distractors. Ground truth is derivable in pure Python because
Synthea is a closed-world dataset.

Impact: a 200K-patient graph becomes a 20K-patient graph that *behaves
identically* for the metrics we care about. 10× storage reduction with no
measurement distortion.

Scientifically: we report both "real N" (number of patients ingested)
and "simulated index density N" (real N plus distractor count). This is
transparent and legitimate.

### 4.2 Nemotron open-source embeddings

Swap `EmbeddingService` default from Gemini API to the Nemotron embedding
model (likely 7B at FP16 on G4, producing 2048-dim vectors). Payoffs:

- **No per-embedding cost, no rate limits.** Gemini's API quotas make
  bulk 5M–25M embedding jobs unworkable.
- **Open-weights reproducibility.** What we compute on Colab today, our
  research partner can recompute in CDOTS AWS tomorrow without API
  drift.
- **Throughput.** G4 pushes roughly 5,000–10,000 embeddings/sec at
  batch, vs 10–50/sec against Gemini even with batching.
- **Storage.** 2048-dim embeddings vs 3072-dim saves ~30% on Neo4j
  vector index size. Matters at the 200K+ tiers.

One-time cost: drop and recreate the `healthcare_embeddings` vector
index at 2048-dim. Handled by a small addition to `setup_database()` or a
one-off migration script.

### 4.3 FHIR loader lazy iteration

The current `_iter_bundles_from_outer_tarball` calls `tarfile.getmembers()`
on the outer 30 GB archive before yielding anything, forcing a full
streaming scan from Google Drive. The patch iterates one member at a
time so `--max-patients N` truly costs only N patients' worth of I/O.

Without this patch, every smoke run costs 20+ minutes of cold-Drive
streaming. With it, a 2K smoke completes in ~60 seconds.

### 4.4 Resumable Colab ingestion

Colab Pro sessions die after ~24 hours, sometimes sooner on idle. The
Colab notebook checkpoints every 2,000 patients:

- Last completed patient ID → `drive://am-experiments/checkpoint.json`
- Already-embedded record hashes → idempotency on Neo4j writes
  (existing `MERGE ... ON CREATE SET` pattern handles this)
- Temporal claims already posted → SpacetimeDB's claim-level idempotency
  handles this if we key claims deterministically on
  `sha256(patient_id:record_type:code:start_date)`

If the session dies, the next session resumes from the last checkpoint.
No restart from zero, no double-ingestion.

---

## 5. Phases

Each phase is gated by the one before it. Do not proceed to the next
phase until the previous produces a clean, inspectable artifact.

### Phase 0 — Infrastructure prep (local, ~2 hours)

Do these before any Colab time is burned. None of them touch data.

- Patch `src/agentic_memory/healthcare/fhir_loader.py` to iterate tar
  members lazily; add a `max_patients` early-exit inside the iterator.
- Fix the SpacetimeDB `TemporalBridge` `JSONDecodeError`: capture the
  Node helper's raw stdout/stderr on a failing request, identify the
  non-JSON line (likely a banner or warning), and either strip it or
  route it to stderr. The UTF-8 encoding patch has already landed.
- Add Nemotron provider support to `EmbeddingService` at 2048-dim
  (NVIDIA `Llama-3.2-NV-EmbedQA-1B-v2` or equivalent; decide based on
  HuggingFace availability at planning time).
- Update `ConnectionManager.setup_database()` to accept a configurable
  dimension; reduce drop/create churn by leaving existing indexes alone
  unless the dim has changed.
- Author the resumable Colab notebook template as
  `experiments/healthcare/colab/run_ingest.ipynb`. Cells:
  1. Mount Drive.
  2. Load Nemotron on G4, warm-start with a 16-text batch.
  3. Read checkpoint; resume from last patient ID.
  4. Stream FHIR, embed batch, POST to Neo4j, post temporal claims.
  5. Checkpoint every 2,000 patients.
- Preflight script (already drafted as `scripts/preflight_checks.py`)
  extended to verify Nemotron loads and Neo4j accepts 2048-dim writes.

### Phase 1 — Query-first generation (local, ~30 min)

- Run QA generator in pure-stream mode against the FHIR tarball.
  Produces `experiments/healthcare/tasks/exp1_tasks.json` and
  `exp2_tasks.json` with all ground truth resolved.
- Collect the set of patient IDs referenced by tasks; call this
  `referenced_patients.json`.
- Pick distractor patients (random sample from the remaining patient
  pool) at 2×, 5×, 10×, and 50× the referenced-patient count. Save
  the cumulative patient list per tier as `tier_{N}_patients.json`.

### Phase 2 — Smoke at N=2K (Colab + VM, ~1 hour)

- `tier_2k_patients.json` → ingest via Colab notebook.
- Run Exp 1 and Exp 2 smoke. Results go to
  `experiments/healthcare/results/exp{1,2}_scale_2k.json`.
- **Gate:** Does the result match Plan A's numbers at the same N? If
  yes, the Nemotron swap is behaving. If no, investigate before scaling.

### Phase 3 — Mid at N=20K (Colab + VM, ~2 hours)

- Same pipeline, larger patient list.
- Checkpoint actually exercised here.
- Record MRR / Hits@K / P/R/F1 at N=20K.
- **Gate:** Does the directional claim from Phase 2 hold? Sanity-check
  latency; does Neo4j vector search still return inside 1s?

### Phase 4 — Scale at N=200K (Colab + VM, ~4–8 hours)

- Host VM disk usage becomes the monitor. Neo4j at ~100 GB should
  still fit on a 200 GB VM with room for the system and telemetry.
- This is the longest continuous run; plan for 1–2 session restarts.
- Checkpoint resume tested end-to-end.
- **Gate:** Plot the 3-point scale curve (2K, 20K, 200K). Is the Exp 1
  decay-vs-flat delta stable? Is the Exp 2 Cypher-vs-vector gap
  widening as expected?

### Phase 5 — Full at N=1M (deferred; separate decision)

- Only proceed if the Phase 4 curve strongly suggests the 200K→1M
  extrapolation is the material claim for publication or for the
  partnership.
- Requires a research-credit-backed VM or CDOTS partner infra. Not
  runnable on the current 200 GB VM.
- Neo4j disk: ~500 GB provisioned minimum.
- Colab budget: ~17 compute units (one afternoon).
- Cutoff: if research credits have not arrived by the time Phase 4
  completes, we ship without Phase 5 and present the 3-point curve as
  the result. Add Phase 5 later as an addendum paper / extended run.

---

## 6. Neo4j host — the one open question

Plan B is entirely runnable **up to N=200K** on the existing 200 GB VM.
For N=1M we need a bigger Neo4j host. Three paths, ordered by
preference:

1. **Research-credit GCP/AWS VM.** Spin up ~500 GB disk + 32 GB RAM,
   run the 1M ingest and experiments, shut down. ~$100–200 of credits
   for a concentrated 2–3 day window. No long-term commitment.
2. **CDOTS partner infra.** If our research partner has spare AWS
   capacity in the CDOTS project, this is the most natural home — the
   1M tier run would essentially prototype the pipeline for eventual
   MIMIC / Penn EHR deployment. Needs the partner email outcome.
3. **Temporary rented VM.** Hetzner / DigitalOcean / Linode give large
   disk at ~$0.10/GB/mo. A 500 GB disk on a reasonable VM for one week
   costs $30–50. Only worth doing if options 1 and 2 fail.

We will not decide between these until after Phase 4 completes. There
is no point provisioning large infra until we know Phase 4 confirms the
trend.

---

## 7. Non-goals / explicit deferrals

These are intentionally **out of scope** for Plan B:

- **Real clinical notes.** Synthea has no free-text notes; both
  experiments are bounded by that. Moving to MIMIC is a separate plan
  (Plan C, sketched below).
- **Latency SLOs.** We record query latency but do not tune for it. A
  real deployment would need different hardware characterization work.
- **Evaluating Nemotron variants.** We pick one and run with it. A
  comparative embedding-model study is its own paper.
- **Distributed Neo4j.** Sharding / Fabric is not explored; the 1M
  tier runs on a single fat instance.
- **Continuous ingestion.** All runs are one-shot batch ingests.
  Incremental / streaming ingestion belongs to a later milestone.

---

## 8. Plan C preview — the real-data bridge

Once Plan B completes, the natural next step is to re-run the same two
experiments on **MIMIC-III (~40K patients)** or **MIMIC-IV (~300K
patients)**. Both require PhysioNet credentialing via your partner's
institutional affiliation. Doing this inside CDOTS AWS is the right
home — it mirrors the infra that will eventually host Penn EHR data,
and it means neither the data nor the code ever moves to a third-party
managed service.

Plan C is not written yet. It will live alongside this plan once
Plan B's 20K or 200K tier is complete and we have concrete findings to
bring to the partner conversation.

---

## 9. Artifacts this plan produces

- `experiments/healthcare/results/exp1_scale_{2k,20k,200k}.json`
- `experiments/healthcare/results/exp2_scale_{2k,20k,200k}.json`
- `experiments/healthcare/results/scale_curve.png` — MRR / F1 vs N.
- `experiments/healthcare/colab/run_ingest.ipynb` — the notebook.
- `experiments/healthcare/tasks/{exp1,exp2}_tasks.json` — ground-truth
  QA with patient-ID references.
- `experiments/healthcare/tasks/tier_{2k,20k,200k}_patients.json` —
  patient list per tier for reproducibility.
- `docs/research/scale-validity-findings.md` — writeup for the partner
  conversation, summarising the curve and the methodology.

---

## 10. Execution order summary

1. Phase 0 prep (local) — hours.
2. Phase 1 QA generation (local) — minutes.
3. Phase 2 smoke at 2K (Colab + VM) — hour.
4. Phase 3 mid at 20K (Colab + VM) — hours.
5. Partner conversation + research credits application, in parallel with
   Phases 2–3.
6. Phase 4 scale at 200K (Colab + VM) — half-day.
7. Decision point: Phase 5 or ship.
8. Phase 5 full at 1M (research-credit VM), if justified.

Total elapsed time, Phases 0–4: about one focused week of engineering,
with Colab time measured in hours not days.
