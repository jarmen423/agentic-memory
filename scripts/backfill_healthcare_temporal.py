"""Backfill SpacetimeDB temporal claims from embedded healthcare export chunks.

This script is the temporal-only companion to
``scripts/import_embedded_healthcare_chunks.py``.

Why this exists:
    The main healthcare import path now treats Neo4j graph ingestion and
    SpacetimeDB temporal writes as separate stages. That separation keeps the
    fast bulk graph import from paying per-row temporal latency in its hot
    path. Once the graph import is complete, this script can replay the same
    exported healthcare rows into the temporal layer without touching Neo4j.

Operational model:
    1. Read ``chunk-*.jsonl.gz`` files produced by
       ``scripts/export_embedded_synthea.py``.
    2. Reconstruct each normalized healthcare row from the export payload.
    3. Convert supported clinical rows into deterministic temporal claims
       using ``agentic_memory.healthcare.temporal_mapper``.
    4. Send those claims to ``TemporalBridge.ingest_claims(...)`` in batches.

Important scope boundary:
    - Encounter rows are intentionally skipped because the current temporal
      experiment only models conditions, medications, observations, and
      procedures.
    - This script does not write to Neo4j at all.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
from pathlib import Path
import sys
from typing import Any, Callable, Iterator

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from agentic_memory.healthcare.temporal_mapper import (
    condition_to_claim,
    medication_to_claim,
    observation_to_claim,
    procedure_to_claim,
)
from agentic_memory.temporal.bridge import TemporalBridge


logger = logging.getLogger("backfill_healthcare_temporal")

_CLAIM_BUILDERS: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    "condition": condition_to_claim,
    "medication": medication_to_claim,
    "observation": observation_to_claim,
    "procedure": procedure_to_claim,
}


def parse_args() -> argparse.Namespace:
    """Parse CLI flags for the temporal-only backfill run."""
    parser = argparse.ArgumentParser(
        description=(
            "Read embedded healthcare export chunks and backfill only the "
            "SpacetimeDB temporal layer."
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
            "Override project_id stored in manifest/chunks. When omitted, the "
            "script uses manifest.json or the first selected chunk row."
        ),
    )
    parser.add_argument(
        "--batch-log-every",
        type=int,
        default=1000,
        help="Log progress every N processed rows.",
    )
    parser.add_argument(
        "--claim-batch-size",
        type=int,
        default=250,
        help=(
            "How many temporal claims to send in one bridge request. Larger "
            "values reduce Python->Node round-trip overhead."
        ),
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help=(
            "Split chunk files into N deterministic shards so multiple "
            "backfill workers can process disjoint chunk subsets."
        ),
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
        help="Optional cap on the number of selected chunks to process.",
    )
    return parser.parse_args()


def select_chunk_paths(
    input_dir: Path,
    *,
    shard_count: int,
    shard_index: int,
    max_chunks: int | None,
) -> list[Path]:
    """Select the chunk files assigned to this worker.

    The logic intentionally matches the graph importer so performance tests and
    future multi-worker temporal runs can shard the same export directory using
    the same command-line conventions.
    """
    if shard_count < 1:
        raise SystemExit("--shard-count must be >= 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise SystemExit("--shard-index must be in [0, --shard-count)")
    if max_chunks is not None and max_chunks < 1:
        raise SystemExit("--max-chunks must be >= 1 when provided")

    chunk_paths = sorted(input_dir.glob("chunk-*.jsonl.gz"))
    if not chunk_paths:
        raise SystemExit(f"No chunk-*.jsonl.gz files found in {input_dir}")

    selected = [
        path for idx, path in enumerate(chunk_paths) if idx % shard_count == shard_index
    ]
    if max_chunks is not None:
        selected = selected[:max_chunks]
    if not selected:
        raise SystemExit(
            "No chunk files selected after applying shard/max-chunks filters: "
            f"input_dir={input_dir} shard_count={shard_count} "
            f"shard_index={shard_index} max_chunks={max_chunks}"
        )
    return selected


def iter_chunk_records(chunk_paths: list[Path]) -> Iterator[dict[str, Any]]:
    """Yield export records from the selected gzip-compressed chunk files."""
    for path in chunk_paths:
        logger.info("Backfilling chunk %s", path.name)
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Invalid JSON in {path} line {line_number}: {exc}"
                    ) from exc


def load_manifest(input_dir: Path) -> dict[str, Any]:
    """Load the export manifest when present.

    The manifest is optional so the backfill script can still run against a
    directory that contains only chunk files, but it is the best source for
    the intended ``project_id`` and total-row metadata.
    """
    manifest_path = input_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def first_selected_record(chunk_paths: list[Path]) -> dict[str, Any]:
    """Return the first export record from the selected chunk set."""
    try:
        return next(iter(iter_chunk_records(chunk_paths)))
    except StopIteration as exc:
        raise RuntimeError("Selected chunk set was empty.") from exc


def resolve_project_id(
    *,
    cli_project_id: str | None,
    manifest: dict[str, Any],
    first_record: dict[str, Any],
) -> str:
    """Choose the project namespace for the temporal backfill.

    Precedence:
        1. Explicit ``--project-id``
        2. ``manifest.json``
        3. First selected chunk row
        4. Fallback name for ad-hoc debugging
    """
    return (
        cli_project_id
        or manifest.get("project_id")
        or first_record.get("project_id")
        or "synthea-export"
    )


def build_temporal_bridge() -> TemporalBridge:
    """Construct a bridge and fail fast when temporal env config is missing."""
    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        raise RuntimeError(
            "Temporal backfill requested, but TemporalBridge is unavailable: "
            f"{bridge.disabled_reason}"
        )
    return bridge


def build_claim(item: dict[str, Any], *, project_id: str) -> dict[str, Any] | None:
    """Translate one exported chunk item into a temporal claim dict.

    Returns ``None`` for record types that are intentionally out of scope for
    the current temporal experiment.
    """
    row = dict(item.get("row") or {})
    record_type = item.get("record_type") or row.get("record_type")
    if record_type == "encounter":
        return None

    builder = _CLAIM_BUILDERS.get(str(record_type))
    if builder is None:
        raise ValueError(f"Unsupported record_type for temporal backfill: {record_type!r}")
    return builder(row, project_id)


def flush_claim_batch(
    *,
    bridge: TemporalBridge,
    pending_claims: list[dict[str, Any]],
) -> tuple[int, int]:
    """Write one pending temporal batch, with row-level fallback on failure.

    Why this helper exists:
        Bulk bridge requests are the core temporal throughput improvement. At
        the same time, we do not want one bad claim to hide which record broke
        the batch. If the batched request fails, we fall back to row-by-row
        writes for that batch so the operator still gets precise error logs.

    Returns:
        Tuple ``(written, errors)`` for this batch.
    """
    if not pending_claims:
        return 0, 0

    try:
        result = bridge.ingest_claims(claims=pending_claims)
        written = int(result.get("written", len(pending_claims)))
        pending_claims.clear()
        return written, 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Temporal claim batch failed for %d claims; retrying row-by-row. Error: %s",
            len(pending_claims),
            exc,
        )

    written = 0
    errors = 0
    for claim in pending_claims:
        try:
            bridge.ingest_claim(**claim)
            written += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning(
                "Temporal backfill error for predicate=%s source_id=%s: %s",
                claim.get("predicate"),
                (claim.get("evidence") or {}).get("sourceId"),
                exc,
            )
    pending_claims.clear()
    return written, errors


def main() -> None:
    """Run the temporal-only backfill from embedded healthcare chunks."""
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
        "Temporal backfill project_id=%s shard=%d/%d chunks=%d manifest_rows=%s claim_batch_size=%d",
        project_id,
        args.shard_index,
        args.shard_count,
        len(chunk_paths),
        manifest.get("total_rows", "unknown"),
        args.claim_batch_size,
    )

    bridge = build_temporal_bridge()

    processed = 0
    written = 0
    skipped = 0
    errors = 0
    by_type: dict[str, int] = {}
    pending_claims: list[dict[str, Any]] = []

    try:
        for item in iter_chunk_records(chunk_paths):
            processed += 1
            record_type = str(item.get("record_type") or "unknown")
            by_type[record_type] = by_type.get(record_type, 0) + 1

            try:
                claim = build_claim(item, project_id=project_id)
                if claim is None:
                    skipped += 1
                else:
                    pending_claims.append(claim)
                    if len(pending_claims) >= args.claim_batch_size:
                        batch_written, batch_errors = flush_claim_batch(
                            bridge=bridge,
                            pending_claims=pending_claims,
                        )
                        written += batch_written
                        errors += batch_errors
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.warning(
                    "Temporal backfill error for record_type=%s content_hash=%s: %s",
                    record_type,
                    item.get("content_hash"),
                    exc,
                )

            if processed % args.batch_log_every == 0:
                logger.info(
                    "Processed %d rows (written=%d skipped=%d errors=%d)",
                    processed,
                    written,
                    skipped,
                    errors,
                )

        if pending_claims:
            batch_written, batch_errors = flush_claim_batch(
                bridge=bridge,
                pending_claims=pending_claims,
            )
            written += batch_written
            errors += batch_errors
    finally:
        bridge.close()

    logger.info(
        "Temporal backfill complete: processed=%d written=%d skipped=%d errors=%d by_type=%s",
        processed,
        written,
        skipped,
        errors,
        json.dumps(by_type, sort_keys=True),
    )


if __name__ == "__main__":
    main()
