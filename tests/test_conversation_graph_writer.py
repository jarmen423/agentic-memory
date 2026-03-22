"""Unit tests for Phase 4 GraphWriter conversation extensions.

Tests cover:
- write_session_node: MERGE on session_id, ON CREATE / ON MATCH branches
- write_has_turn_relationship: HAS_TURN with order property
- write_part_of_turn_relationship: PART_OF Turn -> Session

All tests mock Neo4j connections — no live services required.
"""

from unittest.mock import MagicMock
import pytest

from codememory.core.graph_writer import GraphWriter


def _make_writer():
    """Return a (GraphWriter, mock_conn, mock_session) triple."""
    mock_conn = MagicMock()
    mock_session = MagicMock()
    mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)
    writer = GraphWriter(mock_conn)
    return writer, mock_conn, mock_session


class TestWriteSessionNode:
    """Tests for GraphWriter.write_session_node()."""

    def test_write_session_node_merge_key(self):
        """write_session_node uses MERGE on session_id for Memory:Conversation:Session."""
        writer, _, mock_session = _make_writer()
        props = {
            "session_id": "sess-abc",
            "project_id": "proj-1",
            "source_agent": "claude",
        }
        writer.write_session_node(props=props, turn_index=0, started_at="2026-01-01T00:00:00+00:00")

        assert mock_session.run.called
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE" in cypher
        assert "Memory:Conversation:Session" in cypher
        assert "session_id: $session_id" in cypher

    def test_write_session_node_on_create_on_match(self):
        """write_session_node Cypher contains both ON CREATE SET and ON MATCH SET."""
        writer, _, mock_session = _make_writer()
        props = {"session_id": "sess-xyz", "project_id": "proj-1", "source_agent": "claude"}
        writer.write_session_node(props=props, turn_index=2, started_at="2026-01-01T00:00:00+00:00")

        cypher = mock_session.run.call_args[0][0]
        assert "ON CREATE SET" in cypher
        assert "ON MATCH SET" in cypher

    def test_write_session_node_last_turn_index_case(self):
        """write_session_node uses CASE expression for last_turn_index tracking."""
        writer, _, mock_session = _make_writer()
        props = {"session_id": "sess-xyz", "project_id": "proj-1", "source_agent": "claude"}
        writer.write_session_node(props=props, turn_index=5, started_at="2026-01-01T00:00:00+00:00")

        cypher = mock_session.run.call_args[0][0]
        assert "CASE" in cypher
        assert "last_turn_index" in cypher

    def test_write_session_node_passes_turn_index_param(self):
        """write_session_node passes turn_index as a separate Cypher parameter."""
        writer, _, mock_session = _make_writer()
        props = {"session_id": "sess-xyz", "project_id": "proj-1", "source_agent": "claude"}
        writer.write_session_node(props=props, turn_index=3, started_at="2026-01-01T00:00:00+00:00")

        call_kwargs = mock_session.run.call_args[1]
        assert call_kwargs.get("turn_index") == 3


class TestWriteHasTurnRelationship:
    """Tests for GraphWriter.write_has_turn_relationship()."""

    def test_write_has_turn_relationship_cypher(self):
        """write_has_turn_relationship writes :HAS_TURN relationship with order property."""
        writer, _, mock_session = _make_writer()
        writer.write_has_turn_relationship(
            session_id="sess-abc",
            turn_source_key="chat_mcp",
            turn_content_hash="deadbeef",
            order=0,
        )
        assert mock_session.run.called
        cypher = mock_session.run.call_args[0][0]
        assert ":HAS_TURN" in cypher
        assert "order: $order" in cypher

    def test_write_has_turn_relationship_matches_session_by_session_id(self):
        """write_has_turn_relationship MATCHes Session by session_id."""
        writer, _, mock_session = _make_writer()
        writer.write_has_turn_relationship(
            session_id="sess-abc",
            turn_source_key="chat_mcp",
            turn_content_hash="deadbeef",
            order=1,
        )
        cypher = mock_session.run.call_args[0][0]
        assert "Memory:Conversation:Session" in cypher
        assert "session_id: $session_id" in cypher

    def test_write_has_turn_relationship_matches_turn_by_composite_key(self):
        """write_has_turn_relationship MATCHes Turn by (source_key, content_hash)."""
        writer, _, mock_session = _make_writer()
        writer.write_has_turn_relationship(
            session_id="sess-abc",
            turn_source_key="chat_mcp",
            turn_content_hash="deadbeef",
            order=1,
        )
        cypher = mock_session.run.call_args[0][0]
        assert "source_key: $source_key" in cypher
        assert "content_hash: $content_hash" in cypher


class TestWritePartOfTurnRelationship:
    """Tests for GraphWriter.write_part_of_turn_relationship()."""

    def test_write_part_of_turn_relationship_cypher(self):
        """write_part_of_turn_relationship writes PART_OF from Turn to Session."""
        writer, _, mock_session = _make_writer()
        writer.write_part_of_turn_relationship(
            turn_source_key="chat_mcp",
            turn_content_hash="deadbeef",
            session_id="sess-abc",
        )
        assert mock_session.run.called
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE (t)-[:PART_OF]->(s)" in cypher

    def test_write_part_of_turn_relationship_matches_session_by_session_id(self):
        """write_part_of_turn_relationship MATCHes Session node by session_id."""
        writer, _, mock_session = _make_writer()
        writer.write_part_of_turn_relationship(
            turn_source_key="chat_cli",
            turn_content_hash="cafebabe",
            session_id="sess-xyz",
        )
        cypher = mock_session.run.call_args[0][0]
        assert "Memory:Conversation:Session" in cypher
        assert "session_id: $session_id" in cypher

    def test_write_part_of_turn_matches_turn_by_composite_key(self):
        """write_part_of_turn_relationship MATCHes Turn by (source_key, content_hash)."""
        writer, _, mock_session = _make_writer()
        writer.write_part_of_turn_relationship(
            turn_source_key="chat_cli",
            turn_content_hash="cafebabe",
            session_id="sess-xyz",
        )
        cypher = mock_session.run.call_args[0][0]
        assert "source_key: $source_key" in cypher
        assert "content_hash: $content_hash" in cypher


class TestGraphWriterExistingMethodsUnchanged:
    """Regression tests — existing GraphWriter methods still work after new methods added."""

    def test_write_memory_node_still_works(self):
        """write_memory_node is not broken by new methods."""
        writer, _, mock_session = _make_writer()
        props = {
            "source_key": "chat_mcp",
            "content_hash": "abc123",
            "session_id": "sess-1",
            "source_type": "conversation",
            "ingested_at": "2026-01-01T00:00:00+00:00",
            "ingestion_mode": "active",
            "embedding_model": "gemini-embedding-2-preview",
            "project_id": "proj-1",
            "entities": [],
            "entity_types": [],
            "embedding": [0.1] * 768,
            "content": "Hello world",
        }
        writer.write_memory_node(["Memory", "Conversation", "Turn"], props)
        cypher = mock_session.run.call_args[0][0]
        assert "MERGE" in cypher.upper()

    def test_write_relationship_still_works(self):
        """write_relationship is not broken by new methods."""
        writer, _, mock_session = _make_writer()
        writer.write_relationship("chat_mcp", "abc123", "agentic-memory", "project", "ABOUT")
        cypher = mock_session.run.call_args[0][0]
        assert "ABOUT" in cypher
