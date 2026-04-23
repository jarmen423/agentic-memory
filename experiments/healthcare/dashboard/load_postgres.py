"""Load normalized healthcare experiment dashboard rows into Postgres.

The experiment result JSON files remain the source of truth. This loader imports
the normalized CSV projection produced by `normalize_results.py` into a local or
remote Postgres database so dashboards can query runs, retrieval rows, and model
answers directly.

Typical Hetzner flow:
    python experiments/healthcare/dashboard/normalize_results.py \
        --results-dir experiments/healthcare/results \
        --output-dir experiments/healthcare/dashboard/generated

    python experiments/healthcare/dashboard/load_postgres.py \
        --database-url postgresql://healthcare:healthcare@127.0.0.1:5432/healthcare_experiments \
        --input-dir experiments/healthcare/dashboard/generated

Dependencies:
    Requires `psycopg` v3. Install with:
        python -m pip install "psycopg[binary]"
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - exercised only in missing-env setup
    raise SystemExit(
        "Missing dependency: install psycopg with `python -m pip install \"psycopg[binary]\"`"
    ) from exc


SCHEMA_PATH = Path(__file__).with_name("postgres_schema.sql")


RUN_COLUMNS = [
    "run_id",
    "source_file",
    "source_path",
    "experiment",
    "variant",
    "project_id",
    "timestamp",
    "half_life_hours",
    "n_tasks",
    "max_edges",
    "requested_model",
    "reasoning_effort",
    "context_arm",
    "aggregate_json",
]

TASK_RESULT_COLUMNS = [
    "run_id",
    "task_index",
    "source_file",
    "experiment",
    "variant",
    "task_id",
    "category",
    "ground_truth_json",
    "retrieved_json",
    "retrieved_count",
    "reciprocal_rank",
    "hits_at_1",
    "hits_at_3",
    "precision",
    "recall",
    "f1",
    "latency_ms",
    "retrieval_config_json",
    "operational_metrics_json",
]

MODEL_ANSWER_COLUMNS = [
    "run_id",
    "task_index",
    "source_file",
    "experiment",
    "variant",
    "context_arm",
    "task_id",
    "patient_id",
    "snapshot_date",
    "context_chars",
    "provider",
    "requested_model",
    "resolved_model",
    "reasoning_effort",
    "key_slot",
    "latency_ms",
    "finish_reason",
    "parse_ok",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
    "estimated_cost_usd",
    "future_issue_recall",
    "history_relevance_recall",
    "grounded_evidence_rate",
    "hallucination_rate",
    "exp3_focus_score",
    "raw_text",
    "parsed_json",
    "usage_json",
    "raw_usage_json",
    "score_json",
]

JSON_COLUMNS = {
    "aggregate_json",
    "ground_truth_json",
    "retrieved_json",
    "retrieval_config_json",
    "operational_metrics_json",
    "parsed_json",
    "usage_json",
    "raw_usage_json",
    "score_json",
}

INTEGER_COLUMNS = {
    "n_tasks",
    "max_edges",
    "task_index",
    "retrieved_count",
    "hits_at_1",
    "hits_at_3",
    "context_chars",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
}

FLOAT_COLUMNS = {
    "half_life_hours",
    "reciprocal_rank",
    "precision",
    "recall",
    "f1",
    "latency_ms",
    "estimated_cost_usd",
    "future_issue_recall",
    "history_relevance_recall",
    "grounded_evidence_rate",
    "hallucination_rate",
    "exp3_focus_score",
}

BOOLEAN_COLUMNS = {"parse_ok"}

EMPTY_STRING_COLUMNS = {"raw_text"}


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Load normalized healthcare experiment dashboard CSVs into Postgres.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="Postgres connection URL.",
    )
    parser.add_argument(
        "--input-dir",
        default="experiments/healthcare/dashboard/generated",
        help="Directory containing runs.csv, task_results.csv, and model_answers.csv.",
    )
    parser.add_argument(
        "--schema-file",
        default=str(SCHEMA_PATH),
        help="SQL schema file to apply before importing rows.",
    )
    return parser.parse_args()


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into dictionaries, returning an empty list if absent."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _coerce_value(column: str, value: str) -> Any:
    """Coerce CSV text into the type expected by the Postgres schema."""
    if column in EMPTY_STRING_COLUMNS:
        return value
    if value == "":
        return None
    if column in JSON_COLUMNS:
        return Jsonb(json.loads(value))
    if column in INTEGER_COLUMNS:
        return int(float(value))
    if column in FLOAT_COLUMNS:
        return float(value)
    if column in BOOLEAN_COLUMNS:
        return value in {"1", "true", "True", "yes", "YES"}
    return value


def _row_values(row: dict[str, str], columns: list[str]) -> list[Any]:
    """Return a row's values in schema column order."""
    return [_coerce_value(column, row.get(column, "")) for column in columns]


def _upsert_rows(conn: psycopg.Connection[Any], table: str, columns: list[str], rows: list[dict[str, str]]) -> int:
    """Upsert rows into a table using the table's primary key conflict target."""
    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    quoted_columns = ", ".join(columns)
    update_columns = [column for column in columns if column not in {"run_id", "task_index"}]
    set_clause = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    conflict_target = "(run_id)" if table == "experiment_runs" else "(run_id, task_index)"
    sql = (
        f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders}) "
        f"ON CONFLICT {conflict_target} DO UPDATE SET {set_clause}"
    )

    with conn.cursor() as cur:
        cur.executemany(sql, [_row_values(row, columns) for row in rows])
    return len(rows)


def load_dashboard_rows(database_url: str, input_dir: Path, schema_file: Path) -> dict[str, int]:
    """Apply schema and load normalized CSV rows into Postgres.

    Args:
        database_url: Postgres connection URL.
        input_dir: Directory containing normalized CSV files.
        schema_file: SQL file that creates the dashboard tables.

    Returns:
        Counts of rows imported per table.
    """
    runs = _read_csv(input_dir / "runs.csv")
    task_results = _read_csv(input_dir / "task_results.csv")
    model_answers = _read_csv(input_dir / "model_answers.csv")

    with psycopg.connect(database_url) as conn:
        conn.execute(schema_file.read_text(encoding="utf-8"))
        counts = {
            "experiment_runs": _upsert_rows(conn, "experiment_runs", RUN_COLUMNS, runs),
            "experiment_task_results": _upsert_rows(
                conn,
                "experiment_task_results",
                TASK_RESULT_COLUMNS,
                task_results,
            ),
            "experiment_model_answers": _upsert_rows(
                conn,
                "experiment_model_answers",
                MODEL_ANSWER_COLUMNS,
                model_answers,
            ),
        }
        conn.commit()
    return counts


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    counts = load_dashboard_rows(
        database_url=args.database_url,
        input_dir=Path(args.input_dir),
        schema_file=Path(args.schema_file),
    )
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
