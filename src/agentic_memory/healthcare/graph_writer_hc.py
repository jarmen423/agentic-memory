"""Healthcare-domain graph writer — clinical relationship patterns for Neo4j.

Wraps the shared GraphWriter with clinical-domain relationship methods that
model the patient-encounter-condition-medication graph needed for:

  Experiment 1: Patient → DIAGNOSED_WITH → Condition  (temporal validity)
  Experiment 2: Multi-hop queries across Patient, Condition, Medication,
                Encounter, and Provider nodes.

All writes use the same MERGE-on-composite-key pattern as the base GraphWriter,
ensuring idempotent re-ingestion. Every relationship carries temporal metadata
(valid_from, valid_to, confidence, support_count) in the same schema as the
existing Code, Conversation, and Research relationship patterns.

Relationship types defined here:
  - DIAGNOSED_WITH  Patient → Condition node
  - PRESCRIBED      Patient → Medication node
  - HAD_ENCOUNTER   Patient → Encounter node
  - TREATED_BY      Encounter → Provider entity
  - HAS_CONDITION   Encounter → Condition node  (encounter-scoped condition link)
  - HAS_MEDICATION  Encounter → Medication node (encounter-scoped medication link)
  - HAS_OBSERVATION Encounter → Observation node

Role in the project:
  Instantiated inside HealthcareIngestionPipeline and called after each
  Memory node write. Also used directly by exp2_multihop.py to execute
  multi-hop Cypher queries for the benchmark.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.graph_writer import GraphWriter

logger = logging.getLogger(__name__)


class HealthcareGraphWriter:
    """Clinical-domain relationship writer, built on top of GraphWriter.

    Adds relationship methods for the healthcare entity graph while delegating
    all Memory node and base Entity writes to the shared GraphWriter instance.

    Args:
        connection_manager: Configured ConnectionManager instance.
    """

    def __init__(self, connection_manager: ConnectionManager) -> None:
        """Initialise with a Neo4j connection manager.

        Args:
            connection_manager: Configured ConnectionManager instance.
        """
        self._conn = connection_manager
        # Shared writer handles Memory node writes and Entity upserts
        self.base = GraphWriter(connection_manager)

    # ------------------------------------------------------------------
    # Relationship writers
    # Each method uses MERGE on (Memory node key) + rel type + (Entity key).
    # ON CREATE sets temporal metadata; ON MATCH increments support_count.
    # ------------------------------------------------------------------

    def write_diagnosed_with(
        self,
        *,
        patient_id: str,
        condition_source_key: str,
        condition_content_hash: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        runner: Any | None = None,
    ) -> None:
        """Write DIAGNOSED_WITH from Patient entity to Condition memory node.

        Args:
            patient_id: Patient UUID (Entity:Patient node name).
            condition_source_key: source_key of the Condition Memory node.
            condition_content_hash: content_hash of the Condition Memory node.
            valid_from: ISO-8601 condition onset. Defaults to now.
            valid_to: ISO-8601 condition resolution date. None = still active.
            confidence: Confidence score (1.0 for Synthea ground truth).
            runner: Optional shared session/transaction for batched imports.
        """
        resolved_from = valid_from or self._now()
        cypher = (
            "MATCH (p:Entity:Patient {name: $patient_id})\n"
            "MATCH (c:Memory {source_key: $source_key, content_hash: $content_hash})\n"
            "MERGE (p)-[r:DIAGNOSED_WITH]->(c)\n"
            "ON CREATE SET r.valid_from = $valid_from,\n"
            "              r.valid_to = $valid_to,\n"
            "              r.confidence = $confidence,\n"
            "              r.support_count = 1,\n"
            "              r.contradiction_count = 0\n"
            "ON MATCH SET  r.support_count = r.support_count + 1,\n"
            "              r.valid_to = $valid_to"
        )
        if runner is not None:
            runner.run(
                cypher,
                patient_id=patient_id,
                source_key=condition_source_key,
                content_hash=condition_content_hash,
                valid_from=resolved_from,
                valid_to=valid_to,
                confidence=confidence,
            )
        else:
            with self._conn.session() as s:
                s.run(
                    cypher,
                    patient_id=patient_id,
                    source_key=condition_source_key,
                    content_hash=condition_content_hash,
                    valid_from=resolved_from,
                    valid_to=valid_to,
                    confidence=confidence,
                )
        logger.debug("DIAGNOSED_WITH: patient=%s condition=%s/%s", patient_id, condition_source_key, condition_content_hash)

    def write_prescribed(
        self,
        *,
        patient_id: str,
        medication_source_key: str,
        medication_content_hash: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        runner: Any | None = None,
    ) -> None:
        """Write PRESCRIBED from Patient entity to Medication memory node.

        Args:
            patient_id: Patient UUID (Entity:Patient node name).
            medication_source_key: source_key of the Medication Memory node.
            medication_content_hash: content_hash of the Medication Memory node.
            valid_from: ISO-8601 prescription start. Defaults to now.
            valid_to: ISO-8601 prescription end. None = ongoing.
            confidence: Confidence score.
            runner: Optional shared session/transaction for batched imports.
        """
        resolved_from = valid_from or self._now()
        cypher = (
            "MATCH (p:Entity:Patient {name: $patient_id})\n"
            "MATCH (m:Memory {source_key: $source_key, content_hash: $content_hash})\n"
            "MERGE (p)-[r:PRESCRIBED]->(m)\n"
            "ON CREATE SET r.valid_from = $valid_from,\n"
            "              r.valid_to = $valid_to,\n"
            "              r.confidence = $confidence,\n"
            "              r.support_count = 1,\n"
            "              r.contradiction_count = 0\n"
            "ON MATCH SET  r.support_count = r.support_count + 1,\n"
            "              r.valid_to = $valid_to"
        )
        if runner is not None:
            runner.run(
                cypher,
                patient_id=patient_id,
                source_key=medication_source_key,
                content_hash=medication_content_hash,
                valid_from=resolved_from,
                valid_to=valid_to,
                confidence=confidence,
            )
        else:
            with self._conn.session() as s:
                s.run(
                    cypher,
                    patient_id=patient_id,
                    source_key=medication_source_key,
                    content_hash=medication_content_hash,
                    valid_from=resolved_from,
                    valid_to=valid_to,
                    confidence=confidence,
                )
        logger.debug("PRESCRIBED: patient=%s med=%s/%s", patient_id, medication_source_key, medication_content_hash)

    def write_had_encounter(
        self,
        *,
        patient_id: str,
        encounter_source_key: str,
        encounter_content_hash: str,
        valid_from: str | None = None,
        confidence: float = 1.0,
        runner: Any | None = None,
    ) -> None:
        """Write HAD_ENCOUNTER from Patient entity to Encounter memory node.

        Args:
            patient_id: Patient UUID (Entity:Patient node name).
            encounter_source_key: source_key of the Encounter Memory node.
            encounter_content_hash: content_hash of the Encounter Memory node.
            valid_from: ISO-8601 encounter start date. Defaults to now.
            confidence: Confidence score.
            runner: Optional shared session/transaction for batched imports.
        """
        resolved_from = valid_from or self._now()
        cypher = (
            "MATCH (p:Entity:Patient {name: $patient_id})\n"
            "MATCH (e:Memory {source_key: $source_key, content_hash: $content_hash})\n"
            "MERGE (p)-[r:HAD_ENCOUNTER]->(e)\n"
            "ON CREATE SET r.valid_from = $valid_from,\n"
            "              r.confidence = $confidence,\n"
            "              r.support_count = 1\n"
            "ON MATCH SET  r.support_count = r.support_count + 1"
        )
        if runner is not None:
            runner.run(
                cypher,
                patient_id=patient_id,
                source_key=encounter_source_key,
                content_hash=encounter_content_hash,
                valid_from=resolved_from,
                confidence=confidence,
            )
        else:
            with self._conn.session() as s:
                s.run(
                    cypher,
                    patient_id=patient_id,
                    source_key=encounter_source_key,
                    content_hash=encounter_content_hash,
                    valid_from=resolved_from,
                    confidence=confidence,
                )
        logger.debug("HAD_ENCOUNTER: patient=%s enc=%s/%s", patient_id, encounter_source_key, encounter_content_hash)

    def write_treated_by(
        self,
        *,
        encounter_source_key: str,
        encounter_content_hash: str,
        provider_id: str,
        valid_from: str | None = None,
        confidence: float = 1.0,
        runner: Any | None = None,
    ) -> None:
        """Write TREATED_BY from Encounter memory node to Provider entity.

        This relationship is the terminal hop in the multi-hop Experiment 2
        Cypher query: Patient → HAD_ENCOUNTER → Encounter → TREATED_BY → Provider.

        Args:
            encounter_source_key: source_key of the Encounter Memory node.
            encounter_content_hash: content_hash of the Encounter Memory node.
            provider_id: Provider UUID (Entity:Provider node name).
            valid_from: ISO-8601 encounter start date. Defaults to now.
            confidence: Confidence score.
            runner: Optional shared session/transaction for batched imports.
        """
        resolved_from = valid_from or self._now()
        cypher = (
            "MATCH (e:Memory {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (p:Entity:Provider {name: $provider_id})\n"
            "MERGE (e)-[r:TREATED_BY]->(p)\n"
            "ON CREATE SET r.valid_from = $valid_from,\n"
            "              r.confidence = $confidence,\n"
            "              r.support_count = 1\n"
            "ON MATCH SET  r.support_count = r.support_count + 1"
        )
        if runner is not None:
            runner.run(
                cypher,
                source_key=encounter_source_key,
                content_hash=encounter_content_hash,
                provider_id=provider_id,
                valid_from=resolved_from,
                confidence=confidence,
            )
        else:
            with self._conn.session() as s:
                s.run(
                    cypher,
                    source_key=encounter_source_key,
                    content_hash=encounter_content_hash,
                    provider_id=provider_id,
                    valid_from=resolved_from,
                    confidence=confidence,
                )
        logger.debug("TREATED_BY: enc=%s/%s provider=%s", encounter_source_key, encounter_content_hash, provider_id)

    def write_has_observation(
        self,
        *,
        encounter_source_key: str,
        encounter_content_hash: str,
        obs_source_key: str,
        obs_content_hash: str,
        valid_from: str | None = None,
        confidence: float = 1.0,
        runner: Any | None = None,
    ) -> None:
        """Write HAS_OBSERVATION from Encounter node to Observation node.

        Args:
            encounter_source_key: source_key of the Encounter node.
            encounter_content_hash: content_hash of the Encounter node.
            obs_source_key: source_key of the Observation node.
            obs_content_hash: content_hash of the Observation node.
            valid_from: ISO-8601 observation date. Defaults to now.
            confidence: Confidence score.
            runner: Optional shared session/transaction for batched imports.
        """
        resolved_from = valid_from or self._now()
        cypher = (
            "MATCH (e:Memory {source_key: $enc_sk, content_hash: $enc_ch})\n"
            "MATCH (o:Memory {source_key: $obs_sk, content_hash: $obs_ch})\n"
            "MERGE (e)-[r:HAS_OBSERVATION]->(o)\n"
            "ON CREATE SET r.valid_from = $valid_from,\n"
            "              r.confidence = $confidence,\n"
            "              r.support_count = 1\n"
            "ON MATCH SET  r.support_count = r.support_count + 1"
        )
        if runner is not None:
            runner.run(
                cypher,
                enc_sk=encounter_source_key,
                enc_ch=encounter_content_hash,
                obs_sk=obs_source_key,
                obs_ch=obs_content_hash,
                valid_from=resolved_from,
                confidence=confidence,
            )
        else:
            with self._conn.session() as s:
                s.run(
                    cypher,
                    enc_sk=encounter_source_key,
                    enc_ch=encounter_content_hash,
                    obs_sk=obs_source_key,
                    obs_ch=obs_content_hash,
                    valid_from=resolved_from,
                    confidence=confidence,
                )

    def write_encounter_condition(
        self,
        *,
        encounter_source_key: str,
        encounter_content_hash: str,
        condition_source_key: str,
        condition_content_hash: str,
        valid_from: str | None = None,
        confidence: float = 1.0,
        runner: Any | None = None,
    ) -> None:
        """Write HAS_CONDITION from Encounter node to Condition node.

        Captures the encounter-scoped condition link (separate from the
        patient-level DIAGNOSED_WITH relationship).

        Args:
            encounter_source_key: source_key of the Encounter node.
            encounter_content_hash: content_hash of the Encounter node.
            condition_source_key: source_key of the Condition node.
            condition_content_hash: content_hash of the Condition node.
            valid_from: ISO-8601 onset date. Defaults to now.
            confidence: Confidence score.
            runner: Optional shared session/transaction for batched imports.
        """
        resolved_from = valid_from or self._now()
        cypher = (
            "MATCH (e:Memory {source_key: $enc_sk, content_hash: $enc_ch})\n"
            "MATCH (c:Memory {source_key: $cond_sk, content_hash: $cond_ch})\n"
            "MERGE (e)-[r:HAS_CONDITION]->(c)\n"
            "ON CREATE SET r.valid_from = $valid_from,\n"
            "              r.confidence = $confidence,\n"
            "              r.support_count = 1\n"
            "ON MATCH SET  r.support_count = r.support_count + 1"
        )
        if runner is not None:
            runner.run(
                cypher,
                enc_sk=encounter_source_key,
                enc_ch=encounter_content_hash,
                cond_sk=condition_source_key,
                cond_ch=condition_content_hash,
                valid_from=resolved_from,
                confidence=confidence,
            )
        else:
            with self._conn.session() as s:
                s.run(
                    cypher,
                    enc_sk=encounter_source_key,
                    enc_ch=encounter_content_hash,
                    cond_sk=condition_source_key,
                    cond_ch=condition_content_hash,
                    valid_from=resolved_from,
                    confidence=confidence,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now(self) -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()
