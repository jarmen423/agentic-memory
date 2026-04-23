-- Healthcare experiment dashboard schema for Postgres.
--
-- This schema is intended for the Hetzner experiment VM. The benchmark runners
-- still write JSON artifacts as the source of truth; Postgres gives us a
-- queryable/dashboard-friendly projection over those artifacts.
--
-- Suggested database name:
--   healthcare_experiments

CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    source_path TEXT,
    experiment TEXT NOT NULL,
    variant TEXT,
    project_id TEXT,
    timestamp TIMESTAMPTZ,
    half_life_hours DOUBLE PRECISION,
    n_tasks INTEGER NOT NULL DEFAULT 0,
    max_edges INTEGER,
    requested_model TEXT,
    reasoning_effort TEXT,
    context_arm TEXT,
    aggregate_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS experiment_task_results (
    run_id TEXT NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    task_index INTEGER NOT NULL,
    source_file TEXT,
    experiment TEXT,
    variant TEXT,
    task_id TEXT NOT NULL,
    category TEXT,
    ground_truth_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieved_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieved_count INTEGER NOT NULL DEFAULT 0,
    reciprocal_rank DOUBLE PRECISION NOT NULL DEFAULT 0,
    hits_at_1 INTEGER NOT NULL DEFAULT 0,
    hits_at_3 INTEGER NOT NULL DEFAULT 0,
    precision DOUBLE PRECISION NOT NULL DEFAULT 0,
    recall DOUBLE PRECISION NOT NULL DEFAULT 0,
    f1 DOUBLE PRECISION NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    retrieval_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    operational_metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, task_index)
);

CREATE TABLE IF NOT EXISTS experiment_model_answers (
    run_id TEXT NOT NULL REFERENCES experiment_runs(run_id) ON DELETE CASCADE,
    task_index INTEGER NOT NULL,
    source_file TEXT,
    experiment TEXT,
    variant TEXT,
    context_arm TEXT,
    task_id TEXT NOT NULL,
    patient_id TEXT,
    snapshot_date DATE,
    context_chars INTEGER,
    provider TEXT,
    requested_model TEXT,
    resolved_model TEXT,
    reasoning_effort TEXT,
    key_slot TEXT,
    latency_ms DOUBLE PRECISION,
    finish_reason TEXT,
    parse_ok BOOLEAN NOT NULL DEFAULT false,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    reasoning_tokens INTEGER,
    estimated_cost_usd DOUBLE PRECISION,
    future_issue_recall DOUBLE PRECISION,
    history_relevance_recall DOUBLE PRECISION,
    grounded_evidence_rate DOUBLE PRECISION,
    hallucination_rate DOUBLE PRECISION,
    exp3_focus_score DOUBLE PRECISION,
    raw_text TEXT NOT NULL DEFAULT '',
    parsed_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    usage_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_usage_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    score_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, task_index)
);

CREATE INDEX IF NOT EXISTS idx_experiment_runs_experiment_variant
    ON experiment_runs(experiment, variant);

CREATE INDEX IF NOT EXISTS idx_experiment_task_results_task_id
    ON experiment_task_results(task_id);

CREATE INDEX IF NOT EXISTS idx_experiment_model_answers_task_id
    ON experiment_model_answers(task_id);

CREATE INDEX IF NOT EXISTS idx_experiment_model_answers_patient_id
    ON experiment_model_answers(patient_id);

CREATE INDEX IF NOT EXISTS idx_experiment_model_answers_context_arm
    ON experiment_model_answers(context_arm);

CREATE INDEX IF NOT EXISTS idx_experiment_model_answers_score
    ON experiment_model_answers(exp3_focus_score DESC NULLS LAST);
