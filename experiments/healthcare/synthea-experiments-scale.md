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

---

## Import Acceleration Plan — Preserve Semantics, Change Write Strategy

### Why this section exists

The current two-stage healthcare pipeline is now good enough to prove that:

- export-time embedding on Colab works
- VM-side graph import works
- temporal writes can be turned on when needed

But the current VM importer is still too slow for comfortable iteration at the
`20k patients` tier and becomes unrealistic for larger tiers. The goal of this
plan is to speed up import **without changing the graph semantics** that the
experiments depend on.

This means the acceleration work must preserve:

- the same `Memory:Healthcare:*` node families
- the same `Entity:*` node families
- the same relationship families
  - `HAD_ENCOUNTER`
  - `TREATED_BY`
  - `DIAGNOSED_WITH`
  - `PRESCRIBED`
  - `MENTIONS`
  - `HAS_CONDITION`
  - `HAS_OBSERVATION`
- the same content-hash identity rules
- the same embedding payload semantics
- the same downstream benchmark answers

### Current bottlenecks

The current importer path is centered on:

- `D:\code\agentic-memory\scripts\import_embedded_healthcare_chunks.py`
- `D:\code\agentic-memory\src\agentic_memory\healthcare\pipeline.py`
- `D:\code\agentic-memory\src\agentic_memory\core\graph_writer.py`
- `D:\code\agentic-memory\src\agentic_memory\healthcare\graph_writer_hc.py`

Observed write-pattern problems:

1. The importer processes one exported row at a time.
2. Each row calls `HealthcareIngestionPipeline.ingest(...)`.
3. That one ingest fans out into multiple writer calls.
4. Each writer call opens a fresh Neo4j session and runs one small query.

Approximate round-trip fan-out per record in the current design:

- encounter: memory node + patient entity + provider entity + `HAD_ENCOUNTER` + `TREATED_BY`
- condition: memory node + diagnosis entity + `MENTIONS` + `DIAGNOSED_WITH`
- medication: memory node + medication entity + `MENTIONS` + `PRESCRIBED`
- observation: memory node only
- procedure: memory node + procedure entity

This means the importer is paying transaction/session overhead constantly,
instead of amortizing it across batches.

### Schema risk to fix before parallelizing

The shared memory writer MERGEs memory nodes on:

- `(source_key, content_hash)`

But `ConnectionManager.setup_database()` currently creates:

- vector indexes
- `entity_unique` on `(Entity.name, Entity.type)`

It does **not** currently create a uniqueness constraint on:

- `(Memory.source_key, Memory.content_hash)`

That is a problem for two reasons:

1. It likely makes the hottest MERGE path slower than it should be.
2. It makes aggressive parallelism riskier because duplicate memory nodes are
   easier to create under concurrency if the graph does not enforce identity.

### Phased acceleration strategy

#### Phase A — low-risk speedup without changing ingestion semantics

Do these first:

1. Audit duplicates for `(source_key, content_hash)` on healthcare memory nodes.
2. Add a `Memory` uniqueness constraint on `(source_key, content_hash)`.
3. Refactor the writer layer so `GraphWriter` and `HealthcareGraphWriter` can
   reuse an existing Neo4j session / transaction instead of opening one per
   write call.
4. Change the importer to commit batches of rows in one transaction.

Why this phase matters:

- it keeps the existing pipeline logic almost intact
- it gives a speedup with low semantic risk
- it creates the safety rails needed for later parallel work

#### Phase B — bulk-write fast path

After Phase A is stable, build a dedicated healthcare bulk importer.

Instead of:

- `for row: pipeline.ingest(row)`

the fast path should:

1. Read a batch of exported rows.
2. Normalize them into typed row groups:
   - encounter memory rows
   - condition memory rows
   - medication memory rows
   - observation memory rows
   - procedure memory rows
   - patient entities
   - provider entities
   - diagnosis entities
   - medication entities
   - procedure entities
   - relationship rows by relationship family
3. Write each group using `UNWIND $rows AS row` Cypher batches.

This follows patterns already used elsewhere in the repo for higher-throughput
graph writes.

#### Phase C — shard by patient and run parallel workers

Once the bulk-write path exists, introduce parallel ingest by sharding exported
rows on patient identity:

- `hash(patient_id) % N`

Each worker receives a disjoint shard and imports it independently.

Why patient sharding is the right default:

- most clinical records are patient-scoped
- it minimizes overlap between workers
- it keeps one patient's timeline on one worker
- it makes debugging easier than arbitrary chunk-level parallelism

Recommended rollout:

1. validate with `N=1` worker
2. then `N=4`
3. then `N=8` if Neo4j still has headroom

#### Phase D — temporal as a backfill, not part of the hot loop

Do **not** put temporal writes in the main graph import path for scale runs.

Instead:

1. finish the graph import first
2. run a dedicated temporal backfill over the already-exported rows

This separation is important because:

- graph import and temporal posting have different bottlenecks
- mixing them makes the main ingest wall-clock much worse
- the experiments do not require temporal writes to happen synchronously with
  graph creation

### Current implementation status — 2026-04-18

This plan started as a forward-looking acceleration sketch. It now has real
implementation progress behind it.

What has landed already:

1. **Phase A landed**
   - `ConnectionManager.setup_database()` now bootstraps `memory_unique` on
     `(Memory.source_key, Memory.content_hash)` when the graph is clean.
   - the writer layer can reuse a shared Neo4j runner / transaction
   - the importer can batch row ingests into one explicit transaction
2. **Phase B landed**
   - `scripts/import_embedded_healthcare_chunks.py` supports
     `--import-mode bulk`
   - the bulk importer groups rows by healthcare record type and writes them
     with `UNWIND` batches
3. **The main hidden bottleneck was found and fixed**
   - the biggest speedup did **not** come from batching alone
   - it came from tightening the hot memory lookup path so Cypher matches stay
     label-scoped on `:Memory` and can use the right composite schema objects
4. **Phase C is partially landed**
   - the importer now supports deterministic chunk sharding with:
     - `--shard-count`
     - `--shard-index`
     - `--max-chunks`
   - a VM-side launcher now exists:
     - `D:\code\agentic-memory\scripts\run_parallel_healthcare_import.sh`
   - note: the current implementation shards by **lexical chunk position**,
     not by `hash(patient_id) % N`. That is good enough for controlled throughput
     tests, but patient-based sharding may still be worth revisiting if overlap
     or hotspot issues appear in multi-worker runs.

### Benchmark snapshot — importer iteration results

These measurements were taken during the `20k patients` (`mid`) import work.
Treat them as engineering benchmarks, not publication-ready results.

| Importer state | Graph state | Approx throughput | Notes |
|---|---|---:|---|
| Batched pipeline mode | dirty DB | ~6.5 rows/sec (~23.6k/hr) | first low-risk batching pass |
| Early bulk mode | dirty DB | ~7.5 rows/sec (~27k/hr) | modest gain; bulk path alone was not enough |
| Bulk + tightened memory lookups | dirty DB | ~299 rows/sec (~1.08M/hr) | first major breakthrough |
| Clean bulk run + `memory_unique` | clean DB | ~244–258 rows/sec (~878k–930k/hr) | current meaningful baseline |
| Clean bulk run + STU3 loader fix | clean DB | ~248.7 rows/sec (~895k/hr) | corrected full `20k` baseline with provider + medication paths restored |

Interpretation:

- Phase A helped
- early Phase B helped a little
- the lookup/schema fix changed the regime entirely
- the clean single-worker run is now fast enough that parallelism is worth
  testing on top of it, instead of being a rescue mission for a fundamentally
  broken path

### Corrected `20k` baseline — export and import timings

This is the first `20k` run that should be treated as both:

- the **accuracy** baseline for the STU3/FHIR path
- the **performance** baseline for future temporal backfills and experiment runs

Corrected export baseline (`synthea-scale-mid-fhirfix`):

- source:
  - `G:\My Drive\kubuntu\agentic-memory\big-healtcare-data\synthetic-data\fhir-output1`
- embedding provider:
  - `nemotron_local`
- embedding model:
  - `nvidia/llama-nemotron-embed-vl-1b-v2`
- patients:
  - `20000`
- rows exported:
  - `1152601`
- chunk count:
  - `145`
- chunk size target:
  - `8000`
- embed batch size:
  - `1024`
- total embed time:
  - `1356.895s` (~`22.6 min`)
- total chunk-write time:
  - `4846.503s` (~`80.8 min`)
- total export wall-clock:
  - `16283.134s` (~`271.4 min` / ~`4.52 hr`)

Corrected import baseline (`/root/import-healthcare-fhirfix.log`):

- import start:
  - `2026-04-19 23:08:37.934`
- import finish:
  - `2026-04-20 00:25:51.932`
- rows imported:
  - `1152601`
- import wall-clock:
  - `4633.998s` (~`77.2 min` / ~`1.29 hr`)
- effective import throughput:
  - ~`248.7 rows/sec`
  - ~`895k rows/hour`

Corrected graph-integrity baseline:

- total nodes:
  - `1161307`
- total relationships:
  - `645210`
- duplicate logical memory keys:
  - `0`
- memory labels:
  - `Observation: 706127`
  - `Encounter: 192816`
  - `Procedure: 96536`
  - `Condition: 73102`
  - `Medication: 56687`
- entity types:
  - `patient: 17873`
  - `provider: 17873`
  - `diagnosis: 123`
  - `medication: 99`
  - `procedure: 71`
- benchmark-critical relationships:
  - `HAD_ENCOUNTER: 192816`
  - `TREATED_BY: 192816`
  - `DIAGNOSED_WITH: 73102`
  - `MENTIONS: 129789`
  - `PRESCRIBED: 56687`

### Root cause found — semantic gap was in the STU3 FHIR loader

After the first clean `20k` import, integrity checks showed a worrying shape:

- `Medication` memory nodes were `0`
- `Provider` entities were `0`
- `TREATED_BY` and medication-side `MENTIONS` / `PRESCRIBED` paths were absent

The fast importer was **not** the cause. The exported chunk corpus was already
missing those facts.

What the due diligence found in
`D:\code\agentic-memory\src\agentic_memory\healthcare\fhir_loader.py`:

1. **Encounter provider extraction was wrong for this STU3 export**
   - the loader only read `participant[].individual`
   - the real Synthea STU3 bundles store the provider on `serviceProvider`
2. **Medication requests were losing their medication meaning**
   - the loader expected `MedicationRequest.medicationCodeableConcept`
   - the real STU3 bundles often leave that blank
   - instead, they emit a preceding standalone `Medication` resource in the
     same bundle with the RxNorm code/display

The loader therefore needed to:

- fall back to `Encounter.serviceProvider`
- preserve enough bundle order to let later `MedicationRequest` rows inherit
  code/display from the most recent `Medication` resource

That patch is now implemented in:

- `D:\code\agentic-memory\src\agentic_memory\healthcare\fhir_loader.py`
- `D:\code\agentic-memory\tests\test_fhir_loader.py`

### Verified sample rerun — patched export/import closes the missing paths

To avoid hand-waving, the patched loader was tested end to end on a fresh,
small rerun:

- export source:
  - `G:\My Drive\kubuntu\agentic-memory\big-healtcare-data\synthetic-data\synthea_1m_fhir_3_0_May_24.tar.gz`
- fresh embedded sample:
  - `50` patients
  - `2545` rows
  - output dir:
    - `D:\code\agentic-memory\.tmp-healthcare-fhirfix-sample50`
- imported into a clean Neo4j graph on the VM with the fast bulk path

Artifact-level checks on the fresh export:

- `432` encounter rows
- `432 / 432` encounters had `PROVIDER`
- `147` medication rows present in the exported chunks

Graph-level checks after the clean sample import:

- memory labels:
  - `Encounter: 432`
  - `Condition: 185`
  - `Medication: 141`
  - `Observation: 1554`
  - `Procedure: 194`
- entity types:
  - `patient: 44`
  - `provider: 44`
  - `medication: 41`
  - `diagnosis: 53`
  - `procedure: 26`
- relationship families:
  - `HAD_ENCOUNTER: 432`
  - `TREATED_BY: 432`
  - `DIAGNOSED_WITH: 185`
  - `MENTIONS: 326`
  - `PRESCRIBED: 141`
- duplicate logical memory keys:
  - `0`

Conclusion from the sample rerun:

- the missing provider and medication paths were caused by STU3 parsing
  assumptions, not the accelerated importer
- the patched loader restores those paths in both the exported chunk files and
  the imported Neo4j graph
- the existing clean `20k` import should now be treated as a **performance**
  proof, not an accuracy baseline, because it was built from the pre-fix export

### Recommended files to add or modify

Likely modifications:

- `D:\code\agentic-memory\src\agentic_memory\core\connection.py`
- `D:\code\agentic-memory\src\agentic_memory\core\graph_writer.py`
- `D:\code\agentic-memory\src\agentic_memory\healthcare\graph_writer_hc.py`
- `D:\code\agentic-memory\scripts\import_embedded_healthcare_chunks.py`

Likely new files:

- `D:\code\agentic-memory\src\agentic_memory\healthcare\bulk_rows.py`
- `D:\code\agentic-memory\src\agentic_memory\healthcare\bulk_writer.py`
- `D:\code\agentic-memory\scripts\repartition_embedded_healthcare_chunks.py`
- `D:\code\agentic-memory\scripts\backfill_healthcare_temporal.py`
- `D:\code\agentic-memory\scripts\verify_healthcare_import_parity.py`

### Verification contract — how we prove speed did not break accuracy

The current importer remains the **reference implementation** until the fast
path proves parity against it.

Important clarification:

- the fast importer is intended to preserve the **current actual healthcare
  importer semantics**
- if this differs from older aspirational notes in this document, the code path
  wins until the reference importer is changed and parity is re-established
- this matters especially for relationship families that may exist in the
  broader healthcare model but are not currently emitted by the present import
  path

#### Step 1 — create a gold-standard subset

Use fixed small subsets first:

- 100 patients
- 500 patients

Import each subset twice into separate `project_id`s:

- once with the current importer
- once with the new fast importer

#### Step 2 — compare graph counts

Compare node counts for:

- `Memory:Healthcare:Encounter`
- `Memory:Healthcare:Condition`
- `Memory:Healthcare:Medication`
- `Memory:Healthcare:Observation`
- `Memory:Healthcare:Procedure`
- `Entity:Patient`
- `Entity:Provider`
- `Entity:Diagnosis`
- `Entity:Medication`
- `Entity:Procedure`

Compare relationship counts for:

- `HAD_ENCOUNTER`
- `TREATED_BY`
- `DIAGNOSED_WITH`
- `PRESCRIBED`
- `MENTIONS`
- `HAS_CONDITION`
- `HAS_OBSERVATION`

#### Step 3 — compare exact key sets

Compare the full or sampled sets of:

- memory keys: `(source_key, content_hash)`
- entity keys: `(name, type)`

If these sets differ, the fast importer is not semantically equivalent.

#### Step 4 — compare sampled properties

For sampled memory nodes, compare:

- `project_id`
- `embedding_model`
- patient / encounter IDs
- code and description fields
- date fields
- embedding dimension

#### Step 5 — test idempotency

Run the new importer twice on the same shard and verify:

- node counts do not grow unexpectedly
- relationship counts do not grow unexpectedly
- duplicate key counts remain zero

#### Step 6 — test parallel determinism

Run the new importer with:

- 1 worker
- 4 workers
- 8 workers

The final graph should be identical across worker counts.

#### Step 7 — test benchmark parity

Run the downstream experiment stack against the reference import and the fast
import:

- `D:\code\agentic-memory\experiments\healthcare\qa_generator.py`
- `D:\code\agentic-memory\experiments\healthcare\exp2_multihop.py`
- `D:\code\agentic-memory\experiments\healthcare\exp1_temporal_decay.py`
  - after the temporal backfill path exists

Pass condition:

- same benchmark answers or the same aggregate benchmark metrics, depending on
  the experiment

Fail condition:

- any drift in benchmark output that cannot be explained by an intentional,
  documented semantic change

### Decision rule

The fast importer should only replace the current importer when all of the
following are true:

1. graph counts match on the gold-standard subsets
2. key sets match
3. reruns are idempotent
4. parallel worker counts converge to the same result
5. benchmark outputs remain equivalent

If any of those fail, the acceleration path is a performance experiment, not a
production-ready replacement.

### Post-run plan — what to do immediately after the clean `20k` import finishes

The current clean single-worker import is the first run that matters for both
throughput and accuracy work. Once it completes, do the following in order.

#### Step A — capture the final clean-run benchmark

Record:

- total imported rows
- total elapsed wall-clock time
- effective rows/sec and rows/hour
- total chunk count imported
- final graph node / relationship counts

This becomes the baseline that all future 2-worker and 4-worker tests must beat.

#### Step B — run immediate graph-integrity checks

On the finished clean graph, verify:

- `memory_unique` still exists
- duplicate `(source_key, content_hash)` counts remain zero
- counts by key labels are plausible:
  - `Memory:Healthcare:Encounter`
  - `Memory:Healthcare:Condition`
  - `Memory:Healthcare:Medication`
  - `Memory:Healthcare:Observation`
  - `Memory:Healthcare:Procedure`
  - `Entity:Patient`
  - `Entity:Provider`
  - `Entity:Diagnosis`
  - `Entity:Medication`
  - `Entity:Procedure`
- counts by benchmark-critical relationship families are plausible:
  - `HAD_ENCOUNTER`
  - `TREATED_BY`
  - `DIAGNOSED_WITH`
  - `PRESCRIBED`
  - `MENTIONS`

If these fail, stop before doing parallel runs.

#### Step C — prove fast-path parity on a small gold subset

Use a fixed small subset such as:

- 100 patients
- then 500 patients

Import each subset with:

- the current reference importer path
- the accelerated importer path

Then compare:

- node counts
- relationship counts
- key sets
- sampled properties

This is the first real semantic parity gate.

#### Step D — run clean parallel throughput tests

Only after the clean single-worker baseline and integrity checks pass:

1. wipe the graph again
2. run `2` workers with the sharded launcher
3. if the result is stable and duplicate-free, wipe again and run `4` workers

Use:

- `D:\code\agentic-memory\scripts\run_parallel_healthcare_import.sh`

Goal:

- determine whether Neo4j still scales with modest worker parallelism now that
  the hot lookup path is fixed

#### Step E — freeze the import path and move back to experiment science

Once the importer is both fast enough and parity-safe:

- stop iterating on importer mechanics
- run the healthcare QA / retrieval experiments on the clean `20k` graph
- collect the first scale-validity results that actually matter to the research
  question

#### Step F — temporal remains separate

Do **not** put temporal back into the hot graph import loop yet.

After the graph path is signed off:

- build or run the temporal-only backfill
- benchmark it independently
- keep its cost and failure modes separate from graph ingestion
- use `D:\code\agentic-memory\scripts\check_healthcare_temporal_integrity.py`
  on a smoke subset before the full temporal run
- use `D:\code\agentic-memory\scripts\run_parallel_healthcare_temporal_backfill.sh`
  for multi-worker temporal throughput tests on the VM-local SpacetimeDB

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
