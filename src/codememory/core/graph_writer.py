"""Shared Neo4j write patterns for Memory and Entity nodes.

All writes use MERGE for idempotency — re-ingesting the same content produces
the same node (composite key: source_key + content_hash for Memory nodes,
name + type for Entity nodes).
"""

import logging
from typing import Any

from codememory.core.connection import ConnectionManager

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

    def write_memory_node(
        self,
        labels: list[str],
        properties: dict[str, Any],
        namespace: str | None = None,
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
        """
        labels_str = ":".join(labels)

        if namespace is not None:
            cypher = (
                f"MERGE (m:{labels_str} {{source_key: $source_key, content_hash: $content_hash}})\n"
                "ON CREATE SET m += $props, m.namespace = $namespace\n"
                "ON MATCH SET m.ingested_at = $ingested_at"
            )
            with self._conn.session() as session:
                session.run(
                    cypher,
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
            with self._conn.session() as session:
                session.run(
                    cypher,
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

    def upsert_entity(self, name: str, entity_type: str) -> None:
        """Upsert an Entity node using MERGE on composite key (name, type).

        Applies labels :Entity:{entity_type.capitalize()} to the node.

        Args:
            name: Entity name (e.g. "FastAPI", "John Doe").
            entity_type: Entity type (e.g. "technology", "person").
        """
        type_label = entity_type.capitalize()
        cypher = (
            f"MERGE (e:Entity:{type_label} {{name: $name, type: $type}})"
        )
        with self._conn.session() as session:
            session.run(cypher, name=name, type=entity_type)

        logger.debug("Entity upserted: name=%s type=%s", name, entity_type)

    def write_relationship(
        self,
        source_key: str,
        content_hash: str,
        entity_name: str,
        entity_type: str,
        rel_type: str = "ABOUT",
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
        """
        cypher = (
            "MATCH (m {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (e {name: $entity_name, type: $entity_type})\n"
            f"MERGE (m)-[:{rel_type}]->(e)"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
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
    ) -> None:
        """Write :CITES relationship from Finding to Entity:Source.

        Args:
            finding_source_key: source_key of the Finding node.
            finding_content_hash: content_hash of the Finding node.
            source_url: url of the Entity:Source node.
            rel_props: Relationship properties (url, title, snippet, accessed_at, source_agent).
        """
        cypher = (
            "MATCH (f {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (s:Entity:Source {url: $source_url})\n"
            "MERGE (f)-[r:CITES]->(s)\n"
            "ON CREATE SET r += $rel_props\n"
            "ON MATCH SET r.snippet = $rel_props.snippet, r.accessed_at = $rel_props.accessed_at"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                source_key=finding_source_key,
                content_hash=finding_content_hash,
                source_url=source_url,
                rel_props=rel_props,
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
    ) -> None:
        """Write :HAS_CHUNK relationship from Report to Chunk with order property.

        Args:
            report_project_id: project_id of the Report node.
            report_session_id: session_id of the Report node.
            chunk_source_key: source_key of the Chunk node.
            chunk_content_hash: content_hash of the Chunk node.
            order: Chunk index for ordered reconstruction.
        """
        cypher = (
            "MATCH (r:Memory:Research:Report {project_id: $project_id, session_id: $session_id})\n"
            "MATCH (c {source_key: $source_key, content_hash: $content_hash})\n"
            "MERGE (r)-[rel:HAS_CHUNK {order: $order}]->(c)"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                project_id=report_project_id,
                session_id=report_session_id,
                source_key=chunk_source_key,
                content_hash=chunk_content_hash,
                order=order,
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
    ) -> None:
        """Write :PART_OF relationship from Chunk back to Report.

        This is the reverse of :HAS_CHUNK per CONTEXT.md schema:
        (:Memory:Research:Chunk)-[:PART_OF]->(:Memory:Research:Report)

        Args:
            chunk_source_key: source_key of the Chunk node.
            chunk_content_hash: content_hash of the Chunk node.
            report_project_id: project_id of the Report node.
            report_session_id: session_id of the Report node.
        """
        cypher = (
            "MATCH (c {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (r:Memory:Research:Report {project_id: $project_id, session_id: $session_id})\n"
            "MERGE (c)-[:PART_OF]->(r)"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                source_key=chunk_source_key,
                content_hash=chunk_content_hash,
                project_id=report_project_id,
                session_id=report_session_id,
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
    ) -> None:
        """Write :HAS_TURN relationship from Session to Turn with order property.

        Mirrors write_has_chunk_relationship for the conversation topology.
        Session is matched by session_id; Turn is matched by (source_key, content_hash).

        Args:
            session_id: session_id of the Session node.
            turn_source_key: source_key of the Turn node (e.g. "chat_mcp").
            turn_content_hash: content_hash of the Turn node (sha256 of session_id:turn_index).
            order: Turn index for ordered reconstruction (same value as turn_index).
        """
        cypher = (
            "MATCH (s:Memory:Conversation:Session {session_id: $session_id})\n"
            "MATCH (t {source_key: $source_key, content_hash: $content_hash})\n"
            "MERGE (s)-[rel:HAS_TURN {order: $order}]->(t)"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                session_id=session_id,
                source_key=turn_source_key,
                content_hash=turn_content_hash,
                order=order,
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
    ) -> None:
        """Write :PART_OF relationship from Turn back to Session.

        Reverse arc of HAS_TURN per CONTEXT.md schema:
        (:Memory:Conversation:Turn)-[:PART_OF]->(:Memory:Conversation:Session)

        Args:
            turn_source_key: source_key of the Turn node.
            turn_content_hash: content_hash of the Turn node.
            session_id: session_id of the Session node.
        """
        cypher = (
            "MATCH (t {source_key: $source_key, content_hash: $content_hash})\n"
            "MATCH (s:Memory:Conversation:Session {session_id: $session_id})\n"
            "MERGE (t)-[:PART_OF]->(s)"
        )
        with self._conn.session() as session:
            session.run(
                cypher,
                source_key=turn_source_key,
                content_hash=turn_content_hash,
                session_id=session_id,
            )
        logger.debug(
            "PART_OF relationship written: Turn(%s/%s) -> Session(%s)",
            turn_source_key,
            turn_content_hash,
            session_id,
        )
