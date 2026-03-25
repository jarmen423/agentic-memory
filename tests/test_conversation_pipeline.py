"""Unit tests for Phase 4 ConversationIngestionPipeline.

Tests cover:
- ABC subclass contract and DOMAIN_LABEL
- Role validation (ValueError on invalid roles, ValueError on missing fields)
- Embeddable turn flow (user/assistant): embedding called, entities extracted,
  all graph write methods called
- Non-embeddable turn flow (system/tool): embedding NOT called, entities NOT extracted,
  no entity relationship wiring
- content_hash is session-scoped (same content + different session_id = different hash)
- content_hash is deterministic (same session_id + turn_index = same hash)
- Source registration: all four chat sources in SOURCE_REGISTRY

All tests mock Neo4j, EmbeddingService, EntityExtractionService — no live services.
"""

import hashlib
from unittest.mock import MagicMock

import pytest

from codememory.core.graph_writer import GraphWriter


def _make_pipeline(source_key: str = "chat_mcp"):
    """Return a (pipeline, mock_writer) pair with all dependencies mocked."""
    from codememory.chat.pipeline import ConversationIngestionPipeline

    mock_conn = MagicMock()
    mock_session = MagicMock()
    mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = [{"name": "agentic-memory", "type": "project"}]

    pipeline = ConversationIngestionPipeline(mock_conn, mock_embedder, mock_extractor)

    # Replace writer with MagicMock to inspect calls without hitting Neo4j
    mock_writer = MagicMock()
    pipeline._writer = mock_writer

    return pipeline, mock_writer


def _turn_source(**overrides):
    """Return a minimal valid user turn source dict."""
    base = {
        "role": "user",
        "content": "What is the architecture of agentic-memory?",
        "session_id": "sess-test-abc",
        "project_id": "proj-test",
        "turn_index": 0,
        "source_agent": "claude",
        "ingestion_mode": "active",
        "source_key": "chat_mcp",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ABC subclass contract
# ---------------------------------------------------------------------------


class TestConversationPipelineSubclassContract:
    """Tests for class structure and ABC contract."""

    def test_pipeline_subclass_contract(self):
        """ConversationIngestionPipeline subclasses BaseIngestionPipeline with DOMAIN_LABEL."""
        from codememory.core.base import BaseIngestionPipeline
        from codememory.chat.pipeline import ConversationIngestionPipeline

        assert issubclass(ConversationIngestionPipeline, BaseIngestionPipeline)
        assert ConversationIngestionPipeline.DOMAIN_LABEL == "Conversation"

    def test_ingest_unknown_role_raises_value_error(self):
        """ingest() with role='banana' raises ValueError."""
        pipeline, _ = _make_pipeline()
        with pytest.raises(ValueError, match="banana"):
            pipeline.ingest(_turn_source(role="banana"))

    def test_ingest_missing_required_field_raises_value_error(self):
        """ingest() with missing session_id raises ValueError."""
        pipeline, _ = _make_pipeline()
        source = _turn_source()
        del source["session_id"]
        with pytest.raises(ValueError, match="session_id"):
            pipeline.ingest(source)

    def test_ingest_all_valid_roles_accepted(self):
        """ingest() accepts 'user', 'assistant', 'system', 'tool' without raising."""
        for role in ("user", "assistant", "system", "tool"):
            pipeline, _ = _make_pipeline()
            pipeline.ingest(_turn_source(role=role, tool_name="test" if role == "tool" else None))


# ---------------------------------------------------------------------------
# Embeddable turn flow (user and assistant)
# ---------------------------------------------------------------------------


class TestEmbeddableTurnFlow:
    """Tests for user and assistant turn ingestion (embedded path)."""

    def test_user_turn_calls_embedder(self):
        """ingest(role='user') calls embedding_service.embed() once."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(role="user"))
        assert pipeline._embedder.embed.call_count == 1

    def test_user_turn_calls_entity_extractor(self):
        """ingest(role='user') calls entity_extractor.extract() once."""
        pipeline, _ = _make_pipeline()
        pipeline.ingest(_turn_source(role="user"))
        assert pipeline._extractor.extract.call_count == 1

    def test_user_turn_writes_memory_node(self):
        """ingest(role='user') calls write_memory_node with Turn labels."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(role="user"))
        assert mock_writer.write_memory_node.call_count == 1
        labels = mock_writer.write_memory_node.call_args[0][0]
        assert "Memory" in labels
        assert "Conversation" in labels
        assert "Turn" in labels

    def test_user_turn_writes_session_node(self):
        """ingest(role='user') calls write_session_node once."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(role="user"))
        assert mock_writer.write_session_node.call_count == 1

    def test_user_turn_wires_has_turn_and_part_of(self):
        """ingest(role='user') calls write_has_turn_relationship and write_part_of_turn_relationship."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(role="user"))
        assert mock_writer.write_has_turn_relationship.call_count == 1
        assert mock_writer.write_part_of_turn_relationship.call_count == 1
        assert mock_writer.write_has_turn_relationship.call_args[1]["valid_from"]
        assert mock_writer.write_part_of_turn_relationship.call_args[1]["valid_from"]

    def test_user_turn_wires_entity_relationships(self):
        """ingest(role='user') calls upsert_entity and write_temporal_relationship per entity."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(role="user"))
        # Mock extractor returns 1 entity
        assert mock_writer.upsert_entity.call_count == 1
        assert mock_writer.write_relationship.call_count == 0
        assert mock_writer.write_temporal_relationship.call_count == 1
        assert mock_writer.write_temporal_relationship.call_args[1]["valid_from"]
        assert mock_writer.write_temporal_relationship.call_args[1]["confidence"] == 1.0

    def test_user_turn_result_has_embedded_true(self):
        """ingest(role='user') returns dict with embedded=True."""
        pipeline, _ = _make_pipeline()
        result = pipeline.ingest(_turn_source(role="user"))
        assert result["embedded"] is True
        assert result["entities_count"] == 1

    def test_assistant_turn_also_embeds(self):
        """ingest(role='assistant') calls embedder (same as user)."""
        pipeline, _ = _make_pipeline()
        pipeline.ingest(_turn_source(role="assistant"))
        assert pipeline._embedder.embed.call_count == 1


# ---------------------------------------------------------------------------
# Non-embeddable turn flow (system and tool)
# ---------------------------------------------------------------------------


class TestNonEmbeddableTurnFlow:
    """Tests for system and tool turn ingestion (no embedding path)."""

    def test_system_turn_does_not_call_embedder(self):
        """ingest(role='system') does NOT call embedding_service.embed()."""
        pipeline, _ = _make_pipeline()
        pipeline.ingest(_turn_source(role="system"))
        assert pipeline._embedder.embed.call_count == 0

    def test_system_turn_does_not_call_extractor(self):
        """ingest(role='system') does NOT call entity_extractor.extract()."""
        pipeline, _ = _make_pipeline()
        pipeline.ingest(_turn_source(role="system"))
        assert pipeline._extractor.extract.call_count == 0

    def test_system_turn_node_has_null_embedding(self):
        """ingest(role='system') writes Turn node with embedding=None."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(role="system"))
        props = mock_writer.write_memory_node.call_args[0][1]
        assert props["embedding"] is None
        assert props["embedding_model"] is None

    def test_system_turn_still_writes_session_node(self):
        """ingest(role='system') still calls write_session_node (session must be tracked)."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(role="system"))
        assert mock_writer.write_session_node.call_count == 1

    def test_system_turn_does_not_wire_entity_relationships(self):
        """ingest(role='system') does NOT call upsert_entity or write_temporal_relationship."""
        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(role="system"))
        assert mock_writer.upsert_entity.call_count == 0
        assert mock_writer.write_relationship.call_count == 0
        assert mock_writer.write_temporal_relationship.call_count == 0

    def test_system_turn_result_has_embedded_false(self):
        """ingest(role='system') returns dict with embedded=False."""
        pipeline, _ = _make_pipeline()
        result = pipeline.ingest(_turn_source(role="system"))
        assert result["embedded"] is False


# ---------------------------------------------------------------------------
# Content hash contract
# ---------------------------------------------------------------------------


class TestTurnContentHash:
    """Tests for turn content_hash deduplication behavior."""

    def test_content_hash_is_session_scoped(self):
        """Same content + different session_id produces different content_hash."""
        pipeline1, writer1 = _make_pipeline()
        pipeline2, writer2 = _make_pipeline()

        same_content = "What is the architecture of agentic-memory?"

        pipeline1.ingest(_turn_source(content=same_content, session_id="sess-1", turn_index=0))
        pipeline2.ingest(_turn_source(content=same_content, session_id="sess-2", turn_index=0))

        props1 = writer1.write_memory_node.call_args[0][1]
        props2 = writer2.write_memory_node.call_args[0][1]

        assert props1["content_hash"] != props2["content_hash"], (
            "Different session_ids must produce different content_hash values."
        )

    def test_content_hash_deterministic_same_session_turn(self):
        """Same session_id and turn_index always produces the same content_hash."""
        import hashlib

        pipeline, mock_writer = _make_pipeline()
        pipeline.ingest(_turn_source(session_id="sess-abc", turn_index=3))

        props = mock_writer.write_memory_node.call_args[0][1]
        expected = hashlib.sha256(b"sess-abc:3").hexdigest()
        assert props["content_hash"] == expected

    def test_content_hash_ignores_content_change(self):
        """Same session_id + turn_index with different content produces same content_hash."""
        import hashlib

        pipeline1, writer1 = _make_pipeline()
        pipeline2, writer2 = _make_pipeline()

        pipeline1.ingest(_turn_source(content="First version", session_id="sess-x", turn_index=1))
        pipeline2.ingest(_turn_source(content="Updated version", session_id="sess-x", turn_index=1))

        props1 = writer1.write_memory_node.call_args[0][1]
        props2 = writer2.write_memory_node.call_args[0][1]

        assert props1["content_hash"] == props2["content_hash"], (
            "content_hash must be identical for same session_id + turn_index regardless of content."
        )


# ---------------------------------------------------------------------------
# Source registration
# ---------------------------------------------------------------------------


class TestChatSourceRegistration:
    """Tests for source registration at module import time."""

    def test_all_four_chat_sources_registered(self):
        """All four chat sources are in SOURCE_REGISTRY after import."""
        import codememory.chat.pipeline  # noqa: F401 — ensure module is imported
        from codememory.core.registry import SOURCE_REGISTRY

        for key in ("chat_mcp", "chat_proxy", "chat_ext", "chat_cli"):
            assert key in SOURCE_REGISTRY, f"Source key {key!r} not in SOURCE_REGISTRY"
            assert SOURCE_REGISTRY[key] == ["Memory", "Conversation", "Turn"]
