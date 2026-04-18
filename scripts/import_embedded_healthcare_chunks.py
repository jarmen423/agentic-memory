"""Import pre-embedded healthcare chunks into Neo4j on the VM.

This is the storage/graph half of the two-stage healthcare experiment flow.
It expects chunk files produced by ``scripts/export_embedded_synthea.py`` and
reuses :class:`HealthcareIngestionPipeline` for graph semantics, but it skips
all embedding API/model calls by passing precomputed vectors through the row.

Why this script exists:
    The Colab runtime is good at cheap bursty GPU work, but bad at durable
    graph ingestion. The VM is the opposite. This importer lets us upload the
    exported chunk files and perform the write-heavy Neo4j stage locally on the
    machine that already has the disk and database.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from agentic_memory.core.connection import ConnectionManager
from agentic_memory.healthcare.bulk_import import HealthcareBulkImporter
from agentic_memory.healthcare.pipeline import HealthcareIngestionPipeline


logger = logging.getLogger("import_embedded_healthcare_chunks")


class PrecomputedEmbeddingOnlyService:
    """EmbeddingService stand-in for the importer path.

    The healthcare pipeline now checks the source row for a precomputed vector
    before calling ``embed()``. This object exists to make that contract
    explicit: if the importer ever reaches ``embed()``, the chunk format or
    pipeline wiring is wrong and should fail immediately.
    """

    provider = "precomputed"
    model = "precomputed"

    def embed(self, text: str, *, task_instruction: str | None = None) -> list[float]:
        raise RuntimeError(
            "Importer attempted to compute an embedding. Expected "
            "`precomputed_embedding` to be present in the imported row."
        )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the VM-side importer."""
    parser = argparse.ArgumentParser(
        description="Import chunked healthcare export files into Neo4j using precomputed embeddings.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-dir", required=True, help="Directory containing chunk-*.jsonl.gz exports.")
    parser.add_argument(
        "--project-id",
        default=None,
        help="Override project_id stored in the chunks. When omitted, importer uses the first chunk's project_id.",
    )
    parser.add_argument(
        "--batch-log-every",
        type=int,
        default=1000,
        help="Log progress every N imported records.",
    )
    parser.add_argument(
        "--write-batch-size",
        type=int,
        default=250,
        help=(
            "How many imported rows to group into one explicit Neo4j "
            "transaction before committing. Smaller values reduce rollback "
            "blast radius; larger values reduce per-transaction overhead."
        ),
    )
    parser.add_argument(
        "--import-mode",
        choices=("pipeline", "bulk"),
        default="pipeline",
        help=(
            "Import strategy. 'pipeline' reuses HealthcareIngestionPipeline "
            "row-by-row inside a shared transaction. 'bulk' groups rows by "
            "record type and writes them with UNWIND-based bulk Cypher."
        ),
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help=(
            "Split chunk files into N deterministic shards based on lexical "
            "chunk order. This lets multiple importer workers process "
            "disjoint chunk subsets."
        ),
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help=(
            "Zero-based shard number for this worker. Only chunks where "
            "(chunk_position %% shard_count) == shard_index will be imported."
        ),
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help=(
            "Optional cap on the number of selected chunks to import. Useful "
            "for throughput tests without consuming the full dataset."
        ),
    )
    parser.add_argument(
        "--enable-temporal",
        action="store_true",
        default=False,
        help="Re-enable temporal writes during VM import if desired.",
    )
    return parser.parse_args()


def build_connection_manager() -> ConnectionManager:
    """Build a Neo4j connection manager from ``NEO4J_*`` environment variables."""
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    missing = [
        key
        for key, value in [
            ("NEO4J_URI", uri),
            ("NEO4J_USER/NEO4J_USERNAME", user),
            ("NEO4J_PASSWORD", password),
        ]
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
    return ConnectionManager(uri, user, password)


def select_chunk_paths(
    input_dir: Path,
    *,
    shard_count: int,
    shard_index: int,
    max_chunks: int | None,
) -> list[Path]:
    """Choose the chunk files this importer worker is responsible for.

    Why this helper exists:
        Parallelizing the importer safely is easiest when workers operate on
        disjoint files. This helper turns the full lexical chunk list into a
        deterministic shard assignment so multiple workers can be started with
        ``--shard-count`` / ``--shard-index`` and never compete for the same
        compressed chunk file.
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
    """Yield JSON records from the selected chunk files in lexical order."""
    for path in chunk_paths:
        logger.info("Importing chunk %s", path.name)
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


def build_temporal_bridge(enable_temporal: bool):
    """Return an optional temporal bridge for the importer stage."""
    if not enable_temporal:
        return None
    from agentic_memory.temporal.bridge import TemporalBridge

    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        raise RuntimeError(
            f"Temporal import requested, but bridge is unavailable: {bridge.disabled_reason}"
        )
    return bridge


def first_record_embedding_dim(chunk_paths: list[Path]) -> tuple[int, dict[str, Any]]:
    """Return the vector dimension and first record from the selected chunks."""
    first = next(iter(iter_chunk_records(chunk_paths)))
    vector = first.get("precomputed_embedding")
    if not isinstance(vector, list) or not vector:
        raise RuntimeError(
            "First imported row is missing a non-empty `precomputed_embedding` list."
        )
    return len(vector), first


def build_pipeline_row(item: dict[str, Any]) -> dict[str, Any]:
    """Convert one exported chunk item back into a pipeline-ready row dict."""
    row = dict(item.get("row") or {})
    row["record_type"] = item["record_type"]
    row["precomputed_embedding"] = item["precomputed_embedding"]
    row["precomputed_embedding_model"] = item.get("precomputed_embedding_model")
    return row


def import_batch(
    *,
    conn: ConnectionManager,
    pipeline: HealthcareIngestionPipeline,
    bulk_importer: HealthcareBulkImporter,
    batch_items: list[dict[str, Any]],
    import_mode: str,
) -> tuple[int, int]:
    """Import one batch inside a shared transaction, with safe fallback.

    Why this helper exists:
        The importer used to pay one tiny autocommit write path per query.
        This helper groups many row ingests into one transaction so the writer
        layer can reuse a single runner/commit. If the batch hits an error, we
        roll back and replay the batch row-by-row using the legacy path. That
        keeps correctness and debuggability ahead of raw speed while we harden
        the accelerated importer.

    Returns:
        Tuple ``(errors, temporal_written)`` for this batch.
    """
    if not batch_items:
        return 0, 0

    try:
        with conn.session() as session:
            tx = session.begin_transaction()
            temporal_written = 0
            if import_mode == "bulk":
                bulk_importer.import_batch(tx=tx, batch_items=batch_items)
            else:
                for item in batch_items:
                    result = pipeline.ingest_with_runner(
                        build_pipeline_row(item),
                        runner=tx,
                    )
                    if result.get("temporal_written"):
                        temporal_written += 1
            tx.commit()
            return 0, temporal_written
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Batch import failed for %d rows; retrying row-by-row. Error: %s",
            len(batch_items),
            exc,
        )

    errors = 0
    temporal_written = 0
    for item in batch_items:
        try:
            result = pipeline.ingest(build_pipeline_row(item))
            if result.get("temporal_written"):
                temporal_written += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning(
                "Import error for record_type=%s content_hash=%s: %s",
                item.get("record_type"),
                item.get("content_hash"),
                exc,
            )
    return errors, temporal_written


def main() -> None:
    """Run the VM-side import from chunk files into Neo4j."""
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        raise SystemExit(f"--input-dir is not a directory: {input_dir}")
    if args.import_mode == "bulk" and args.enable_temporal:
        raise SystemExit(
            "--import-mode bulk does not currently support temporal writes. "
            "Run graph import first, then temporal as a separate backfill step."
        )

    chunk_paths = select_chunk_paths(
        input_dir,
        shard_count=args.shard_count,
        shard_index=args.shard_index,
        max_chunks=args.max_chunks,
    )

    embedding_dim, first = first_record_embedding_dim(chunk_paths)
    project_id = args.project_id or first.get("project_id") or "synthea-export"
    logger.info(
        "Importer project_id=%s embedding_dim=%d shard=%d/%d chunks=%d",
        project_id,
        embedding_dim,
        args.shard_index,
        args.shard_count,
        len(chunk_paths),
    )

    conn = build_connection_manager()
    conn.setup_database(embedding_dim=embedding_dim)

    temporal_bridge = build_temporal_bridge(args.enable_temporal)
    pipeline = HealthcareIngestionPipeline(
        connection_manager=conn,
        embedding_service=PrecomputedEmbeddingOnlyService(),
        entity_extractor=None,
        temporal_bridge=temporal_bridge,
        project_id=project_id,
        enable_llm_extraction=False,
    )
    bulk_importer = HealthcareBulkImporter(project_id=project_id)

    total = 0
    errors = 0
    temporal_written = 0
    pending_batch: list[dict[str, Any]] = []

    for item in iter_chunk_records(chunk_paths):
        pending_batch.append(item)
        if len(pending_batch) < args.write_batch_size:
            continue

        batch_errors, batch_temporal = import_batch(
            conn=conn,
            pipeline=pipeline,
            bulk_importer=bulk_importer,
            batch_items=pending_batch,
            import_mode=args.import_mode,
        )
        total += len(pending_batch)
        errors += batch_errors
        temporal_written += batch_temporal
        pending_batch.clear()

        if total % args.batch_log_every == 0:
            logger.info(
                "Imported %d rows (errors=%d temporal=%d)",
                total,
                errors,
                temporal_written,
            )

    if pending_batch:
        batch_errors, batch_temporal = import_batch(
            conn=conn,
            pipeline=pipeline,
            bulk_importer=bulk_importer,
            batch_items=pending_batch,
            import_mode=args.import_mode,
        )
        total += len(pending_batch)
        errors += batch_errors
        temporal_written += batch_temporal

    logger.info(
        "Import complete: rows=%d errors=%d temporal=%d",
        total,
        errors,
        temporal_written,
    )
    conn.close()


if __name__ == "__main__":
    main()
