"""Verify temporal backfill integrity against a healthcare export subset.

This script is the temporal counterpart to our graph integrity checks.

Why this exists:
    Before running a full temporal backfill, we want a fast smoke test that
    proves two things on a small, isolated project namespace:

    1. the export rows map to the expected temporal predicates
    2. SpacetimeDB actually contains exactly those project-scoped counts after
       the smoke backfill finishes

    The check intentionally focuses on edge/evidence totals and per-predicate
    counts because those are the stable temporal invariants that should remain
    true even if internal node ids or maintenance details change.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import json
import logging
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentic_memory.temporal.bridge import TemporalBridge
from backfill_healthcare_temporal import (
    build_claim,
    first_selected_record,
    iter_chunk_records,
    load_manifest,
    resolve_project_id,
    select_chunk_paths,
)


logger = logging.getLogger("check_healthcare_temporal_integrity")


def _normalize_name(value: str) -> str:
    """Match the SpacetimeDB helper's name normalization rule."""
    return " ".join(value.strip().lower().split())


def _normalize_predicate(value: str) -> str:
    """Match the SpacetimeDB helper's predicate normalization rule."""
    cleaned = []
    for char in value.strip().upper():
        if char.isalnum() or char == "_":
            cleaned.append(char)
        elif char in {" ", "-"}:
            cleaned.append("_")
    return "".join(cleaned)


def _normalize_part(value: Any) -> str:
    """Match the helper's string-normalization before hashing.

    We do not need the exact hash value for integrity checks; we only need the
    same equality semantics. Converting the same conceptual parts into a stable
    tuple gives us that without re-implementing the FNV-1a hash.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return "0" if not math.isfinite(value) else str(value)
        return str(value)
    return str(value)


def _edge_identity(claim: dict[str, Any]) -> tuple[str, ...]:
    """Build the same logical edge identity used by the temporal reducer.

    The reducer hashes project id, normalized node identity, normalized
    predicate, and validity window into ``edgeId``. For smoke-test parity we
    only need the same equality relation, so a normalized tuple is enough.
    """
    return (
        _normalize_part(claim["project_id"]),
        _normalize_part(claim["subject_kind"]),
        _normalize_name(str(claim["subject_name"])),
        _normalize_predicate(str(claim["predicate"])),
        _normalize_part(claim["object_kind"]),
        _normalize_name(str(claim["object_name"])),
        _normalize_part(claim.get("valid_from_us")),
        _normalize_part(claim.get("valid_to_us") if claim.get("valid_to_us") is not None else "open"),
    )


def _evidence_identity(claim: dict[str, Any]) -> tuple[str, ...]:
    """Build the same logical evidence identity used by the temporal helper.

    Important nuance:
        The Python healthcare mapper does not populate ``evidence.hash``.
        The Node bridge fills that in before reducer ingest by hashing a JSON
        payload that includes ``projectId``, source identifiers, ``sourceUri``,
        ``rawExcerpt``, and ``capturedAtUs``.

        The integrity check must mirror that helper behavior exactly. If it
        instead treats a missing hash as an empty string, it will undercount
        distinct evidence rows that share ``sourceId`` but differ in excerpt or
        URI content.
    """
    evidence = claim["evidence"]
    evidence_hash = evidence.get("hash")
    if not evidence_hash:
        helper_hash_payload = {
            "projectId": claim["project_id"],
            "sourceKind": evidence["sourceKind"],
            "sourceId": evidence["sourceId"],
            "sourceUri": evidence.get("sourceUri"),
            "rawExcerpt": evidence.get("rawExcerpt"),
            "capturedAtUs": str(evidence.get("capturedAtUs")),
        }
        evidence_hash = hashlib.sha256(
            json.dumps(helper_hash_payload, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return (
        _normalize_part(claim["project_id"]),
        _normalize_part(evidence["sourceKind"]),
        _normalize_part(evidence["sourceId"]),
        _normalize_part(evidence_hash),
        _normalize_part(evidence.get("capturedAtUs")),
    )


def parse_args() -> argparse.Namespace:
    """Parse CLI flags for the temporal smoke-test integrity checker."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare expected temporal counts from embedded healthcare chunks "
            "to the actual counts stored in SpacetimeDB for one project."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing chunk-*.jsonl.gz and usually manifest.json.",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help=(
            "Project namespace to validate. When omitted, uses manifest.json "
            "or the first selected chunk row. For smoke tests, use a dedicated "
            "temporary project id so exact-match checks stay meaningful."
        ),
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help="Same deterministic shard split used by the backfill script.",
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="Zero-based shard number for this worker.",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help="Optional cap on the selected chunk count for smoke verification.",
    )
    return parser.parse_args()


def build_expected_stats(
    *,
    chunk_paths: list[Path],
    project_id: str,
) -> dict[str, Any]:
    """Compute the temporal counts the selected chunk subset should produce."""
    processed = 0
    skipped = 0
    expected_written = 0
    by_predicate: dict[str, int] = {}
    deduped_edges: set[tuple[str, ...]] = set()
    deduped_evidence: set[tuple[str, ...]] = set()
    deduped_by_predicate: dict[str, int] = {}

    for item in iter_chunk_records(chunk_paths):
        processed += 1
        claim = build_claim(item, project_id=project_id)
        if claim is None:
            skipped += 1
            continue
        expected_written += 1
        predicate = _normalize_predicate(str(claim["predicate"]))
        by_predicate[predicate] = by_predicate.get(predicate, 0) + 1
        edge_id = _edge_identity(claim)
        evidence_id = _evidence_identity(claim)
        if edge_id not in deduped_edges:
            deduped_edges.add(edge_id)
            deduped_by_predicate[predicate] = deduped_by_predicate.get(predicate, 0) + 1
        deduped_evidence.add(evidence_id)

    return {
        "processed": processed,
        "skipped": skipped,
        "rawWritten": expected_written,
        "rawByPredicate": dict(sorted(by_predicate.items())),
        "written": len(deduped_edges),
        "evidence": len(deduped_evidence),
        "byPredicate": dict(sorted(deduped_by_predicate.items())),
    }


def assert_stats_match(
    *,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> None:
    """Raise ``SystemExit`` when temporal stats diverge from expectations."""
    actual_edge_total = int(((actual.get("edges") or {}).get("total")) or 0)
    actual_evidence_total = int(((actual.get("evidence") or {}).get("total")) or 0)
    actual_by_predicate = {
        str(key): int(value)
        for key, value in (((actual.get("edges") or {}).get("byPredicate")) or {}).items()
    }

    mismatches: list[str] = []
    if actual_edge_total != int(expected["written"]):
        mismatches.append(
            f"edge total mismatch: expected {expected['written']} got {actual_edge_total}"
        )
    if actual_evidence_total != int(expected["evidence"]):
        mismatches.append(
            f"evidence total mismatch: expected {expected['evidence']} got {actual_evidence_total}"
        )
    if actual_by_predicate != expected["byPredicate"]:
        mismatches.append(
            "predicate counts mismatch: "
            f"expected {json.dumps(expected['byPredicate'], sort_keys=True)} "
            f"got {json.dumps(actual_by_predicate, sort_keys=True)}"
        )

    if mismatches:
        raise SystemExit(
            "Temporal integrity check failed:\n- " + "\n- ".join(mismatches)
        )


def main() -> None:
    """Run the temporal integrity check for one export subset and project."""
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        raise SystemExit(f"--input-dir is not a directory: {input_dir}")

    chunk_paths = select_chunk_paths(
        input_dir,
        shard_count=args.shard_count,
        shard_index=args.shard_index,
        max_chunks=args.max_chunks,
    )
    manifest = load_manifest(input_dir)
    first_record = first_selected_record(chunk_paths)
    project_id = resolve_project_id(
        cli_project_id=args.project_id,
        manifest=manifest,
        first_record=first_record,
    )

    logger.info(
        "Checking temporal integrity for project_id=%s shard=%d/%d chunks=%d",
        project_id,
        args.shard_index,
        args.shard_count,
        len(chunk_paths),
    )

    expected = build_expected_stats(chunk_paths=chunk_paths, project_id=project_id)
    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        raise SystemExit(
            "Temporal bridge unavailable for integrity check: "
            f"{bridge.disabled_reason}"
        )

    try:
        actual = bridge.project_stats(project_id=project_id)
    finally:
        bridge.close()

    assert_stats_match(expected=expected, actual=actual)
    logger.info(
        "Temporal integrity check passed: expected=%s actual_edges=%s actual_evidence=%s",
        json.dumps(expected, sort_keys=True),
        json.dumps((actual.get("edges") or {}), sort_keys=True),
        json.dumps((actual.get("evidence") or {}), sort_keys=True),
    )


if __name__ == "__main__":
    main()
