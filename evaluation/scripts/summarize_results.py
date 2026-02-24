#!/usr/bin/env python3
"""Summarize benchmark results and derive a recommendation signal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 1.0 if numerator <= 0 else float("inf")
    return numerator / denominator


def _round(value: float, digits: int = 4) -> float:
    return float(round(value, digits))


def _build_aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [
        row
        for row in rows
        if row.get("status") == "completed" and row.get("success") is not None
    ]

    task_count = len(rows)
    completed_count = len(completed)
    success_count = sum(1 for row in completed if bool(row.get("success")))

    if completed_count == 0:
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

    latency_values = [float(row.get("latency_ms") or 0.0) for row in completed]
    token_cost_values = [float(row.get("token_cost_usd") or 0.0) for row in completed]
    retries_values = [float(row.get("retries") or 0.0) for row in completed]
    operator_steps_values = [float(row.get("operator_steps") or 0.0) for row in completed]

    return {
        "task_count": task_count,
        "completed_count": completed_count,
        "success_count": success_count,
        "success_rate": _round(success_count / completed_count),
        "avg_latency_ms": _round(sum(latency_values) / completed_count, 2),
        "avg_token_cost_usd": _round(sum(token_cost_values) / completed_count, 6),
        "avg_retries": _round(sum(retries_values) / completed_count, 2),
        "avg_operator_steps": _round(sum(operator_steps_values) / completed_count, 2),
    }


def _derive_recommendation(payload: dict[str, Any]) -> str:
    aggregates = payload.get("aggregates", {})
    mcp = aggregates.get("mcp_native")
    adapter = aggregates.get("skill_adapter")
    if not mcp or not adapter:
        return "pending"

    parity = payload.get("decision_gate", {}).get("parity_requirements", {})
    max_success_delta = float(parity.get("success_rate_delta_max", 0.0))
    max_latency_ratio = float(parity.get("latency_increase_ratio_max", 1.1))
    max_token_ratio = float(parity.get("token_cost_increase_ratio_max", 1.1))
    max_steps_ratio = float(parity.get("operator_steps_increase_ratio_max", 1.25))

    if min(int(mcp.get("completed_count", 0)), int(adapter.get("completed_count", 0))) == 0:
        return "pending"

    success_delta = float(mcp["success_rate"]) - float(adapter["success_rate"])
    latency_ratio = _safe_ratio(float(adapter["avg_latency_ms"]), float(mcp["avg_latency_ms"]))
    token_ratio = _safe_ratio(float(adapter["avg_token_cost_usd"]), float(mcp["avg_token_cost_usd"]))
    steps_ratio = _safe_ratio(float(adapter["avg_operator_steps"]), float(mcp["avg_operator_steps"]))

    if (
        success_delta <= max_success_delta
        and latency_ratio <= max_latency_ratio
        and token_ratio <= max_token_ratio
        and steps_ratio <= max_steps_ratio
    ):
        return "dual_first_class"
    return "mcp_native_default"


def _to_markdown(payload: dict[str, Any]) -> str:
    aggregates = payload.get("aggregates", {})
    mcp = aggregates.get("mcp_native", {})
    adapter = aggregates.get("skill_adapter", {})
    recommendation = payload.get("decision_gate", {}).get("recommendation", "pending")

    return "\n".join(
        [
            "# Benchmark Summary",
            "",
            f"- Run ID: `{payload.get('run_metadata', {}).get('run_id', 'unknown')}`",
            f"- Recommendation signal: `{recommendation}`",
            "",
            "| Workflow | Success Rate | Avg Latency (ms) | Avg Token Cost (USD) | Avg Retries | Avg Operator Steps | Completed |",
            "|----------|--------------|------------------|----------------------|-------------|--------------------|-----------|",
            f"| `mcp_native` | {mcp.get('success_rate', 0.0)} | {mcp.get('avg_latency_ms', 0.0)} | {mcp.get('avg_token_cost_usd', 0.0)} | {mcp.get('avg_retries', 0.0)} | {mcp.get('avg_operator_steps', 0.0)} | {mcp.get('completed_count', 0)}/{mcp.get('task_count', 0)} |",
            f"| `skill_adapter` | {adapter.get('success_rate', 0.0)} | {adapter.get('avg_latency_ms', 0.0)} | {adapter.get('avg_token_cost_usd', 0.0)} | {adapter.get('avg_retries', 0.0)} | {adapter.get('avg_operator_steps', 0.0)} | {adapter.get('completed_count', 0)}/{adapter.get('task_count', 0)} |",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute aggregate benchmark metrics and recommendation signal."
    )
    parser.add_argument("--input", required=True, help="Input results JSON file.")
    parser.add_argument(
        "--output-json",
        default="",
        help="Output JSON path (defaults to overwriting --input).",
    )
    parser.add_argument(
        "--output-md",
        default="",
        help="Optional markdown summary output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_json_path = Path(args.output_json) if args.output_json else input_path

    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Error: input not found: {input_path}")
        return 1
    except json.JSONDecodeError:
        print(f"Error: invalid JSON: {input_path}")
        return 1

    rows = payload.get("results")
    if not isinstance(rows, list) or not rows:
        print("Error: results array is missing or empty.")
        return 1

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        workflow = str(row.get("workflow", "")).strip()
        grouped.setdefault(workflow, []).append(row)

    payload["aggregates"] = {
        workflow: _build_aggregate(workflow_rows)
        for workflow, workflow_rows in grouped.items()
    }

    decision_gate = payload.setdefault("decision_gate", {})
    decision_gate.setdefault("status", "pending")
    decision_gate.setdefault(
        "parity_requirements",
        {
            "success_rate_delta_max": 0.0,
            "latency_increase_ratio_max": 1.1,
            "token_cost_increase_ratio_max": 1.1,
            "operator_steps_increase_ratio_max": 1.25,
        },
    )
    decision_gate["recommendation"] = _derive_recommendation(payload)
    if decision_gate["recommendation"] != "pending":
        decision_gate["status"] = "evaluated"

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    summary = _to_markdown(payload)
    if args.output_md:
        output_md_path = Path(args.output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(summary, encoding="utf-8")
        print(f"Wrote markdown summary: {output_md_path}")

    print(f"Wrote summarized JSON: {output_json_path}")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

