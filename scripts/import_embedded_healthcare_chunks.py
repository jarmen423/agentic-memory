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


def iter_chunk_records(input_dir: Path) -> Iterator[dict[str, Any]]:
    """Yield JSON records from all chunk files in lexical order."""
    chunk_paths = sorted(input_dir.glob("chunk-*.jsonl.gz"))
    if not chunk_paths:
        raise SystemExit(f"No chunk-*.jsonl.gz files found in {input_dir}")

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


def first_record_embedding_dim(input_dir: Path) -> tuple[int, dict[str, Any]]:
    """Return the vector dimension and first record from the input directory."""
    first = next(iter(iter_chunk_records(input_dir)))
    vector = first.get("precomputed_embedding")
    if not isinstance(vector, list) or not vector:
        raise RuntimeError(
            "First imported row is missing a non-empty `precomputed_embedding` list."
        )
    return len(vector), first


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

    embedding_dim, first = first_record_embedding_dim(input_dir)
    project_id = args.project_id or first.get("project_id") or "synthea-export"
    logger.info("Importer project_id=%s embedding_dim=%d", project_id, embedding_dim)

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

    total = 0
    errors = 0
    temporal_written = 0

    for item in iter_chunk_records(input_dir):
        row = dict(item.get("row") or {})
        row["record_type"] = item["record_type"]
        row["precomputed_embedding"] = item["precomputed_embedding"]
        row["precomputed_embedding_model"] = item.get("precomputed_embedding_model")

        try:
            result = pipeline.ingest(row)
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
        finally:
            total += 1

        if total % args.batch_log_every == 0:
            logger.info(
                "Imported %d rows (errors=%d temporal=%d)",
                total,
                errors,
                temporal_written,
            )

    logger.info(
        "Import complete: rows=%d errors=%d temporal=%d",
        total,
        errors,
        temporal_written,
    )
    conn.close()


if __name__ == "__main__":
    main()
