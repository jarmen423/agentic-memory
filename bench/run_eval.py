"""CLI wrapper for the Python retrieval evaluation harness.

This script keeps the eval entrypoint close to ``bench/`` while delegating the
real work to :mod:`agentic_memory.eval.retrieval_eval`, which lives in the
package so tests and future agents can import it directly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_memory.eval.retrieval_eval import (
    DEFAULT_POOL_LIMIT,
    enforce_smoke_gate,
    load_eval_profile,
    run_live_eval,
    run_smoke_eval,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the eval CLI parser."""

    parser = argparse.ArgumentParser(description="Run retrieval evaluation.")
    parser.add_argument(
        "--backend",
        choices=["smoke", "live"],
        default="smoke",
        help="Use deterministic smoke corpora or the current configured live stack.",
    )
    parser.add_argument(
        "--profile",
        choices=["smoke", "gold"],
        default="smoke",
        help="Load the smoke subset or the full gold query fixtures.",
    )
    parser.add_argument(
        "--pool-limit",
        type=int,
        default=DEFAULT_POOL_LIMIT,
        help="Maximum result pool size to evaluate per query/mode.",
    )
    parser.add_argument(
        "--output-dir",
        default="bench/results/eval",
        help="Directory for JSON/Markdown reports.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Optional repository root for live code evaluation.",
    )
    parser.add_argument(
        "--smoke-gate",
        action="store_true",
        help="Fail when the smoke subset misses top-5/top-10 on the recommended mode per domain.",
    )
    return parser


def main() -> int:
    """Run the requested evaluation backend and write reports."""

    parser = build_parser()
    args = parser.parse_args()
    queries = load_eval_profile(args.profile)
    if args.backend == "smoke":
        report = run_smoke_eval(queries=queries, pool_limit=max(1, int(args.pool_limit)))
    else:
        report = run_live_eval(
            queries=queries,
            pool_limit=max(1, int(args.pool_limit)),
            repo_root=Path(args.repo_root).resolve() if args.repo_root else None,
        )

    json_path, markdown_path = write_report(report, output_dir=Path(args.output_dir))
    if args.smoke_gate:
        enforce_smoke_gate(report)

    print(
        json.dumps(
            {
                "backend": report.backend,
                "profile": report.profile,
                "json": str(json_path.resolve()),
                "markdown": str(markdown_path.resolve()),
                "query_count": len(report.results),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
