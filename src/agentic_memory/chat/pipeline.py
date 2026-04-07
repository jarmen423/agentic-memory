"""Conversation ingestion pipeline — turn-by-turn chat memory path.

ConversationIngestionPipeline subclasses BaseIngestionPipeline to ingest
conversation turns as :Memory:Conversation:Turn nodes. Each turn is one
atomic ingest call — no chunking. Session grouping is handled by the
companion :Memory:Conversation:Session node written per-turn.
"""

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
from agentic_memory.temporal.bridge import TemporalBridge

logger = logging.getLogger(__name__)

# Register all four chat sources at import time per CONTEXT.md
register_source("chat_mcp", ["Memory", "Conversation", "Turn"])
register_source("chat_proxy", ["Memory", "Conversation", "Turn"])
register_source("chat_ext", ["Memory", "Conversation", "Turn"])
register_source("chat_cli", ["Memory", "Conversation", "Turn"])

VALID_ROLES = frozenset({"user", "assistant", "system", "tool"})
EMBEDDABLE_ROLES = frozenset({"user", "assistant"})
VALID_SOURCE_KEYS = frozenset({"chat_mcp", "chat_proxy", "chat_ext", "chat_cli"})


class ConversationIngestionPipeline(BaseIngestionPipeline):
    """Concrete pipeline for conversation turn ingestion.

    Each call to ingest() handles one turn. Session grouping nodes are
    written automatically. Only user and assistant turns are embedded;
    system and tool turns are stored as metadata without embeddings.

    Args:
        connection_manager: Neo4j ConnectionManager instance.
        embedding_service: EmbeddingService configured for Gemini.
        entity_extractor: EntityExtractionService for named entity extraction.
    """

    DOMAIN_LABEL = "Conversation"

    def __init__(
        self,
        connection_manager: ConnectionManager,
        embedding_service: EmbeddingService,
        entity_extractor: EntityExtractionService,
        temporal_bridge: TemporalBridge | None = None,
    ) -> None:
        """Initialize the conversation ingestion pipeline.

        Args:
            connection_manager: Configured ConnectionManager instance.
            embedding_service: Configured EmbeddingService (Gemini provider).
            entity_extractor: Configured EntityExtractionService (Groq).
        """
        super().__init__(connection_manager)
        self._embedder = embedding_service
        self._extractor = entity_extractor
        self._writer = GraphWriter(connection_manager)
        self._temporal_bridge = temporal_bridge

    def ingest(self, source: dict[str, Any]) -> dict[str, Any]:
        """Ingest a single conversation turn into the memory graph.

        Validates required fields, conditionally embeds (user/assistant only),
        extracts entities, writes the Turn node and Session node, then wires
        all relationships.

        Args:
            source: Dict matching the turn schema. Required keys:
                role, content, session_id, project_id, turn_index.
                Optional: source_agent, model, tool_name, tool_call_id,
                tokens_input, tokens_output, timestamp, ingestion_mode,
                source_key.

        Returns:
            Summary dict: {role, session_id, turn_index, content_hash,
                embedded, entities_count, project_id}.

        Raises:
            ValueError: If required fields are missing or role is not one of
                ["user", "assistant", "system", "tool"].
        """
        # 1. Validate required fields
        for field in ("role", "content", "session_id", "project_id", "turn_index"):
            if field not in source or source[field] is None:
                raise ValueError(f"Missing required turn field: {field!r}")

        role = source["role"]
        if role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role {role!r}. Must be one of: {sorted(VALID_ROLES)}"
            )
        source_key = source.get("source_key", "chat_mcp")
        if source_key not in VALID_SOURCE_KEYS:
            raise ValueError(
                f"Invalid source_key {source_key!r}. Must be one of: "
                f"{sorted(VALID_SOURCE_KEYS)}"
            )

        return self._ingest_turn(source)

    def _ingest_turn(self, source: dict[str, Any]) -> dict[str, Any]:
        """Core turn ingestion — called after validation.

        Args:
            source: Validated turn dict.

        Returns:
            Summary dict with ingestion results.
        """
        now = self._now()
        role = source["role"]
        content = source["content"]
        session_id = source["session_id"]
        project_id = source["project_id"]
        turn_index = source["turn_index"]
        source_key = source.get("source_key", "chat_mcp")

        # content_hash: session-scoped identity key per CONTEXT.md
        # sha256(f"{session_id}:{turn_index}") — content NOT in hash so
        # re-delivery of updated turn content overwrites the node in place.
        content_hash = self._turn_content_hash(session_id, turn_index)

        # 2. Role-conditional embedding and entity extraction
        embedded = False
        entities: list[dict[str, Any]] = []
        embedding: list[float] | None = None
        embedding_model: str | None = None

        if role in EMBEDDABLE_ROLES:
            # Entity extraction (one LLM call per turn, user/assistant only)
            entities = self._extractor.extract(content)
            embed_text = build_embed_text(content, entities)
            embedding = self._embedder.embed(embed_text)
            embedding_model = "gemini-embedding-2-preview"
            embedded = True

        entity_names = [e["name"] for e in entities]
        entity_types = [e["type"] for e in entities]

        # Token count approximation (no tiktoken per CONTEXT.md)
        tokens_approx = int(len(content.split()) * 1.3)

        # 3. Build Turn node properties
        # timestamp: use source-provided if present, else ingested_at
        timestamp = source.get("timestamp") or now

        turn_props: dict[str, Any] = {
            "content": content,
            "role": role,
            "embedding": embedding,
            "turn_index": turn_index,
            "session_id": session_id,
            "project_id": project_id,
            "source_agent": source.get("source_agent"),
            "model": source.get("model"),
            "tool_name": source.get("tool_name"),
            "tool_call_id": source.get("tool_call_id"),
            "tokens_input": source.get("tokens_input"),
            "tokens_output": source.get("tokens_output"),
            "tokens_approx": tokens_approx,
            "timestamp": timestamp,
            "ingested_at": now,
            "ingestion_mode": source.get("ingestion_mode", "active"),
            "embedding_model": embedding_model,
            "source_key": source_key,
            "source_type": "conversation",
            "content_hash": content_hash,
            "entities": entity_names,
            "entity_types": entity_types,
        }

        # 4. Write Turn node (MERGE on source_key + content_hash)
        labels = self.node_labels(source_key)
        self._writer.write_memory_node(labels, turn_props)

        # 5. Upsert Session node
        session_props: dict[str, Any] = {
            "session_id": session_id,
            "project_id": project_id,
            "source_agent": source.get("source_agent"),
        }
        self._writer.write_session_node(
            props=session_props,
            turn_index=turn_index,
            started_at=timestamp,
        )

        # 6. Wire relationships: Session -> Turn (HAS_TURN) and Turn -> Session (PART_OF)
        self._writer.write_has_turn_relationship(
            session_id=session_id,
            turn_source_key=source_key,
            turn_content_hash=content_hash,
            order=turn_index,
            valid_from=now,
            confidence=1.0,
        )
        self._writer.write_part_of_turn_relationship(
            turn_source_key=source_key,
            turn_content_hash=content_hash,
            session_id=session_id,
            valid_from=now,
            confidence=1.0,
        )

        # 7. Wire entity relationships (only for embedded turns)
        if embedded:
            for entity in entities:
                self._writer.upsert_entity(entity["name"], entity["type"])
                rel_type = "ABOUT" if entity["type"] == "project" else "MENTIONS"
                self._writer.write_temporal_relationship(
                    source_key=source_key,
                    content_hash=content_hash,
                    entity_name=entity["name"],
                    entity_type=entity["type"],
                    rel_type=rel_type,
                    valid_from=now,
                    confidence=1.0,
                )
                self._shadow_write_entity_relation(
                    project_id=project_id,
                    session_id=session_id,
                    turn_index=turn_index,
                    timestamp=timestamp,
                    content=content,
                    entity=entity,
                    predicate=rel_type,
                )

        logger.info(
            "Turn ingested: session_id=%s turn_index=%d role=%s embedded=%s entities=%d",
            session_id,
            turn_index,
            role,
            embedded,
            len(entities),
        )

        return {
            "role": role,
            "session_id": session_id,
            "turn_index": turn_index,
            "content_hash": content_hash,
            "embedded": embedded,
            "entities_count": len(entities),
            "project_id": project_id,
        }

    def _turn_content_hash(self, session_id: str, turn_index: int) -> str:
        """Deterministic SHA-256 hash for Turn deduplication.

        Hash encodes (session_id, turn_index) per CONTEXT.md MERGE key.
        Content itself is excluded so that re-delivery of updated turn
        content overwrites in place without creating duplicate nodes.

        Args:
            session_id: Caller-owned session identifier.
            turn_index: 0-based position of the turn within the session.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        composite = f"{session_id}:{turn_index}"
        return hashlib.sha256(composite.encode()).hexdigest()

    def _now(self) -> str:
        """Current UTC timestamp in ISO format.

        Returns:
            ISO-8601 UTC datetime string.
        """
        return datetime.now(timezone.utc).isoformat()

    def _shadow_write_entity_relation(
        self,
        *,
        project_id: str,
        session_id: str,
        turn_index: int,
        timestamp: str,
        content: str,
        entity: dict[str, Any],
        predicate: str,
    ) -> None:
        """Best-effort temporal shadow write for conversation entity mentions."""
        if self._temporal_bridge is None or not self._temporal_bridge.is_available():
            return

        source_id = f"{session_id}:{turn_index}"
        evidence = {
            "sourceKind": "conversation_turn",
            "sourceId": source_id,
            "capturedAtUs": self._iso_to_micros(timestamp),
            "rawExcerpt": content[:500],
        }

        try:
            self._temporal_bridge.ingest_relation(
                project_id=project_id,
                subject_kind="conversation_turn",
                subject_name=source_id,
                predicate=predicate,
                object_kind=entity["type"],
                object_name=entity["name"],
                valid_from_us=self._iso_to_micros(timestamp),
                confidence=1.0,
                evidence=evidence,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Conversation temporal shadow write failed: session_id=%s turn_index=%s error=%s",
                session_id,
                turn_index,
                exc,
            )

    def _iso_to_micros(self, value: str) -> int:
        """Convert an ISO timestamp to UTC microseconds."""
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000)
