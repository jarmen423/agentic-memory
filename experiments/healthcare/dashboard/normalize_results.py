"""Normalize healthcare experiment result JSON into dashboard-ready tables.

This script is intentionally boring and explicit.

The experiment runners are the source of truth for benchmark execution. Their
JSON outputs already contain everything we need:

- run metadata
- aggregate metrics
- per-task results
- operational metrics such as latency and token usage

This script turns those JSON files into tidy CSV and JSON artifacts that are
easier to load into a future Cloudflare-backed dashboard or a Hetzner-hosted
Postgres dashboard.

Output files:
    runs.csv
        One row per result JSON file.
    task_results.csv
        One row per scored task.
    model_answers.csv
        One row per LLM answer when a result file contains generation outputs
        such as `Exp 3`.
    manifest.json
        Source file inventory and column discovery metadata.

The intended storage split is:
    D1 or Postgres
        Queryable rows such as runs, task results, and model answers.
    R2
        Raw result JSON, CSV exports, logs, and other large artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("healthcare_dashboard_normalize")


@dataclass
class LoadedResult:
    """In-memory representation of one experiment result JSON file."""

    source_path: Path
    metadata: dict[str, Any]
    aggregate: dict[str, Any]
    results: list[dict[str, Any]]
    payload: dict[str, Any]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Normalize healthcare experiment result JSON into dashboard-ready rows.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--results-dir",
        default="experiments/healthcare/results",
        help="Directory containing the raw experiment result JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        default="experiments/healthcare/dashboard/generated",
        help="Directory where normalized CSV/JSON files will be written.",
    )
    return parser.parse_args()


def _json_text(value: Any) -> str:
    """Serialize a value as compact JSON text for CSV storage."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _to_scalar(value: Any) -> Any:
    """Convert values into CSV-friendly scalars."""
    if isinstance(value, bool):
        return int(value)
    if value is None:
        return ""
    return value


def _load_result_file(path: Path) -> LoadedResult:
    """Load and validate one healthcare experiment result file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    aggregate = payload.get("aggregate") or {}
    results = payload.get("results") or []
    tasks_file = str(payload.get("tasks_file", ""))
    inferred_context_arm = payload.get("context_arm", "")
    if not inferred_context_arm and "exp3_tasks_mid_fhirfix_rawbaseline" in tasks_file:
        inferred_context_arm = "full_raw_chart_until_visit"
    elif not inferred_context_arm and "exp3_tasks_mid_fhirfix" in tasks_file:
        inferred_context_arm = "curated_snapshot_oracle"

    # Exp 3 generation artifacts predate the generic dashboard schema and keep
    # run metadata at the top level. Normalize those fields here so dashboard
    # code does not need experiment-specific branches.
    if not metadata and payload.get("experiment"):
        metadata = {
            "experiment": payload.get("experiment", ""),
            "variant": inferred_context_arm,
            "requested_model": payload.get("requested_model", ""),
            "reasoning_effort": payload.get("reasoning_effort", ""),
            "context_arm": inferred_context_arm,
            "n_tasks": payload.get("n_tasks", len(results)),
            "smoke": payload.get("smoke", False),
        }

    if not isinstance(metadata, dict) or not isinstance(aggregate, dict) or not isinstance(results, list):
        raise ValueError(f"Unexpected result file shape in {path}")
    return LoadedResult(
        source_path=path,
        metadata=metadata,
        aggregate=aggregate,
        results=results,
        payload=payload,
    )


def _discover_result_files(results_dir: Path) -> list[Path]:
    """Return raw result JSON files in a stable order."""
    all_files = sorted(path for path in results_dir.glob("*.json") if path.is_file())
    stems = {path.stem for path in all_files}

    # Some generation runs have both a raw artifact and a later `_scored`
    # artifact containing the same model answer plus score fields. Prefer the
    # scored copy so dashboard answer counts are not doubled.
    result_files: list[Path] = []
    for path in all_files:
        if f"{path.stem}_scored" in stems:
            continue
        result_files.append(path)
    return result_files


def _build_run_row(loaded: LoadedResult) -> dict[str, Any]:
    """Build one normalized row for the experiment run summary."""
    metadata = loaded.metadata
    aggregate = loaded.aggregate
    run_id = loaded.source_path.stem

    row: dict[str, Any] = {
        "run_id": run_id,
        "source_file": loaded.source_path.name,
        "source_path": str(loaded.source_path),
        "experiment": metadata.get("experiment", ""),
        "variant": metadata.get("variant", ""),
        "project_id": metadata.get("project_id", ""),
        "timestamp": metadata.get("timestamp", ""),
        "half_life_hours": metadata.get("half_life_hours", ""),
        "n_tasks": int(metadata.get("n_tasks", len(loaded.results) or 0)),
        "max_edges": metadata.get("max_edges", ""),
        "requested_model": metadata.get("requested_model", ""),
        "reasoning_effort": metadata.get("reasoning_effort", ""),
        "context_arm": metadata.get("context_arm", metadata.get("variant", "")),
        "aggregate_json": _json_text(aggregate),
    }

    for key, value in aggregate.items():
        row[f"agg_{key}"] = _to_scalar(value)
    return row


def _usage_metric(task: dict[str, Any], key: str) -> Any:
    """Read a token/cost usage metric from a generation task result.

    Exp 3 stores provider response details under `task["result"]["usage"]`.
    Keeping this tiny accessor separate makes the model-answer row builder easy
    to read and avoids leaking nested result-shape assumptions everywhere.
    """
    result_payload = task.get("result") or {}
    usage = result_payload.get("usage") or {}
    return usage.get(key, "")


def _build_model_answer_rows(loaded: LoadedResult) -> list[dict[str, Any]]:
    """Build rows for LLM generation outputs such as Exp 3.

    The model's answer currently lives in two places:
        - `result.raw_text`: the exact long string returned by the model
        - `result.parsed_json`: the structured answer extracted from that text

    This table makes those fields explicit so a dashboard can show the answer
    directly instead of forcing someone to inspect raw nested JSON blobs.
    """
    metadata = loaded.metadata
    run_id = loaded.source_path.stem
    rows: list[dict[str, Any]] = []

    for index, task in enumerate(loaded.results, start=1):
        result_payload = task.get("result") or {}
        if not isinstance(result_payload, dict):
            continue
        if "raw_text" not in result_payload and "parsed_json" not in result_payload:
            continue

        score = task.get("score") or {}
        parsed_json = result_payload.get("parsed_json")
        raw_usage = (result_payload.get("usage") or {}).get("raw_usage") or {}

        row: dict[str, Any] = {
            "run_id": run_id,
            "source_file": loaded.source_path.name,
            "experiment": metadata.get("experiment", ""),
            "variant": metadata.get("variant", ""),
            "context_arm": task.get("context_arm", metadata.get("context_arm", "")),
            "task_index": index,
            "task_id": task.get("task_id", ""),
            "patient_id": task.get("patient_id", ""),
            "snapshot_date": task.get("snapshot_date", ""),
            "context_chars": _to_scalar(task.get("context_chars", "")),
            "provider": result_payload.get("provider", ""),
            "requested_model": result_payload.get("requested_model", metadata.get("requested_model", "")),
            "resolved_model": result_payload.get("resolved_model", ""),
            "reasoning_effort": result_payload.get("reasoning_effort", metadata.get("reasoning_effort", "")),
            "key_slot": result_payload.get("key_slot", ""),
            "latency_ms": _to_scalar(result_payload.get("latency_ms", 0.0)),
            "finish_reason": result_payload.get("finish_reason", ""),
            "parse_ok": int(bool(result_payload.get("parse_ok", False))),
            "raw_text": result_payload.get("raw_text", ""),
            "parsed_json": _json_text(parsed_json if parsed_json is not None else {}),
            "usage_json": _json_text(result_payload.get("usage") or {}),
            "raw_usage_json": _json_text(raw_usage),
            "input_tokens": _to_scalar(_usage_metric(task, "input_tokens")),
            "output_tokens": _to_scalar(_usage_metric(task, "output_tokens")),
            "total_tokens": _to_scalar(_usage_metric(task, "total_tokens")),
            "reasoning_tokens": _to_scalar(_usage_metric(task, "reasoning_tokens")),
            "estimated_cost_usd": _to_scalar(_usage_metric(task, "estimated_cost_usd")),
            "score_json": _json_text(score),
            "future_issue_recall": _to_scalar(score.get("future_issue_recall", "")),
            "history_relevance_recall": _to_scalar(score.get("history_relevance_recall", "")),
            "grounded_evidence_rate": _to_scalar(score.get("grounded_evidence_rate", "")),
            "hallucination_rate": _to_scalar(score.get("hallucination_rate", "")),
            "exp3_focus_score": _to_scalar(score.get("exp3_focus_score", "")),
        }
        rows.append(row)

    return rows


def _build_task_rows(loaded: LoadedResult) -> list[dict[str, Any]]:
    """Build one row per scored task result."""
    metadata = loaded.metadata
    run_id = loaded.source_path.stem
    rows: list[dict[str, Any]] = []

    for index, task in enumerate(loaded.results, start=1):
        operational_metrics = task.get("operational_metrics") or {}
        retrieval_config = task.get("retrieval_config") or {}
        retrieved = task.get("retrieved") or []
        ground_truth = task.get("ground_truth") or []

        row: dict[str, Any] = {
            "run_id": run_id,
            "source_file": loaded.source_path.name,
            "experiment": metadata.get("experiment", ""),
            "variant": metadata.get("variant", ""),
            "task_index": index,
            "task_id": task.get("task_id", ""),
            "category": task.get("category", ""),
            "ground_truth_json": _json_text(ground_truth),
            "retrieved_json": _json_text(retrieved),
            "retrieved_count": len(retrieved),
            "reciprocal_rank": _to_scalar(task.get("reciprocal_rank", 0.0)),
            "hits_at_1": int(bool(task.get("hits_at_1", False))),
            "hits_at_3": int(bool(task.get("hits_at_3", False))),
            "precision": _to_scalar(task.get("precision", 0.0)),
            "recall": _to_scalar(task.get("recall", 0.0)),
            "f1": _to_scalar(task.get("f1", 0.0)),
            "latency_ms": _to_scalar(task.get("latency_ms", 0.0)),
            "retrieval_config_json": _json_text(retrieval_config),
            "operational_metrics_json": _json_text(operational_metrics),
        }

        for key, value in operational_metrics.items():
            row[f"op_{key}"] = _to_scalar(value)
        rows.append(row)

    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], preferred_columns: list[str]) -> None:
    """Write a list of dictionaries to CSV with a stable column order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(preferred_columns)

    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def normalize_results(results_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Normalize all experiment result JSON files in one directory.

    Args:
        results_dir: Directory that contains raw result JSON files.
        output_dir: Directory where normalized outputs should be written.

    Returns:
        A manifest dictionary describing the output files and discovered
        columns.
    """
    result_files = _discover_result_files(results_dir)
    if not result_files:
        raise FileNotFoundError(f"No result JSON files found in {results_dir}")

    loaded_results = [_load_result_file(path) for path in result_files]
    run_rows = [_build_run_row(loaded) for loaded in loaded_results]
    task_rows: list[dict[str, Any]] = []
    model_answer_rows: list[dict[str, Any]] = []
    for loaded in loaded_results:
        task_rows.extend(_build_task_rows(loaded))
        model_answer_rows.extend(_build_model_answer_rows(loaded))

    aggregate_columns = sorted(
        {
            key
            for row in run_rows
            for key in row.keys()
            if key.startswith("agg_")
        }
    )
    task_columns = sorted(
        {
            key
            for row in task_rows
            for key in row.keys()
            if key.startswith("op_")
        }
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "runs.csv",
        run_rows,
        preferred_columns=[
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
        ],
    )
    _write_csv(
        output_dir / "task_results.csv",
        task_rows,
        preferred_columns=[
            "run_id",
            "source_file",
            "experiment",
            "variant",
            "task_index",
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
        ],
    )
    _write_csv(
        output_dir / "model_answers.csv",
        model_answer_rows,
        preferred_columns=[
            "run_id",
            "source_file",
            "experiment",
            "variant",
            "context_arm",
            "task_index",
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
        ],
    )

    manifest = {
        "results_dir": str(results_dir),
        "output_dir": str(output_dir),
        "run_count": len(run_rows),
        "task_count": len(task_rows),
        "model_answer_count": len(model_answer_rows),
        "source_files": [path.name for path in result_files],
        "aggregate_columns": aggregate_columns,
        "task_metric_columns": task_columns,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir)

    manifest = normalize_results(results_dir=results_dir, output_dir=output_dir)
    logger.info(
        "Normalized %d run files and %d task rows into %s",
        manifest["run_count"],
        manifest["task_count"],
        output_dir,
    )
    logger.info("Wrote runs.csv, task_results.csv, model_answers.csv, and manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
