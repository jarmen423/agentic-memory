"""Evaluation runner and scoring utilities for healthcare experiments.

Provides:
  - EvalResult: dataclass for a single scored task result
  - score_temporal_task: MRR / Hits@K scoring for Experiment 1
  - score_cohort_task: Precision / Recall / F1 scoring for Experiment 2
  - ExperimentRunner: base class that runs a list of tasks and collects results
  - TemporalExperimentRunner: Experiment 1 runner (decay ON vs OFF)
  - CohortExperimentRunner: Experiment 2 runner (Cypher vs vector)

Metric definitions:
  Experiment 1 (Temporal Decay):
    - MRR (Mean Reciprocal Rank): For each task, retrieve top-K nodes by
      relevance score. Find the rank of the ground-truth answer. 1/rank for
      that task; average over all tasks.
    - Hits@K: Binary 1/0 whether ground truth appears in top-K.

  Experiment 2 (Multi-hop):
    - Precision = |retrieved ∩ ground_truth| / |retrieved|
    - Recall    = |retrieved ∩ ground_truth| / |ground_truth|
    - F1        = 2 * P * R / (P + R)
    - Computed over provider_ids (the terminal node of the multi-hop query).

Role in the project:
  Imported by exp1_temporal_decay.py and exp2_multihop.py. Can also be used
  standalone to re-score previously collected raw retrieval outputs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Result dataclasses
# ------------------------------------------------------------------


@dataclass
class EvalResult:
    """Scored result for a single benchmark task.

    Attributes:
        task_id: ID from the task dict (e.g. "EXP1-T0001").
        category: Task category string.
        retrieved: List of retrieved answer strings (ordered by relevance).
        ground_truth: Expected correct answer(s) as a list.
        reciprocal_rank: 1/rank if ground truth found, else 0.0.
        hits_at_1: True if ground truth is the top-1 result.
        hits_at_3: True if ground truth is in top-3 results.
        precision: For cohort tasks: |retrieved ∩ ground_truth| / |retrieved|.
        recall: For cohort tasks: |retrieved ∩ ground_truth| / |ground_truth|.
        f1: Harmonic mean of precision and recall.
        retrieval_config: Dict describing the retrieval settings (e.g.
            {"half_life_hours": 168, "method": "temporal_decay"}).
        latency_ms: Retrieval wall-clock time in milliseconds.
    """

    task_id: str
    category: str
    retrieved: list[str]
    ground_truth: list[str]
    reciprocal_rank: float = 0.0
    hits_at_1: bool = False
    hits_at_3: bool = False
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0


# ------------------------------------------------------------------
# Scoring functions
# ------------------------------------------------------------------


def score_temporal_task(
    task: dict[str, Any],
    retrieved: list[str],
    retrieval_config: dict[str, Any],
    latency_ms: float = 0.0,
) -> EvalResult:
    """Score a single Experiment 1 (temporal QA) task.

    For "temporal_recency" tasks: checks if the ground_truth string appears
    in the retrieved list and at what rank.
    For "temporal_active_medications" tasks: checks overlap between
    retrieved items and ground_truth_medications list.

    Args:
        task: Task dict from QA generator (Experiment 1 schema).
        retrieved: Ordered list of retrieved answer strings, most relevant first.
        retrieval_config: Dict describing retrieval parameters (e.g. half_life_hours).
        latency_ms: Retrieval latency in milliseconds.

    Returns:
        Scored EvalResult.
    """
    task_id = task.get("id", "unknown")
    category = task.get("category", "unknown")

    # Determine ground truth list based on category
    if category == "temporal_recency":
        ground_truth = [task.get("ground_truth", "")]
    elif category == "temporal_active_medications":
        ground_truth = task.get("ground_truth_medications", [])
    else:
        ground_truth = [task.get("ground_truth", "")]

    gt_lower = {g.lower() for g in ground_truth if g}
    retrieved_lower = [r.lower() for r in retrieved]

    # MRR: find lowest rank of any ground-truth item
    rr = 0.0
    for rank, item in enumerate(retrieved_lower, start=1):
        if item in gt_lower:
            rr = 1.0 / rank
            break

    hits_1 = bool(retrieved_lower[:1]) and (retrieved_lower[0] in gt_lower)
    hits_3 = any(item in gt_lower for item in retrieved_lower[:3])

    # Precision/Recall over the full retrieved set (for multi-answer tasks)
    retrieved_set = set(retrieved_lower)
    intersection = retrieved_set & gt_lower
    precision = len(intersection) / len(retrieved_set) if retrieved_set else 0.0
    recall = len(intersection) / len(gt_lower) if gt_lower else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return EvalResult(
        task_id=task_id,
        category=category,
        retrieved=retrieved,
        ground_truth=ground_truth,
        reciprocal_rank=rr,
        hits_at_1=hits_1,
        hits_at_3=hits_3,
        precision=precision,
        recall=recall,
        f1=f1,
        retrieval_config=retrieval_config,
        latency_ms=latency_ms,
    )


def score_cohort_task(
    task: dict[str, Any],
    retrieved_provider_ids: list[str],
    retrieval_config: dict[str, Any],
    latency_ms: float = 0.0,
) -> EvalResult:
    """Score a single Experiment 2 (multi-hop cohort) task.

    Computes Precision / Recall / F1 over provider_ids, comparing the
    retrieved set to the ground_truth_provider_ids from the task dict.

    Args:
        task: Task dict from QA generator (Experiment 2 schema).
        retrieved_provider_ids: List of provider UUID strings returned by
            the retrieval method being evaluated.
        retrieval_config: Dict describing retrieval parameters
            (e.g. {"method": "cypher_multihop"}).
        latency_ms: Retrieval latency in milliseconds.

    Returns:
        Scored EvalResult.
    """
    task_id = task.get("id", "unknown")
    gt_providers = set(task.get("ground_truth_provider_ids", []))
    retrieved_set = set(retrieved_provider_ids)

    intersection = retrieved_set & gt_providers
    precision = len(intersection) / len(retrieved_set) if retrieved_set else 0.0
    recall = len(intersection) / len(gt_providers) if gt_providers else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return EvalResult(
        task_id=task_id,
        category=task.get("category", "multihop_cohort"),
        retrieved=retrieved_provider_ids,
        ground_truth=sorted(gt_providers),
        precision=precision,
        recall=recall,
        f1=f1,
        retrieval_config=retrieval_config,
        latency_ms=latency_ms,
    )


# ------------------------------------------------------------------
# Aggregate metrics
# ------------------------------------------------------------------


def aggregate_temporal_results(results: list[EvalResult]) -> dict[str, float]:
    """Compute aggregate metrics for Experiment 1 results.

    Args:
        results: List of EvalResult from temporal QA tasks.

    Returns:
        Dict with keys: mrr, hits_at_1, hits_at_3, mean_latency_ms, n_tasks.
    """
    if not results:
        return {"mrr": 0.0, "hits_at_1": 0.0, "hits_at_3": 0.0, "mean_latency_ms": 0.0, "n_tasks": 0}

    n = len(results)
    return {
        "mrr": sum(r.reciprocal_rank for r in results) / n,
        "hits_at_1": sum(1 for r in results if r.hits_at_1) / n,
        "hits_at_3": sum(1 for r in results if r.hits_at_3) / n,
        "mean_latency_ms": sum(r.latency_ms for r in results) / n,
        "n_tasks": n,
    }


def aggregate_cohort_results(results: list[EvalResult]) -> dict[str, float]:
    """Compute aggregate metrics for Experiment 2 results.

    Args:
        results: List of EvalResult from cohort tasks.

    Returns:
        Dict with keys: mean_precision, mean_recall, mean_f1, mean_latency_ms, n_tasks.
    """
    if not results:
        return {"mean_precision": 0.0, "mean_recall": 0.0, "mean_f1": 0.0, "mean_latency_ms": 0.0, "n_tasks": 0}

    n = len(results)
    return {
        "mean_precision": sum(r.precision for r in results) / n,
        "mean_recall": sum(r.recall for r in results) / n,
        "mean_f1": sum(r.f1 for r in results) / n,
        "mean_latency_ms": sum(r.latency_ms for r in results) / n,
        "n_tasks": n,
    }


# ------------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------------


def save_results(
    results: list[EvalResult],
    aggregate: dict[str, float],
    output_path: str | Path,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write experiment results and aggregate metrics to a JSON file.

    Args:
        results: Per-task EvalResult list.
        aggregate: Aggregate metric dict from aggregate_* functions.
        output_path: Destination file path. Parent directories are created.
        metadata: Optional experiment metadata (timestamps, config, etc.).
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "metadata": metadata or {},
        "aggregate": aggregate,
        "results": [
            {
                "task_id": r.task_id,
                "category": r.category,
                "ground_truth": r.ground_truth,
                "retrieved": r.retrieved[:10],  # Truncate for readability
                "reciprocal_rank": round(r.reciprocal_rank, 4),
                "hits_at_1": r.hits_at_1,
                "hits_at_3": r.hits_at_3,
                "precision": round(r.precision, 4),
                "recall": round(r.recall, 4),
                "f1": round(r.f1, 4),
                "retrieval_config": r.retrieval_config,
                "latency_ms": round(r.latency_ms, 1),
            }
            for r in results
        ],
    }

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    logger.info("Results written to %s (%d tasks).", path, len(results))


def print_summary_table(
    configs: list[str],
    aggregates: list[dict[str, float]],
    experiment_id: str,
) -> None:
    """Print a formatted comparison table to stdout.

    Args:
        configs: List of retrieval config names (column headers).
        aggregates: Parallel list of aggregate metric dicts.
        experiment_id: "exp1" or "exp2" — controls which metrics to show.
    """
    print(f"\n{'=' * 70}")
    print(f"  Experiment Results: {experiment_id}")
    print(f"{'=' * 70}")

    if experiment_id == "exp1":
        metrics = ["mrr", "hits_at_1", "hits_at_3", "mean_latency_ms"]
    else:
        metrics = ["mean_precision", "mean_recall", "mean_f1", "mean_latency_ms"]

    # Header row
    header = f"{'Metric':<22}" + "".join(f"{c:>16}" for c in configs)
    print(header)
    print("-" * len(header))

    for m in metrics:
        row = f"{m:<22}" + "".join(
            f"{agg.get(m, 0.0):>16.4f}" for agg in aggregates
        )
        print(row)

    if experiment_id == "exp1" and len(aggregates) >= 2:
        # Delta row: last config vs first config
        delta_mrr = aggregates[-1].get("mrr", 0.0) - aggregates[0].get("mrr", 0.0)
        print("-" * len(header))
        print(f"{'Δ MRR (last - first)':<22}{delta_mrr:>16.4f}")

    print(f"{'=' * 70}\n")
