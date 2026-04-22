"""Run the Exp 1A isolated temporal-retrieval sweep.

This module is Phase 5's execution surface for Exp 1A. It turns the four
fixture bundles generated in Phase 1 into a resumable retrieval benchmark:

- sample a deterministic pilot slice from the fixture files
- execute every requested arm / half-life combination
- append one JSONL row per completed task-arm-half-life cell
- aggregate the finished rows into a heatmap-friendly JSON summary
- write a short pilot report that highlights obvious empty-cell or
  half-life-sensitivity failures

Why the runner samples *task slices* instead of naively re-anchoring tasks:
the current fixture corpus mixes calendar-sweep anchors with clinical-event
anchors. Recomputing gold labels for a new `as_of` date would be a generator
job, not a runner job. The runner therefore treats each saved task as the
authoritative question and groups it into a canonical snapshot *bucket* for
aggregation. Calendar-sweep tasks land in their exact bucket; event-anchored
tasks are assigned to the nearest configured snapshot date so the pilot can
still compare early-vs-late timeline slices without rewriting task gold.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_memory.temporal.bridge import TemporalBridge  # noqa: E402
from experiments.healthcare.eval_runner import (  # noqa: E402
    in_family_mrr,
    interval_precision_at_k,
    same_family_retention,
    temporal_error_days,
    time_sliced_hits_at_1,
)
from experiments.healthcare.exp1A_temporal_retrieval.arms import (  # noqa: E402
    BaseArm,
    Candidate,
    build_phase4_arms,
)
from experiments.healthcare.exp1A_temporal_retrieval.task_schema import (  # noqa: E402
    validate_exp1a_task,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_SNAPSHOTS = (
    "2008-06-30",
    "2012-06-30",
    "2016-06-30",
    "2020-06-30",
)


@dataclass(frozen=True)
class RunConfig:
    """Configuration surface for the Exp 1A runner.

    Attributes:
        dataset: Fixture suffix used in `exp1A_tasks_{family}_{dataset}.json`.
        tasks_dir: Directory containing the generated Exp 1A fixtures.
        output_dir: Destination directory for JSONL, heatmap, and report files.
        project_id: Temporal graph namespace used by the bridge-backed arms.
        families: Exp 1A ranking families to evaluate.
        snapshots: Canonical snapshot bucket labels used for sampling and
            aggregation.
        tasks_per_family_snapshot: Deterministic sample size per family /
            snapshot bucket for the pilot.
        min_tasks_per_cell: Guardrail that fails fast if a requested sample
            bucket is too sparse to produce a meaningful heatmap cell.
        arm_names: Optional subset of Phase 4 arm names. Empty means all six.
        half_life_hours: Temporal half-life sweep in hours.
        top_k: Number of candidates each arm returns and the interval precision
            metric inspects.
        retention_k: K used by same-family retention.
        seed: RNG seed for deterministic task sampling.
        heartbeat_every: Emit a progress line after this many completed cells.
    """

    dataset: str
    tasks_dir: Path
    output_dir: Path
    project_id: str
    families: tuple[str, ...]
    snapshots: tuple[str, ...]
    tasks_per_family_snapshot: int
    min_tasks_per_cell: int
    arm_names: tuple[str, ...]
    half_life_hours: tuple[float, ...]
    top_k: int
    retention_k: int
    seed: int
    heartbeat_every: int


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the Exp 1A runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.pilot.yaml")),
        help="YAML config describing the Exp 1A sweep.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python log level for runner progress messages.",
    )
    return parser.parse_args()


def load_config(path: str | Path) -> RunConfig:
    """Load the YAML run configuration and coerce it into typed fields.

    Args:
        path: YAML config file path.

    Returns:
        Parsed `RunConfig`.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return RunConfig(
        dataset=str(raw["dataset"]),
        tasks_dir=Path(raw["tasks_dir"]),
        output_dir=Path(raw["output_dir"]),
        project_id=str(raw["project_id"]),
        families=tuple(str(item) for item in raw["families"]),
        snapshots=tuple(str(item) for item in raw["snapshots"]),
        tasks_per_family_snapshot=int(raw["tasks_per_family_snapshot"]),
        min_tasks_per_cell=int(raw.get("min_tasks_per_cell", 10)),
        arm_names=tuple(str(item) for item in raw.get("arm_names", [])),
        half_life_hours=tuple(float(item) for item in raw["half_life_hours"]),
        top_k=int(raw.get("top_k", 5)),
        retention_k=int(raw.get("retention_k", 20)),
        seed=int(raw.get("seed", 42)),
        heartbeat_every=int(raw.get("heartbeat_every", 50)),
    )


def main() -> int:
    """Execute the configured sweep and write JSON/Markdown artifacts."""
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv(REPO_ROOT / ".env")

    config = load_config(args.config)
    selected_tasks = select_task_sample(config)
    results_path = config.output_dir / "results.jsonl"
    heatmap_path = config.output_dir / "heatmap.json"
    report_path = Path(__file__).with_name("PILOT_REPORT.md")

    bridge = TemporalBridge.from_env()
    arms = build_selected_arms(config, bridge)

    existing_rows, completed_keys = load_existing_results(results_path)
    run_rows = execute_sweep(
        config=config,
        tasks=selected_tasks,
        arms=arms,
        results_path=results_path,
        completed_keys=completed_keys,
    )
    all_rows = existing_rows + run_rows

    heatmap = build_heatmap(config, all_rows)
    write_json(heatmap_path, heatmap)
    write_pilot_report(report_path, config, selected_tasks, all_rows, heatmap)

    LOGGER.info(
        "Exp 1A run complete. Wrote %d result rows to %s and %d heatmap cells to %s.",
        len(all_rows),
        results_path,
        len(heatmap["cells"]),
        heatmap_path,
    )
    return 0


def select_task_sample(config: RunConfig) -> list[dict[str, Any]]:
    """Pick a deterministic pilot slice from the saved fixtures.

    The runner samples *saved tasks*, not raw patient facts. This preserves the
    generator's gold labels and keeps event-anchored families honest.

    Args:
        config: Active runner configuration.

    Returns:
        Selected task dictionaries with an added `snapshot_bucket` field.

    Raises:
        ValueError: If a requested family / snapshot bucket lacks the minimum
            number of tasks configured for the pilot gate.
    """
    rng = random.Random(config.seed)
    selected: list[dict[str, Any]] = []

    for family in config.families:
        tasks = load_family_tasks(config.tasks_dir, family, config.dataset)
        grouped: dict[str, list[dict[str, Any]]] = {snapshot: [] for snapshot in config.snapshots}
        for task in tasks:
            bucket = snapshot_bucket_for_task(task["as_of_date"], config.snapshots)
            if bucket not in grouped:
                continue
            task_copy = dict(task)
            task_copy["snapshot_bucket"] = bucket
            grouped[bucket].append(task_copy)

        for snapshot in config.snapshots:
            bucket_tasks = sorted(grouped[snapshot], key=lambda item: item["id"])
            if len(bucket_tasks) < config.min_tasks_per_cell:
                raise ValueError(
                    "Exp 1A pilot bucket is too sparse: "
                    f"family={family} snapshot={snapshot} available={len(bucket_tasks)} "
                    f"required_min={config.min_tasks_per_cell}"
                )
            sample_size = min(config.tasks_per_family_snapshot, len(bucket_tasks))
            selected.extend(rng.sample(bucket_tasks, sample_size))

    selected.sort(key=lambda item: (item["family"], item["snapshot_bucket"], item["id"]))
    return selected


def load_family_tasks(tasks_dir: Path, family: str, dataset: str) -> list[dict[str, Any]]:
    """Load one family fixture file and validate every task.

    Args:
        tasks_dir: Directory containing Exp 1A task JSON files.
        family: Ranking family name.
        dataset: Fixture suffix, for example `mid_fhirfix`.

    Returns:
        List of validated task dictionaries.
    """
    path = tasks_dir / f"exp1A_tasks_{family}_{dataset}.json"
    tasks = json.loads(path.read_text(encoding="utf-8"))
    for task in tasks:
        validate_exp1a_task(task)
    return tasks


def build_selected_arms(config: RunConfig, bridge: TemporalBridge) -> list[BaseArm]:
    """Construct the requested arm subset in design-table order.

    Args:
        config: Active runner configuration.
        bridge: Shared `TemporalBridge` instance for bridge-backed arms.

    Returns:
        Ordered list of arm instances used by the sweep.
    """
    arms = build_phase4_arms(project_id=config.project_id, bridge=bridge, seed=config.seed)
    if not config.arm_names:
        return arms
    allowed = set(config.arm_names)
    return [arm for arm in arms if arm.arm_name in allowed]


def execute_sweep(
    *,
    config: RunConfig,
    tasks: list[dict[str, Any]],
    arms: list[BaseArm],
    results_path: Path,
    completed_keys: set[tuple[str, str, float]],
) -> list[dict[str, Any]]:
    """Run every missing task/arm/half-life cell and append JSONL rows.

    Args:
        config: Active runner configuration.
        tasks: Selected task sample for this run.
        arms: Retrieval arms to evaluate.
        results_path: JSONL destination path.
        completed_keys: Resume set built from existing JSONL rows.

    Returns:
        Newly written JSON-serializable result rows.
    """
    results_path.parent.mkdir(parents=True, exist_ok=True)
    new_rows: list[dict[str, Any]] = []
    total_cells = len(tasks) * len(arms) * len(config.half_life_hours)
    completed_cells = len(completed_keys)

    with results_path.open("a", encoding="utf-8") as handle:
        for task in tasks:
            for arm in arms:
                for half_life in config.half_life_hours:
                    key = result_identity_key(task["id"], arm.arm_name, half_life)
                    if key in completed_keys:
                        continue

                    start = time.perf_counter()
                    candidates = arm.retrieve(task, k=config.top_k, half_life=half_life)
                    latency_ms = round((time.perf_counter() - start) * 1000.0, 1)
                    row = score_result_row(
                        config=config,
                        task=task,
                        arm=arm,
                        half_life=half_life,
                        candidates=candidates,
                        latency_ms=latency_ms,
                    )
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()

                    new_rows.append(row)
                    completed_keys.add(key)
                    completed_cells += 1
                    if completed_cells % max(config.heartbeat_every, 1) == 0:
                        LOGGER.info(
                            "[%d/%d] arm=%s hl=%s snapshot=%s family=%s task=%s latency_ms=%.1f candidates=%d",
                            completed_cells,
                            total_cells,
                            arm.arm_name,
                            format_half_life(half_life),
                            task["snapshot_bucket"],
                            task["family"],
                            task["id"],
                            latency_ms,
                            row["operational"]["candidate_count"],
                        )

    return new_rows


def score_result_row(
    *,
    config: RunConfig,
    task: dict[str, Any],
    arm: BaseArm,
    half_life: float,
    candidates: list[Candidate],
    latency_ms: float,
) -> dict[str, Any]:
    """Build the JSONL row for one completed retrieval cell.

    Args:
        config: Active runner configuration.
        task: Task fixture being evaluated.
        arm: Retrieval arm instance that produced the candidates.
        half_life: Half-life value used for this retrieval.
        candidates: Ranked candidates returned by the arm.
        latency_ms: Retrieval latency in milliseconds.

    Returns:
        JSON-serializable result row.
    """
    candidate_payloads = [candidate_to_payload(candidate) for candidate in candidates]
    family_of = lambda item: item.get("concept_family")
    hits_at_1 = time_sliced_hits_at_1(candidate_payloads, task["gold"], task["as_of_date"])
    if hits_at_1 == 1.0:
        temporal_error = 0.0
    else:
        temporal_error = round(
            temporal_error_days(candidate_payloads[0] if candidate_payloads else None, task["as_of_date"]),
            4,
        )
    metrics = {
        "time_sliced_hits_at_1": hits_at_1,
        "in_family_mrr": round(in_family_mrr(candidate_payloads, task["gold"], family_of), 4),
        "interval_precision_at_k": interval_precision_at_k(candidate_payloads, task["as_of_date"], config.top_k),
        "temporal_error_days": temporal_error,
        "same_family_retention": same_family_retention(
            candidate_payloads,
            str(task["concept_family"]),
            family_of,
            k=config.retention_k,
        ),
    }
    operational = {
        "latency_ms": latency_ms,
        "candidate_count": len(candidate_payloads),
        "edge_count": int(arm.last_retrieval_metadata.get("raw_edge_count", len(candidate_payloads))),
        "emitted_candidate_count": int(arm.last_retrieval_metadata.get("emitted_candidate_count", len(candidate_payloads))),
        "fallback_used": bool(arm.last_retrieval_metadata.get("fallback_used", False)),
        "metadata": dict(arm.last_retrieval_metadata),
    }
    return {
        "task_id": task["id"],
        "patient_id": task["patient_id"],
        "family": task["family"],
        "category": task["category"],
        "query": task["query"],
        "anchor_source": task["anchor_source"],
        "as_of_date": task["as_of_date"],
        "snapshot_bucket": task["snapshot_bucket"],
        "concept_family": task["concept_family"],
        "arm": arm.arm_name,
        "half_life_hours": half_life,
        "half_life_label": format_half_life(half_life),
        "gold": {
            "answer": task["gold"]["answer"],
            "valid_from": task["gold"]["valid_from"],
            "valid_to": task["gold"]["valid_to"],
            "source_id": task["gold"].get("source_id"),
        },
        "metrics": metrics,
        "operational": operational,
        "retrieved": candidate_payloads,
    }


def candidate_to_payload(candidate: Candidate) -> dict[str, Any]:
    """Convert a `Candidate` dataclass into a JSON-friendly dictionary.

    Args:
        candidate: Ranked Exp 1A candidate.

    Returns:
        Dictionary containing the normalized scoring fields plus the original
        raw row for later audit/debugging.
    """
    return {
        "description": candidate.description,
        "answer": candidate.answer,
        "valid_from": candidate.valid_from,
        "valid_to": candidate.valid_to,
        "score": round(candidate.score, 6),
        "concept_family": candidate.concept_family,
        "source_id": candidate.source_id,
        "predicate": candidate.predicate,
        "source_type": candidate.source_type,
        "raw": candidate.raw,
    }


def build_heatmap(config: RunConfig, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate JSONL rows into per-cell metric summaries.

    Args:
        config: Active runner configuration.
        rows: All completed result rows, including resumed rows.

    Returns:
        Heatmap-ready dictionary keyed by `(arm, half_life, snapshot, family)`
        cells with mean metrics and operational summaries.
    """
    grouped: dict[tuple[str, float, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["arm"]),
            float(row["half_life_hours"]),
            str(row["snapshot_bucket"]),
            str(row["family"]),
        )
        grouped.setdefault(key, []).append(row)

    cells: list[dict[str, Any]] = []
    for (arm_name, half_life, snapshot, family), bucket_rows in sorted(grouped.items()):
        hits = [float(row["metrics"]["time_sliced_hits_at_1"]) for row in bucket_rows]
        mrr = [float(row["metrics"]["in_family_mrr"]) for row in bucket_rows]
        interval_precision = [float(row["metrics"]["interval_precision_at_k"]) for row in bucket_rows]
        temporal_error = [float(row["metrics"]["temporal_error_days"]) for row in bucket_rows]
        retention = [float(row["metrics"]["same_family_retention"]) for row in bucket_rows]
        latencies = [float(row["operational"]["latency_ms"]) for row in bucket_rows]
        candidate_counts = [int(row["operational"]["candidate_count"]) for row in bucket_rows]
        edge_counts = [int(row["operational"]["edge_count"]) for row in bucket_rows]
        fallback_count = sum(1 for row in bucket_rows if row["operational"].get("fallback_used"))

        cells.append(
            {
                "arm": arm_name,
                "half_life_hours": half_life,
                "half_life_label": format_half_life(half_life),
                "snapshot_bucket": snapshot,
                "family": family,
                "n_tasks": len(bucket_rows),
                "metrics": {
                    "time_sliced_hits_at_1": {
                        "mean": round(statistics.fmean(hits), 4),
                        "wilson95": wilson_interval(int(sum(hits)), len(hits)),
                    },
                    "in_family_mrr": {"mean": round(statistics.fmean(mrr), 4)},
                    "interval_precision_at_k": {"mean": round(statistics.fmean(interval_precision), 4)},
                    "temporal_error_days": {
                        "mean": round(statistics.fmean(temporal_error), 4),
                        "median": round(statistics.median(temporal_error), 4),
                    },
                    "same_family_retention": {"mean": round(statistics.fmean(retention), 4)},
                },
                "operational": {
                    "latency_ms": {
                        "p50": percentile(latencies, 50),
                        "p95": percentile(latencies, 95),
                    },
                    "candidate_count": {
                        "mean": round(statistics.fmean(candidate_counts), 3),
                        "min": min(candidate_counts),
                        "max": max(candidate_counts),
                    },
                    "edge_count": {
                        "mean": round(statistics.fmean(edge_counts), 3),
                        "min": min(edge_counts),
                        "max": max(edge_counts),
                    },
                    "fallback_rate": round(fallback_count / len(bucket_rows), 4),
                },
            }
        )

    return {
        "config": {
            "dataset": config.dataset,
            "families": list(config.families),
            "snapshots": list(config.snapshots),
            "tasks_per_family_snapshot": config.tasks_per_family_snapshot,
            "half_life_hours": list(config.half_life_hours),
            "top_k": config.top_k,
            "retention_k": config.retention_k,
            "seed": config.seed,
        },
        "cells": cells,
    }


def write_pilot_report(
    report_path: Path,
    config: RunConfig,
    tasks: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    heatmap: dict[str, Any],
) -> None:
    """Write a concise pilot summary for the experiment log.

    Args:
        report_path: Markdown report destination.
        config: Active runner configuration.
        tasks: Selected pilot task sample.
        rows: Completed result rows.
        heatmap: Aggregate heatmap dictionary built from `rows`.
    """
    sampled_counts: dict[tuple[str, str], int] = {}
    for task in tasks:
        key = (str(task["family"]), str(task["snapshot_bucket"]))
        sampled_counts[key] = sampled_counts.get(key, 0) + 1

    empty_counts: dict[str, int] = {}
    for row in rows:
        if int(row["operational"]["candidate_count"]) == 0:
            empty_counts[row["arm"]] = empty_counts.get(row["arm"], 0) + 1

    arm_snapshot_family_hits: dict[tuple[str, str, str], list[float]] = {}
    for cell in heatmap["cells"]:
        key = (str(cell["arm"]), str(cell["snapshot_bucket"]), str(cell["family"]))
        arm_snapshot_family_hits.setdefault(key, []).append(
            float(cell["metrics"]["time_sliced_hits_at_1"]["mean"])
        )

    arm_half_life_hits: dict[tuple[str, float], list[float]] = {}
    for cell in heatmap["cells"]:
        key = (str(cell["arm"]), float(cell["half_life_hours"]))
        arm_half_life_hits.setdefault(key, []).append(
            float(cell["metrics"]["time_sliced_hits_at_1"]["mean"])
        )

    half_life_watchlines: list[str] = []
    for arm_name in ("hard_overlap_decay_tiebreak", "soft_decay_only", "soft_decay_hard_overlap"):
        arm_rows = {
            half_life: statistics.fmean(values)
            for (name, half_life), values in arm_half_life_hits.items()
            if name == arm_name
        }
        if not arm_rows:
            continue
        low = min(arm_rows.values())
        high = max(arm_rows.values())
        half_life_watchlines.append(
            f"- `{arm_name}` Hits@1 range across configured half-lives: {low:.4f} to {high:.4f}"
        )

    estimated_seconds = 0.0
    if rows:
        estimated_seconds = statistics.fmean(
            float(row["operational"]["latency_ms"]) for row in rows
        ) * (len(tasks) * len(config.half_life_hours) * max(len({row['arm'] for row in rows}), 1)) / 1000.0

    lines = [
        "# Exp 1A Pilot Report",
        "",
        "## Pilot Scope",
        "",
        f"- Dataset: `{config.dataset}`",
        f"- Families: {', '.join(f'`{family}`' for family in config.families)}",
        f"- Snapshot buckets: {', '.join(f'`{snapshot}`' for snapshot in config.snapshots)}",
        f"- Tasks per family/snapshot bucket: `{config.tasks_per_family_snapshot}`",
        f"- Arms: {', '.join(f'`{cell.arm_name}`' for cell in build_phase4_arms(project_id=config.project_id, bridge=None, seed=config.seed) if not config.arm_names or cell.arm_name in set(config.arm_names))}",
        f"- Half-lives: {', '.join(f'`{format_half_life(value)}`' for value in config.half_life_hours)}",
        "",
        "## Task Coverage",
        "",
    ]

    for family in config.families:
        for snapshot in config.snapshots:
            lines.append(
                f"- `{family}` / `{snapshot}` sampled tasks: `{sampled_counts.get((family, snapshot), 0)}`"
            )

    lines.extend(
        [
            "",
            "## Operational Findings",
            "",
        ]
    )
    if empty_counts:
        for arm_name, count in sorted(empty_counts.items()):
            lines.append(f"- Empty-candidate rows for `{arm_name}`: `{count}`")
    else:
        lines.append("- No result rows returned zero candidates.")

    lines.extend(
        [
            "",
            "## Half-Life Watchlist",
            "",
            "- Record the earlier `halflife_sensitivity` preflight signal (`3/20` top-1 flips between `30d` and `1095d`) here once the authoritative VM pilot finishes so arm 6 vs arm 3 can be compared against that early warning.",
        ]
    )
    lines.extend(half_life_watchlines or ["- Half-life deltas are not available until at least one row has been scored per decay-aware arm."])

    lines.extend(
        [
            "",
            "## Runtime Estimate",
            "",
            f"- Approximate wall-clock at current mean latency: `{estimated_seconds / 3600:.2f}` hours for the configured sweep.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_existing_results(path: Path) -> tuple[list[dict[str, Any]], set[tuple[str, str, float]]]:
    """Load prior JSONL rows so interrupted runs can resume.

    Args:
        path: Existing results JSONL path.

    Returns:
        Tuple of parsed rows and the identity-key set used to skip completed
        cells.
    """
    if not path.exists():
        return [], set()
    rows: list[dict[str, Any]] = []
    completed: set[tuple[str, str, float]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            rows.append(row)
            completed.add(
                result_identity_key(
                    str(row["task_id"]),
                    str(row["arm"]),
                    float(row["half_life_hours"]),
                )
            )
    return rows, completed


def result_identity_key(task_id: str, arm_name: str, half_life: float) -> tuple[str, str, float]:
    """Build the resume key for one result row."""
    return (task_id, arm_name, round(float(half_life), 6))


def snapshot_bucket_for_task(as_of_date: str, snapshots: tuple[str, ...]) -> str:
    """Assign one task anchor date to the nearest configured snapshot bucket.

    This is the runner's compromise for clinical-event anchors. The task keeps
    its real `as_of_date` for scoring; the bucket only controls sampling and
    aggregation.
    """
    anchor = date.fromisoformat(as_of_date)
    snapshot_dates = [date.fromisoformat(snapshot) for snapshot in snapshots]
    index = min(
        range(len(snapshot_dates)),
        key=lambda idx: (abs((anchor - snapshot_dates[idx]).days), snapshot_dates[idx]),
    )
    return snapshots[index]


def format_half_life(hours: float) -> str:
    """Render a half-life value in the same style as the design docs."""
    if hours % (24.0 * 365.0) == 0:
        years = hours / (24.0 * 365.0)
        return f"{int(years)}y"
    if hours % 24.0 == 0:
        days = hours / 24.0
        return f"{int(days)}d"
    return f"{hours:g}h"


def percentile(values: list[float], percentile_rank: float) -> float:
    """Return an interpolated percentile for a non-empty numeric list."""
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 4)
    ordered = sorted(values)
    position = (len(ordered) - 1) * (percentile_rank / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 4)
    weight = position - lower
    interpolated = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return round(interpolated, 4)


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> dict[str, float]:
    """Compute a Wilson 95% interval for a binomial success rate."""
    if trials <= 0:
        return {"low": 0.0, "high": 0.0}
    phat = successes / trials
    denominator = 1 + (z**2 / trials)
    center = (phat + (z**2 / (2 * trials))) / denominator
    margin = (
        z
        * math.sqrt((phat * (1 - phat) / trials) + (z**2 / (4 * trials**2)))
        / denominator
    )
    return {
        "low": round(max(0.0, center - margin), 4),
        "high": round(min(1.0, center + margin), 4),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON artifact with parent-directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
