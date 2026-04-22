"""Phase 2 preflight checks for Exp 1A temporal retrieval.

This harness exists to fail fast before any expensive arm sweep runs. The
original Exp 1 benchmark looked healthy enough to execute, but several hidden
setup problems meant its numbers could not answer the intended question. Exp 1A
therefore adds explicit preflight checks for:

1. Task-shape sanity: every task actually has same-family alternatives.
2. Anchor/interval sanity: the written benchmark contract and the generated
   fixtures agree about whether temporal distance can mechanically fire.
3. Predicate inventory sanity: the temporal store contains the predicates the
   experiment claims to rely on.
4. Retrieval sensitivity sanity: changing the half-life can change at least one
   top-1 result on a small supersession pilot.

The harness writes a human-readable report regardless of success. If any check
fails, it also writes a diagnostic report and exits non-zero so later phases do
not proceed on a broken setup.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_memory.temporal.bridge import TemporalBridge
from experiments.healthcare.exp1A_temporal_retrieval.concept_mappings import (
    ATC_CLASS_MAP,
)
from experiments.healthcare.exp1A_temporal_retrieval.task_schema import (
    validate_exp1a_task,
)
from experiments.healthcare.qa_generator import SyntheaQAGenerator

EXPECTED_CORE_PREDICATES = {"PRESCRIBED", "DIAGNOSED_WITH", "HAS_CONDITION"}
EXPECTED_DOSE_PREDICATES = {"DOSE_CHANGED", "HAS_DOSE", "DOSE_ESCALATED", "DOSE_STATE"}


@dataclass
class PreflightCheckResult:
    """Structured result for one preflight assertion."""

    name: str
    passed: bool
    summary: str
    details: list[str]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the Exp 1A preflight harness."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--project-id",
        default="synthea-scale-mid-fhirfix",
        help="Temporal project namespace to inspect through TemporalBridge.",
    )
    parser.add_argument(
        "--tasks-dir",
        default=str(REPO_ROOT / "experiments" / "healthcare" / "tasks"),
        help="Directory containing the generated Exp 1A task fixtures.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="Number of supersession tasks to probe for half-life sensitivity.",
    )
    parser.add_argument(
        "--results-path",
        default=str(Path(__file__).with_name("PREFLIGHT_RESULTS.md")),
        help="Markdown report written for every preflight run.",
    )
    parser.add_argument(
        "--diagnostic-path",
        default=str(Path(__file__).with_name("PREFLIGHT_DIAGNOSTIC.md")),
        help="Markdown diagnostic written only when a check fails.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the full Exp 1A preflight suite and write markdown reports."""
    args = parse_args()
    load_dotenv(REPO_ROOT / ".env", override=False)
    tasks_by_family = load_exp1a_tasks(Path(args.tasks_dir))

    checks = [
        assert_distractor_counts(tasks_by_family),
        assert_non_overlap_fraction(tasks_by_family),
        assert_predicate_presence(args.project_id),
        assert_halflife_sensitivity(
            tasks_by_family.get("supersession", [])[: args.sample_size],
            project_id=args.project_id,
        ),
    ]

    results_path = Path(args.results_path)
    results_path.write_text(render_results_report(args.project_id, checks), encoding="utf-8")

    failed = [check for check in checks if not check.passed]
    if failed:
        diagnostic_path = Path(args.diagnostic_path)
        diagnostic_path.write_text(
            render_diagnostic_report(args.project_id, failed),
            encoding="utf-8",
        )
        return 1
    return 0


def load_exp1a_tasks(tasks_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load and validate every generated Exp 1A fixture file."""
    tasks_by_family: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(tasks_dir.glob("exp1A_tasks_*_mid_fhirfix.json")):
        if "summary" in path.name:
            continue
        family = path.name.replace("exp1A_tasks_", "").replace("_mid_fhirfix.json", "")
        tasks = json.loads(path.read_text(encoding="utf-8"))
        for task in tasks:
            validate_exp1a_task(task)
        tasks_by_family[family] = tasks
    return tasks_by_family


def assert_distractor_counts(tasks_by_family: dict[str, list[dict[str, Any]]]) -> PreflightCheckResult:
    """Assert that every task fixture exposes at least two same-family options.

    Why this check uses the task fixture:
        The current TemporalBridge exposes retrieval and project-level stats, but
        it does not yet offer a cheap full patient-neighborhood scan primitive.
        The generated fixture is therefore the most reliable deterministic view
        of the same-family candidate bank available before the arm runner
        exists.
    """
    failing: list[str] = []
    task_total = 0
    for family, tasks in tasks_by_family.items():
        for task in tasks:
            task_total += 1
            candidate_count = 1 + len(task.get("distractors", []))
            if candidate_count < 2:
                failing.append(f"{family}:{task['id']} candidate_count={candidate_count}")
    if failing:
        return PreflightCheckResult(
            name="distractor_counts",
            passed=False,
            summary=f"{len(failing)} of {task_total} tasks do not expose at least two same-family options.",
            details=failing[:20],
        )
    return PreflightCheckResult(
        name="distractor_counts",
        passed=True,
        summary=f"All {task_total} tasks expose at least two same-family options via gold+distractors.",
        details=[],
    )


def assert_non_overlap_fraction(tasks_by_family: dict[str, list[dict[str, Any]]]) -> PreflightCheckResult:
    """Check the written non-overlap rule from the design and prompt text.

    This intentionally evaluates the literal written assertion even though the
    rest of the Exp 1A design expects the gold fact to be active at ``as_of``.
    If this check fails, the preflight should stop and force the contradiction
    into the open rather than silently choosing one interpretation.
    """
    target_tasks = [
        task
        for family in ("supersession", "regimen_change")
        for task in tasks_by_family.get(family, [])
    ]
    literal_non_overlap = [
        task for task in target_tasks if not task.get("gold_interval_contains_as_of", False)
    ]
    non_boundary = [
        task for task in target_tasks if not task.get("gold_anchor_is_boundary", False)
    ]
    literal_rate = len(literal_non_overlap) / len(target_tasks) if target_tasks else 0.0
    non_boundary_rate = len(non_boundary) / len(target_tasks) if target_tasks else 0.0
    passed = literal_rate >= 0.40
    details = [
        f"literal_non_overlap_rate={literal_rate:.3f} ({len(literal_non_overlap)}/{len(target_tasks)})",
        f"design_consistent_non_boundary_rate={non_boundary_rate:.3f} ({len(non_boundary)}/{len(target_tasks)})",
        "The generated fixtures intentionally make the gold fact active at as_of; "
        "otherwise time-sliced retrieval would not have a well-defined correct answer.",
    ]
    if not passed:
        details.append(
            "This failure indicates a written-spec contradiction, not a generator bug: "
            "the prompt/design text says gold should not contain as_of, while the task "
            "families and scoring rules require the gold fact to be active at as_of."
        )
    return PreflightCheckResult(
        name="non_overlap_fraction",
        passed=passed,
        summary=(
            "Literal written non-overlap rule passes."
            if passed
            else "Literal written non-overlap rule fails; the benchmark spec is internally inconsistent."
        ),
        details=details,
    )


def assert_predicate_presence(project_id: str) -> PreflightCheckResult:
    """Assert that the temporal store contains the predicates Exp 1A expects."""
    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        return PreflightCheckResult(
            name="predicate_presence",
            passed=False,
            summary=f"TemporalBridge unavailable: {bridge.disabled_reason}",
            details=[],
        )
    stats = bridge.project_stats(project_id=project_id)
    predicates = set((stats.get("edges") or {}).get("byPredicate", {}).keys())
    missing_core = sorted(EXPECTED_CORE_PREDICATES - predicates)
    dose_present = sorted(EXPECTED_DOSE_PREDICATES & predicates)
    passed = not missing_core and bool(dose_present)
    details = [
        f"available_predicates={sorted(predicates)}",
        f"missing_core_predicates={missing_core}",
        f"present_dose_predicates={dose_present}",
    ]
    if not passed:
        details.append(
            "Current temporal graph exposes PRESCRIBED/DIAGNOSED_WITH/OBSERVED/UNDERWENT, "
            "but not HAS_CONDITION and not any dedicated dose-change predicate. "
            "That means the written Phase 2 expectation is ahead of the current graph shape."
        )
    return PreflightCheckResult(
        name="predicate_presence",
        passed=passed,
        summary=(
            "All expected temporal predicates are present."
            if passed
            else "Temporal predicate inventory does not match the written Exp 1A preflight contract."
        ),
        details=details,
    )


def assert_halflife_sensitivity(
    sample_tasks: list[dict[str, Any]],
    *,
    project_id: str,
) -> PreflightCheckResult:
    """Assert that changing half-life can change at least one supersession top-1.

    The check uses the bridge directly, with no hard-overlap rescue logic, so it
    approximates the future soft-decay-only arm. We intentionally keep this
    small because the goal is only to catch total invariance before a long run.
    """
    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        return PreflightCheckResult(
            name="halflife_sensitivity",
            passed=False,
            summary=f"TemporalBridge unavailable: {bridge.disabled_reason}",
            details=[],
        )

    generator = SyntheaQAGenerator(REPO_ROOT)
    changed: list[str] = []
    unchanged = 0
    for task in sample_tasks:
        top_30d = extract_top_supersession_candidate(
            bridge=bridge,
            generator=generator,
            task=task,
            project_id=project_id,
            half_life_hours=24 * 30,
        )
        top_1095d = extract_top_supersession_candidate(
            bridge=bridge,
            generator=generator,
            task=task,
            project_id=project_id,
            half_life_hours=24 * 1095,
        )
        if top_30d != top_1095d:
            changed.append(
                f"{task['id']}: 30d={top_30d} vs 1095d={top_1095d}"
            )
        else:
            unchanged += 1

    passed = bool(changed)
    details = [
        f"sample_size={len(sample_tasks)}",
        f"changed_top1_count={len(changed)}",
        f"unchanged_top1_count={unchanged}",
    ] + changed[:10]
    return PreflightCheckResult(
        name="halflife_sensitivity",
        passed=passed,
        summary=(
            "At least one sampled supersession task changes top-1 between 30d and 1095d."
            if passed
            else "No sampled supersession task changed top-1 between 30d and 1095d."
        ),
        details=details,
    )


def extract_top_supersession_candidate(
    *,
    bridge: TemporalBridge,
    generator: SyntheaQAGenerator,
    task: dict[str, Any],
    project_id: str,
    half_life_hours: float,
) -> tuple[str, int | None, int | None] | None:
    """Return the top in-family supersession candidate for one bridge call."""
    as_of_us = int(datetime.fromisoformat(task["as_of_date"]).timestamp() * 1_000_000)
    result = bridge.retrieve(
        project_id=project_id,
        seed_entities=[{"kind": "patient", "name": task["patient_id"]}],
        as_of_us=as_of_us,
        half_life_hours=half_life_hours,
        max_edges=100,
        max_hops=2,
    )
    for row in result.get("results", []):
        if row.get("predicate") != "PRESCRIBED":
            continue
        object_name = ((row.get("object") or {}).get("name")) or ""
        if generator._lookup_exp1a_mapping(object_name, ATC_CLASS_MAP) != task["concept_family"]:
            continue
        return (
            object_name,
            row.get("validFromUs"),
            row.get("validToUs"),
        )
    return None


def render_results_report(project_id: str, checks: list[PreflightCheckResult]) -> str:
    """Render the normal markdown report for a preflight run."""
    lines = [
        "# Exp 1A Preflight Results",
        "",
        f"- Project: `{project_id}`",
        f"- Repo root: `{REPO_ROOT}`",
        f"- Run date: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Overall: `{'PASS' if all(check.passed for check in checks) else 'FAIL'}`",
        "",
    ]
    for check in checks:
        lines.append(f"## {check.name}")
        lines.append("")
        lines.append(f"- Status: `{'PASS' if check.passed else 'FAIL'}`")
        lines.append(f"- Summary: {check.summary}")
        if check.details:
            lines.append("- Details:")
            for detail in check.details:
                lines.append(f"  - {detail}")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_diagnostic_report(project_id: str, failed: list[PreflightCheckResult]) -> str:
    """Render the stop-and-fix markdown diagnostic for failed preflight checks."""
    lines = [
        "# Exp 1A Preflight Diagnostic",
        "",
        f"- Project: `{project_id}`",
        f"- Run date: `{datetime.now().isoformat(timespec='seconds')}`",
        "- Outcome: stop before Phase 3+ because at least one Phase 2 gate failed.",
        "",
        "## Failed Assertions",
        "",
    ]
    for check in failed:
        lines.append(f"### {check.name}")
        lines.append("")
        lines.append(f"- Failure: {check.summary}")
        lines.append("- Likely root cause:")
        if check.name == "non_overlap_fraction":
            lines.append(
                "  - The written Phase 2 assertion conflicts with the Exp 1A task design. "
                "A correct time-sliced gold answer must be active at `as_of`, but the "
                "current assertion asks for the opposite."
            )
            lines.append("- Proposed fix:")
            lines.append(
                "  - Change the check to require non-boundary anchors or a material share "
                "of same-family distractors outside `as_of`, rather than requiring the gold "
                "interval itself to exclude `as_of`."
            )
        elif check.name == "predicate_presence":
            lines.append(
                "  - The temporal graph currently contains `PRESCRIBED`, `DIAGNOSED_WITH`, "
                "`OBSERVED`, and `UNDERWENT`, but not `HAS_CONDITION` and not a dedicated "
                "dose-change predicate. The Phase 2 expectation is ahead of the current data model."
            )
            lines.append("- Proposed fix:")
            lines.append(
                "  - Either relax the assertion to the predicates that actually exist, or "
                "backfill/add the missing predicate semantics before continuing."
            )
        else:
            lines.append("  - See details below.")
            lines.append("- Proposed fix:")
            lines.append("  - Investigate the failing task/sample before continuing.")
        if check.details:
            lines.append("- Evidence:")
            for detail in check.details:
                lines.append(f"  - {detail}")
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
