-- Healthcare experiment dashboard schema for Cloudflare D1.
--
-- This is a first-pass schema for the normalized run and task rows produced by
-- normalize_results.py. It is intentionally conservative:
-- - keep the raw JSON artifacts in R2
-- - keep the query-friendly rows in D1
-- - add more columns later as the dashboard matures

CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    experiment TEXT NOT NULL,
    variant TEXT NOT NULL,
    project_id TEXT,
    timestamp TEXT,
    half_life_hours REAL,
    n_tasks INTEGER NOT NULL DEFAULT 0,
    max_edges INTEGER,
    aggregate_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiment_task_results (
    run_id TEXT NOT NULL,
    task_index INTEGER NOT NULL,
    task_id TEXT NOT NULL,
    category TEXT,
    ground_truth_json TEXT,
    retrieved_json TEXT,
    retrieved_count INTEGER NOT NULL DEFAULT 0,
    reciprocal_rank REAL NOT NULL DEFAULT 0,
    hits_at_1 INTEGER NOT NULL DEFAULT 0,
    hits_at_3 INTEGER NOT NULL DEFAULT 0,
    precision REAL NOT NULL DEFAULT 0,
    recall REAL NOT NULL DEFAULT 0,
    f1 REAL NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0,
    retrieval_config_json TEXT,
    operational_metrics_json TEXT,
    PRIMARY KEY (run_id, task_index),
    FOREIGN KEY (run_id) REFERENCES experiment_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_experiment_task_results_task_id
    ON experiment_task_results(task_id);

CREATE INDEX IF NOT EXISTS idx_experiment_runs_experiment_variant
    ON experiment_runs(experiment, variant);
