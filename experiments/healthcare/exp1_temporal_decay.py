"""Experiment 1 — Temporal Decay for Clinical Relevance.

Hypothesis:
    SpacetimeDB PPR temporal decay improves the retrieval rank of the most
    recent / temporally relevant clinical fact compared to flat vector search.

What this script does:
    1. Generates (or loads) temporal QA task pairs from the Synthea CSV files.
    2. For each task, runs retrieval via TemporalBridge with three half-life
       variants: 24h, 168h (1 week), 720h (30 days), plus a "flat" baseline
       (decay disabled via a very large half-life).
    3. Scores each retrieved result against the CSV-derived ground truth using
       MRR (Mean Reciprocal Rank), Hits@1, and Hits@3.
    4. Writes per-task results and aggregate metrics to a JSON file and prints
       a comparison table to stdout.

Usage (after running ingest_synthea.py):
    python experiments/healthcare/exp1_temporal_decay.py \\
        --data-dir "G:/My Drive/.../synthea_2017_02_27/" \\
        --project-id synthea-experiment \\
        --n-tasks 200 \\
        --output-dir experiments/healthcare/results

Required environment variables:
    STDB_MODULE_NAME or STDB_BINDINGS_MODULE — SpacetimeDB connection settings
    (See packages/am-temporal-kg/README for setup instructions)

The retrieval function used here:
    TemporalBridge.retrieve(seed_entities=[{kind:"patient", name:patient_id}],
                            half_life_hours=<variant>,
                            max_edges=20)

The retrieved edges (predicate=DIAGNOSED_WITH or PRESCRIBED) are extracted and
their object_name strings form the ranked candidate list for scoring.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from experiments.healthcare.eval_runner import (
    EvalResult,
    aggregate_temporal_results,
    print_summary_table,
    save_results,
    score_temporal_task,
)
from experiments.healthcare.qa_generator import SyntheaQAGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("exp1_temporal_decay")

# Half-life variants to evaluate (in hours).
# "flat" disables decay by using an astronomically large half-life.
_HALF_LIFE_VARIANTS: list[tuple[str, float]] = [
    ("flat_no_decay", 1e9),
    ("decay_24h", 24.0),
    ("decay_168h", 168.0),
    ("decay_720h", 720.0),
]

# Predicates to extract from temporal retrieval results for condition QA tasks
_CONDITION_PREDICATES = {"DIAGNOSED_WITH", "HAS_CONDITION"}
# Predicates for medication QA tasks
_MEDICATION_PREDICATES = {"PRESCRIBED"}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Experiment 1: Temporal Decay vs Flat retrieval on clinical QA.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Path to extracted Synthea CSV directory (for QA generation).",
    )
    parser.add_argument(
        "--project-id",
        default="synthea-experiment",
        help="SpacetimeDB project namespace (must match ingest_synthea.py --project-id).",
    )
    parser.add_argument(
        "--n-tasks",
        type=int,
        default=200,
        help="Number of temporal QA tasks to generate and evaluate.",
    )
    parser.add_argument(
        "--tasks-file",
        default=None,
        help="Optional: load pre-generated tasks from this JSON file instead of generating.",
    )
    parser.add_argument(
        "--output-dir",
        default="experiments/healthcare/results",
        help="Directory to write result JSON files.",
    )
    parser.add_argument(
        "--max-edges",
        type=int,
        default=20,
        help="Max edges returned per temporal retrieval call.",
    )
    parser.add_argument(
        "--as-of-date",
        default="2017-01-01",
        help="Reference date for active-medication QA tasks (YYYY-MM-DD).",
    )
    return parser.parse_args()


def retrieve_for_task(
    bridge,
    task: dict,
    project_id: str,
    half_life_hours: float,
    max_edges: int,
) -> tuple[list[str], float]:
    """Run temporal retrieval for a single task and extract candidate strings.

    Seeds the retrieval with the patient entity from the task. Extracts
    object_name values from edges whose predicate matches the task category.

    Args:
        bridge: TemporalBridge instance.
        task: Task dict from QA generator.
        project_id: SpacetimeDB project namespace.
        half_life_hours: PPR decay half-life in hours.
        max_edges: Max edges to retrieve.

    Returns:
        Tuple of (ranked_candidate_strings, latency_ms).
    """
    patient_id = task.get("patient_id", "")
    category = task.get("category", "")

    # Determine which predicates to filter for this task type
    if "medication" in category:
        target_predicates = _MEDICATION_PREDICATES
    else:
        target_predicates = _CONDITION_PREDICATES

    t0 = time.perf_counter()
    try:
        result = bridge.retrieve(
            project_id=project_id,
            seed_entities=[{"kind": "patient", "name": patient_id}],
            half_life_hours=half_life_hours,
            max_edges=max_edges,
            max_hops=2,
        )
    except Exception as exc:
        logger.warning("Retrieval failed for task %s: %s", task.get("id"), exc)
        return [], 0.0

    latency_ms = (time.perf_counter() - t0) * 1000

    # Extract edges and sort by relevance (highest first)
    edges = result.get("edges", [])
    edges_sorted = sorted(edges, key=lambda e: e.get("relevance", 0.0), reverse=True)

    # Extract object_name strings for matching predicates only
    candidates = []
    for edge in edges_sorted:
        pred = edge.get("pred", "")
        if pred in target_predicates:
            obj_name = edge.get("objName") or edge.get("object_name") or ""
            if obj_name and obj_name not in candidates:
                candidates.append(obj_name)

    return candidates, latency_ms


def run_experiment(args: argparse.Namespace) -> None:
    """Main experiment loop.

    Args:
        args: Parsed argument namespace.
    """
    from agentic_memory.temporal.bridge import TemporalBridge

    # Build temporal bridge
    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        logger.error(
            "SpacetimeDB bridge unavailable: %s\n"
            "Run 'cd packages/am-temporal-kg && npx spacetime start' first.",
            bridge.disabled_reason,
        )
        sys.exit(1)

    # Generate or load tasks
    if args.tasks_file:
        logger.info("Loading tasks from %s", args.tasks_file)
        tasks = SyntheaQAGenerator.load_tasks(args.tasks_file)
    else:
        logger.info("Generating %d temporal QA tasks from %s", args.n_tasks, args.data_dir)
        generator = SyntheaQAGenerator(args.data_dir)
        tasks = generator.generate_temporal_qa(
            n_patients=args.n_tasks,
            as_of_date=args.as_of_date,
        )
        # Save generated tasks for reproducibility
        task_path = Path(args.output_dir) / "exp1_tasks_generated.json"
        SyntheaQAGenerator.save_tasks(tasks, task_path)
        logger.info("Generated tasks saved to %s", task_path)

    logger.info("Running Experiment 1 on %d tasks with %d half-life variants...", len(tasks), len(_HALF_LIFE_VARIANTS))

    # Run each half-life variant
    all_results: dict[str, list[EvalResult]] = {}
    all_aggregates: list[dict] = []
    config_names: list[str] = []

    for config_name, half_life in _HALF_LIFE_VARIANTS:
        logger.info("--- Running variant: %s (half_life=%.0fh) ---", config_name, half_life)
        retrieval_config = {
            "method": "temporal_ppr",
            "half_life_hours": half_life,
            "variant": config_name,
            "max_edges": args.max_edges,
        }

        results: list[EvalResult] = []
        for task in tasks:
            candidates, latency_ms = retrieve_for_task(
                bridge=bridge,
                task=task,
                project_id=args.project_id,
                half_life_hours=half_life,
                max_edges=args.max_edges,
            )
            result = score_temporal_task(
                task=task,
                retrieved=candidates,
                retrieval_config=retrieval_config,
                latency_ms=latency_ms,
            )
            results.append(result)

        agg = aggregate_temporal_results(results)
        logger.info(
            "  MRR=%.4f  Hits@1=%.4f  Hits@3=%.4f  latency=%.1fms",
            agg["mrr"],
            agg["hits_at_1"],
            agg["hits_at_3"],
            agg["mean_latency_ms"],
        )

        # Save per-variant results
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = Path(args.output_dir) / f"exp1_{config_name}_{timestamp}.json"
        save_results(
            results=results,
            aggregate=agg,
            output_path=out_path,
            metadata={
                "experiment": "exp1_temporal_decay",
                "variant": config_name,
                "half_life_hours": half_life,
                "project_id": args.project_id,
                "n_tasks": len(tasks),
                "max_edges": args.max_edges,
                "timestamp": timestamp,
            },
        )

        all_results[config_name] = results
        all_aggregates.append(agg)
        config_names.append(config_name)

    # Print comparison table
    print_summary_table(
        configs=config_names,
        aggregates=all_aggregates,
        experiment_id="exp1",
    )

    # Hypothesis check: does 168h decay beat flat baseline?
    flat_mrr = all_aggregates[0]["mrr"]  # first variant = flat
    best_mrr = max(a["mrr"] for a in all_aggregates[1:])
    best_name = config_names[all_aggregates.index(max(all_aggregates[1:], key=lambda a: a["mrr"]))]
    print(f"Best decay variant: {best_name}  MRR={best_mrr:.4f}  (vs flat={flat_mrr:.4f})")
    if best_mrr > flat_mrr:
        print("✓ Hypothesis SUPPORTED: temporal decay improves clinical retrieval rank.")
    else:
        print("✗ Hypothesis NOT supported at this sample size / decay setting.")


if __name__ == "__main__":
    run_experiment(parse_args())
