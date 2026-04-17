"""Reusable embedding-payload builders for Synthea healthcare records.

This module extracts the "prepare a healthcare row for embedding" logic from
the Neo4j ingestion path so we can run a two-stage experiment pipeline:

1. Colab/GPU stage:
   - stream Synthea rows
   - derive deterministic field-based entities
   - build the exact text that should be embedded
   - compute vectors in large batches
   - export chunk files to durable storage
2. VM/local-Neo4j stage:
   - read exported chunks
   - ingest graph structure using precomputed vectors
   - avoid recomputing embeddings on the VM

Why this file exists:
    The original healthcare pipeline computed the embedding input and then
    immediately wrote to Neo4j in the same hot loop. That made the notebook
    architecture brittle and slow because GPU work and remote database writes
    were tightly coupled. These helpers make the embedding preparation step
    reusable without forcing callers to instantiate the full ingestion pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from agentic_memory.core.entity_extraction import build_embed_text
from agentic_memory.healthcare.embed_text import (
    build_condition_embed_text,
    build_encounter_embed_text,
    build_medication_embed_text,
    build_observation_embed_text,
    build_procedure_embed_text,
)


_SOURCE_KEY_BY_RECORD_TYPE: dict[str, str] = {
    "encounter": "synthea_encounter",
    "condition": "synthea_condition",
    "medication": "synthea_medication",
    "observation": "synthea_observation",
    "procedure": "synthea_procedure",
}


@dataclass(frozen=True)
class HealthcareEmbeddingPayload:
    """Deterministic embedding input derived from one healthcare record.

    Attributes:
        record_type: Clinical record family such as ``condition`` or
            ``medication``.
        source_key: Agentic Memory source key used for Neo4j labels and
            content identity.
        content_hash: Deterministic composite-key hash for the record.
        embed_text: Human-readable summary text built from the row's fields.
        entities: Deterministic field-derived entity list. This matches the
            bulk-ingest path where we avoid LLM extraction costs.
        enriched_text: Final text sent to the embedding model after
            ``build_embed_text`` prepends entity context.
    """

    record_type: str
    source_key: str
    content_hash: str
    embed_text: str
    entities: list[dict[str, Any]]
    enriched_text: str


def build_healthcare_embedding_payload(
    row: dict[str, Any],
    record_type: str,
) -> HealthcareEmbeddingPayload:
    """Return the deterministic embedding payload for one healthcare row.

    Args:
        row: Normalized healthcare record row from ``SyntheaFHIRLoader`` or
            ``SyntheaCSVLoader``.
        record_type: One of ``encounter``, ``condition``, ``medication``,
            ``observation``, or ``procedure``.

    Returns:
        A :class:`HealthcareEmbeddingPayload` containing the same content hash,
        entity list, and enriched embed text the Neo4j ingestion pipeline uses.

    Raises:
        ValueError: If ``record_type`` is unknown.
    """
    if record_type not in _SOURCE_KEY_BY_RECORD_TYPE:
        raise ValueError(
            f"Unsupported healthcare record_type {record_type!r}. "
            f"Expected one of {sorted(_SOURCE_KEY_BY_RECORD_TYPE)}."
        )

    source_key = _SOURCE_KEY_BY_RECORD_TYPE[record_type]
    embed_text = build_healthcare_embed_text(row, record_type)
    entities = derive_healthcare_entities_from_fields(row, record_type)
    enriched_text = build_embed_text(embed_text, entities)
    content_hash = compute_healthcare_content_hash(row, record_type)

    return HealthcareEmbeddingPayload(
        record_type=record_type,
        source_key=source_key,
        content_hash=content_hash,
        embed_text=embed_text,
        entities=entities,
        enriched_text=enriched_text,
    )


def build_healthcare_embed_text(row: dict[str, Any], record_type: str) -> str:
    """Build the canonical embedding text for one healthcare row.

    Args:
        row: Healthcare record row.
        record_type: Clinical record family for the row.

    Returns:
        The same prose summary string the healthcare pipeline embeds.
    """
    build_fn_map = {
        "encounter": build_encounter_embed_text,
        "condition": build_condition_embed_text,
        "medication": build_medication_embed_text,
        "observation": build_observation_embed_text,
        "procedure": build_procedure_embed_text,
    }
    try:
        return build_fn_map[record_type](row)
    except KeyError as exc:  # pragma: no cover - guarded by caller
        raise ValueError(f"Unsupported healthcare record_type {record_type!r}.") from exc


def derive_healthcare_entities_from_fields(
    row: dict[str, Any],
    record_type: str,
) -> list[dict[str, Any]]:
    """Derive deterministic entities from structured healthcare fields.

    This mirrors the non-LLM bulk-ingestion path in
    :class:`HealthcareIngestionPipeline`. The goal is to keep exported chunks
    semantically aligned with the graph ingest path without paying for model
    extraction.

    Args:
        row: Healthcare record row.
        record_type: Clinical record family for the row.

    Returns:
        List of ``{\"name\": ..., \"type\": ...}`` entity dicts.
    """
    entities: list[dict[str, Any]] = []

    patient_id = row.get("PATIENT")
    if patient_id:
        entities.append({"name": patient_id, "type": "patient"})

    provider_id = row.get("PROVIDER")
    if provider_id:
        entities.append({"name": provider_id, "type": "provider"})

    if record_type == "condition":
        description = row.get("DESCRIPTION")
        if description:
            entities.append({"name": description, "type": "diagnosis"})
    elif record_type == "medication":
        description = row.get("DESCRIPTION")
        if description:
            entities.append({"name": description, "type": "medication"})
    elif record_type == "procedure":
        description = row.get("DESCRIPTION")
        if description:
            entities.append({"name": description, "type": "procedure"})

    return entities


def compute_healthcare_content_hash(row: dict[str, Any], record_type: str) -> str:
    """Return the pipeline-compatible content hash for one healthcare row.

    Args:
        row: Healthcare record row.
        record_type: Clinical record family for the row.

    Returns:
        Hex-encoded SHA-256 digest built from the same composite keys the
        healthcare pipeline uses during direct ingest.
    """
    if record_type == "encounter":
        encounter_id = row.get("Id") or row.get("id") or ""
        return _hash_fields(encounter_id)
    if record_type == "condition":
        return _hash_fields(
            row.get("PATIENT", ""),
            row.get("ENCOUNTER", ""),
            row.get("CODE", ""),
            row.get("START", ""),
        )
    if record_type == "medication":
        return _hash_fields(
            row.get("PATIENT", ""),
            row.get("ENCOUNTER", ""),
            row.get("CODE", ""),
            row.get("START", ""),
        )
    if record_type == "observation":
        return _hash_fields(
            row.get("PATIENT", ""),
            row.get("ENCOUNTER", ""),
            row.get("CODE", ""),
            row.get("DATE", ""),
        )
    if record_type == "procedure":
        return _hash_fields(
            row.get("PATIENT", ""),
            row.get("ENCOUNTER", ""),
            row.get("CODE", ""),
            row.get("DATE", ""),
        )
    raise ValueError(
        f"Unsupported healthcare record_type {record_type!r}. "
        f"Expected one of {sorted(_SOURCE_KEY_BY_RECORD_TYPE)}."
    )


def _hash_fields(*fields: str) -> str:
    """SHA-256 hash of the pipeline's colon-joined composite identity key."""
    composite = ":".join(field or "" for field in fields)
    return hashlib.sha256(composite.encode()).hexdigest()
