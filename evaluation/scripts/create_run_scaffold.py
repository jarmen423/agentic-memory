#!/usr/bin/env python3
"""Create a benchmark run scaffold for MCP-native vs skill-adapter evaluation."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_WORKFLOWS = {"mcp_native", "skill_adapter"}


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Path("evaluation/results") / f"run-{timestamp}.json"


def _parse_workflows(raw: str) -> list[str]:
    workflows = [part.strip() for part in raw.split(",") if part.strip()]
    if not workflows:
        raise ValueError("At least one workflow is required.")
    invalid = [workflow for workflow in workflows if workflow not in ALLOWED_WORKFLOWS]
    if invalid:
        raise ValueError(f"Unsupported workflows: {', '.join(invalid)}")
    return workflows


def _load_tasks(tasks_path: Path) -> tuple[str, list[Task]]:
    try:
        payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Tasks file not found: {tasks_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Tasks file is not valid JSON: {tasks_path}") from exc

    version = str(payload.get("version", "unknown"))
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("Tasks file must contain a non-empty 'tasks' array.")

    tasks: list[Task] = []
    seen_ids: set[str] = set()
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            raise ValueError("Each task must be an object.")
        task_id = str(raw_task.get("id", "")).strip()
        title = str(raw_task.get("title", "")).strip()
        if not task_id or not title:
            raise ValueError("Each task requires non-empty 'id' and 'title'.")
        if task_id in seen_ids:
            raise ValueError(f"Duplicate task id detected: {task_id}")
        seen_ids.add(task_id)
        tasks.append(Task(task_id=task_id, title=title))

    return version, tasks


def _empty_aggregate(task_count: int) -> dict[str, Any]:
    return {
        "task_count": task_count,
        "completed_count": 0,
        "success_count": 0,
        "success_rate": 0.0,
        "avg_latency_ms": 0.0,
        "avg_token_cost_usd": 0.0,
        "avg_retries": 0.0,
        "avg_operator_steps": 0.0,
    }


def _make_result_row(task: Task, workflow: str) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "task_title": task.title,
        "workflow": workflow,
        "status": "pending",
        "success": None,
        "latency_ms": None,
        "token_cost_usd": None,
        "retries": 0,
        "operator_steps": None,
        "notes": "",
    }


def _build_scaffold(
    *,
    run_id: str,
    dataset_version: str,
    tasks_file: Path,
    tasks: list[Task],
    workflows: list[str],
    operator: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "run_metadata": {
            "run_id": run_id,
            "created_at": _utc_now_iso(),
            "dataset_version": dataset_version,
            "workflows": workflows,
            "operator": operator,
            "notes": notes,
        },
        "tasks_file": tasks_file.as_posix(),
        "results": [
            _make_result_row(task, workflow)
            for workflow in workflows
            for task in tasks
        ],
        "aggregates": {
            workflow: _empty_aggregate(len(tasks))
            for workflow in workflows
        },
        "decision_gate": {
            "status": "pending",
            "parity_requirements": {
                "success_rate_delta_max": 0.0,
                "latency_increase_ratio_max": 1.1,
                "token_cost_increase_ratio_max": 1.1,
                "operator_steps_increase_ratio_max": 1.25,
            },
            "recommendation": "pending",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a benchmark run scaffold for MCP-native vs skill-adapter evaluation."
    )
    parser.add_argument(
        "--tasks",
        default="evaluation/tasks/benchmark_tasks.json",
        help="Path to benchmark tasks JSON file.",
    )
    parser.add_argument(
        "--workflows",
        default="mcp_native,skill_adapter",
        help="Comma-separated workflows (mcp_native, skill_adapter).",
    )
    parser.add_argument(
        "--operator",
        default="unassigned",
        help="Operator or evaluator name for run metadata.",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional run notes.",
    )
    parser.add_argument(
        "--run-id",
        default=f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        help="Explicit run identifier.",
    )
    parser.add_argument(
        "--output",
        default=str(_default_output_path()),
        help="Output path for scaffold JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    tasks_path = Path(args.tasks)
    output_path = Path(args.output)

    try:
        workflows = _parse_workflows(args.workflows)
        dataset_version, tasks = _load_tasks(tasks_path)
    except ValueError as err:
        print(f"Error: {err}")
        return 1

    scaffold = _build_scaffold(
        run_id=args.run_id,
        dataset_version=dataset_version,
        tasks_file=tasks_path,
        tasks=tasks,
        workflows=workflows,
        operator=args.operator,
        notes=args.notes,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(scaffold, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote scaffold: {output_path}")
    print(f"Tasks: {len(tasks)}")
    print(f"Workflows: {', '.join(workflows)}")
    print(f"Rows: {len(scaffold['results'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

