"""Generate Exp 1A temporal-retrieval task fixtures on the experiment VM.

This script is intentionally a thin command-line wrapper around
``SyntheaQAGenerator``. The heavy work stays in ``qa_generator.py`` so Exp 1A
and Exp 1B can reuse the same deterministic task families. This script writes
only Exp 1A's four ranking families. The yes/no medication-history generator
(``generate_retrospective_state_tasks``) stays in ``qa_generator.py`` for Exp
1B reuse, but is intentionally excluded here because its answer shape does not
fit Exp 1A's ranking metrics.

Run this on the Hetzner experiment VM against ``/root/embedded-exports``;
local Windows runs are not authoritative because the corrected export and
temporal graph live on the VM.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.healthcare.exp1A_temporal_retrieval.concept_mappings import (  # noqa: E402
    ATC_CLASS_MAP,
    INDICATION_MAP,
)
from experiments.healthcare.exp1A_temporal_retrieval.task_schema import (  # noqa: E402
    validate_exp1a_task,
)
from experiments.healthcare.qa_generator import SyntheaQAGenerator  # noqa: E402

LOGGER = logging.getLogger(__name__)

def main() -> int:
    """Generate and validate every Exp 1A task-family fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default="/root/embedded-exports",
        help="Corrected embedded export directory on the experiment VM.",
    )
    parser.add_argument(
        "--dataset",
        default="mid_fhirfix",
        help="Dataset suffix used in output fixture names.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "experiments" / "healthcare" / "tasks"),
        help="Directory where exp1A_tasks_*.json fixtures are written.",
    )
    parser.add_argument(
        "--max-per-family",
        type=int,
        default=250,
        help="Maximum tasks to keep per family; use 0 for no cap.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    generator = SyntheaQAGenerator(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    max_tasks = args.max_per_family or None

    family_builders: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "supersession": lambda: generator.generate_supersession_tasks(
            atc_class_map=ATC_CLASS_MAP,
            max_tasks=max_tasks,
        ),
        "regimen_change": lambda: generator.generate_regimen_change_tasks(
            indication_map=INDICATION_MAP,
            max_tasks=max_tasks,
        ),
        "recurring_condition": lambda: generator.generate_recurring_condition_tasks(
            max_tasks=max_tasks,
        ),
        "dose_escalation": lambda: generator.generate_dose_escalation_tasks(
            max_tasks=max_tasks,
        ),
    }

    summary: dict[str, Any] = {}
    for family, build in family_builders.items():
        LOGGER.info("Generating Exp 1A family: %s", family)
        tasks = build()
        for task in tasks:
            validate_exp1a_task(task)
        output_path = output_dir / f"exp1A_tasks_{family}_{args.dataset}.json"
        SyntheaQAGenerator.save_tasks(tasks, output_path)
        summary[family] = summarize_family(tasks)
        if len(tasks) < 150:
            LOGGER.warning(
                "Family %s produced only %d tasks; see generator docstrings for likely sparsity causes.",
                family,
                len(tasks),
            )

    summary_path = output_dir / f"exp1A_tasks_summary_{args.dataset}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    LOGGER.info("Wrote Exp 1A summary to %s", summary_path)
    return 0


def summarize_family(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Return fixture diagnostics used by Phase 1 spot checks."""
    non_boundary = [
        task for task in tasks
        if not task.get("gold_anchor_is_boundary")
    ]
    contains_anchor = [
        task for task in tasks
        if task.get("gold_interval_contains_as_of")
    ]
    return {
        "task_count": len(tasks),
        "anchor_sources": sorted({task["anchor_source"] for task in tasks}),
        "concept_family_count": len({task["concept_family"] for task in tasks}),
        "non_boundary_gold_anchor_rate": (
            len(non_boundary) / len(tasks) if tasks else 0.0
        ),
        "gold_contains_as_of_rate": (
            len(contains_anchor) / len(tasks) if tasks else 0.0
        ),
        "min_distractors": min((len(task["distractors"]) for task in tasks), default=0),
        "max_distractors": max((len(task["distractors"]) for task in tasks), default=0),
    }


if __name__ == "__main__":
    raise SystemExit(main())
