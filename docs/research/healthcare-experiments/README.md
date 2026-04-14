# Healthcare Public Dataset Experiment Plan

## Why This Exists

This directory is the working plan for experiments on large, publicly
available healthcare datasets that are relevant to retrieval, memory,
prediction, and multimodal reasoning.

The goal is not to jump straight to a generic "medical AI assistant."
The goal is to build a defensible experiment ladder that:

- starts with datasets that are practical to access
- uses strong baselines and leakage controls
- tests transfer across sites and modalities
- stays relevant to Agent Memory's long-term retrieval and memory story

## Current Access Status

As of 2026-04-14, this machine does **not** show evidence of ready-to-use
MIMIC / PhysioNet access.

Checks performed:

- no repo-local MIMIC or PhysioNet configuration was found in this repo
- no `PHYSIONET_*` or `MIMIC*` environment variables were set in the current shell
- no user-home `.netrc`, `_netrc`, `.physionet`, or related credential files were found
- no obvious local download directories for MIMIC / PhysioNet corpora were found in the checked locations

Practical meaning:

- you may already have an application pending or approved with PhysioNet
- but this machine is **not yet configured** in a way that lets the repo use those datasets immediately

## Experiment Design Rules

All experiments in this directory should follow these rules:

1. Split by patient, not row.
2. Prefer time-based splits when the task models early prediction.
3. Define the prediction window before the outcome occurs.
4. Track calibration, not just AUROC.
5. Run at least one external-transfer evaluation when possible.
6. Treat summarization and generation as grounded tasks, not free-form medical advice.
7. Document every likely leakage path before training.

## Recommended Dataset Portfolio

### Structured EHR

- **MIMIC-IV**
  - role: main structured hospital / ICU training corpus
  - source: https://physionet.org/content/mimiciv/
  - notes: best anchor dataset if access is approved
- **eICU-CRD**
  - role: multicenter external validation
  - source: https://physionet.org/content/eicu-crd/
- **HiRID**
  - role: high-resolution ICU temporal validation
  - source: https://physionet.org/content/hirid/

### Clinical Notes

- **MIMIC-IV-Note**
  - role: retrieval and grounded summarization over notes
  - source: https://physionet.org/content/mimic-iv-note/2.1/

### Imaging

- **MIMIC-CXR**
  - role: chest X-ray + report multimodal experiments
  - source: https://physionet.org/content/mimic-cxr/
- **CheXpert**
  - role: external transfer for chest imaging tasks
  - source: https://aimi.stanford.edu/datasets/chexpert-chest-x-rays

### Synthetic / Low-Friction Setup

- **Synthea**
  - role: pipeline rehearsal, schema design, synthetic pretraining
  - source: https://synthetichealth.github.io/synthea/
- **CMS DE-SynPUF**
  - role: synthetic claims-style pretraining and data plumbing
  - source: https://www.cms.gov/Research-Statistics-Data-and-Systems/Downloadable-Public-Use-Files/SynPUFs/DE_Syn_PUF.html

## Experiment Roadmap

### Experiment 1: Synthetic Pipeline Rehearsal

**Goal**

Build the ingestion, feature extraction, split logic, and evaluation pipeline on
datasets that are easy to access before spending time on credentialed data.

**Datasets**

- Synthea
- CMS DE-SynPUF

**Tasks**

- patient trajectory feature extraction
- next-event or next-code prediction
- longitudinal retrieval over patient timelines

**Baselines**

- frequency baseline
- logistic regression on aggregated features
- XGBoost on visit-level aggregates

**Success criteria**

- repeatable preprocessing pipeline
- patient-level train / validation / test splits
- one working retrieval task and one working prediction task

### Experiment 2: Temporal Risk Prediction on Real EHR

**Goal**

Predict clinically important outcomes from the first `6h`, `24h`, and `48h` of
an encounter, then test how well performance transfers across datasets.

**Primary datasets**

- train: MIMIC-IV
- external validation: eICU-CRD, HiRID

**Candidate labels**

- in-hospital mortality
- ICU length-of-stay bucket
- mechanical ventilation need
- AKI or sepsis onset if labels can be defined cleanly

**Baselines**

- logistic regression
- XGBoost
- GRU-D or transformer-based sequence model

**Metrics**

- AUROC
- AUPRC
- Brier score
- calibration error
- subgroup performance slices where available

**Key risk**

- leakage from variables or notes that occur after the intended prediction window

### Experiment 3: Clinical Note Retrieval and Grounded Summarization

**Goal**

Test whether retrieval over longitudinal notes improves factual, evidence-backed
summaries compared with generation that relies on the current encounter alone.

**Datasets**

- MIMIC-IV
- MIMIC-IV-Note

**Tasks**

- retrieve relevant prior admissions or note snippets for a current case
- grounded summarization with explicit evidence references
- diagnosis-support evidence retrieval rather than diagnosis generation

**Baselines**

- BM25
- dense bi-encoder retrieval
- hybrid sparse + dense retrieval

**Metrics**

- Recall@k
- MRR / nDCG
- citation precision
- unsupported-claim rate from manual review on a sample

**Key risk**

- using note-derived labels to evaluate note generation without isolating leakage

### Experiment 4: Multimodal Chest X-Ray Grounding

**Goal**

Evaluate whether combining image, report, and structured context improves
classification, retrieval, or report-grounding tasks.

**Datasets**

- MIMIC-CXR
- CheXpert for external transfer

**Tasks**

- pathology label prediction
- report retrieval
- report section generation with grounded evidence checks

**Baselines**

- image-only model
- report-only model
- fused image + report model
- fused image + report + structured context model if linkage is clean

**Metrics**

- AUROC / AUPRC
- retrieval Recall@k
- factual consistency for generated text
- external-transfer delta

**Key risk**

- report-derived label leakage that inflates multimodal gains

### Experiment 5: Synthetic-to-Real Transfer

**Goal**

Measure whether synthetic pretraining helps real-data efficiency or whether it
is mainly useful as an engineering bootstrap.

**Datasets**

- pretrain: Synthea, CMS DE-SynPUF
- finetune / evaluate: MIMIC-IV

**Tasks**

- next-event prediction
- patient embedding learning
- retrieval over longitudinal records

**Metrics**

- downstream task performance
- sample efficiency curve
- transfer delta versus random initialization

**Key risk**

- over-claiming transfer value when synthetic data only improves pipeline maturity

## Priority Order

If time or access is limited, execute in this order:

1. Experiment 1: Synthetic Pipeline Rehearsal
2. Experiment 2: Temporal Risk Prediction
3. Experiment 3: Note Retrieval and Grounded Summarization
4. Experiment 5: Synthetic-to-Real Transfer
5. Experiment 4: Multimodal Chest X-Ray Grounding

That order gives the fastest path to:

- working infrastructure
- publishable baselines
- external validation
- product-relevant retrieval findings

## MIMIC Access Checklist

Before any MIMIC-backed work, verify the following outside the repo:

1. PhysioNet approval email exists and the correct datasets are listed.
2. Required credentialing / training is complete.
3. This machine has working download credentials configured.
4. A small test download can be performed successfully.
5. The local storage path for protected data is chosen outside this repo.
6. The repo records only the path convention and setup notes, not credentials.

## What To Add Next

When the access question is resolved, add these files in this directory:

- `DATA_ACCESS.md`
  - approval state, allowed datasets, and local storage conventions
- `EXPERIMENT_MATRIX.md`
  - one row per experiment with hypothesis, labels, splits, baselines, and metrics
- `RUNBOOK.md`
  - setup steps, preprocessing commands, and evaluation workflow

## Notes For Future Agents

- Do not assume that "publicly available" healthcare data is anonymously downloadable.
- Do not assume MIMIC access exists just because an application was submitted.
- Prefer retrieval, prediction, and grounded summarization tasks over open-ended medical chat.
- In healthcare, better ranking does not establish truth, safety, or clinical appropriateness.
