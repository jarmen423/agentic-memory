# Healthcare Experiments Plan: Synthea + Agentic Memory

## Context

Goal: validate two core architectural differentiators of the agentic-memory system using
healthcare data — **temporal decay retrieval** and **multi-hop graph reasoning** — using
Synthea synthetic data as a freely-available MIMIC-III substitute.

**Synthea data available** at:
`G:\My Drive\kubuntu\agentic-memory\big-healtcare-data\synthetic-data\`
- `synthea_2017_02_27.tar.gz` — **Use this first.** CSV format (patients, encounters,
  conditions, medications, observations, procedures). Simpler to parse, no external deps.
- `synthea_1m_fhir_3_0_May_24.tar.gz` — FHIR R3 JSON bundles, 1M patients. Reserve for
  scale/follow-on work.

**Codebase:** `D:\code\agentic-memory`  
**Note:** UI may show `agentic-memory-vm-branch` — ignore it; use the path above.

---

## Synthea vs MIMIC-III Fitness Check

| Criterion | MIMIC-III | Synthea CSV |
|---|---|---|
| Access | Credentialed (PhysioNet) | Open, no restrictions |
| Clinical notes | Real de-identified notes | **None** — embed structured prose instead |
| Temporal event sequences | Real ICU timelines | Realistic synthetic timelines |
| Diagnoses (ICD codes) | ICD-9 | SNOMED CT codes |
| Medications | Real prescriptions | Realistic synthetic |
| Suitability for Exp 1 (temporal decay) | ✅ | ✅ |
| Suitability for Exp 2 (multi-hop) | ✅ | ✅ |

**Verdict:** Synthea CSV is a valid substitute for both experiments. The lack of clinical
notes is the only gap; mitigated by constructing structured prose summaries for embedding.

---

## Experiments

### Experiment 1 — Temporal Decay for Clinical Relevance

**Hypothesis:** SpacetimeDB PPR temporal decay improves retrieval rank of the
"correct" (most recent / temporally relevant) clinical fact vs flat vector search.

**Metric:** MRR (Mean Reciprocal Rank), Hits@1, Hits@3 — decay ON vs decay OFF.
Test three half-life variants: 24h, 168h (1 week), 720h (30 days).

**Ground truth:** derived directly from CSV — no LLM needed.
Example QA pair: "Most recent active condition for patient X?" → answer = condition
with latest `START` and no `STOP` in `conditions.csv`.

### Experiment 2 — Multi-hop Clinical Reasoning

**Hypothesis:** Neo4j Cypher multi-hop traversal outperforms flat vector similarity
on multi-constraint cohort queries.

**Metric:** Precision / Recall / F1 per cohort query — Cypher vs vector-only.

**Ground truth:** derived by joining CSV tables in pure Python (no pandas).
Example query: "Providers who treated patients with hypertension AND metoprolol?"
→ join conditions → medications → encounters → providers.

---

## New Files to Create

```
src/agentic_memory/healthcare/
    __init__.py
    pipeline.py          — HealthcareIngestionPipeline(BaseIngestionPipeline)
    csv_loader.py        — SyntheaCSVLoader (reads all 7 CSV tables, no pandas)
    embed_text.py        — build_*_embed_text() per record type
    graph_writer_hc.py   — HealthcareGraphWriter (wraps GraphWriter, adds clinical rels)
    temporal_mapper.py   — condition/medication/observation → TemporalBridge claim dicts

experiments/healthcare/
    __init__.py
    qa_generator.py      — derives ground-truth QA pairs from CSV (no LLM)
    eval_runner.py       — scoring loop: MRR, Precision/Recall/F1
    exp1_temporal_decay.py   — Experiment 1 entry point
    exp2_multihop.py         — Experiment 2 entry point
    tasks/               — generated QA JSON files written here at runtime
    results/             — output JSONs written here at runtime

scripts/
    ingest_synthea.py    — CLI: extracts tarball → runs pipeline
    run_exp1.sh          — thin wrapper for exp1
    run_exp2.sh          — thin wrapper for exp2
```

### Modified Existing File (one-line addition)

- `src/agentic_memory/core/connection.py`
  → Add `healthcare_embeddings` vector index DDL to `setup_database()`, following
    identical pattern as existing three vector index statements (lines ~60-73).

---

## Implementation Details

### Ingestion Pipeline (`healthcare/pipeline.py`)

Subclasses `BaseIngestionPipeline` with `DOMAIN_LABEL = "Healthcare"`.  
Mirrors `src/agentic_memory/chat/pipeline.py` constructor and dispatch pattern.

**CSV load order** (respects foreign key dependencies):
1. patients.csv → build `patient_id → name_token` lookup dict  
2. encounters.csv → Encounter nodes + `HAD_ENCOUNTER` rels  
3. conditions.csv → Condition nodes + `DIAGNOSED_WITH` rels + temporal claims  
4. medications.csv → Medication nodes + `PRESCRIBED` rels + temporal claims  
5. observations.csv → Observation nodes + `HAS_OBSERVATION` rels  
6. procedures.csv → Procedure nodes  

**No LLM entity extraction during bulk ingestion** (cost reason: 1M rows × $0.0001 ≈ $100+).
Entities derived directly from CSV fields:

| CSV field | Entity name | Entity type |
|---|---|---|
| `PATIENT` UUID | patient UUID | `"patient"` |
| `PROVIDER` UUID | provider UUID | `"provider"` |
| `DESCRIPTION` on conditions | ICD description | `"diagnosis"` |
| `DESCRIPTION` on medications | drug name | `"medication"` |
| `DESCRIPTION` on procedures | procedure name | `"procedure"` |

LLM extraction preserved as `--enable-llm-extraction` flag for small validation runs.

**Embed text strategy** (no real clinical notes in Synthea):

```
Encounter:   "Patient {id_short} encounter on {START}. Reason: {REASONDESCRIPTION}. Provider: {PROVIDER}."
Condition:   "Condition: {DESCRIPTION} (ICD: {CODE}). Active from {START} to {STOP or ongoing}."
Observation: "Observation on {DATE}: {DESCRIPTION} = {VALUE} {UNITS}."
Medication:  "Medication: {DESCRIPTION}. Prescribed {START}, stopped {STOP or ongoing}."
Procedure:   "Procedure: {DESCRIPTION} (code: {CODE}) on {DATE}."
```

Entity-enriched text uses existing `build_embed_text()` from
`src/agentic_memory/core/entity_extraction.py`.

**content_hash for rows without UUIDs:**
Conditions, observations, procedures have no `Id` column → use:
`sha256(f"{PATIENT}:{ENCOUNTER}:{CODE}:{START}")`
Consistent with `chat/pipeline.py` pattern of `sha256(session_id:turn_index)`.

### Temporal Mapper (`healthcare/temporal_mapper.py`)

Maps Synthea rows → `TemporalBridge.ingest_claim()` kwargs dicts.

```python
condition_to_claim(row)  → { subject: patient_id, predicate: "DIAGNOSED_WITH",
                               object: description, valid_from_us: START_micros,
                               valid_to_us: STOP_micros or None, confidence: 1.0 }
medication_to_claim(row) → same pattern with "PRESCRIBED"
observation_to_claim(row) → point-in-time (no valid_to)
```

`date_to_micros()` converts `"YYYY-MM-DD"` → UTC midnight microseconds.

### Graph Writer (`healthcare/graph_writer_hc.py`)

Wraps existing `GraphWriter`. Clinical relationship methods:
- `write_diagnosed_with(patient_id, condition_node_key, valid_from, valid_to, confidence)`
- `write_prescribed(patient_id, medication_node_key, valid_from, valid_to, confidence)`
- `write_treated_by(encounter_node_key, provider_id, valid_from, confidence)`
- `write_has_encounter(patient_id, encounter_node_key, valid_from, confidence)`
- `write_has_observation(encounter_node_key, obs_node_key, valid_from, confidence)`

All use `MERGE ... ON CREATE SET ... ON MATCH SET` idempotency (same as GraphWriter).
All shadow-write to SpacetimeDB in best-effort `try/except` block.

### CLI (`scripts/ingest_synthea.py`)

```
python scripts/ingest_synthea.py \
  --data-dir "G:/My Drive/.../synthea_2017_02_27/" \
  --project-id synthea-experiment \
  --batch-size 500 \
  --max-patients 1000 \          # omit for full dataset
  --enable-temporal \            # writes to SpacetimeDB
  --enable-llm-extraction        # optional; off by default for bulk runs
```

Script calls `ConnectionManager.from_env()` (reads `NEO4J_URI`, `NEO4J_USER`,
`NEO4J_PASSWORD`) then `setup_database()` before ingestion begins.

### Benchmark QA Generator (`experiments/healthcare/qa_generator.py`)

Two generators, both pure Python / no LLM:

**Exp 1 — temporal QA pairs:**
```json
{
  "id": "EXP1-T001",
  "patient_id": "...",
  "query": "What is patient X's most recent active condition?",
  "ground_truth": "Type 2 diabetes mellitus",
  "ground_truth_date": "2015-03-12",
  "competing_conditions": ["Hypertension", "Prediabetes"],
  "as_of_date": "2017-01-01"
}
```

**Exp 2 — cohort queries:**
```json
{
  "id": "EXP2-C001",
  "query": "Which providers treated patients who had both hypertension AND were prescribed metoprolol?",
  "condition_code": "44054006",
  "medication_code": "200033",
  "ground_truth_patient_ids": ["uuid1", ...],
  "ground_truth_provider_ids": ["puuid1", ...],
  "expected_count": 42
}
```

### Multi-hop Cypher Template (Exp 2)

```cypher
MATCH (pat:Entity:Patient)-[:DIAGNOSED_WITH]->(cond:Memory:Healthcare:Condition)
WHERE cond.icd_code = $condition_code
WITH collect(pat.name) AS target_patients

MATCH (pat2:Entity:Patient)-[:PRESCRIBED]->(med:Memory:Healthcare:Medication)
WHERE med.medication_code = $medication_code
  AND pat2.name IN target_patients
WITH collect(pat2.name) AS matched_patients

MATCH (enc:Memory:Healthcare:Encounter)-[:TREATED_BY]->(prov:Entity:Provider)
MATCH (pat3:Entity:Patient)-[:HAD_ENCOUNTER]->(enc)
WHERE pat3.name IN matched_patients
RETURN DISTINCT prov.name AS provider_id, count(enc) AS encounter_count
ORDER BY encounter_count DESC
```

---

## Implementation Order (dependency-respecting)

1. `temporal_mapper.py` — pure date math, no deps
2. `embed_text.py` — pure string construction, no deps
3. `csv_loader.py` — pure CSV I/O, no deps
4. `graph_writer_hc.py` — depends on existing `GraphWriter`
5. `connection.py` DDL addition — one line alongside pipeline
6. `healthcare/pipeline.py` — depends on all above + existing core services
7. `scripts/ingest_synthea.py` — depends on pipeline
8. `qa_generator.py` — depends on csv_loader only (can parallelize with pipeline)
9. `eval_runner.py` — depends on qa_generator
10. `exp1_temporal_decay.py` — depends on eval_runner + TemporalBridge
11. `exp2_multihop.py` — depends on eval_runner + ConnectionManager

---

## Verification

1. **Ingest dry-run** (100 patients, no temporal):
   ```
   python scripts/ingest_synthea.py --max-patients 100 --project-id test
   ```
   Verify in Neo4j Browser: `MATCH (n:Memory:Healthcare) RETURN count(n)` > 0

2. **Verify relationships:**
   ```cypher
   MATCH (p:Entity:Patient)-[r:DIAGNOSED_WITH]->(c:Memory:Healthcare:Condition)
   RETURN p.name, type(r), c.description LIMIT 10
   ```

3. **Exp 1 smoke test** (10 QA pairs, 3 decay variants):
   ```
   python experiments/healthcare/exp1_temporal_decay.py --tasks 10
   ```
   Expect: `results/exp1_{timestamp}.json` with MRR values per decay variant.

4. **Exp 2 smoke test** (5 cohort queries):
   ```
   python experiments/healthcare/exp2_multihop.py --queries 5
   ```
   Expect: `results/exp2_{timestamp}.json` with Precision/Recall/F1 for Cypher vs vector.
