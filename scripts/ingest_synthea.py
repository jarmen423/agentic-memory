"""CLI entry point — ingest Synthea CSV data into Neo4j + SpacetimeDB.

Usage:
    python scripts/ingest_synthea.py \\
        --data-dir "G:/My Drive/.../synthea_2017_02_27/" \\
        --project-id synthea-experiment \\
        --batch-size 500 \\
        --max-patients 1000 \\
        --enable-temporal \\
        --enable-llm-extraction

Required environment variables:
    NEO4J_URI       — e.g. bolt://localhost:7687
    NEO4J_USER      — e.g. neo4j
    NEO4J_PASSWORD  — your Neo4j password

Optional environment variables (embedding provider):
    EMBEDDING_PROVIDER   — "gemini" (default), "openai", or "nemotron"
    GOOGLE_API_KEY       — required for Gemini
    OPENAI_API_KEY       — required for OpenAI
    GROQ_API_KEY         — required for LLM entity extraction (--enable-llm-extraction)

Ingestion order (respects foreign-key dependencies):
    1. patients.csv    → builds patient lookup + populates max_patients filter
    2. encounters.csv  → Encounter nodes, HAD_ENCOUNTER + TREATED_BY rels
    3. conditions.csv  → Condition nodes, DIAGNOSED_WITH rels + temporal claims
    4. medications.csv → Medication nodes, PRESCRIBED rels + temporal claims
    5. observations.csv → Observation nodes + temporal claims
    6. procedures.csv  → Procedure nodes + temporal claims

For a dev run (fast, 100 patients, no SpacetimeDB):
    python scripts/ingest_synthea.py --data-dir /path/to/csv --max-patients 100

For the full experimental run with temporal layer:
    python scripts/ingest_synthea.py --data-dir /path/to/csv --enable-temporal
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Allow running from the repo root without installing the package
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

# Auto-load .env from repo root so the script works without manually sourcing it.
# python-dotenv is a dev dependency; if absent we fall through silently.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

# STDB_BINDINGS_MODULE is stored as a relative path in .env.
# The bridge subprocess resolves it with path.resolve() from its CWD, so we
# convert it to absolute here before any subprocess is spawned.
_bindings = os.environ.get("STDB_BINDINGS_MODULE", "")
if _bindings and not os.path.isabs(_bindings):
    os.environ["STDB_BINDINGS_MODULE"] = str(_REPO_ROOT / _bindings)

from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.embedding import EmbeddingService
from agentic_memory.healthcare.pipeline import HealthcareIngestionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("ingest_synthea")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed argparse namespace.
    """
    parser = argparse.ArgumentParser(
        description="Ingest Synthea CSV healthcare data into the agentic-memory graph.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help=(
            "Path to Synthea data. Can be: "
            "(1) a .tar.gz file (outer Synthea download — FHIR bundles streamed without extraction), "
            "(2) a directory of extracted .tar.gz sub-archives, or "
            "(3) a directory of CSV files (requires running Synthea locally with --exporter.csv.export=true)."
        ),
    )
    parser.add_argument(
        "--project-id",
        default="synthea-experiment",
        help="Project namespace used for SpacetimeDB temporal isolation.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of records to process before logging a progress update.",
    )
    parser.add_argument(
        "--max-patients",
        type=int,
        default=None,
        help="Limit to this many unique patients. Omit for the full dataset.",
    )
    parser.add_argument(
        "--enable-temporal",
        action="store_true",
        default=False,
        help="Shadow-write temporal claims to SpacetimeDB (requires STDB setup).",
    )
    parser.add_argument(
        "--enable-llm-extraction",
        action="store_true",
        default=False,
        help=(
            "Run LLM entity extraction per row (slow, costs API credits). "
            "Default: structured field-derived extraction (free, fast)."
        ),
    )
    parser.add_argument(
        "--skip-observations",
        action="store_true",
        default=False,
        help="Skip observations.csv (large table — reduces run time for quick tests).",
    )
    return parser.parse_args()


def build_connection_manager() -> ConnectionManager:
    """Build a ConnectionManager from NEO4J_* environment variables.

    Returns:
        Configured ConnectionManager.

    Raises:
        SystemExit: If required env vars are missing.
    """
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")

    missing = [k for k, v in [("NEO4J_URI", uri), ("NEO4J_USER/NEO4J_USERNAME", user), ("NEO4J_PASSWORD", password)] if not v]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    return ConnectionManager(uri, user, password)


def build_embedding_service() -> EmbeddingService:
    """Build an EmbeddingService using the configured provider.

    Provider is selected via EMBEDDING_PROVIDER env var (default: gemini).

    Returns:
        Configured EmbeddingService.
    """
    provider = os.getenv("EMBEDDING_PROVIDER", "gemini")

    api_key_map = {
        "gemini": os.getenv("GOOGLE_API_KEY"),
        "openai": os.getenv("OPENAI_API_KEY"),
        "nemotron": os.getenv("NVIDIA_API_KEY"),
    }
    api_key = api_key_map.get(provider)
    if not api_key:
        logger.warning(
            "No API key found for provider '%s'. Set the appropriate env var.", provider
        )

    return EmbeddingService(provider=provider, api_key=api_key)


def ingest_table(
    pipeline: HealthcareIngestionPipeline,
    rows,
    record_type: str,
    batch_size: int,
    label: str,
) -> dict[str, int]:
    """Ingest all rows from a single CSV table via the pipeline.

    Args:
        pipeline: Configured HealthcareIngestionPipeline.
        rows: Iterable of normalised CSV row dicts.
        record_type: One of "encounter", "condition", "medication", etc.
        batch_size: Rows per progress log line.
        label: Human-readable table name for log messages.

    Returns:
        Dict with keys: total, errors, temporal_written.
    """
    total = errors = temporal = 0

    for row in rows:
        row["record_type"] = record_type
        try:
            result = pipeline.ingest(row)
            if result.get("temporal_written"):
                temporal += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning("Error ingesting %s row: %s", label, exc)
        finally:
            total += 1

        if total % batch_size == 0:
            logger.info(
                "[%s] %d rows processed, %d errors, %d temporal writes",
                label,
                total,
                errors,
                temporal,
            )

    logger.info(
        "[%s] DONE: %d rows, %d errors, %d temporal writes",
        label,
        total,
        errors,
        temporal,
    )
    return {"total": total, "errors": errors, "temporal_written": temporal}


def main() -> None:
    """Run the full Synthea ingestion pipeline."""
    args = parse_args()

    # Validate data directory
    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        logger.error("--data-dir does not exist or is not a directory: %s", data_dir)
        sys.exit(1)

    # Build services
    conn = build_connection_manager()
    embedder = build_embedding_service()

    # Optional: LLM entity extractor
    extractor = None
    if args.enable_llm_extraction:
        from agentic_memory.core.entity_extraction import EntityExtractionService
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            logger.error("--enable-llm-extraction requires GROQ_API_KEY env var.")
            sys.exit(1)
        extractor = EntityExtractionService(
            api_key=groq_key,
            allowed_types=["patient", "provider", "diagnosis", "medication", "procedure"],
        )

    # Optional: SpacetimeDB temporal bridge
    temporal_bridge = None
    if args.enable_temporal:
        from agentic_memory.temporal.bridge import TemporalBridge
        temporal_bridge = TemporalBridge.from_env()
        if not temporal_bridge.is_available():
            logger.warning(
                "SpacetimeDB bridge unavailable (%s). Temporal writes disabled.",
                temporal_bridge.disabled_reason,
            )
            temporal_bridge = None

    # Bootstrap Neo4j schema (vector indexes + constraints)
    logger.info("Running setup_database()...")
    conn.setup_database()

    # Initialise pipeline
    pipeline = HealthcareIngestionPipeline(
        connection_manager=conn,
        embedding_service=embedder,
        entity_extractor=extractor,
        temporal_bridge=temporal_bridge,
        project_id=args.project_id,
        enable_llm_extraction=args.enable_llm_extraction,
    )

    # Auto-detect data format: FHIR (nested tarballs) or CSV (directory)
    # Both Synthea downloads from synthea.mitre.org/downloads are FHIR bundles.
    # CSV requires running Synthea locally with --exporter.csv.export=true.
    is_fhir_tarball = data_dir.suffix in (".gz", ".tgz") or data_dir.name.endswith(".tar.gz")
    is_fhir_dir = data_dir.is_dir() and not (data_dir / "patients.csv").exists()

    if is_fhir_tarball or is_fhir_dir:
        logger.info("Detected FHIR bundle format — using SyntheaFHIRLoader.")
        from agentic_memory.healthcare.fhir_loader import SyntheaFHIRLoader
        fhir_loader = SyntheaFHIRLoader(data_dir, max_patients=args.max_patients)

        logger.info("Loading patient lookup...")
        patient_lookup = fhir_loader.load_patient_lookup()
        logger.info("Patients loaded: %d", len(patient_lookup))

        # Reset loader so iter_records() starts from the beginning
        from agentic_memory.healthcare.fhir_loader import SyntheaFHIRLoader
        fhir_loader2 = SyntheaFHIRLoader(data_dir, max_patients=args.max_patients)

        totals: dict[str, dict[str, int]] = {}
        record_type_counts: dict[str, int] = {}
        record_type_errors: dict[str, int] = {}
        record_type_temporal: dict[str, int] = {}

        total = errors = temporal = 0
        for row in fhir_loader2.iter_records():
            record_type = row.get("record_type", "unknown")

            # Skip observations if flagged
            if record_type == "observation" and args.skip_observations:
                continue

            try:
                result = pipeline.ingest(row)
                if result.get("temporal_written"):
                    temporal += 1
                    record_type_temporal[record_type] = record_type_temporal.get(record_type, 0) + 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                record_type_errors[record_type] = record_type_errors.get(record_type, 0) + 1
                logger.warning("Error ingesting %s row: %s", record_type, exc)
            finally:
                total += 1
                record_type_counts[record_type] = record_type_counts.get(record_type, 0) + 1

            if total % args.batch_size == 0:
                logger.info(
                    "[FHIR] %d rows processed, %d errors, %d temporal",
                    total,
                    errors,
                    temporal,
                )

        for rtype, count in record_type_counts.items():
            totals[rtype] = {
                "total": count,
                "errors": record_type_errors.get(rtype, 0),
                "temporal_written": record_type_temporal.get(rtype, 0),
            }

    else:
        logger.info("Detected CSV format — using SyntheaCSVLoader.")
        from agentic_memory.healthcare.csv_loader import SyntheaCSVLoader
        loader = SyntheaCSVLoader(data_dir=data_dir, max_patients=args.max_patients)

        available = loader.available_tables()
        logger.info("Available Synthea tables: %s", available)

        logger.info("Loading patient lookup...")
        patient_lookup = loader.load_patient_lookup()
        logger.info("Patients loaded: %d", len(patient_lookup))

        totals: dict[str, dict[str, int]] = {}

        if "encounters" in available:
            totals["encounters"] = ingest_table(
                pipeline, loader.encounters(), "encounter", args.batch_size, "encounters"
            )
        if "conditions" in available:
            totals["conditions"] = ingest_table(
                pipeline, loader.conditions(), "condition", args.batch_size, "conditions"
            )
        if "medications" in available:
            totals["medications"] = ingest_table(
                pipeline, loader.medications(), "medication", args.batch_size, "medications"
            )
        if "observations" in available and not args.skip_observations:
            totals["observations"] = ingest_table(
                pipeline, loader.observations(), "observation", args.batch_size, "observations"
            )
        elif args.skip_observations:
            logger.info("Skipping observations (--skip-observations flag set).")
        if "procedures" in available:
            totals["procedures"] = ingest_table(
                pipeline, loader.procedures(), "procedure", args.batch_size, "procedures"
            )

    # Final summary
    logger.info("=" * 60)
    logger.info("INGESTION COMPLETE")
    for table, stats in totals.items():
        logger.info(
            "  %-15s  total=%-8d  errors=%-5d  temporal=%d",
            table,
            stats["total"],
            stats["errors"],
            stats["temporal_written"],
        )
    logger.info("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
