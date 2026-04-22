"""Smoke-test runner for the six Exp 1A retrieval arms.

Phase 4's goal is not to run the full benchmark. It is only to prove that each
arm can return a sane-looking candidate list for a small random sample from
each ranking family. This script loads the four Exp 1A fixture bundles, samples
five tasks per family by default, runs every arm, and prints the top-K results
for manual inspection.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_memory.temporal.bridge import TemporalBridge
from experiments.healthcare.exp1A_temporal_retrieval.arms import (
    HardOverlapArm,
    HardOverlapDecayTiebreakArm,
    SoftDecayHardOverlapArm,
    build_phase4_arms,
)
from experiments.healthcare.exp1A_temporal_retrieval.task_schema import (
    validate_exp1a_task,
)

EXP1A_RANKING_FAMILIES = (
    "supersession",
    "regimen_change",
    "recurring_condition",
    "dose_escalation",
)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the Phase 4 smoke runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks-dir",
        default=str(REPO_ROOT / "experiments" / "healthcare" / "tasks"),
        help="Directory containing the Exp 1A task fixtures.",
    )
    parser.add_argument(
        "--project-id",
        default="synthea-scale-mid-fhirfix",
        help="Temporal graph namespace for the bridge-backed arms.",
    )
    parser.add_argument(
        "--sample-per-family",
        type=int,
        default=5,
        help="Number of random tasks to sample per ranking family.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Number of candidates each arm should print per task.",
    )
    parser.add_argument(
        "--half-life-hours",
        type=float,
        default=24.0 * 365.0,
        help="Half-life passed to the decay-aware arms.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for task sampling and arm RNG setup.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the smoke gate and exit non-zero on any failed arm/task pair."""
    args = parse_args()
    load_dotenv(REPO_ROOT / ".env", override=False)
    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        raise SystemExit(f"Temporal bridge unavailable: {bridge.disabled_reason}")

    tasks_by_family = load_tasks(Path(args.tasks_dir))
    sampled_tasks = sample_tasks(tasks_by_family, sample_per_family=args.sample_per_family, seed=args.seed)
    arms = build_phase4_arms(project_id=args.project_id, bridge=bridge, seed=args.seed)

    failures: list[str] = []
    for family in EXP1A_RANKING_FAMILIES:
        print(f"\n=== FAMILY: {family} ===")
        for task in sampled_tasks[family]:
            print(f"\nTASK {task['id']} :: {task['query']}")
            for arm in arms:
                candidates = arm.retrieve(task, k=args.k, half_life=args.half_life_hours)
                if not candidates:
                    failures.append(f"{arm.arm_name}:{task['id']} returned 0 candidates")
                    print(f"  [{arm.arm_name}] NO CANDIDATES")
                    continue
                if isinstance(arm, (HardOverlapArm, HardOverlapDecayTiebreakArm, SoftDecayHardOverlapArm)):
                    invalid = [
                        candidate.answer
                        for candidate in candidates
                        if not _candidate_overlaps_task(candidate.valid_from, candidate.valid_to, task["as_of_date"])
                    ]
                    if invalid:
                        failures.append(
                            f"{arm.arm_name}:{task['id']} returned non-overlap candidates: {invalid}"
                        )
                print(f"  [{arm.arm_name}]")
                for candidate in candidates:
                    print(
                        "    - "
                        f"{candidate.answer} | interval={candidate.valid_from}..{candidate.valid_to} "
                        f"| family={candidate.concept_family} | score={candidate.score:.4f}"
                    )

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nSmoke gate passed: all six arms returned candidates for the sampled ranking-family tasks.")
    return 0


def load_tasks(tasks_dir: Path) -> dict[str, list[dict]]:
    """Load and validate the four Exp 1A ranking-family fixture bundles."""
    tasks_by_family: dict[str, list[dict]] = {}
    for family in EXP1A_RANKING_FAMILIES:
        path = tasks_dir / f"exp1A_tasks_{family}_mid_fhirfix.json"
        tasks = json.loads(path.read_text(encoding="utf-8"))
        for task in tasks:
            validate_exp1a_task(task)
        tasks_by_family[family] = tasks
    return tasks_by_family


def sample_tasks(
    tasks_by_family: dict[str, list[dict]],
    *,
    sample_per_family: int,
    seed: int,
) -> dict[str, list[dict]]:
    """Choose a deterministic random sample per family for the smoke gate."""
    rng = random.Random(seed)
    sampled: dict[str, list[dict]] = {}
    for index, family in enumerate(EXP1A_RANKING_FAMILIES):
        family_rng = random.Random(rng.randint(0, 1_000_000) + index)
        tasks = list(tasks_by_family[family])
        family_rng.shuffle(tasks)
        sampled[family] = tasks[:sample_per_family]
    return sampled


def _candidate_overlaps_task(
    valid_from: str | None,
    valid_to: str | None,
    as_of: str,
) -> bool:
    """Return whether one printed candidate overlaps the task anchor date."""
    if valid_from is None:
        return False
    return valid_from <= as_of and (valid_to is None or as_of <= valid_to)


if __name__ == "__main__":
    raise SystemExit(main())
