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

EXPECTED_REQUIRED_PREDICATES = {"PRESCRIBED", "DIAGNOSED_WITH"}
OPTIONAL_PREDICATES = {"OBSERVED", "UNDERWENT"}
EXP1A_RANKING_FAMILIES = (
    "supersession",
    "regimen_change",
    "recurring_condition",
    "dose_escalation",
)


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
        assert_task_wellformed(tasks_by_family),
        assert_distractor_gap_fraction(tasks_by_family),
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
    diagnostic_path = Path(args.diagnostic_path)
    if diagnostic_path.exists():
        diagnostic_path.unlink()
    return 0


def load_exp1a_tasks(tasks_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load and validate Exp 1A's four ranking-family fixture files.

    Exp 1A and Exp 1B intentionally share the same tasks directory. We therefore
    load the four ranking families explicitly instead of globbing every
    ``exp1A_tasks_*`` file. This prevents the counterfactual/yes-no fixture from
    being silently pulled back into Exp 1A if someone leaves an old
    ``retrospective_state`` artifact beside the ranking bundles.
    """
    tasks_by_family: dict[str, list[dict[str, Any]]] = {}
    for family in EXP1A_RANKING_FAMILIES:
        path = tasks_dir / f"exp1A_tasks_{family}_mid_fhirfix.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing Exp 1A fixture for family {family!r}: {path}")
        tasks = json.loads(path.read_text(encoding="utf-8"))
        for task in tasks:
            validate_exp1a_task(task)
        tasks_by_family[family] = tasks
    return tasks_by_family


def assert_task_wellformed(tasks_by_family: dict[str, list[dict[str, Any]]]) -> PreflightCheckResult:
    """Assert that every task satisfies the Phase 2 well-formedness contract."""
    failing: list[str] = []
    task_total = 0
    for family, tasks in tasks_by_family.items():
        for task in tasks:
            task_total += 1
            candidate_count = 1 + len(task.get("distractors", []))
            as_of_date = task["as_of_date"]
            gold = task["gold"]
            valid_from = gold.get("valid_from")
            valid_to = gold.get("valid_to")
            if candidate_count < 2:
                failing.append(f"{family}:{task['id']} candidate_count={candidate_count}")
            if not task.get("gold_interval_contains_as_of", False):
                failing.append(f"{family}:{task['id']} gold does not overlap as_of={as_of_date}")
            if as_of_date in {valid_from, valid_to}:
                failing.append(
                    f"{family}:{task['id']} as_of lands on gold boundary "
                    f"(valid_from={valid_from}, valid_to={valid_to}, as_of={as_of_date})"
                )
    if failing:
        return PreflightCheckResult(
            name="task_wellformed",
            passed=False,
            summary=f"{len(failing)} well-formedness violations were found across {task_total} tasks.",
            details=failing[:20],
        )
    return PreflightCheckResult(
        name="task_wellformed",
        passed=True,
        summary=(
            f"All {task_total} tasks have at least two same-family candidates, "
            "gold overlaps as_of, and as_of is not on a gold boundary."
        ),
        details=[],
    )


def assert_distractor_gap_fraction(tasks_by_family: dict[str, list[dict[str, Any]]]) -> PreflightCheckResult:
    """Assert that enough tasks expose out-of-interval distractor gaps.

    The gold fact is supposed to overlap ``as_of``. Soft decay can therefore
    only affect ranking when at least one same-family distractor lives entirely
    outside the query interval, putting that distractor in the decayed zone.
    """
    target_tasks = [
        task
        for family in ("supersession", "regimen_change")
        for task in tasks_by_family.get(family, [])
    ]
    gapped_tasks: list[str] = []
    ungapped_examples: list[str] = []
    for task in target_tasks:
        as_of = task["as_of_date"]
        has_gap = any(
            distractor_gap_outside_as_of(distractor, as_of)
            for distractor in task.get("distractors", [])
        )
        if has_gap:
            gapped_tasks.append(task["id"])
        elif len(ungapped_examples) < 20:
            ungapped_examples.append(task["id"])
    gap_rate = len(gapped_tasks) / len(target_tasks) if target_tasks else 0.0
    passed = gap_rate >= 0.40
    details = [
        f"gap_rate={gap_rate:.3f} ({len(gapped_tasks)}/{len(target_tasks)})",
        "A task counts as gapped only when at least one same-family distractor "
        "has valid_to < as_of or valid_from > as_of.",
    ]
    if not passed:
        details.append("example_ungapped_tasks=" + ", ".join(ungapped_examples))
    return PreflightCheckResult(
        name="distractor_gap_fraction",
        passed=passed,
        summary=(
            "The distractor-gap rule passes."
            if passed
            else "Too few supersession/regimen tasks have out-of-interval same-family distractors."
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
    missing_required = sorted(EXPECTED_REQUIRED_PREDICATES - predicates)
    optional_present = sorted(OPTIONAL_PREDICATES & predicates)
    details = [
        f"available_predicates={sorted(predicates)}",
        f"missing_required_predicates={missing_required}",
        f"optional_present_predicates={optional_present}",
    ]
    passed = not missing_required
    return PreflightCheckResult(
        name="predicate_presence",
        passed=passed,
        summary=(
            "All required temporal predicates are present."
            if passed
            else "Required Exp 1A temporal predicates are missing from the current project."
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
        if check.name == "distractor_gap_fraction":
            lines.append(
                "  - Phase 1 anchor selection or distractor construction is producing "
                "too many tasks where every same-family distractor still straddles `as_of`, "
                "so soft decay never gets a chance to penalize the distractor class."
            )
            lines.append("- Proposed fix:")
            lines.append(
                "  - Regenerate the affected task families with stricter anchor-policy rules: "
                "prefer anchors that sit well inside the gold interval while leaving at least "
                "one earlier or later same-family distractor entirely outside `as_of`."
            )
        elif check.name == "predicate_presence":
            lines.append(
                "  - The temporal graph is missing one of the required Exp 1A predicates "
                "(`PRESCRIBED` or `DIAGNOSED_WITH`) for this project."
            )
            lines.append("- Proposed fix:")
            lines.append(
                "  - Repair the backfill or point the experiment at the correct project "
                "before continuing."
            )
        elif check.name == "halflife_sensitivity":
            lines.append(
                "  - The half-life probe stayed invariant across the sampled supersession tasks. "
                "This usually means the distractor-gap rule was only satisfied vacuously, "
                "for example by tiny temporal gaps that do not materially change ranking."
            )
            lines.append("- Proposed fix:")
            lines.append(
                "  - Treat this as a Phase 1 regeneration signal. Tighten the anchor-policy "
                "and distractor-gap construction rather than weakening preflight."
            )
        elif check.name == "task_wellformed":
            task_wellformed_note = classify_task_wellformed_failure(check.details)
            lines.append(f"  - {task_wellformed_note['root_cause']}")
            lines.append("- Proposed fix:")
            lines.append(f"  - {task_wellformed_note['proposed_fix']}")
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


def distractor_gap_outside_as_of(distractor: dict[str, Any], as_of: str) -> bool:
    """Return whether a distractor interval lies entirely outside ``as_of``."""
    valid_from = distractor.get("valid_from")
    valid_to = distractor.get("valid_to")
    return (bool(valid_to) and valid_to < as_of) or (bool(valid_from) and valid_from > as_of)


def classify_task_wellformed_failure(details: list[str]) -> dict[str, str]:
    """Summarize the dominant task-wellformed failure mode.

    This keeps the markdown diagnostic specific enough to tell the user whether
    preflight found broad generator corruption or a single family whose task
    semantics no longer match the shared Exp 1A contract.
    """
    retrospective_non_overlap = [
        detail
        for detail in details
        if detail.startswith("retrospective_state:") and "gold does not overlap as_of" in detail
    ]
    if details and len(retrospective_non_overlap) == len(details):
        return {
            "root_cause": (
                "The failure is localized to the `retrospective_state` family. "
                "That family is a year-level yes/no classification task, but "
                "Exp 1A is a ranking benchmark whose contract requires every "
                "gold interval to overlap `as_of`. Negative retrospective tasks "
                "therefore violate the ranking invariant by design."
            ),
            "proposed_fix": (
                "Treat this as a Phase 0 scoping error, not a rule-weakening or "
                "gold-regeneration signal. Remove `retrospective_state` from the "
                "Exp 1A bundle and consume it under Exp 1B's "
                "`counterfactual_timing` family instead."
            ),
        }
    return {
        "root_cause": (
            "Some generated tasks are malformed: missing enough same-family "
            "candidates, gold not active at `as_of`, or `as_of` landing exactly "
            "on the gold boundary."
        ),
        "proposed_fix": "Regenerate the malformed families before continuing.",
    }


if __name__ == "__main__":
    raise SystemExit(main())
