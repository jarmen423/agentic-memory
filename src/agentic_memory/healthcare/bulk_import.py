"""Bulk Neo4j import helpers for healthcare chunk files.

This module implements the Phase B "real bulk-write fast path" for the
two-stage Synthea experiment flow. The existing importer path routes every
exported row back through ``HealthcareIngestionPipeline.ingest()``, which is
semantically safe but expensive because one logical record fans out into many
small Cypher writes.

The bulk importer keeps the same graph shape but changes *how* writes are sent
to Neo4j:

- build Memory node property maps in Python once per row
- group records by healthcare record type
- bulk upsert Memory nodes with ``UNWIND``
- bulk upsert Entity nodes with ``UNWIND``
- bulk write the currently-used healthcare relationships with ``UNWIND``

Important scope limit:
    This module intentionally matches the *current* healthcare pipeline
    semantics, not the aspirational docstring/model semantics. For example, the
    current pipeline writes:

    - Encounter nodes + Patient/Provider + HAD_ENCOUNTER + TREATED_BY
    - Condition nodes + Diagnosis + MENTIONS + DIAGNOSED_WITH
    - Medication nodes + Medication entity + MENTIONS + PRESCRIBED
    - Observation nodes only
    - Procedure nodes + Procedure entity only

    It does **not** currently write HAS_CONDITION or HAS_OBSERVATION during the
    importer path, so the bulk path also does not write them. This keeps the
    fast path parity target honest.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


class HealthcareBulkImporter:
    """Bulk healthcare importer that preserves current graph semantics.

    Args:
        project_id: Project namespace to stamp onto imported Memory nodes.
    """

    def __init__(self, *, project_id: str) -> None:
        """Store the project namespace used for imported rows."""
        self._project_id = project_id

    def import_batch(self, *, tx: Any, batch_items: list[dict[str, Any]]) -> None:
        """Import one exported chunk batch into Neo4j via bulk ``UNWIND`` writes.

        Args:
            tx: Open Neo4j transaction with a ``run(...)`` method.
            batch_items: Exported chunk rows from
                ``scripts/export_embedded_synthea.py``.
        """
        if not batch_items:
            return

        now = self._now()
        grouped_memory_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        patient_entities: set[str] = set()
        provider_entities: set[str] = set()
        diagnosis_entities: set[str] = set()
        medication_entities: set[str] = set()
        procedure_entities: set[str] = set()
        had_encounter_rows: list[dict[str, Any]] = []
        treated_by_rows: list[dict[str, Any]] = []
        diagnosed_with_rows: list[dict[str, Any]] = []
        prescribed_rows: list[dict[str, Any]] = []
        mentions_diagnosis_rows: list[dict[str, Any]] = []
        mentions_medication_rows: list[dict[str, Any]] = []

        for item in batch_items:
            row = dict(item.get("row") or {})
            record_type = str(item["record_type"])
            source_key = str(item["source_key"])
            content_hash = str(item["content_hash"])
            entities = list(item.get("entities") or [])
            embedding = [float(value) for value in item["precomputed_embedding"]]
            embedding_model = str(
                item.get("precomputed_embedding_model") or "precomputed"
            )
            embed_text = str(item.get("embed_text") or "")

            props = self._build_memory_props(
                row=row,
                record_type=record_type,
                source_key=source_key,
                content_hash=content_hash,
                embed_text=embed_text,
                embedding=embedding,
                embedding_model=embedding_model,
                entities=entities,
                now=now,
            )
            grouped_memory_rows[record_type].append(
                {"source_key": source_key, "content_hash": content_hash, "props": props}
            )

            patient_id = row.get("PATIENT")
            provider_id = row.get("PROVIDER")
            description = row.get("DESCRIPTION") or row.get("CODE") or "unknown"

            if record_type == "encounter":
                if patient_id:
                    patient_entities.add(str(patient_id))
                    had_encounter_rows.append(
                        {
                            "patient_id": str(patient_id),
                            "source_key": source_key,
                            "content_hash": content_hash,
                            "valid_from": row.get("START") or now,
                            "confidence": 1.0,
                        }
                    )
                if provider_id:
                    provider_entities.add(str(provider_id))
                    treated_by_rows.append(
                        {
                            "source_key": source_key,
                            "content_hash": content_hash,
                            "provider_id": str(provider_id),
                            "valid_from": row.get("START") or now,
                            "confidence": 1.0,
                        }
                    )

            elif record_type == "condition":
                if description:
                    diagnosis_entities.add(str(description))
                    mentions_diagnosis_rows.append(
                        {
                            "source_key": source_key,
                            "content_hash": content_hash,
                            "entity_name": str(description),
                            "valid_from": row.get("START") or now,
                            "valid_to": self._date_to_iso(row.get("STOP")),
                            "confidence": 1.0,
                            "support_count": 1,
                            "contradiction_count": 0,
                        }
                    )
                if patient_id:
                    patient_entities.add(str(patient_id))
                    diagnosed_with_rows.append(
                        {
                            "patient_id": str(patient_id),
                            "source_key": source_key,
                            "content_hash": content_hash,
                            "valid_from": row.get("START") or now,
                            "valid_to": self._date_to_iso(row.get("STOP")),
                            "confidence": 1.0,
                        }
                    )

            elif record_type == "medication":
                if description:
                    medication_entities.add(str(description))
                    mentions_medication_rows.append(
                        {
                            "source_key": source_key,
                            "content_hash": content_hash,
                            "entity_name": str(description),
                            "valid_from": row.get("START") or now,
                            "valid_to": self._date_to_iso(row.get("STOP")),
                            "confidence": 1.0,
                            "support_count": 1,
                            "contradiction_count": 0,
                        }
                    )
                if patient_id:
                    patient_entities.add(str(patient_id))
                    prescribed_rows.append(
                        {
                            "patient_id": str(patient_id),
                            "source_key": source_key,
                            "content_hash": content_hash,
                            "valid_from": row.get("START") or now,
                            "valid_to": self._date_to_iso(row.get("STOP")),
                            "confidence": 1.0,
                        }
                    )

            elif record_type == "procedure":
                if description:
                    procedure_entities.add(str(description))

        self._write_memory_nodes(tx=tx, record_type="encounter", rows=grouped_memory_rows["encounter"])
        self._write_memory_nodes(tx=tx, record_type="condition", rows=grouped_memory_rows["condition"])
        self._write_memory_nodes(tx=tx, record_type="medication", rows=grouped_memory_rows["medication"])
        self._write_memory_nodes(tx=tx, record_type="observation", rows=grouped_memory_rows["observation"])
        self._write_memory_nodes(tx=tx, record_type="procedure", rows=grouped_memory_rows["procedure"])

        self._write_entities(tx=tx, label="Patient", entity_type="patient", names=patient_entities)
        self._write_entities(tx=tx, label="Provider", entity_type="provider", names=provider_entities)
        self._write_entities(tx=tx, label="Diagnosis", entity_type="diagnosis", names=diagnosis_entities)
        self._write_entities(tx=tx, label="Medication", entity_type="medication", names=medication_entities)
        self._write_entities(tx=tx, label="Procedure", entity_type="procedure", names=procedure_entities)

        self._write_had_encounter(tx=tx, rows=had_encounter_rows)
        self._write_treated_by(tx=tx, rows=treated_by_rows)
        self._write_mentions(tx=tx, entity_type="diagnosis", rows=mentions_diagnosis_rows)
        self._write_mentions(tx=tx, entity_type="medication", rows=mentions_medication_rows)
        self._write_diagnosed_with(tx=tx, rows=diagnosed_with_rows)
        self._write_prescribed(tx=tx, rows=prescribed_rows)

    def _build_memory_props(
        self,
        *,
        row: dict[str, Any],
        record_type: str,
        source_key: str,
        content_hash: str,
        embed_text: str,
        embedding: list[float],
        embedding_model: str,
        entities: list[dict[str, Any]],
        now: str,
    ) -> dict[str, Any]:
        """Build the same Memory-node property map as the pipeline path."""
        base = {
            "source_key": source_key,
            "content_hash": content_hash,
            "content": embed_text,
            "embedding": embedding,
            "embedding_model": embedding_model,
            "entities": [entity["name"] for entity in entities],
            "entity_types": [entity["type"] for entity in entities],
            "ingested_at": now,
            "timestamp": now,
            "ingestion_mode": "active",
            "project_id": self._project_id,
            "session_id": self._project_id,
        }

        if record_type == "encounter":
            return {
                **base,
                "encounter_id": row.get("Id") or row.get("id") or "",
                "patient_id": row.get("PATIENT"),
                "provider_id": row.get("PROVIDER"),
                "encounter_start": row.get("START"),
                "encounter_stop": row.get("STOP"),
                "encounter_class": row.get("CLASS"),
                "reason_code": row.get("REASONCODE"),
                "reason_description": row.get("REASONDESCRIPTION"),
                "description": row.get("DESCRIPTION"),
                "source_type": "healthcare",
            }
        if record_type == "condition":
            return {
                **base,
                "patient_id": row.get("PATIENT"),
                "encounter_id": row.get("ENCOUNTER"),
                "icd_code": row.get("CODE"),
                "description": row.get("DESCRIPTION"),
                "condition_start": row.get("START"),
                "condition_stop": self._date_to_iso(row.get("STOP")),
                "source_type": "healthcare",
            }
        if record_type == "medication":
            return {
                **base,
                "patient_id": row.get("PATIENT"),
                "encounter_id": row.get("ENCOUNTER"),
                "medication_code": row.get("CODE"),
                "description": row.get("DESCRIPTION"),
                "medication_start": row.get("START"),
                "medication_stop": self._date_to_iso(row.get("STOP")),
                "dispenses": row.get("DISPENSES"),
                "total_cost": row.get("TOTALCOST"),
                "source_type": "healthcare",
            }
        if record_type == "observation":
            return {
                **base,
                "patient_id": row.get("PATIENT"),
                "encounter_id": row.get("ENCOUNTER"),
                "observation_code": row.get("CODE"),
                "description": row.get("DESCRIPTION"),
                "value": row.get("VALUE"),
                "units": row.get("UNITS"),
                "observation_type": row.get("TYPE"),
                "observation_date": row.get("DATE"),
                "source_type": "healthcare",
            }
        if record_type == "procedure":
            return {
                **base,
                "patient_id": row.get("PATIENT"),
                "encounter_id": row.get("ENCOUNTER"),
                "procedure_code": row.get("CODE"),
                "description": row.get("DESCRIPTION"),
                "procedure_date": row.get("DATE"),
                "cost": row.get("COST"),
                "source_type": "healthcare",
            }
        raise ValueError(f"Unsupported record_type for bulk import: {record_type!r}")

    def _write_memory_nodes(self, *, tx: Any, record_type: str, rows: list[dict[str, Any]]) -> None:
        """Bulk upsert Memory nodes for one healthcare record family."""
        if not rows:
            return

        labels_by_type = {
            "encounter": "Memory:Healthcare:Encounter",
            "condition": "Memory:Healthcare:Condition",
            "medication": "Memory:Healthcare:Medication",
            "observation": "Memory:Healthcare:Observation",
            "procedure": "Memory:Healthcare:Procedure",
        }
        labels = labels_by_type[record_type]
        tx.run(
            f"""
            UNWIND $rows AS row
            MERGE (m:{labels} {{source_key: row.source_key, content_hash: row.content_hash}})
            ON CREATE SET m += row.props
            ON MATCH SET m.ingested_at = row.props.ingested_at
            """,
            rows=rows,
        )

    def _write_entities(
        self,
        *,
        tx: Any,
        label: str,
        entity_type: str,
        names: set[str],
    ) -> None:
        """Bulk upsert one healthcare entity family."""
        if not names:
            return
        rows = [{"name": name, "type": entity_type} for name in sorted(names)]
        tx.run(
            f"""
            UNWIND $rows AS row
            MERGE (e:Entity:{label} {{name: row.name, type: row.type}})
            """,
            rows=rows,
        )

    def _write_had_encounter(self, *, tx: Any, rows: list[dict[str, Any]]) -> None:
        """Bulk write ``HAD_ENCOUNTER`` relationships."""
        if not rows:
            return
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (p:Entity:Patient {name: row.patient_id, type: 'patient'})
            MATCH (e:Memory {source_key: row.source_key, content_hash: row.content_hash})
            MERGE (p)-[r:HAD_ENCOUNTER]->(e)
            ON CREATE SET r.valid_from = row.valid_from,
                          r.confidence = row.confidence,
                          r.support_count = 1
            ON MATCH SET  r.support_count = r.support_count + 1
            """,
            rows=rows,
        )

    def _write_treated_by(self, *, tx: Any, rows: list[dict[str, Any]]) -> None:
        """Bulk write ``TREATED_BY`` relationships."""
        if not rows:
            return
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (e:Memory {source_key: row.source_key, content_hash: row.content_hash})
            MATCH (p:Entity:Provider {name: row.provider_id, type: 'provider'})
            MERGE (e)-[r:TREATED_BY]->(p)
            ON CREATE SET r.valid_from = row.valid_from,
                          r.confidence = row.confidence,
                          r.support_count = 1
            ON MATCH SET  r.support_count = r.support_count + 1
            """,
            rows=rows,
        )

    def _write_mentions(
        self,
        *,
        tx: Any,
        entity_type: str,
        rows: list[dict[str, Any]],
    ) -> None:
        """Bulk write ``MENTIONS`` relationships for diagnosis/medication."""
        if not rows:
            return
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (m:Memory {source_key: row.source_key, content_hash: row.content_hash})
            MATCH (e:Entity {name: row.entity_name, type: $entity_type})
            MERGE (m)-[r:MENTIONS]->(e)
            ON CREATE SET r.valid_from = row.valid_from,
                          r.valid_to = row.valid_to,
                          r.confidence = row.confidence,
                          r.support_count = row.support_count,
                          r.contradiction_count = row.contradiction_count
            ON MATCH SET  r.support_count = r.support_count + 1,
                          r.confidence = CASE WHEN row.confidence > r.confidence
                                              THEN row.confidence
                                              ELSE r.confidence END
            """,
            rows=rows,
            entity_type=entity_type,
        )

    def _write_diagnosed_with(self, *, tx: Any, rows: list[dict[str, Any]]) -> None:
        """Bulk write ``DIAGNOSED_WITH`` relationships."""
        if not rows:
            return
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (p:Entity:Patient {name: row.patient_id, type: 'patient'})
            MATCH (c:Memory {source_key: row.source_key, content_hash: row.content_hash})
            MERGE (p)-[r:DIAGNOSED_WITH]->(c)
            ON CREATE SET r.valid_from = row.valid_from,
                          r.valid_to = row.valid_to,
                          r.confidence = row.confidence,
                          r.support_count = 1,
                          r.contradiction_count = 0
            ON MATCH SET  r.support_count = r.support_count + 1,
                          r.valid_to = row.valid_to
            """,
            rows=rows,
        )

    def _write_prescribed(self, *, tx: Any, rows: list[dict[str, Any]]) -> None:
        """Bulk write ``PRESCRIBED`` relationships."""
        if not rows:
            return
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (p:Entity:Patient {name: row.patient_id, type: 'patient'})
            MATCH (m:Memory {source_key: row.source_key, content_hash: row.content_hash})
            MERGE (p)-[r:PRESCRIBED]->(m)
            ON CREATE SET r.valid_from = row.valid_from,
                          r.valid_to = row.valid_to,
                          r.confidence = row.confidence,
                          r.support_count = 1,
                          r.contradiction_count = 0
            ON MATCH SET  r.support_count = r.support_count + 1,
                          r.valid_to = row.valid_to
            """,
            rows=rows,
        )

    @staticmethod
    def _now() -> str:
        """Return current UTC time in ISO-8601 format."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _date_to_iso(date_str: str | None) -> str | None:
        """Normalize Synthea date strings to ``YYYY-MM-DD`` or ``None``."""
        if not date_str or not str(date_str).strip():
            return None
        return str(date_str).strip()[:10]
