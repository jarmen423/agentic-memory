"""Healthcare ingestion pipeline — Synthea CSV → Neo4j + SpacetimeDB.

HealthcareIngestionPipeline subclasses BaseIngestionPipeline to ingest
Synthea clinical records as Memory:Healthcare:* nodes. Each call to ingest()
handles one row (one encounter, condition, medication, observation, or
procedure). The caller (scripts/ingest_synthea.py) feeds rows from
SyntheaCSVLoader one at a time.

Design decisions:
  - No LLM entity extraction during bulk ingestion. Synthea fields are
    already structured (ICD codes, drug names, provider UUIDs) so entities
    are derived directly from CSV columns. This avoids ~$100+ in LLM API
    costs for a full 1M-patient run. LLM extraction can be enabled via the
    enable_llm_extraction flag for small validation subsets.
  - content_hash uses composite field keys (not UUIDs) for rows that lack a
    primary key Id (conditions, observations, procedures).
  - Temporal claims are shadow-written to SpacetimeDB in a best-effort
    try/except block, identical to the pattern in web/pipeline.py.

Node labels produced:
  :Memory:Healthcare:Encounter
  :Memory:Healthcare:Condition
  :Memory:Healthcare:Medication
  :Memory:Healthcare:Observation
  :Memory:Healthcare:Procedure

Entity labels produced:
  :Entity:Patient   (name = patient UUID)
  :Entity:Provider  (name = provider UUID)
  :Entity:Diagnosis (name = condition DESCRIPTION)
  :Entity:Medication (name = medication DESCRIPTION)
  :Entity:Procedure (name = procedure DESCRIPTION)

Role in the project:
  The pipeline is instantiated once in scripts/ingest_synthea.py with all
  required services, then called in a tight loop over SyntheaCSVLoader rows.
  It is also the entry point for integration tests in tests/test_healthcare_pipeline.py.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from agentic_memory.core.base import BaseIngestionPipeline
from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.embedding import EmbeddingService
from agentic_memory.core.entity_extraction import EntityExtractionService, build_embed_text
from agentic_memory.core.graph_writer import GraphWriter
from agentic_memory.core.registry import register_source
from agentic_memory.healthcare.embed_text import (
    build_condition_embed_text,
    build_encounter_embed_text,
    build_medication_embed_text,
    build_observation_embed_text,
    build_procedure_embed_text,
)
from agentic_memory.healthcare.graph_writer_hc import HealthcareGraphWriter
from agentic_memory.healthcare.temporal_mapper import (
    condition_to_claim,
    date_to_micros,
    medication_to_claim,
    observation_to_claim,
    procedure_to_claim,
)
from agentic_memory.temporal.bridge import TemporalBridge

logger = logging.getLogger(__name__)

# Register all healthcare source keys at import time.
# Labels follow the same Memory:Domain:RecordType pattern as other domains.
register_source("synthea_encounter", ["Memory", "Healthcare", "Encounter"])
register_source("synthea_condition", ["Memory", "Healthcare", "Condition"])
register_source("synthea_medication", ["Memory", "Healthcare", "Medication"])
register_source("synthea_observation", ["Memory", "Healthcare", "Observation"])
register_source("synthea_procedure", ["Memory", "Healthcare", "Procedure"])

# Record types dispatched by ingest()
_VALID_RECORD_TYPES = frozenset(
    {"encounter", "condition", "medication", "observation", "procedure"}
)

# Entity types used for the healthcare domain (replaces the default taxonomy)
_HEALTHCARE_ENTITY_TYPES = [
    "patient", "provider", "diagnosis", "medication", "procedure"
]


class HealthcareIngestionPipeline(BaseIngestionPipeline):
    """Ingestion pipeline for Synthea CSV healthcare records.

    Each call to ingest() handles one clinical record (one CSV row plus a
    "record_type" discriminator). The caller is responsible for feeding rows
    in the correct order: patients → encounters → conditions → medications →
    observations → procedures.

    Args:
        connection_manager: Neo4j ConnectionManager instance.
        embedding_service: EmbeddingService (Gemini/OpenAI/Nemotron).
        entity_extractor: EntityExtractionService (used only when
            enable_llm_extraction=True).
        temporal_bridge: Optional TemporalBridge for SpacetimeDB writes.
            When None or unavailable, temporal writes are silently skipped.
        project_id: Project namespace for SpacetimeDB temporal isolation.
        enable_llm_extraction: If True, run LLM entity extraction per row.
            Default False — structured field extraction is used instead.
    """

    DOMAIN_LABEL = "Healthcare"

    def __init__(
        self,
        connection_manager: ConnectionManager,
        embedding_service: EmbeddingService,
        entity_extractor: EntityExtractionService | None = None,
        temporal_bridge: TemporalBridge | None = None,
        project_id: str = "synthea-experiment",
        enable_llm_extraction: bool = False,
    ) -> None:
        """Initialise the healthcare ingestion pipeline.

        Args:
            connection_manager: Configured ConnectionManager instance.
            embedding_service: Configured EmbeddingService.
            entity_extractor: Configured EntityExtractionService. Required
                only when enable_llm_extraction=True.
            temporal_bridge: Optional SpacetimeDB bridge for temporal claims.
            project_id: Namespace for SpacetimeDB writes.
            enable_llm_extraction: Run LLM extraction instead of field-derived
                entity detection. Slow for bulk runs (one LLM call per row).
        """
        super().__init__(connection_manager)
        self._embedder = embedding_service
        self._extractor = entity_extractor
        self._temporal_bridge = temporal_bridge
        self._project_id = project_id
        self._enable_llm_extraction = enable_llm_extraction
        self._writer = GraphWriter(connection_manager)
        self._hc_writer = HealthcareGraphWriter(connection_manager)

        if enable_llm_extraction and entity_extractor is None:
            raise ValueError(
                "entity_extractor must be provided when enable_llm_extraction=True"
            )

    def ingest(self, source: dict[str, Any]) -> dict[str, Any]:
        """Ingest a single Synthea CSV row into the memory graph.

        Dispatches to the appropriate _ingest_* method based on the
        "record_type" field in source.

        Args:
            source: Dict with a "record_type" key plus the raw CSV row fields.
                record_type must be one of: "encounter", "condition",
                "medication", "observation", "procedure".

        Returns:
            Summary dict: {record_type, source_key, content_hash,
                entities_count, temporal_written}.

        Raises:
            ValueError: If record_type is missing or not a valid value.
        """
        record_type = source.get("record_type")
        if not record_type or record_type not in _VALID_RECORD_TYPES:
            raise ValueError(
                f"Invalid or missing record_type {record_type!r}. "
                f"Must be one of: {sorted(_VALID_RECORD_TYPES)}"
            )

        dispatch = {
            "encounter": self._ingest_encounter,
            "condition": self._ingest_condition,
            "medication": self._ingest_medication,
            "observation": self._ingest_observation,
            "procedure": self._ingest_procedure,
        }
        return dispatch[record_type](source)

    # ------------------------------------------------------------------
    # Per-record-type ingest methods
    # ------------------------------------------------------------------

    def _ingest_encounter(self, row: dict[str, Any]) -> dict[str, Any]:
        """Ingest one encounters.csv row.

        Writes an Encounter Memory node, upserts Patient and Provider entities,
        and wires HAD_ENCOUNTER and TREATED_BY relationships.

        Args:
            row: Encounter CSV row dict (with record_type already set).

        Returns:
            Summary dict.
        """
        source_key = "synthea_encounter"
        # Encounters have a UUID Id column
        encounter_id = row.get("Id") or row.get("id") or ""
        content_hash = self._hash_fields(encounter_id)
        now = self._now()

        embed_text = build_encounter_embed_text(row)
        entities = self._extract_entities_from_fields(row, "encounter")
        enriched_text = build_embed_text(embed_text, entities)
        embedding = self._embedder.embed(enriched_text)

        props = self._base_props(
            source_key=source_key,
            content_hash=content_hash,
            embed_text=embed_text,
            embedding=embedding,
            entities=entities,
            now=now,
            extra={
                "encounter_id": encounter_id,
                "patient_id": row.get("PATIENT"),
                "provider_id": row.get("PROVIDER"),
                "encounter_start": row.get("START"),
                "encounter_stop": row.get("STOP"),
                "encounter_class": row.get("CLASS"),
                "reason_code": row.get("REASONCODE"),
                "reason_description": row.get("REASONDESCRIPTION"),
                "description": row.get("DESCRIPTION"),
                "source_type": "healthcare",
            },
        )

        labels = self.node_labels(source_key)
        self._writer.write_memory_node(labels, props)

        # Upsert Patient and Provider entities
        patient_id = row.get("PATIENT")
        provider_id = row.get("PROVIDER")
        if patient_id:
            self._writer.upsert_entity(patient_id, "patient")
            self._hc_writer.write_had_encounter(
                patient_id=patient_id,
                encounter_source_key=source_key,
                encounter_content_hash=content_hash,
                valid_from=row.get("START"),
                confidence=1.0,
            )
        if provider_id:
            self._writer.upsert_entity(provider_id, "provider")
            self._hc_writer.write_treated_by(
                encounter_source_key=source_key,
                encounter_content_hash=content_hash,
                provider_id=provider_id,
                valid_from=row.get("START"),
                confidence=1.0,
            )

        logger.debug("Encounter ingested: %s patient=%s", encounter_id, patient_id)
        return {
            "record_type": "encounter",
            "source_key": source_key,
            "content_hash": content_hash,
            "entities_count": len(entities),
            "temporal_written": False,
        }

    def _ingest_condition(self, row: dict[str, Any]) -> dict[str, Any]:
        """Ingest one conditions.csv row.

        Writes a Condition Memory node, upserts Diagnosis entity, wires
        DIAGNOSED_WITH from Patient and HAS_CONDITION from Encounter, and
        shadow-writes temporal claim to SpacetimeDB.

        Args:
            row: Condition CSV row dict.

        Returns:
            Summary dict.
        """
        source_key = "synthea_condition"
        # No UUID — composite key
        content_hash = self._hash_fields(
            row.get("PATIENT", ""),
            row.get("ENCOUNTER", ""),
            row.get("CODE", ""),
            row.get("START", ""),
        )
        now = self._now()

        embed_text = build_condition_embed_text(row)
        entities = self._extract_entities_from_fields(row, "condition")
        enriched_text = build_embed_text(embed_text, entities)
        embedding = self._embedder.embed(enriched_text)

        stop_iso = self._date_to_iso(row.get("STOP"))
        props = self._base_props(
            source_key=source_key,
            content_hash=content_hash,
            embed_text=embed_text,
            embedding=embedding,
            entities=entities,
            now=now,
            extra={
                "patient_id": row.get("PATIENT"),
                "encounter_id": row.get("ENCOUNTER"),
                "icd_code": row.get("CODE"),
                "description": row.get("DESCRIPTION"),
                "condition_start": row.get("START"),
                "condition_stop": stop_iso,
                "source_type": "healthcare",
            },
        )

        labels = self.node_labels(source_key)
        self._writer.write_memory_node(labels, props)

        patient_id = row.get("PATIENT")
        description = row.get("DESCRIPTION") or row.get("CODE") or "unknown"

        # Upsert Diagnosis entity and wire patient-level relationship
        if description:
            self._writer.upsert_entity(description, "diagnosis")
            self._writer.write_temporal_relationship(
                source_key=source_key,
                content_hash=content_hash,
                entity_name=description,
                entity_type="diagnosis",
                rel_type="MENTIONS",
                valid_from=row.get("START"),
                valid_to=stop_iso,
                confidence=1.0,
            )
        if patient_id:
            self._hc_writer.write_diagnosed_with(
                patient_id=patient_id,
                condition_source_key=source_key,
                condition_content_hash=content_hash,
                valid_from=row.get("START"),
                valid_to=stop_iso,
                confidence=1.0,
            )

        # Temporal shadow write to SpacetimeDB (best-effort)
        temporal_written = self._shadow_write_claim(
            condition_to_claim(row, self._project_id)
        )

        logger.debug(
            "Condition ingested: %s patient=%s temporal=%s",
            description,
            patient_id,
            temporal_written,
        )
        return {
            "record_type": "condition",
            "source_key": source_key,
            "content_hash": content_hash,
            "entities_count": len(entities),
            "temporal_written": temporal_written,
        }

    def _ingest_medication(self, row: dict[str, Any]) -> dict[str, Any]:
        """Ingest one medications.csv row.

        Writes a Medication Memory node, upserts Medication entity, wires
        PRESCRIBED from Patient, and shadow-writes temporal claim.

        Args:
            row: Medication CSV row dict.

        Returns:
            Summary dict.
        """
        source_key = "synthea_medication"
        content_hash = self._hash_fields(
            row.get("PATIENT", ""),
            row.get("ENCOUNTER", ""),
            row.get("CODE", ""),
            row.get("START", ""),
        )
        now = self._now()

        embed_text = build_medication_embed_text(row)
        entities = self._extract_entities_from_fields(row, "medication")
        enriched_text = build_embed_text(embed_text, entities)
        embedding = self._embedder.embed(enriched_text)

        stop_iso = self._date_to_iso(row.get("STOP"))
        props = self._base_props(
            source_key=source_key,
            content_hash=content_hash,
            embed_text=embed_text,
            embedding=embedding,
            entities=entities,
            now=now,
            extra={
                "patient_id": row.get("PATIENT"),
                "encounter_id": row.get("ENCOUNTER"),
                "medication_code": row.get("CODE"),
                "description": row.get("DESCRIPTION"),
                "medication_start": row.get("START"),
                "medication_stop": stop_iso,
                "dispenses": row.get("DISPENSES"),
                "total_cost": row.get("TOTALCOST"),
                "source_type": "healthcare",
            },
        )

        labels = self.node_labels(source_key)
        self._writer.write_memory_node(labels, props)

        patient_id = row.get("PATIENT")
        description = row.get("DESCRIPTION") or row.get("CODE") or "unknown"

        if description:
            self._writer.upsert_entity(description, "medication")
            self._writer.write_temporal_relationship(
                source_key=source_key,
                content_hash=content_hash,
                entity_name=description,
                entity_type="medication",
                rel_type="MENTIONS",
                valid_from=row.get("START"),
                valid_to=stop_iso,
                confidence=1.0,
            )
        if patient_id:
            self._hc_writer.write_prescribed(
                patient_id=patient_id,
                medication_source_key=source_key,
                medication_content_hash=content_hash,
                valid_from=row.get("START"),
                valid_to=stop_iso,
                confidence=1.0,
            )

        temporal_written = self._shadow_write_claim(
            medication_to_claim(row, self._project_id)
        )

        return {
            "record_type": "medication",
            "source_key": source_key,
            "content_hash": content_hash,
            "entities_count": len(entities),
            "temporal_written": temporal_written,
        }

    def _ingest_observation(self, row: dict[str, Any]) -> dict[str, Any]:
        """Ingest one observations.csv row.

        Writes an Observation Memory node. Point-in-time events (DATE only).
        No patient-level relationship is wired for observations because the
        encounter → patient link is enough for the experiment queries.

        Args:
            row: Observation CSV row dict.

        Returns:
            Summary dict.
        """
        source_key = "synthea_observation"
        content_hash = self._hash_fields(
            row.get("PATIENT", ""),
            row.get("ENCOUNTER", ""),
            row.get("CODE", ""),
            row.get("DATE", ""),
        )
        now = self._now()

        embed_text = build_observation_embed_text(row)
        entities = self._extract_entities_from_fields(row, "observation")
        enriched_text = build_embed_text(embed_text, entities)
        embedding = self._embedder.embed(enriched_text)

        props = self._base_props(
            source_key=source_key,
            content_hash=content_hash,
            embed_text=embed_text,
            embedding=embedding,
            entities=entities,
            now=now,
            extra={
                "patient_id": row.get("PATIENT"),
                "encounter_id": row.get("ENCOUNTER"),
                "observation_code": row.get("CODE"),
                "description": row.get("DESCRIPTION"),
                "value": row.get("VALUE"),
                "units": row.get("UNITS"),
                "observation_type": row.get("TYPE"),
                "observation_date": row.get("DATE"),
                "source_type": "healthcare",
            },
        )

        labels = self.node_labels(source_key)
        self._writer.write_memory_node(labels, props)

        temporal_written = self._shadow_write_claim(
            observation_to_claim(row, self._project_id)
        )

        return {
            "record_type": "observation",
            "source_key": source_key,
            "content_hash": content_hash,
            "entities_count": len(entities),
            "temporal_written": temporal_written,
        }

    def _ingest_procedure(self, row: dict[str, Any]) -> dict[str, Any]:
        """Ingest one procedures.csv row.

        Writes a Procedure Memory node and upserts a Procedure entity.
        Point-in-time events (DATE only, no duration in Synthea CSV).

        Args:
            row: Procedure CSV row dict.

        Returns:
            Summary dict.
        """
        source_key = "synthea_procedure"
        content_hash = self._hash_fields(
            row.get("PATIENT", ""),
            row.get("ENCOUNTER", ""),
            row.get("CODE", ""),
            row.get("DATE", ""),
        )
        now = self._now()

        embed_text = build_procedure_embed_text(row)
        entities = self._extract_entities_from_fields(row, "procedure")
        enriched_text = build_embed_text(embed_text, entities)
        embedding = self._embedder.embed(enriched_text)

        props = self._base_props(
            source_key=source_key,
            content_hash=content_hash,
            embed_text=embed_text,
            embedding=embedding,
            entities=entities,
            now=now,
            extra={
                "patient_id": row.get("PATIENT"),
                "encounter_id": row.get("ENCOUNTER"),
                "procedure_code": row.get("CODE"),
                "description": row.get("DESCRIPTION"),
                "procedure_date": row.get("DATE"),
                "cost": row.get("COST"),
                "source_type": "healthcare",
            },
        )

        labels = self.node_labels(source_key)
        self._writer.write_memory_node(labels, props)

        description = row.get("DESCRIPTION") or row.get("CODE") or "unknown"
        if description:
            self._writer.upsert_entity(description, "procedure")

        temporal_written = self._shadow_write_claim(
            procedure_to_claim(row, self._project_id)
        )

        return {
            "record_type": "procedure",
            "source_key": source_key,
            "content_hash": content_hash,
            "entities_count": len(entities),
            "temporal_written": temporal_written,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_props(
        self,
        *,
        source_key: str,
        content_hash: str,
        embed_text: str,
        embedding: list[float],
        entities: list[dict[str, Any]],
        now: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the full Memory node properties dict.

        Assembles the universal required fields (source_key, content_hash,
        embedding, entities, ingested_at, etc.) plus domain-specific extras.

        Args:
            source_key: Source identifier (e.g. "synthea_condition").
            content_hash: SHA-256 composite hash.
            embed_text: The prose string that was embedded.
            embedding: Vector from EmbeddingService.
            entities: List of {name, type} dicts.
            now: ISO-8601 ingestion timestamp.
            extra: Domain-specific properties to merge in.

        Returns:
            Properties dict ready for GraphWriter.write_memory_node().
        """
        return {
            "source_key": source_key,
            "content_hash": content_hash,
            "content": embed_text,  # prose summary stored as node content
            "embedding": embedding,
            "embedding_model": "gemini-embedding-2-preview",
            "entities": [e["name"] for e in entities],
            "entity_types": [e["type"] for e in entities],
            "ingested_at": now,
            "timestamp": now,
            "ingestion_mode": "active",
            "project_id": self._project_id,
            "session_id": self._project_id,  # session_id required by schema
            **extra,
        }

    def _extract_entities_from_fields(
        self,
        row: dict[str, Any],
        record_type: str,
    ) -> list[dict[str, Any]]:
        """Derive entities directly from CSV fields (no LLM).

        This is the default path for bulk ingestion. The structured CSV fields
        provide the same information an LLM would extract from unstructured text.
        LLM extraction is only used when self._enable_llm_extraction is True.

        Args:
            row: Normalised CSV row dict.
            record_type: One of "encounter", "condition", "medication",
                "observation", "procedure".

        Returns:
            List of {name: str, type: str} entity dicts.
        """
        if self._enable_llm_extraction and self._extractor is not None:
            # Build a prose summary then run LLM extraction on it
            build_fn_map = {
                "encounter": build_encounter_embed_text,
                "condition": build_condition_embed_text,
                "medication": build_medication_embed_text,
                "observation": build_observation_embed_text,
                "procedure": build_procedure_embed_text,
            }
            text = build_fn_map[record_type](row)
            return self._extractor.extract(text)

        # Structured field extraction — no LLM required
        entities: list[dict[str, Any]] = []

        patient_id = row.get("PATIENT")
        if patient_id:
            entities.append({"name": patient_id, "type": "patient"})

        provider_id = row.get("PROVIDER")
        if provider_id:
            entities.append({"name": provider_id, "type": "provider"})

        if record_type == "condition":
            desc = row.get("DESCRIPTION")
            if desc:
                entities.append({"name": desc, "type": "diagnosis"})

        elif record_type == "medication":
            desc = row.get("DESCRIPTION")
            if desc:
                entities.append({"name": desc, "type": "medication"})

        elif record_type == "procedure":
            desc = row.get("DESCRIPTION")
            if desc:
                entities.append({"name": desc, "type": "procedure"})

        # Observations carry no standalone entity beyond patient/encounter

        return entities

    def _shadow_write_claim(self, claim: dict[str, Any]) -> bool:
        """Best-effort write of a temporal claim to SpacetimeDB.

        Mirrors the _shadow_write_entity_relation pattern from chat/pipeline.py.
        Failures are logged as warnings but never propagate — Neo4j writes are
        the source of truth; SpacetimeDB is a secondary temporal layer.

        Args:
            claim: Dict of kwargs for TemporalBridge.ingest_claim().

        Returns:
            True if the claim was written successfully, False otherwise.
        """
        if self._temporal_bridge is None or not self._temporal_bridge.is_available():
            return False
        try:
            self._temporal_bridge.ingest_claim(**claim)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Healthcare temporal shadow write failed: predicate=%s error=%s",
                claim.get("predicate"),
                exc,
            )
            return False

    @staticmethod
    def _hash_fields(*fields: str) -> str:
        """SHA-256 hash of a colon-joined composite key.

        Args:
            *fields: String values to join (any falsy value → empty string).

        Returns:
            Hex-encoded SHA-256 digest.
        """
        composite = ":".join(f or "" for f in fields)
        return hashlib.sha256(composite.encode()).hexdigest()

    @staticmethod
    def _now() -> str:
        """Current UTC time as ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _date_to_iso(date_str: str | None) -> str | None:
        """Convert a Synthea YYYY-MM-DD date to a minimal ISO string or None."""
        if not date_str or not date_str.strip():
            return None
        return date_str.strip()[:10]  # Keep YYYY-MM-DD only
