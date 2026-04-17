"""Export Synthea rows plus precomputed embeddings as chunked JSONL files.

This script is the Colab/GPU half of the two-stage healthcare experiment flow.
It intentionally does *not* talk to Neo4j. Instead it:

1. Streams Synthea rows from FHIR tarballs or CSV directories.
2. Builds the exact text/field-derived entity context used by the healthcare
   ingestion pipeline.
3. Computes embeddings in batches so the GPU is doing useful work.
4. Writes chunked ``.jsonl.gz`` files that the VM-side importer can later load
   into Neo4j without recomputing vectors.

Operational goal:
    Use the expensive GPU runtime only for the embedding-heavy stage. Shut the
    runtime down once chunk files exist on durable storage, then run the Neo4j
    import locally on the storage-heavy VM.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Iterable, Iterator

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from agentic_memory.core.embedding import EmbeddingService
from agentic_memory.healthcare.embedding_payloads import (
    HealthcareEmbeddingPayload,
    build_healthcare_embedding_payload,
)


logger = logging.getLogger("export_embedded_synthea")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the export stage."""
    parser = argparse.ArgumentParser(
        description=(
            "Stream Synthea records, compute embeddings in batches, and export "
            "chunked JSONL files for later Neo4j import."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--data-dir", required=True, help="FHIR tarball, FHIR directory, or CSV directory.")
    parser.add_argument("--output-dir", required=True, help="Directory that will receive chunk-*.jsonl.gz files.")
    parser.add_argument(
        "--project-id",
        default="synthea-export",
        help="Project namespace persisted into each exported record for the importer.",
    )
    parser.add_argument(
        "--max-patients",
        type=int,
        default=None,
        help="Optional patient cap for smoke/mid export runs.",
    )
    parser.add_argument(
        "--chunk-records",
        type=int,
        default=4000,
        help="How many fully embedded records to write per output chunk file.",
    )
    parser.add_argument(
        "--embed-batch-size",
        type=int,
        default=256,
        help="How many prepared texts to send to EmbeddingService.embed_batch at once.",
    )
    parser.add_argument(
        "--skip-observations",
        action="store_true",
        default=False,
        help="Skip observation records to reduce export size for quicker experiments.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Delete existing chunk/manifest files in the output directory before exporting.",
    )
    return parser.parse_args()


def build_embedding_service() -> EmbeddingService:
    """Build the embedding provider used for the export stage.

    The same environment-based provider selection used elsewhere in the repo
    applies here. For the Colab workflow this is typically ``nemotron_local``.
    """
    provider = os.getenv("EMBEDDING_PROVIDER", "gemini")
    api_key_map = {
        "gemini": os.getenv("GOOGLE_API_KEY"),
        "openai": os.getenv("OPENAI_API_KEY"),
        "nemotron": os.getenv("NVIDIA_API_KEY"),
        "nemotron_local": os.getenv("NVIDIA_API_KEY"),
    }
    api_key = api_key_map.get(provider)
    model = os.getenv("AM_LOCAL_EMBED_MODEL") if provider == "nemotron_local" else None
    return EmbeddingService(provider=provider, api_key=api_key, model=model)


def iter_synthea_rows(
    data_dir: Path,
    *,
    max_patients: int | None,
    skip_observations: bool,
) -> Iterator[dict[str, Any]]:
    """Yield normalized Synthea rows in the same order as the ingest CLI.

    Args:
        data_dir: Path to the source dataset.
        max_patients: Optional patient cap.
        skip_observations: Whether to omit observation records.
    """
    is_fhir_tarball = data_dir.suffix in (".gz", ".tgz") or data_dir.name.endswith(".tar.gz")
    is_fhir_dir = data_dir.is_dir() and not (data_dir / "patients.csv").exists()

    if is_fhir_tarball or is_fhir_dir:
        from agentic_memory.healthcare.fhir_loader import SyntheaFHIRLoader

        loader = SyntheaFHIRLoader(data_dir, max_patients=max_patients)
        for row in loader.iter_records():
            if skip_observations and row.get("record_type") == "observation":
                continue
            yield row
        return

    from agentic_memory.healthcare.csv_loader import SyntheaCSVLoader

    loader = SyntheaCSVLoader(data_dir=data_dir, max_patients=max_patients)
    available = set(loader.available_tables())
    ordered_tables: list[tuple[str, Iterable[dict[str, Any]], str]] = []
    if "encounters" in available:
        ordered_tables.append(("encounter", loader.encounters(), "encounters"))
    if "conditions" in available:
        ordered_tables.append(("condition", loader.conditions(), "conditions"))
    if "medications" in available:
        ordered_tables.append(("medication", loader.medications(), "medications"))
    if "observations" in available and not skip_observations:
        ordered_tables.append(("observation", loader.observations(), "observations"))
    if "procedures" in available:
        ordered_tables.append(("procedure", loader.procedures(), "procedures"))

    for record_type, rows, _label in ordered_tables:
        for row in rows:
            row["record_type"] = record_type
            yield row


def write_chunk(
    output_dir: Path,
    *,
    chunk_index: int,
    rows: list[dict[str, Any]],
) -> Path:
    """Write one gzip-compressed JSONL chunk to disk.

    Args:
        output_dir: Destination directory.
        chunk_index: Monotonic chunk number for stable file naming.
        rows: Fully embedded export rows to write.

    Returns:
        Path to the written chunk file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = output_dir / f"chunk-{chunk_index:05d}.jsonl.gz"
    with gzip.open(chunk_path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
    return chunk_path


def prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    """Make the export destination safe for one fresh run.

    Why this exists:
        The exporter writes deterministic chunk filenames such as
        ``chunk-00001.jsonl.gz``. If a prior run already left files in the same
        directory, a smaller rerun could silently leave stale extra chunks
        behind. That would confuse the VM importer, which reads every
        ``chunk-*.jsonl.gz`` file it finds.

    Args:
        output_dir: Directory that will receive the export artifacts.
        overwrite: Whether to clear prior export artifacts first.

    Raises:
        SystemExit: If the directory already contains export artifacts and the
            caller did not explicitly allow overwriting them.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    prior_chunks = sorted(output_dir.glob("chunk-*.jsonl.gz"))
    manifest_path = output_dir / "manifest.json"
    has_prior_export = bool(prior_chunks or manifest_path.exists())

    if not has_prior_export:
        return

    if not overwrite:
        raise SystemExit(
            f"Output directory already contains export artifacts: {output_dir}\n"
            "Pass --overwrite to clear old chunk-*.jsonl.gz files and manifest.json, "
            "or choose a new output directory."
        )

    for chunk_path in prior_chunks:
        chunk_path.unlink()
    if manifest_path.exists():
        manifest_path.unlink()

    # Remove other gzip sidecars created by interrupted experiments so the
    # directory reflects only this run's artifacts.
    for stray in output_dir.glob("*.tmp"):
        if stray.is_file():
            stray.unlink()

    logger.info("Cleared existing export artifacts from %s", output_dir)


def flush_embedding_batch(
    *,
    embedder: EmbeddingService,
    pending_records: list[tuple[dict[str, Any], HealthcareEmbeddingPayload]],
    completed_rows: list[dict[str, Any]],
    project_id: str,
) -> None:
    """Embed the pending records and append export-ready dicts to ``completed_rows``."""
    if not pending_records:
        return

    vectors = embedder.embed_batch([payload.enriched_text for _, payload in pending_records])
    if len(vectors) != len(pending_records):
        raise RuntimeError(
            f"Embedding batch size mismatch: got {len(vectors)} vectors for "
            f"{len(pending_records)} pending records."
        )

    model_name = str(getattr(embedder, "model", None) or getattr(embedder, "provider", "unknown"))
    for (row, payload), vector in zip(pending_records, vectors, strict=True):
        completed_rows.append(
            {
                "project_id": project_id,
                "record_type": payload.record_type,
                "source_key": payload.source_key,
                "content_hash": payload.content_hash,
                "row": row,
                "precomputed_embedding_model": model_name,
                "precomputed_embedding": vector,
                # Durable explanation/debug fields. The importer does not need
                # them to function, but they make the chunk format inspectable
                # without re-deriving semantics.
                "embed_text": payload.embed_text,
                "entities": payload.entities,
            }
        )
    pending_records.clear()


def main() -> None:
    """Run the export stage from raw Synthea rows to chunked embedded files."""
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    if not data_dir.exists():
        raise SystemExit(f"--data-dir does not exist: {data_dir}")
    prepare_output_dir(output_dir, overwrite=args.overwrite)

    embedder = build_embedding_service()
    logger.info(
        "Starting embedded export: provider=%s model=%s output_dir=%s",
        embedder.provider,
        getattr(embedder, "model", None),
        output_dir,
    )

    pending_records: list[tuple[dict[str, Any], HealthcareEmbeddingPayload]] = []
    completed_rows: list[dict[str, Any]] = []
    chunk_index = 0
    total_rows = 0

    manifest: dict[str, Any] = {
        "project_id": args.project_id,
        "embedding_provider": embedder.provider,
        "embedding_model": getattr(embedder, "model", None),
        "data_dir": str(data_dir),
        "max_patients": args.max_patients,
        "chunk_records": args.chunk_records,
        "embed_batch_size": args.embed_batch_size,
        "skip_observations": args.skip_observations,
        "chunks": [],
    }

    for row in iter_synthea_rows(
        data_dir,
        max_patients=args.max_patients,
        skip_observations=args.skip_observations,
    ):
        record_type = row.get("record_type")
        if not isinstance(record_type, str):
            raise RuntimeError(f"Row missing record_type: {row}")

        payload = build_healthcare_embedding_payload(row, record_type)
        pending_records.append((row, payload))
        total_rows += 1

        if len(pending_records) >= args.embed_batch_size:
            flush_embedding_batch(
                embedder=embedder,
                pending_records=pending_records,
                completed_rows=completed_rows,
                project_id=args.project_id,
            )

        if len(completed_rows) >= args.chunk_records:
            chunk_index += 1
            chunk_rows = completed_rows[: args.chunk_records]
            del completed_rows[: args.chunk_records]
            chunk_path = write_chunk(output_dir, chunk_index=chunk_index, rows=chunk_rows)
            manifest["chunks"].append({"path": str(chunk_path), "records": len(chunk_rows)})
            logger.info(
                "Wrote %s with %d records (rows_seen=%d)",
                chunk_path.name,
                len(chunk_rows),
                total_rows,
            )

    flush_embedding_batch(
        embedder=embedder,
        pending_records=pending_records,
        completed_rows=completed_rows,
        project_id=args.project_id,
    )

    if completed_rows:
        chunk_index += 1
        chunk_path = write_chunk(output_dir, chunk_index=chunk_index, rows=completed_rows)
        manifest["chunks"].append({"path": str(chunk_path), "records": len(completed_rows)})
        logger.info(
            "Wrote %s with %d records (final chunk)",
            chunk_path.name,
            len(completed_rows),
        )

    manifest["total_rows"] = total_rows
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Export complete: rows=%d chunks=%d manifest=%s", total_rows, chunk_index, manifest_path)


if __name__ == "__main__":
    main()
