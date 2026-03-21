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
