"""Measure STOP-date fidelity for chunked Synthea medication claims in SpacetimeDB.

This script answers the specific Phase 6 question raised in
``docs/research/healthcare-experiments/TEMPORAL_BRIDGE_STOP_DATE_FIDELITY.md``:
when a Synthea medication row has a populated ``STOP`` date, how often does the
temporal graph preserve that stop date on the corresponding ``PRESCRIBED``
edge?

Why this script exists:
    Retrieval-level debugging already showed concrete cases where the task
    fixture had a closed medication interval but the temporal graph behaved as
    if that edge were still open. Before interpreting any half-life result, we
    need the blast radius of that ingest fidelity issue.

What the script does:
    1. Iterate exported healthcare chunk rows that map to medication claims
       with a non-empty ``valid_to_us``.
    2. Rebuild the exact temporal claim shape used by the backfill mapper.
    3. Ask the temporal helper for exact graph-edge matches keyed by patient,
       medication description, predicate, and ``valid_from_us``.
    4. Compare Synthea's expected ``STOP`` to the graph edge's ``validToUs``.
    5. Emit a mismatch CSV plus a compact JSON summary for notebook/report use.

Operational note:
    Run this on the authoritative healthcare VM where the corrected export and
    temporal graph live. Local Windows runs are not authoritative for this
    benchmark.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from agentic_memory.temporal.bridge import TemporalBridge
from backfill_healthcare_temporal import (
    build_claim,
    first_selected_record,
    iter_chunk_records,
    load_manifest,
    resolve_project_id,
    select_chunk_paths,
)


LOGGER = logging.getLogger("check_healthcare_stop_date_blast_radius")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the STOP-date fidelity audit."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        default="/root/embedded-exports",
        help="Directory containing chunk-*.jsonl.gz from the corrected export.",
    )
    parser.add_argument(
        "--project-id",
        default="synthea-scale-mid-fhirfix",
        help="Temporal project namespace to inspect.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="How many medication lookups to send to the helper in one request.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Optional cap on closed medication claims to inspect; 0 means no cap.",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help="Same deterministic shard split used by the temporal backfill script.",
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
        help="Optional cap on selected chunk files for focused debugging.",
    )
    parser.add_argument(
        "--mismatch-csv",
        default=str(_REPO_ROOT / "experiments" / "healthcare" / "results" / "stop_date_blast_radius_mismatches.csv"),
        help="CSV path written for rows whose graph stop date does not match Synthea.",
    )
    parser.add_argument(
        "--summary-json",
        default=str(_REPO_ROOT / "experiments" / "healthcare" / "results" / "stop_date_blast_radius_summary.json"),
        help="JSON summary path written for notebook/report consumption.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the STOP-date blast-radius audit and write summary artifacts."""
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        raise SystemExit(
            "Temporal bridge unavailable for STOP-date audit: "
            f"{bridge.disabled_reason}"
        )

    input_dir = Path(args.input_dir)
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
    mismatch_rows: list[dict[str, Any]] = []
    summary = {
        "project_id": project_id,
        "input_dir": str(input_dir),
        "run_date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chunk_count": len(chunk_paths),
        "medication_rows_seen": 0,
        "closed_medication_rows_seen": 0,
        "closed_rows_considered": 0,
        "closed_rows_with_match": 0,
        "closed_rows_exact_stop_match": 0,
        "closed_rows_mismatch": 0,
        "closed_rows_graph_open": 0,
        "closed_rows_missing_in_graph": 0,
        "closed_rows_unlinked_match_only": 0,
        "closed_rows_multiple_matches": 0,
    }

    pending_claims: list[dict[str, Any]] = []
    for item in iter_chunk_records(chunk_paths):
        row = dict(item.get("row") or {})
        record_type = str(item.get("record_type") or row.get("record_type") or "")
        if record_type != "medication":
            continue
        summary["medication_rows_seen"] += 1
        if not row.get("STOP"):
            continue
        summary["closed_medication_rows_seen"] += 1
        if args.max_rows and summary["closed_rows_considered"] + len(pending_claims) >= args.max_rows:
            break
        claim = build_claim(item, project_id=project_id)
        if claim is None or claim.get("predicate") != "PRESCRIBED" or claim.get("valid_to_us") is None:
            continue
        pending_claims.append(claim)
        if len(pending_claims) >= args.batch_size:
            process_claim_batch(
                bridge=bridge,
                claims=pending_claims,
                summary=summary,
                mismatch_rows=mismatch_rows,
            )
            pending_claims = []

    if pending_claims:
        process_claim_batch(
            bridge=bridge,
            claims=pending_claims,
            summary=summary,
            mismatch_rows=mismatch_rows,
        )

    mismatch_csv = Path(args.mismatch_csv)
    mismatch_csv.parent.mkdir(parents=True, exist_ok=True)
    write_mismatch_csv(mismatch_csv, mismatch_rows)

    summary["mismatch_rate"] = (
        summary["closed_rows_mismatch"] / summary["closed_rows_considered"]
        if summary["closed_rows_considered"]
        else 0.0
    )
    summary["exact_match_rate"] = (
        summary["closed_rows_exact_stop_match"] / summary["closed_rows_considered"]
        if summary["closed_rows_considered"]
        else 0.0
    )
    summary["mismatch_csv"] = str(mismatch_csv)
    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    LOGGER.info(
        "STOP-date audit complete: considered=%d exact_matches=%d mismatches=%d graph_open=%d missing=%d unlinked_only=%d",
        summary["closed_rows_considered"],
        summary["closed_rows_exact_stop_match"],
        summary["closed_rows_mismatch"],
        summary["closed_rows_graph_open"],
        summary["closed_rows_missing_in_graph"],
        summary["closed_rows_unlinked_match_only"],
    )
    LOGGER.info("Summary JSON: %s", summary_path)
    LOGGER.info("Mismatch CSV: %s", mismatch_csv)
    return 0


def process_claim_batch(
    *,
    bridge: TemporalBridge,
    claims: list[dict[str, Any]],
    summary: dict[str, Any],
    mismatch_rows: list[dict[str, Any]],
) -> None:
    """Inspect one claim batch and fold its outcomes into the running summary."""
    response = bridge.inspect_claim_edges(
            project_id=str(claims[0]["project_id"]),
        claims=[
            {
                "subjectKind": claim["subject_kind"],
                "subjectName": claim["subject_name"],
                "predicate": claim["predicate"],
                "objectKind": claim["object_kind"],
                "objectName": claim["object_name"],
                "validFromUs": claim["valid_from_us"],
                "evidenceSourceId": (claim.get("evidence") or {}).get("sourceId"),
            }
            for claim in claims
        ],
    )

    for claim, inspected in zip(claims, response.get("claims", []), strict=True):
        summary["closed_rows_considered"] += 1
        outcome = classify_claim_outcome(claim, inspected)
        if outcome["has_match"]:
            summary["closed_rows_with_match"] += 1
        if outcome["exact_stop_match"]:
            summary["closed_rows_exact_stop_match"] += 1
        else:
            summary["closed_rows_mismatch"] += 1
            mismatch_rows.append(outcome["csv_row"])
        if outcome["graph_open"]:
            summary["closed_rows_graph_open"] += 1
        if outcome["missing_in_graph"]:
            summary["closed_rows_missing_in_graph"] += 1
        if outcome["unlinked_match_only"]:
            summary["closed_rows_unlinked_match_only"] += 1
        if outcome["multiple_matches"]:
            summary["closed_rows_multiple_matches"] += 1


def classify_claim_outcome(claim: dict[str, Any], inspected: dict[str, Any]) -> dict[str, Any]:
    """Classify one medication claim against its graph-edge inspection result."""
    matches = list(inspected.get("matches") or [])
    preferred = next((match for match in matches if match.get("evidenceSourceMatched")), None)
    matched_by_source = preferred is not None
    chosen = preferred or (matches[0] if matches else None)
    edge = (chosen or {}).get("edge") or {}

    expected_valid_to_us = claim.get("valid_to_us")
    graph_valid_to_us = edge.get("validToUs")
    exact_stop_match = bool(
        chosen
        and expected_valid_to_us is not None
        and graph_valid_to_us == expected_valid_to_us
    )
    graph_open = bool(chosen and graph_valid_to_us is None)
    missing_in_graph = not matches
    unlinked_match_only = bool(matches and not matched_by_source)
    multiple_matches = len(matches) > 1

    csv_row = {
        "patient_id": claim["subject_name"],
        "code": extract_code_from_source_id((claim.get("evidence") or {}).get("sourceId")),
        "start": micros_to_date(claim.get("valid_from_us")),
        "synthea_stop": micros_to_date(expected_valid_to_us),
        "graph_valid_to": micros_to_date(graph_valid_to_us),
        "graph_valid_to_us": graph_valid_to_us,
        "match_count": len(matches),
        "matched_by_evidence_source": matched_by_source,
        "missing_in_graph": missing_in_graph,
        "graph_open": graph_open,
        "unlinked_match_only": unlinked_match_only,
        "object_name": claim["object_name"],
        "evidence_source_id": (claim.get("evidence") or {}).get("sourceId"),
        "matched_edge_id": edge.get("edgeId"),
    }
    return {
        "has_match": bool(matches),
        "exact_stop_match": exact_stop_match,
        "graph_open": graph_open,
        "missing_in_graph": missing_in_graph,
        "unlinked_match_only": unlinked_match_only,
        "multiple_matches": multiple_matches,
        "csv_row": csv_row,
    }


def write_mismatch_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write mismatch rows to CSV with a stable field order."""
    fieldnames = [
        "patient_id",
        "code",
        "start",
        "synthea_stop",
        "graph_valid_to",
        "graph_valid_to_us",
        "match_count",
        "matched_by_evidence_source",
        "missing_in_graph",
        "graph_open",
        "unlinked_match_only",
        "object_name",
        "evidence_source_id",
        "matched_edge_id",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def micros_to_date(value: int | None) -> str | None:
    """Convert microseconds-since-epoch to an ISO date string."""
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc).date().isoformat()


def extract_code_from_source_id(source_id: str | None) -> str | None:
    """Extract the medication code from the deterministic mapper source id."""
    if not source_id:
        return None
    parts = source_id.split(":")
    if len(parts) < 4:
        return None
    return parts[2]


if __name__ == "__main__":
    raise SystemExit(main())
