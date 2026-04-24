"""One-task forensic for the failing Exp 1A arm-6 pilot path.

This script is intentionally narrow. The pilot already showed a bimodal
`hard_overlap=1.0` / bridge-backed-arms=`0.0` pattern, so the next step is not
another broad run. It is one fully-instrumented reproduction on one real task.

The output order mirrors the requested forensic checklist:

    (a) gold payload from the fixture
    (b) raw bridge response count
    (c) predicate-filter survivor count + predicates seen
    (d) family-filter survivor count + example family drops
    (e) overlap-filter survivor count
    (f) one bridge candidate that looks textually like the gold, side-by-side
    (g) the metric return value on that candidate alone

Run this on the authoritative healthcare VM where the temporal bridge is
available. The default task selection is "first failing supersession task from
the arm-6 pilot results"; that keeps the script aligned with the concrete pilot
failure instead of whatever a synthetic local sample happens to produce.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_memory.temporal.bridge import TemporalBridge  # noqa: E402
from experiments.healthcare.eval_runner import time_sliced_hits_at_1  # noqa: E402
from experiments.healthcare.exp1A_temporal_retrieval.arms import (  # noqa: E402
    SoftDecayHardOverlapArm,
    _candidate_family_for_task,
    _date_to_micros,
    _interval_overlaps,
)
from experiments.healthcare.exp1A_temporal_retrieval.task_schema import (  # noqa: E402
    validate_exp1a_task,
)

DEFAULT_PILOT_RESULT_CANDIDATES = (
    REPO_ROOT / "experiments" / "healthcare" / "results" / "exp1A_pilot" / "results.jsonl",
    Path("/root/agentic-memory-exp1ab-phase5/experiments/healthcare/results/exp1A_pilot/results.jsonl"),
)


def parse_args() -> argparse.Namespace:
    """Parse CLI options for the one-task forensic."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task-id",
        default=None,
        help="Exact Exp 1A task id. Defaults to the first failing supersession task from the pilot results.",
    )
    parser.add_argument(
        "--family",
        default=None,
        help="Optional family hint for direct fixture lookup. When omitted the script searches all Exp 1A family fixtures.",
    )
    parser.add_argument(
        "--dataset",
        default="mid_fhirfix",
        help="Fixture suffix used in exp1A_tasks_{family}_{dataset}.json.",
    )
    parser.add_argument(
        "--tasks-dir",
        default=str(REPO_ROOT / "experiments" / "healthcare" / "tasks"),
        help="Directory containing the Exp 1A task fixtures.",
    )
    parser.add_argument(
        "--results-jsonl",
        default=None,
        help="Optional pilot results JSONL used for default task selection.",
    )
    parser.add_argument(
        "--project-id",
        default="synthea-scale-mid-fhirfix",
        help="Temporal graph namespace used by arm 6.",
    )
    parser.add_argument(
        "--half-life-hours",
        type=float,
        default=720.0,
        help="Half-life to reproduce. Defaults to 30 days (720 hours).",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Requested top-K emitted by arm 6 during the forensic.",
    )
    return parser.parse_args()


def main() -> int:
    """Resolve one task, replay arm 6 once, and print the forensic checklist."""
    args = parse_args()
    task_id = args.task_id or find_default_task_id(args.results_jsonl)
    task = load_task(Path(args.tasks_dir), task_id, args.dataset, family_hint=args.family)
    bridge = TemporalBridge.from_env()
    arm = SoftDecayHardOverlapArm(project_id=args.project_id, bridge=bridge)

    response = bridge.retrieve(
        project_id=args.project_id,
        seed_entities=[{"kind": "patient", "name": task["patient_id"]}],
        as_of_us=_date_to_micros(task["as_of_date"]),
        half_life_hours=args.half_life_hours,
        max_edges=max(args.k * 50, 250),
        max_hops=2,
    )
    raw_rows = response.get("results", [])
    predicate_values_seen = sorted({str(row.get("predicate")) for row in raw_rows})
    predicate_survivors = [
        row for row in raw_rows
        if str(row.get("predicate")) in arm._allowed_predicates(task)
    ]

    family_survivors: list[dict[str, Any]] = []
    family_drop_examples: list[tuple[str, str | None, str | None]] = []
    for index, row in enumerate(predicate_survivors, start=1):
        candidate = arm._bridge_row_to_candidate(task, row, rank=index)
        if candidate is None:
            continue
        resolved_family = _candidate_family_for_task(task, candidate.description)
        if resolved_family != task.get("concept_family"):
            if len(family_drop_examples) < 3:
                family_drop_examples.append(
                    (
                        candidate.description,
                        resolved_family,
                        task.get("concept_family"),
                    )
                )
            continue
        family_survivors.append(candidate_to_payload(candidate))

    overlap_survivors = [
        candidate for candidate in family_survivors
        if _interval_overlaps(
            candidate.get("valid_from"),
            candidate.get("valid_to"),
            task["as_of_date"],
        )
    ]

    textual_match = find_textual_gold_match(predicate_survivors, family_survivors, task, arm)
    candidate_only_metric = (
        time_sliced_hits_at_1([textual_match], task["gold"], task["as_of_date"])
        if textual_match is not None
        else None
    )

    print("(a) gold")
    print(json.dumps(task["gold"], indent=2))
    print()

    print("(b) raw_bridge_response_count")
    print(len(raw_rows))
    print()

    print("(c) predicate_filter")
    print(json.dumps({
        "survivor_count": len(predicate_survivors),
        "predicate_values_seen": predicate_values_seen,
    }, indent=2))
    print()

    print("(d) family_filter")
    print(json.dumps({
        "survivor_count": len(family_survivors),
        "example_drops": family_drop_examples,
    }, indent=2))
    print()

    print("(e) overlap_filter")
    print(json.dumps({"survivor_count": len(overlap_survivors)}, indent=2))
    print()

    print("(f) textual_gold_match")
    if textual_match is None:
        print(json.dumps({"match_found": False}, indent=2))
    else:
        print(json.dumps({
            "match_found": True,
            "candidate": {
                "answer": textual_match.get("answer"),
                "valid_from": textual_match.get("valid_from"),
                "valid_to": textual_match.get("valid_to"),
                "concept_family": textual_match.get("concept_family"),
            },
            "gold": {
                "answer": task["gold"].get("answer"),
                "valid_from": task["gold"].get("valid_from"),
                "valid_to": task["gold"].get("valid_to"),
                "concept_family": task["gold"].get("concept_family"),
            },
        }, indent=2))
    print()

    print("(g) candidate_only_metric")
    print(json.dumps({
        "metric_name": "time_sliced_hits_at_1",
        "value": candidate_only_metric,
    }, indent=2))
    return 0


def find_default_task_id(results_jsonl_arg: str | None) -> str:
    """Return the first failing supersession task from the arm-6 pilot.

    Args:
        results_jsonl_arg: Optional explicit results JSONL path.

    Returns:
        Task id for the first arm-6 supersession miss found in the pilot rows.

    Raises:
        FileNotFoundError: If no candidate results JSONL file exists.
        ValueError: If the results file exists but contains no failing
            supersession row for `soft_decay_hard_overlap`.
    """
    for path in candidate_result_paths(results_jsonl_arg):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if (
                    row.get("arm") == "soft_decay_hard_overlap"
                    and row.get("family") == "supersession"
                    and float(row.get("metrics", {}).get("time_sliced_hits_at_1", 0.0)) == 0.0
                ):
                    return str(row["task_id"])
        raise ValueError(f"No failing supersession task found in {path}")
    raise FileNotFoundError("No pilot results JSONL found for default task selection.")


def candidate_result_paths(explicit_path: str | None) -> list[Path]:
    """Return the ordered list of result-file locations to probe."""
    paths: list[Path] = []
    if explicit_path:
        paths.append(Path(explicit_path))
    paths.extend(DEFAULT_PILOT_RESULT_CANDIDATES)
    return paths


def load_task(tasks_dir: Path, task_id: str, dataset: str, family_hint: str | None) -> dict[str, Any]:
    """Load one task fixture row by id.

    Args:
        tasks_dir: Directory containing Exp 1A family fixtures.
        task_id: Exact task id to load.
        dataset: Fixture suffix, such as `mid_fhirfix`.
        family_hint: Optional family name to reduce search scope.

    Returns:
        The matching task dictionary.

    Raises:
        FileNotFoundError: If the task id is absent from the fixture bundle.
    """
    families = [family_hint] if family_hint else [
        "supersession",
        "regimen_change",
        "recurring_condition",
        "dose_escalation",
    ]
    for family in families:
        if family is None:
            continue
        path = tasks_dir / f"exp1A_tasks_{family}_{dataset}.json"
        if not path.exists():
            continue
        tasks = json.loads(path.read_text(encoding="utf-8"))
        for task in tasks:
            if task.get("id") == task_id:
                validate_exp1a_task(task)
                return task
    raise FileNotFoundError(f"Task {task_id} not found in {tasks_dir}")


def find_textual_gold_match(
    predicate_survivors: list[dict[str, Any]],
    family_survivors: list[dict[str, Any]],
    task: dict[str, Any],
    arm: SoftDecayHardOverlapArm,
) -> dict[str, Any] | None:
    """Return one bridge candidate whose description shares a gold token.

    Args:
        predicate_survivors: Raw bridge rows surviving only the predicate filter.
        family_survivors: Candidate payloads surviving the family filter.
        task: Task fixture being diagnosed.
        arm: Arm instance used to map bridge rows into candidate payloads.

    Returns:
        Candidate payload dictionary or `None` if no textually similar bridge
        candidate exists.
    """
    stop_tokens = {
        "mg",
        "ml",
        "mcg",
        "actuat",
        "oral",
        "tablet",
        "capsule",
        "solution",
        "injectable",
        "cream",
        "ointment",
        "hr",
        "day",
    }
    tokens = {
        token
        for token in re.findall(r"[A-Za-z0-9]+", str(task["gold"].get("description", "")).lower())
        if len(token) >= 3 and token not in stop_tokens
    }
    for candidate in family_survivors:
        description = str(candidate.get("description", "")).lower()
        if any(token in description for token in tokens):
            return candidate
    if len(family_survivors) == 1:
        return family_survivors[0]
    for index, row in enumerate(predicate_survivors, start=1):
        candidate = arm._bridge_row_to_candidate(task, row, rank=index)
        if candidate is None:
            continue
        description = candidate.description.lower()
        if any(token in description for token in tokens):
            return candidate_to_payload(candidate)
    return None


def candidate_to_payload(candidate: Any) -> dict[str, Any]:
    """Convert a candidate-like object into the runner's scoring payload."""
    return {
        "description": candidate.description,
        "answer": candidate.answer,
        "valid_from": candidate.valid_from,
        "valid_to": candidate.valid_to,
        "concept_family": candidate.concept_family,
        "source_id": candidate.source_id,
    }


if __name__ == "__main__":
    raise SystemExit(main())
