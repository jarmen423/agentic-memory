"""Shared Neo4j write patterns for Memory and Entity nodes.

All writes use MERGE for idempotency — re-ingesting the same content produces
the same node (composite key: source_key + content_hash for Memory nodes,
name + type for Entity nodes).
"""

import logging
from datetime import datetime, timezone
from typing import Any

from agentic_memory.core.connection import ConnectionManager

logger = logging.getLogger(__name__)


class GraphWriter:
    """Shared Neo4j write patterns for Memory and Entity nodes.

    All writes use MERGE for idempotency (re-ingest same content = same node).
    Uses composite key (source_key, content_hash) per CONTEXT.md guidance.
    """

    def __init__(self, connection_manager: ConnectionManager) -> None:
        """Initialize GraphWriter with a Neo4j connection manager.

        Args:
            connection_manager: Configured ConnectionManager instance.
        """
        self._conn = connection_manager

    def _run(
        self,
        cypher: str,
        *,
        runner: Any | None = None,
        **params: Any,
    ) -> None:
        """Execute one Neo4j write either on a shared runner or a fresh session.

        Why this helper exists:
            The original healthcare import path opened a brand-new session for
            nearly every small write. That is accurate but expensive. The
            accelerated importer now passes a shared transaction/runner so a
            whole batch can amortize session and commit overhead without
            changing the Cypher semantics.

        Args:
            cypher: Write query to execute.
            runner: Optional existing Neo4j ``Session`` or ``Transaction`` with
                a ``run(...)`` method. When omitted, this helper preserves the
                historical behavior and uses a short-lived session.
            **params: Query parameters.
        """
        if runner is not None:
            runner.run(cypher, **params)
            return

        with self._conn.session() as session:
            session.run(cypher, **params)

    def write_memory_node(
        self,
        labels: list[str],
        properties: dict[str, Any],
        namespace: str | None = None,
        *,
        runner: Any | None = None,
    ) -> None:
        """Write (upsert) a Memory node using MERGE on composite key.

        Uses MERGE on (source_key, content_hash) so re-ingesting identical
        content updates the ingested_at timestamp but preserves the node.

        All required metadata fields must be present in properties:
            source_key, content_hash, session_id, source_type, ingested_at,
            ingestion_mode, embedding_model, project_id, entities, entity_types,
            embedding, text

        Args:
            labels: Neo4j node labels, e.g. ["Memory", "Code", "Chunk"].
            properties: Dict with all required metadata fields.
            namespace: Optional organizational scope (e.g. "professional",
                "personal"). When provided, stored as namespace property.
                When omitted, namespace is not written to the node.
            runner: Optional existing Neo4j session/transaction. Importers pass
                this to group many writes into one transaction without changing
                the node identity or property semantics.
        """
        labels_str = ":".join(labels)

        if namespace is not None:
            cypher = (
                f"MERGE (m:{labels_str} {{source_key: $source_key, content_hash: $content_hash}})\n"
                "ON CREATE SET m += $props, m.namespace = $namespace\n"
                "ON MATCH SET m.ingested_at = $ingested_at"
            )
            self._run(
                cypher,
                runner=runner,
                source_key=properties["source_key"],
                content_hash=properties["content_hash"],
                props=properties,
                ingested_at=properties["ingested_at"],
                namespace=namespace,
            )
        else:
            cypher = (
                f"MERGE (m:{labels_str} {{source_key: $source_key, content_hash: $content_hash}})\n"
                "ON CREATE SET m += $props\n"
                "ON MATCH SET m.ingested_at = $ingested_at"
            )
            self._run(
                cypher,
                runner=runner,
                source_key=properties["source_key"],
                content_hash=properties["content_hash"],
                props=properties,
                ingested_at=properties["ingested_at"],
            )

        logger.debug(
            "Memory node upserted: source_key=%s content_hash=%s labels=%s",
            properties.get("source_key"),
            properties.get("content_hash"),
            labels_str,
        )

    def upsert_entity(
        self,
        name: str,
        entity_type: str,
        *,
        runner: Any | None = None,
    ) -> None:
        """Upsert an Entity node using MERGE on composite key (name, type).

        Applies labels :Entity:{entity_type.capitalize()} to the node.

        Args:
            name: Entity name (e.g. "FastAPI", "John Doe").
            entity_type: Entity type (e.g. "technology", "person").
            runner: Optional shared session/transaction for batched imports.
        """
        type_label = entity_type.capitalize()
        cypher = (
            f"MERGE (e:Entity:{type_label} {{name: $name, type: $type}})"
        )
        self._run(cypher, runner=runner, name=name, type=entity_type)

        logger.debug("Entity upserted: name=%s type=%s", name, entity_type)

    def write_relationship(
        self,
        source_key: str,
        content_hash: str,
        entity_name: str,
        entity_type: str,
        rel_type: str = "ABOUT",
        *,
        runner: Any | None = None,
    ) -> None:
        """Write a relationship from a Memory node to an Entity node.

        Uses MATCH to find both nodes then MERGE the relationship for
        idempotency. Supports ABOUT, MENTIONS, and BELONGS_TO relationship types.

        Args:
            source_key: source_key of the Memory node.
            content_hash: content_hash of the Memory node.
            entity_name: name of the Entity node.
            entity_type: type of the Entity node.
            rel_type: Relationship type. Defaults to "ABOUT".
                Valid values: "ABOUT", "MENTIONS", "BELONGS_TO".
            runner: Optional shared session/transaction for batched imports.
        """
        cypher = (
            "MATCH (m {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (e {name: $entity_name, type: $entity_type})\n"
            f"MERGE (m)-[:{rel_type}]->(e)"
        )
        self._run(
            cypher,
            runner=runner,
            source_key=source_key,
            content_hash=content_hash,
            entity_name=entity_name,
            entity_type=entity_type,
        )

        logger.debug(
            "Relationship written: Memory(%s/%s) -[:%s]-> Entity(%s)",
            source_key,
            content_hash,
            rel_type,
            entity_name,
        )

    def _resolve_valid_from(self, valid_from: str | None) -> str:
        """Return the provided validity start or a current UTC timestamp."""
        return valid_from or datetime.now(timezone.utc).isoformat()

    def write_temporal_relationship(
        self,
        source_key: str,
        content_hash: str,
        entity_name: str,
        entity_type: str,
        rel_type: str = "ABOUT",
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        support_count: int = 1,
        contradiction_count: int = 0,
        *,
        runner: Any | None = None,
    ) -> None:
        """Write a temporal relationship from a Memory node to an Entity node.

        Uses a MERGE pattern keyed only by the relationship type and endpoint
        identity, then sets temporal metadata in ON CREATE/ON MATCH branches.

        Args:
            source_key: source_key of the Memory node.
            content_hash: content_hash of the Memory node.
            entity_name: name of the Entity node.
            entity_type: type of the Entity node.
            rel_type: Relationship type to write.
            valid_from: ISO-8601 validity start. Defaults to current UTC time.
            valid_to: Optional ISO-8601 validity end.
            confidence: Confidence score between 0.0 and 1.0.
            support_count: Initial support count for a new relationship.
            contradiction_count: Initial contradiction count for a new relationship.
            runner: Optional shared session/transaction for batched imports.
        """
        resolved_valid_from = self._resolve_valid_from(valid_from)
        cypher = (
            "MATCH (m {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (e {name: $entity_name, type: $entity_type})\n"
            f"MERGE (m)-[r:{rel_type}]->(e)\n"
            "ON CREATE SET r.valid_from = $valid_from,\n"
            "              r.valid_to = $valid_to,\n"
            "              r.confidence = $confidence,\n"
            "              r.support_count = $support_count,\n"
            "              r.contradiction_count = $contradiction_count\n"
            "ON MATCH SET  r.support_count = r.support_count + 1,\n"
            "              r.confidence = CASE WHEN $confidence > r.confidence\n"
            "                                  THEN $confidence\n"
            "                                  ELSE r.confidence END"
        )
        self._run(
            cypher,
            runner=runner,
            source_key=source_key,
            content_hash=content_hash,
            entity_name=entity_name,
            entity_type=entity_type,
            valid_from=resolved_valid_from,
            valid_to=valid_to,
            confidence=confidence,
            support_count=support_count,
            contradiction_count=contradiction_count,
        )
        logger.debug(
            "Temporal relationship written: Memory(%s/%s) -[:%s]-> Entity(%s)",
            source_key,
            content_hash,
            rel_type,
            entity_name,
        )

    def update_relationship_validity(
        self,
        source_key: str,
        content_hash: str,
        entity_name: str,
        entity_type: str,
        rel_type: str,
        valid_to: str,
    ) -> None:
        """Set the validity end timestamp on an existing relationship.

        Args:
            source_key: source_key of the Memory node.
            content_hash: content_hash of the Memory node.
            entity_name: name of the Entity node.
            entity_type: type of the Entity node.
            rel_type: Relationship type to update.
            valid_to: ISO-8601 validity end timestamp.
        """
        cypher = (
            "MATCH (m {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (e {name: $entity_name, type: $entity_type})\n"
            f"MATCH (m)-[r:{rel_type}]->(e)\n"
            "SET r.valid_to = $valid_to"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                source_key=source_key,
                content_hash=content_hash,
                entity_name=entity_name,
                entity_type=entity_type,
                valid_to=valid_to,
            )

    def increment_contradiction(
        self,
        source_key: str,
        content_hash: str,
        entity_name: str,
        entity_type: str,
        rel_type: str,
    ) -> None:
        """Increment contradiction_count on an existing relationship.

        Args:
            source_key: source_key of the Memory node.
            content_hash: content_hash of the Memory node.
            entity_name: name of the Entity node.
            entity_type: type of the Entity node.
            rel_type: Relationship type to update.
        """
        cypher = (
            "MATCH (m {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (e {name: $entity_name, type: $entity_type})\n"
            f"MATCH (m)-[r:{rel_type}]->(e)\n"
            "SET r.contradiction_count = coalesce(r.contradiction_count, 0) + 1"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                source_key=source_key,
                content_hash=content_hash,
                entity_name=entity_name,
                entity_type=entity_type,
            )

    def write_report_node(self, properties: dict[str, Any]) -> None:
        """Write (upsert) a Report parent node using MERGE on (project_id, session_id).

        Report nodes have NO text and NO embedding. They are metadata-only parents.

        Args:
            properties: Dict with project_id, session_id, title, source_agent,
                source_key, source_type, ingested_at, research_question,
                ingestion_mode, embedding_model (null), entities, entity_types.
        """
        cypher = (
            "MERGE (m:Memory:Research:Report {project_id: $project_id, session_id: $session_id})\n"
            "ON CREATE SET m += $props\n"
            "ON MATCH SET m.ingested_at = $ingested_at, m.title = $props.title, "
            "m.entities = $props.entities, m.entity_types = $props.entity_types"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                project_id=properties["project_id"],
                session_id=properties["session_id"],
                props=properties,
                ingested_at=properties["ingested_at"],
            )
        logger.debug(
            "Report node upserted: project_id=%s session_id=%s",
            properties.get("project_id"),
            properties.get("session_id"),
        )

    def write_source_node(self, url: str, title: str | None = None) -> None:
        """Write (upsert) an Entity:Source node using MERGE on url.

        Source nodes are reference-only — no embedding.

        Args:
            url: Source URL (unique key).
            title: Optional human-readable title for the source.
        """
        cypher = (
            "MERGE (s:Entity:Source {url: $url})\n"
            "ON CREATE SET s.title = $title\n"
            "ON MATCH SET s.title = $title"
        )
        with self._conn.session() as session:
            session.run(cypher, url=url, title=title)
        logger.debug("Source node upserted: url=%s", url)

    def write_cites_relationship(
        self,
        finding_source_key: str,
        finding_content_hash: str,
        source_url: str,
        rel_props: dict[str, Any],
        valid_from: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        """Write :CITES relationship from Finding to Entity:Source.

        Args:
            finding_source_key: source_key of the Finding node.
            finding_content_hash: content_hash of the Finding node.
            source_url: url of the Entity:Source node.
            rel_props: Relationship properties (url, title, snippet, accessed_at, source_agent).
            valid_from: ISO-8601 validity start. Defaults to current UTC time.
            confidence: Confidence score between 0.0 and 1.0.
        """
        resolved_valid_from = self._resolve_valid_from(valid_from)
        temporal_rel_props = {
            **rel_props,
            "valid_from": resolved_valid_from,
            "valid_to": None,
            "confidence": confidence,
            "support_count": 1,
            "contradiction_count": 0,
        }
        cypher = (
            "MATCH (f {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (s:Entity:Source {url: $source_url})\n"
            "MERGE (f)-[r:CITES]->(s)\n"
            "ON CREATE SET r += $rel_props\n"
            "ON MATCH SET r.snippet = $rel_props.snippet,\n"
            "              r.accessed_at = $rel_props.accessed_at,\n"
            "              r.support_count = r.support_count + 1,\n"
            "              r.confidence = CASE WHEN $confidence > r.confidence\n"
            "                                  THEN $confidence\n"
            "                                  ELSE r.confidence END"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                source_key=finding_source_key,
                content_hash=finding_content_hash,
                source_url=source_url,
                rel_props=temporal_rel_props,
                confidence=confidence,
            )
        logger.debug(
            "CITES relationship written: Finding(%s/%s) -> Source(%s)",
            finding_source_key,
            finding_content_hash,
            source_url,
        )

    def write_has_chunk_relationship(
        self,
        report_project_id: str,
        report_session_id: str,
        chunk_source_key: str,
        chunk_content_hash: str,
        order: int,
        valid_from: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        """Write :HAS_CHUNK relationship from Report to Chunk with order property.

        Args:
            report_project_id: project_id of the Report node.
            report_session_id: session_id of the Report node.
            chunk_source_key: source_key of the Chunk node.
            chunk_content_hash: content_hash of the Chunk node.
            order: Chunk index for ordered reconstruction.
            valid_from: ISO-8601 validity start. Defaults to current UTC time.
            confidence: Confidence score between 0.0 and 1.0.
        """
        resolved_valid_from = self._resolve_valid_from(valid_from)
        cypher = (
            "MATCH (r:Memory:Research:Report {project_id: $project_id, session_id: $session_id})\n"
            "MATCH (c {source_key: $source_key, content_hash: $content_hash})\n"
            "MERGE (r)-[rel:HAS_CHUNK {order: $order}]->(c)\n"
            "ON CREATE SET rel.valid_from = $valid_from,\n"
            "              rel.valid_to = null,\n"
            "              rel.confidence = $confidence,\n"
            "              rel.support_count = 1,\n"
            "              rel.contradiction_count = 0\n"
            "ON MATCH SET  rel.support_count = rel.support_count + 1,\n"
            "              rel.confidence = CASE WHEN $confidence > rel.confidence\n"
            "                                    THEN $confidence\n"
            "                                    ELSE rel.confidence END"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                project_id=report_project_id,
                session_id=report_session_id,
                source_key=chunk_source_key,
                content_hash=chunk_content_hash,
                order=order,
                valid_from=resolved_valid_from,
                confidence=confidence,
            )
        logger.debug(
            "HAS_CHUNK relationship written: Report(%s/%s) -> Chunk(%s/%s) order=%d",
            report_project_id,
            report_session_id,
            chunk_source_key,
            chunk_content_hash,
            order,
        )

    def write_part_of_relationship(
        self,
        chunk_source_key: str,
        chunk_content_hash: str,
        report_project_id: str,
        report_session_id: str,
        valid_from: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        """Write :PART_OF relationship from Chunk back to Report.

        This is the reverse of :HAS_CHUNK per CONTEXT.md schema:
        (:Memory:Research:Chunk)-[:PART_OF]->(:Memory:Research:Report)

        Args:
            chunk_source_key: source_key of the Chunk node.
            chunk_content_hash: content_hash of the Chunk node.
            report_project_id: project_id of the Report node.
            report_session_id: session_id of the Report node.
            valid_from: ISO-8601 validity start. Defaults to current UTC time.
            confidence: Confidence score between 0.0 and 1.0.
        """
        resolved_valid_from = self._resolve_valid_from(valid_from)
        cypher = (
            "MATCH (c {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (r:Memory:Research:Report {project_id: $project_id, session_id: $session_id})\n"
            "MERGE (c)-[rel:PART_OF]->(r)\n"
            "ON CREATE SET rel.valid_from = $valid_from,\n"
            "              rel.valid_to = null,\n"
            "              rel.confidence = $confidence,\n"
            "              rel.support_count = 1,\n"
            "              rel.contradiction_count = 0\n"
            "ON MATCH SET  rel.support_count = rel.support_count + 1,\n"
            "              rel.confidence = CASE WHEN $confidence > rel.confidence\n"
            "                                    THEN $confidence\n"
            "                                    ELSE rel.confidence END"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                source_key=chunk_source_key,
                content_hash=chunk_content_hash,
                project_id=report_project_id,
                session_id=report_session_id,
                valid_from=resolved_valid_from,
                confidence=confidence,
            )
        logger.debug(
            "PART_OF relationship written: Chunk(%s/%s) -> Report(%s/%s)",
            chunk_source_key,
            chunk_content_hash,
            report_project_id,
            report_session_id,
        )

    def write_session_node(
        self,
        props: dict[str, Any],
        turn_index: int,
        started_at: str,
    ) -> None:
        """Write (upsert) a Session grouping node using MERGE on session_id.

        On first write: sets started_at, turn_count=1, last_turn_index=turn_index.
        On subsequent writes: increments turn_count, updates last_turn_index to max
        of existing and new turn_index.

        Args:
            props: Full session property dict including session_id, project_id,
                source_agent. Must contain 'session_id'.
            turn_index: The turn_index of the turn being ingested (used in
                CASE expression to track max last_turn_index).
            started_at: ISO-8601 UTC string for the session start timestamp
                (only written ON CREATE).
        """
        cypher = (
            "MERGE (s:Memory:Conversation:Session {session_id: $session_id})\n"
            "ON CREATE SET\n"
            "    s += $props,\n"
            "    s.started_at = $started_at,\n"
            "    s.turn_count = 1,\n"
            "    s.last_turn_index = $turn_index\n"
            "ON MATCH SET\n"
            "    s.last_turn_index = CASE\n"
            "        WHEN s.last_turn_index < $turn_index THEN $turn_index\n"
            "        ELSE s.last_turn_index\n"
            "    END,\n"
            "    s.turn_count = s.turn_count + 1,\n"
            "    s.source_agent = $props.source_agent"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                session_id=props["session_id"],
                props=props,
                started_at=started_at,
                turn_index=turn_index,
            )
        logger.debug(
            "Session node upserted: session_id=%s turn_index=%d",
            props.get("session_id"),
            turn_index,
        )

    def write_has_turn_relationship(
        self,
        session_id: str,
        turn_source_key: str,
        turn_content_hash: str,
        order: int,
        valid_from: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        """Write :HAS_TURN relationship from Session to Turn with order property.

        Mirrors write_has_chunk_relationship for the conversation topology.
        Session is matched by session_id; Turn is matched by (source_key, content_hash).

        Args:
            session_id: session_id of the Session node.
            turn_source_key: source_key of the Turn node (e.g. "chat_mcp").
            turn_content_hash: content_hash of the Turn node (sha256 of session_id:turn_index).
            order: Turn index for ordered reconstruction (same value as turn_index).
            valid_from: ISO-8601 validity start. Defaults to current UTC time.
            confidence: Confidence score between 0.0 and 1.0.
        """
        resolved_valid_from = self._resolve_valid_from(valid_from)
        cypher = (
            "MATCH (s:Memory:Conversation:Session {session_id: $session_id})\n"
            "MATCH (t {source_key: $source_key, content_hash: $content_hash})\n"
            "MERGE (s)-[rel:HAS_TURN {order: $order}]->(t)\n"
            "ON CREATE SET rel.valid_from = $valid_from,\n"
            "              rel.valid_to = null,\n"
            "              rel.confidence = $confidence,\n"
            "              rel.support_count = 1,\n"
            "              rel.contradiction_count = 0\n"
            "ON MATCH SET  rel.support_count = rel.support_count + 1,\n"
            "              rel.confidence = CASE WHEN $confidence > rel.confidence\n"
            "                                    THEN $confidence\n"
            "                                    ELSE rel.confidence END"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                session_id=session_id,
                source_key=turn_source_key,
                content_hash=turn_content_hash,
                order=order,
                valid_from=resolved_valid_from,
                confidence=confidence,
            )
        logger.debug(
            "HAS_TURN relationship written: Session(%s) -> Turn(%s/%s) order=%d",
            session_id,
            turn_source_key,
            turn_content_hash,
            order,
        )

    def write_part_of_turn_relationship(
        self,
        turn_source_key: str,
        turn_content_hash: str,
        session_id: str,
        valid_from: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        """Write :PART_OF relationship from Turn back to Session.

        Reverse arc of HAS_TURN per CONTEXT.md schema:
        (:Memory:Conversation:Turn)-[:PART_OF]->(:Memory:Conversation:Session)

        Args:
            turn_source_key: source_key of the Turn node.
            turn_content_hash: content_hash of the Turn node.
            session_id: session_id of the Session node.
            valid_from: ISO-8601 validity start. Defaults to current UTC time.
            confidence: Confidence score between 0.0 and 1.0.
        """
        resolved_valid_from = self._resolve_valid_from(valid_from)
        cypher = (
            "MATCH (t {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (s:Memory:Conversation:Session {session_id: $session_id})\n"
            "MERGE (t)-[rel:PART_OF]->(s)\n"
            "ON CREATE SET rel.valid_from = $valid_from,\n"
            "              rel.valid_to = null,\n"
            "              rel.confidence = $confidence,\n"
            "              rel.support_count = 1,\n"
            "              rel.contradiction_count = 0\n"
            "ON MATCH SET  rel.support_count = rel.support_count + 1,\n"
            "              rel.confidence = CASE WHEN $confidence > rel.confidence\n"
            "                                    THEN $confidence\n"
            "                                    ELSE rel.confidence END"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                source_key=turn_source_key,
                content_hash=turn_content_hash,
                session_id=session_id,
                valid_from=resolved_valid_from,
                confidence=confidence,
            )
        logger.debug(
            "PART_OF relationship written: Turn(%s/%s) -> Session(%s)",
            turn_source_key,
            turn_content_hash,
            session_id,
        )
