# Healthcare Experiments Dashboard - Non-Design Build Prompt

Use this file as the non-design portion of a prompt for an agent building the
healthcare experiment dashboard. It intentionally avoids visual style guidance.
It only defines data sources, schema, expected behavior, and validation.

## Goal

Build a dashboard for inspecting healthcare experiment results across retrieval
and generation arms.

The dashboard should make it easy to answer:

- Which experiment runs exist?
- How do arms compare on score, latency, token usage, and estimated cost?
- What did the model actually answer for each Exp 3 task?
- What was the parsed structured answer?
- Which tasks scored poorly and need qualitative review?
- Which context arm produced the answer?

## Canonical Repo

Local Windows repo path:

- `D:\code\agentic-memory`

Canonical healthcare experiment host:

- Hetzner VM via SSH:
  - `ssh root@178.104.198.244`

Do not use `m26-vm` for healthcare experiment data.

## Current Dashboard Data Layer

The dashboard data layer already exists. Do not rebuild it from scratch unless
there is a concrete reason.

Relevant local folder:

- `D:\code\agentic-memory\experiments\healthcare\dashboard`

Relevant files:

- `D:\code\agentic-memory\experiments\healthcare\dashboard\README.md`
- `D:\code\agentic-memory\experiments\healthcare\dashboard\normalize_results.py`
- `D:\code\agentic-memory\experiments\healthcare\dashboard\load_postgres.py`
- `D:\code\agentic-memory\experiments\healthcare\dashboard\postgres_schema.sql`
- `D:\code\agentic-memory\experiments\healthcare\dashboard\d1_schema.sql`
- `D:\code\agentic-memory\experiments\healthcare\dashboard\generated\runs.csv`
- `D:\code\agentic-memory\experiments\healthcare\dashboard\generated\task_results.csv`
- `D:\code\agentic-memory\experiments\healthcare\dashboard\generated\model_answers.csv`
- `D:\code\agentic-memory\experiments\healthcare\dashboard\generated\manifest.json`

The normalized CSVs are generated from raw result JSON by:

```powershell
.\.venv-agentic-memory\Scripts\python.exe experiments\healthcare\dashboard\normalize_results.py `
  --results-dir experiments\healthcare\results `
  --output-dir experiments\healthcare\dashboard\generated
```

## Hetzner Postgres

Postgres is running on the Hetzner VM in Docker.

Container:

- `healthcare-experiments-postgres`

Database:

- `healthcare_experiments`

User:

- `healthcare`

Password:

- `healthcare`

Host binding on Hetzner:

- `127.0.0.1:5432`

The DB is intentionally bound to loopback on the VM. If connecting from local
Windows, use an SSH tunnel:

```powershell
ssh -N -L 15432:127.0.0.1:5432 root@178.104.198.244
```

Then connect locally with:

- host: `localhost`
- port: `15432`
- database: `healthcare_experiments`
- user: `healthcare`
- password: `healthcare`
- SSL: disabled

If the dashboard app runs on the Hetzner VM, connect directly with:

- host: `127.0.0.1`
- port: `5432`
- database: `healthcare_experiments`
- user: `healthcare`
- password: `healthcare`
- SSL: disabled

## Postgres Tables

The schema lives in:

- `D:\code\agentic-memory\experiments\healthcare\dashboard\postgres_schema.sql`

Tables:

- `experiment_runs`
  - one row per run artifact
- `experiment_task_results`
  - one row per retrieval-style task result
- `experiment_model_answers`
  - one row per LLM answer, including Exp 3 raw/parsed answers and scoring

Important `experiment_model_answers` columns:

- `run_id`
- `task_index`
- `task_id`
- `patient_id`
- `snapshot_date`
- `context_arm`
- `provider`
- `requested_model`
- `resolved_model`
- `latency_ms`
- `parse_ok`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `reasoning_tokens`
- `estimated_cost_usd`
- `future_issue_recall`
- `history_relevance_recall`
- `grounded_evidence_rate`
- `hallucination_rate`
- `exp3_focus_score`
- `raw_text`
- `parsed_json`
- `usage_json`
- `score_json`

## Where Model Answers Are

In source JSON:

- `results[].result.raw_text`
  - exact model output string
- `results[].result.parsed_json`
  - structured answer extracted from model output

In Postgres:

- `experiment_model_answers.raw_text`
- `experiment_model_answers.parsed_json`

For the Exp 3 raw full-chart baseline, the important source files are:

- `D:\code\agentic-memory\experiments\healthcare\results\exp3_previsit_focus_20260422_211414.json`
- `D:\code\agentic-memory\experiments\healthcare\results\exp3_previsit_focus_20260422_211414_scored.json`

## Task And Answer-Key Files

Task files:

- `D:\code\agentic-memory\experiments\healthcare\tasks\exp1_tasks_mid_fhirfix.json`
- `D:\code\agentic-memory\experiments\healthcare\tasks\exp2_tasks_mid_fhirfix.json`
- `D:\code\agentic-memory\experiments\healthcare\tasks\exp3_tasks_mid_fhirfix.json`
- `D:\code\agentic-memory\experiments\healthcare\tasks\exp3_tasks_mid_fhirfix_rawbaseline.json`

For Exp 3, the deterministic answer key is embedded in each task under:

- `ground_truth`

Important Exp 3 task fields:

- `task_id`
- `patient_id`
- `snapshot_date`
- `chart_snapshot`
- `full_raw_chart_until_visit`
- `ground_truth`

Use `full_raw_chart_until_visit` as the serious brute-force baseline context.
Treat `chart_snapshot` as the older curated/debug context.

## Current Known Arms

Exp 3 answer arms currently loaded in Postgres:

- `curated_snapshot_oracle`
- `full_raw_chart_until_visit`
- blank/smoke rows from early smoke runs

The blank/smoke rows should either be hidden by default or grouped as smoke/dev
artifacts.

Current expected comparison query:

```sql
SELECT
  context_arm,
  count(*) AS answers,
  round(avg(total_tokens)::numeric, 1) AS avg_tokens,
  round(avg(latency_ms)::numeric, 1) AS avg_latency_ms,
  round(avg(exp3_focus_score)::numeric, 4) AS avg_focus
FROM experiment_model_answers
GROUP BY context_arm
ORDER BY context_arm;
```

Expected meaningful rows:

- `curated_snapshot_oracle`
  - `answers = 50`
  - `avg_tokens ~= 1151.5`
  - `avg_latency_ms ~= 22009.9`
  - `avg_focus ~= 0.2820`
- `full_raw_chart_until_visit`
  - `answers = 50`
  - `avg_tokens ~= 4409.4`
  - `avg_latency_ms ~= 16919.4`
  - `avg_focus ~= 0.2835`

## Minimum Dashboard Requirements

Build these data views first:

1. Run overview
   - List rows from `experiment_runs`.
   - Show `run_id`, `experiment`, `variant`, `context_arm`, `n_tasks`,
     `requested_model`, `reasoning_effort`.

2. Arm comparison
   - Aggregate `experiment_model_answers` by `context_arm`.
   - Show answer count, average focus score, average token usage, average
     latency, and average estimated cost.
   - Hide blank/smoke rows by default, but allow showing them.

3. Model answer table
   - Query `experiment_model_answers`.
   - Show task id, patient id, context arm, score, total tokens, latency, parse
     status, and finish reason.
   - Allow sorting by `exp3_focus_score`, `total_tokens`, `latency_ms`, and
     `estimated_cost_usd`.
   - Allow filtering by `run_id`, `context_arm`, `parse_ok`, and patient id.

4. Model answer detail
   - Show `raw_text`.
   - Show pretty-printed `parsed_json`.
   - Show `score_json`.
   - Show `usage_json`.
   - Include task metadata: `task_id`, `patient_id`, `snapshot_date`,
     `context_arm`, `resolved_model`.

5. Poor-task review queue
   - List lowest-scoring Exp 3 answers.
   - Suggested default:
     - `ORDER BY exp3_focus_score ASC NULLS LAST LIMIT 25`
   - Include enough fields to decide whether the issue is model quality,
     scorer weakness, missing context, or hallucination.

## Useful SQL Queries

List runs:

```sql
SELECT
  run_id,
  experiment,
  variant,
  context_arm,
  n_tasks,
  requested_model,
  reasoning_effort,
  imported_at
FROM experiment_runs
ORDER BY imported_at DESC;
```

Arm comparison:

```sql
SELECT
  context_arm,
  count(*) AS answers,
  round(avg(exp3_focus_score)::numeric, 4) AS avg_focus,
  round(avg(total_tokens)::numeric, 1) AS avg_tokens,
  round(avg(latency_ms)::numeric, 1) AS avg_latency_ms,
  round(avg(estimated_cost_usd)::numeric, 6) AS avg_cost
FROM experiment_model_answers
WHERE context_arm IS NOT NULL
  AND context_arm <> ''
GROUP BY context_arm
ORDER BY context_arm;
```

Lowest scoring answers:

```sql
SELECT
  task_id,
  patient_id,
  context_arm,
  exp3_focus_score,
  future_issue_recall,
  grounded_evidence_rate,
  hallucination_rate,
  total_tokens,
  latency_ms
FROM experiment_model_answers
WHERE exp3_focus_score IS NOT NULL
ORDER BY exp3_focus_score ASC
LIMIT 25;
```

Answer detail:

```sql
SELECT
  task_id,
  patient_id,
  context_arm,
  raw_text,
  parsed_json,
  score_json,
  usage_json
FROM experiment_model_answers
WHERE task_id = $1
ORDER BY run_id;
```

Compare one task across arms:

```sql
SELECT
  context_arm,
  exp3_focus_score,
  total_tokens,
  latency_ms,
  parsed_json
FROM experiment_model_answers
WHERE task_id = $1
ORDER BY context_arm;
```

## Data Refresh Workflow

When new result JSON files are produced:

1. Copy or sync result JSONs into:
   - `D:\code\agentic-memory\experiments\healthcare\results`
   - `/root/agentic-memory/experiments/healthcare/results`

2. Regenerate normalized CSVs from repo root:

```powershell
.\.venv-agentic-memory\Scripts\python.exe experiments\healthcare\dashboard\normalize_results.py `
  --results-dir experiments\healthcare\results `
  --output-dir experiments\healthcare\dashboard\generated
```

3. Copy generated CSVs to Hetzner:

```powershell
scp D:\code\agentic-memory\experiments\healthcare\dashboard\generated\runs.csv `
    D:\code\agentic-memory\experiments\healthcare\dashboard\generated\task_results.csv `
    D:\code\agentic-memory\experiments\healthcare\dashboard\generated\model_answers.csv `
    D:\code\agentic-memory\experiments\healthcare\dashboard\generated\manifest.json `
    root@178.104.198.244:/root/agentic-memory/experiments/healthcare/dashboard/generated/
```

4. Reload Postgres on Hetzner:

```bash
cd /root/agentic-memory

python3 experiments/healthcare/dashboard/load_postgres.py \
  --database-url postgresql://healthcare:healthcare@127.0.0.1:5432/healthcare_experiments \
  --input-dir experiments/healthcare/dashboard/generated
```

If result files were removed or duplicate cleanup is needed, truncate and reload:

```bash
docker exec healthcare-experiments-postgres psql \
  -U healthcare \
  -d healthcare_experiments \
  -c 'TRUNCATE experiment_model_answers, experiment_task_results, experiment_runs CASCADE;'

python3 experiments/healthcare/dashboard/load_postgres.py \
  --database-url postgresql://healthcare:healthcare@127.0.0.1:5432/healthcare_experiments \
  --input-dir experiments/healthcare/dashboard/generated
```

## Implementation Constraints

- Do not hardcode `m26-vm`.
- Do not expose Postgres publicly; use SSH tunnel or run the app on Hetzner.
- Do not treat smoke/dev rows as main experimental results.
- Do not collapse `raw_text` and `parsed_json`; expose both.
- Do not overwrite source result JSONs.
- Do not change benchmark runners unless required for dashboard data integrity.
- Prefer read-only dashboard access to the database.
- Keep SQL queries simple and inspectable.
- Add basic error states for database unavailable, empty result set, and malformed
  JSON fields.

## Validation Checklist

Before calling the dashboard usable:

- It connects to Postgres with the documented connection settings.
- It shows at least `12` run rows from `experiment_runs`.
- It shows at least `107` model-answer rows from `experiment_model_answers`.
- It shows exactly `50` rows for `full_raw_chart_until_visit`.
- It shows exactly `50` rows for `curated_snapshot_oracle`.
- It can open one answer and display both `raw_text` and pretty `parsed_json`.
- It can sort answers by `exp3_focus_score`.
- It can filter answers by `context_arm`.
- It can show average tokens and latency by context arm.
