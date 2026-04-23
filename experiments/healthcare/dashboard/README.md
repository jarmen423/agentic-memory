# Healthcare Dashboard Prep

This folder is a first-pass storage and export layer for the healthcare
experiments.

The goal is not to change the benchmark runners. The goal is to take the
current source-of-truth result JSON files in:

- `D:\code\agentic-memory\experiments\healthcare\results`

and turn them into tidy, dashboard-ready rows that can be loaded into Postgres
on the Hetzner experiment VM, Cloudflare D1, and/or stored as raw artifacts in
R2.

## Where the model answers are

For `Exp 3`, the model answers are in each result JSON under:

- `results[].result.raw_text`
  - the exact long string returned by the model
- `results[].result.parsed_json`
  - the structured answer extracted from the raw string

For the raw full-chart baseline, the main local file is:

- `D:\code\agentic-memory\experiments\healthcare\results\exp3_previsit_focus_20260422_211414.json`

The scored copy is:

- `D:\code\agentic-memory\experiments\healthcare\results\exp3_previsit_focus_20260422_211414_scored.json`

After normalization, those answer fields are flattened into:

- `D:\code\agentic-memory\experiments\healthcare\dashboard\generated\model_answers.csv`

## What goes where

### Postgres

Use Postgres on the Hetzner VM when we want a real dashboard backend with richer
queries than CSV or D1:

- one row per experiment run
- one row per retrieval task result
- one row per model answer
- JSONB columns for parsed answers, scores, usage, and raw metrics

The schema is:

- `D:\code\agentic-memory\experiments\healthcare\dashboard\postgres_schema.sql`

The loader is:

- `D:\code\agentic-memory\experiments\healthcare\dashboard\load_postgres.py`

### D1

Use D1 for rows you want to filter, aggregate, and chart:

- one row per experiment run
- one row per task result
- one row per model answer
- optionally, later, one row per exported dashboard snapshot

This is the structured/queryable part of the dashboard stack.

### R2

Use R2 for large or immutable artifacts:

- the raw experiment result JSON files
- CSV exports generated from those JSON files
- log captures
- chart snapshots or HTML reports

This is the durable object store part of the stack.

## Result JSON shape

The current healthcare result files already have a stable shape:

- `metadata`
  - run identity and config
- `aggregate`
  - benchmark metrics and operational summaries
- `results`
  - one entry per task

Example fields you can expect:

- `metadata.experiment`
- `metadata.variant`
- `metadata.project_id`
- `aggregate.mrr`
- `aggregate.mean_latency_ms`
- `results[].task_id`
- `results[].reciprocal_rank`
- `results[].operational_metrics`

## Normalized outputs

The normalizer writes three tidy files:

- `runs.csv`
  - one row per result JSON file
- `task_results.csv`
  - one row per task result
- `model_answers.csv`
  - one row per LLM answer, including raw answer text, parsed JSON, tokens,
    latency, cost, score fields, and context metadata

It also writes:

- `manifest.json`
  - counts, discovered columns, and source file list

## Canonical command

From the repo root:

```powershell
python experiments/healthcare/dashboard/normalize_results.py `
  --results-dir experiments/healthcare/results `
  --output-dir experiments/healthcare/dashboard/generated
```

## Hetzner Postgres import

On the Hetzner experiment VM, a practical local Postgres setup is:

```bash
docker run -d \
  --name healthcare-experiments-postgres \
  --restart unless-stopped \
  -e POSTGRES_DB=healthcare_experiments \
  -e POSTGRES_USER=healthcare \
  -e POSTGRES_PASSWORD=healthcare \
  -p 127.0.0.1:5432:5432 \
  -v healthcare_experiments_pgdata:/var/lib/postgresql/data \
  postgres:16
```

Then import:

```bash
python -m pip install "psycopg[binary]"

python experiments/healthcare/dashboard/normalize_results.py \
  --results-dir experiments/healthcare/results \
  --output-dir experiments/healthcare/dashboard/generated

python experiments/healthcare/dashboard/load_postgres.py \
  --database-url postgresql://healthcare:healthcare@127.0.0.1:5432/healthcare_experiments \
  --input-dir experiments/healthcare/dashboard/generated
```

Useful first queries:

```sql
SELECT run_id, experiment, context_arm, n_tasks, requested_model
FROM experiment_runs
ORDER BY imported_at DESC;

SELECT task_id, patient_id, context_arm, exp3_focus_score, total_tokens, latency_ms
FROM experiment_model_answers
ORDER BY exp3_focus_score NULLS FIRST
LIMIT 20;

SELECT task_id, parsed_json
FROM experiment_model_answers
WHERE run_id = 'exp3_previsit_focus_20260422_211414'
LIMIT 1;
```

## D1 schema sketch

The companion SQL stub is:

- `D:\code\agentic-memory\experiments\healthcare\dashboard\d1_schema.sql`

It defines three core tables:

- `experiment_runs`
- `experiment_task_results`
- `experiment_model_answers`

The exporter emits a few extra flattened metric columns too, so the schema is
intended as a stable starting point, not a hard ceiling.

## Why this exists now

This is meant to help with a future partner-facing dashboard without forcing us
to redesign the experiments themselves.

The benchmark runners still write JSON. This layer just makes those outputs easy
to ingest elsewhere.

## Web dashboard (API + UI)

The read-only dashboard that queries this Postgres database lives in
[`web/README.md`](web/README.md) (FastAPI on loopback, optional Cloudflare Tunnel).
