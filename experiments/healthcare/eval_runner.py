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
from datetime import date, datetime, timezone
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


def time_sliced_hits_at_1(
    retrieved: list[dict[str, Any]],
    gold: dict[str, Any],
    as_of: str | date | datetime,
) -> float:
    """Return whether the top-1 retrieved candidate is the gold interval.

    Exp 1A is a ranking benchmark, not just a family-classification benchmark.
    This helper therefore treats a top-1 candidate as correct only when it
    resolves to the same interval-bearing fact as ``gold`` and that interval
    overlaps the task's ``as_of`` date.

    Args:
        retrieved: Ordered candidate payloads returned by one arm.
        gold: Gold interval payload from the task fixture.
        as_of: Snapshot date used for the temporal question.

    Returns:
        ``1.0`` when the top-1 candidate matches ``gold`` and overlaps
        ``as_of``; otherwise ``0.0``.

    Examples:
        >>> gold = {
        ...     "answer": "Metformin",
        ...     "valid_from": "2020-01-01",
        ...     "valid_to": "2020-12-31",
        ... }
        >>> time_sliced_hits_at_1([gold], gold, "2020-06-01")
        1.0
        >>> miss = {
        ...     "answer": "Metformin",
        ...     "valid_from": "2018-01-01",
        ...     "valid_to": "2018-12-31",
        ... }
        >>> time_sliced_hits_at_1([miss], gold, "2020-06-01")
        0.0
    """
    if not retrieved:
        return 0.0
    picked = retrieved[0]
    if not _interval_overlaps_as_of(picked, as_of):
        return 0.0
    return 1.0 if _candidates_match(picked, gold) else 0.0


def in_family_mrr(
    retrieved: list[dict[str, Any]],
    gold: dict[str, Any],
    family_of_fn: Callable[[dict[str, Any]], str | None],
) -> float:
    """Compute reciprocal rank after filtering to the gold candidate family.

    The intent is to isolate the ranking behavior within the task's relevant
    family, without letting unrelated-family retrieval noise dominate the
    metric.

    Args:
        retrieved: Ordered candidate payloads returned by one arm.
        gold: Gold interval payload from the task fixture.
        family_of_fn: Callable that extracts a family label from one candidate.

    Returns:
        Reciprocal rank of ``gold`` among same-family candidates, or ``0.0`` if
        ``gold`` never appears in-family.

    Examples:
        >>> family_of = lambda item: item.get("concept_family")
        >>> gold = {
        ...     "answer": "Metformin",
        ...     "concept_family": "metformin",
        ...     "valid_from": "2020-01-01",
        ...     "valid_to": "2020-12-31",
        ... }
        >>> wrong_family = {"answer": "Lisinopril", "concept_family": "lisinopril"}
        >>> older_same_family = {
        ...     "answer": "Metformin",
        ...     "concept_family": "metformin",
        ...     "valid_from": "2019-01-01",
        ...     "valid_to": "2019-12-31",
        ... }
        >>> in_family_mrr([wrong_family, older_same_family, gold], gold, family_of)
        0.5
    """
    gold_family = family_of_fn(gold)
    if gold_family is None:
        return 0.0

    in_family_rank = 0
    for candidate in retrieved:
        if family_of_fn(candidate) != gold_family:
            continue
        in_family_rank += 1
        if _candidates_match(candidate, gold):
            return 1.0 / in_family_rank
    return 0.0


def interval_precision_at_k(
    retrieved: list[dict[str, Any]],
    as_of: str | date | datetime,
    k: int,
) -> float:
    """Measure how many of the top-K intervals are active at ``as_of``.

    Args:
        retrieved: Ordered candidate payloads returned by one arm.
        as_of: Snapshot date used for the temporal question.
        k: Number of leading candidates to inspect.

    Returns:
        Fraction of the top-K candidates whose intervals overlap ``as_of``.

    Examples:
        >>> candidates = [
        ...     {"valid_from": "2020-01-01", "valid_to": "2020-12-31"},
        ...     {"valid_from": "2018-01-01", "valid_to": "2018-12-31"},
        ...     {"valid_from": "2020-03-01", "valid_to": None},
        ... ]
        >>> interval_precision_at_k(candidates, "2020-06-01", 3)
        0.6667
    """
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    overlapping = sum(1 for candidate in top_k if _interval_overlaps_as_of(candidate, as_of))
    return round(overlapping / len(top_k), 4)


def temporal_error_days(
    picked: dict[str, Any] | None,
    as_of: str | date | datetime,
) -> float:
    """Return signed distance from ``as_of`` to the picked interval midpoint.

    The metric is diagnostic rather than binary: a wrong answer that is one
    week off is qualitatively different from one that points to an event a
    decade away. The sign preserves direction so downstream analysis can tell
    whether a system tends to retrieve intervals that are too early or too
    late.

    Args:
        picked: Selected candidate payload. ``None`` means nothing was picked.
        as_of: Snapshot date used for the temporal question.

    Returns:
        Signed day distance between the picked interval midpoint and ``as_of``.
        Negative values mean the picked interval is earlier than ``as_of``;
        positive values mean it is later. Returns ``float("inf")`` when no
        valid interval exists.

    Examples:
        >>> picked = {"valid_from": "2020-01-01", "valid_to": "2020-01-01"}
        >>> temporal_error_days(picked, "2020-01-08")
        -7.0
    """
    if picked is None:
        return float("inf")

    start = _coerce_to_datetime(picked.get("valid_from"))
    end = _coerce_to_datetime(picked.get("valid_to")) or start
    anchor = _coerce_to_datetime(as_of)
    if start is None or anchor is None:
        return float("inf")
    midpoint = start + ((end - start) / 2)
    return (midpoint - anchor).total_seconds() / 86_400.0


def same_family_retention(
    retrieved: list[dict[str, Any]],
    target_family: str,
    family_of_fn: Callable[[dict[str, Any]], str | None],
    k: int = 20,
) -> float:
    """Return the fraction of top-K candidates that stay in the target family.

    Args:
        retrieved: Ordered candidate payloads returned by one arm.
        target_family: Family label the task expects.
        family_of_fn: Callable that extracts a family label from one candidate.
        k: Number of leading candidates to inspect.

    Returns:
        Fraction of the requested K slots that stay in ``target_family``.
        The denominator remains ``k`` even when fewer than ``k`` candidates are
        returned, so thin-result arms are penalized instead of looking better
        just because they emitted fewer rows.

    Examples:
        >>> family_of = lambda item: item.get("concept_family")
        >>> retrieved = [
        ...     {"concept_family": "metformin"},
        ...     {"concept_family": "metformin"},
        ...     {"concept_family": "lisinopril"},
        ...     {"concept_family": "metformin"},
        ...     {"concept_family": "warfarin"},
        ... ]
        >>> same_family_retention(retrieved, "metformin", family_of, k=5)
        0.6
    """
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not retrieved:
        return 0.0
    in_family = sum(1 for candidate in top_k if family_of_fn(candidate) == target_family)
    return round(in_family / k, 4)


def _candidates_match(candidate: dict[str, Any], gold: dict[str, Any]) -> bool:
    """Return whether two interval-bearing payloads resolve to the same fact.

    Source ids are the strongest identity signal when they are available. When
    they are not, we fall back to the tuple that Exp 1A scoring actually cares
    about: answer/description plus interval boundaries.
    """
    candidate_source_id = candidate.get("source_id")
    gold_source_id = gold.get("source_id")
    if candidate_source_id and gold_source_id:
        return candidate_source_id == gold_source_id
    return _candidate_identity_key(candidate) == _candidate_identity_key(gold)


def _candidate_identity_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """Build the fallback identity tuple used for interval-level matching."""
    return (
        (candidate.get("answer") or candidate.get("description") or "").strip().lower(),
        _normalize_date_text(candidate.get("valid_from")),
        _normalize_date_text(candidate.get("valid_to")),
    )


def _interval_overlaps_as_of(
    candidate: dict[str, Any],
    as_of: str | date | datetime,
) -> bool:
    """Return whether one candidate interval contains the anchor date."""
    start = _coerce_to_datetime(candidate.get("valid_from"))
    end = _coerce_to_datetime(candidate.get("valid_to"))
    anchor = _coerce_to_datetime(as_of)
    if start is None or anchor is None:
        return False
    if end is not None and end < start:
        return False
    return start <= anchor and (end is None or anchor <= end)


def _normalize_date_text(value: Any) -> str | None:
    """Normalize a date-ish value into ISO text for tuple comparisons."""
    normalized = _coerce_to_datetime(value)
    if normalized is None:
        return None
    return normalized.date().isoformat()


def _coerce_to_datetime(value: Any) -> datetime | None:
    """Convert date-like input into a midnight UTC ``datetime`` when possible."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        for parser in (datetime.fromisoformat,):
            try:
                parsed = parser(stripped.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                continue
        try:
            parsed_date = date.fromisoformat(stripped)
        except ValueError:
            return None
        return datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            tzinfo=timezone.utc,
        )
    return None


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
