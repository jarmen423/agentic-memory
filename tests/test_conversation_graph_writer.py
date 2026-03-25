"""Unit tests for Phase 4 GraphWriter conversation extensions.

Tests cover:
- write_session_node: MERGE on session_id, ON CREATE / ON MATCH branches
- write_has_turn_relationship: HAS_TURN with order property
- write_part_of_turn_relationship: PART_OF Turn -> Session

All tests mock Neo4j connections — no live services required.
"""

import pytest
from unittest.mock import MagicMock

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
        assert "MERGE (t)-[rel:PART_OF]->(s)" in cypher

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


class TestTemporalRelationships:
    """Tests for the temporal relationship GraphWriter helpers."""

    def test_write_temporal_relationship_sets_temporal_fields(self):
        """write_temporal_relationship writes temporal fields on create."""
        writer, _, mock_session = _make_writer()

        writer.write_temporal_relationship(
            source_key="chat_mcp",
            content_hash="abc123",
            entity_name="agentic-memory",
            entity_type="project",
            rel_type="ABOUT",
            valid_from="2026-03-25T12:00:00+00:00",
            valid_to=None,
            confidence=0.9,
            support_count=1,
            contradiction_count=0,
        )

        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]

        assert "MERGE (m)-[r:ABOUT]->(e)" in cypher
        assert "ON CREATE SET r.valid_from = $valid_from" in cypher
        assert "r.valid_to = $valid_to" in cypher
        assert "r.confidence = $confidence" in cypher
        assert "r.support_count = $support_count" in cypher
        assert "r.contradiction_count = $contradiction_count" in cypher
        assert params["valid_from"] == "2026-03-25T12:00:00+00:00"
        assert params["confidence"] == 0.9

    def test_write_temporal_relationship_updates_support_and_confidence_on_match(self):
        """write_temporal_relationship increments support_count and keeps max confidence."""
        writer, _, mock_session = _make_writer()

        writer.write_temporal_relationship(
            source_key="chat_mcp",
            content_hash="abc123",
            entity_name="agentic-memory",
            entity_type="project",
            rel_type="ABOUT",
            valid_from="2026-03-25T12:00:00+00:00",
            confidence=0.8,
        )

        cypher = mock_session.run.call_args[0][0]
        assert "ON MATCH SET" in cypher
        assert "r.support_count = r.support_count + 1" in cypher
        assert "CASE WHEN $confidence > r.confidence" in cypher

    def test_write_temporal_relationship_merge_excludes_temporal_fields(self):
        """write_temporal_relationship MERGEs only on relationship type and endpoints."""
        writer, _, mock_session = _make_writer()

        writer.write_temporal_relationship(
            source_key="chat_mcp",
            content_hash="abc123",
            entity_name="agentic-memory",
            entity_type="project",
            rel_type="ABOUT",
            valid_from="2026-03-25T12:00:00+00:00",
        )

        cypher = mock_session.run.call_args[0][0]
        merge_line = next(line for line in cypher.splitlines() if line.startswith("MERGE"))
        assert merge_line == "MERGE (m)-[r:ABOUT]->(e)"
        assert "valid_from" not in merge_line

    def test_update_relationship_validity_sets_valid_to(self):
        """update_relationship_validity sets valid_to on an existing relationship."""
        writer, _, mock_session = _make_writer()

        writer.update_relationship_validity(
            source_key="chat_mcp",
            content_hash="abc123",
            entity_name="agentic-memory",
            entity_type="project",
            rel_type="ABOUT",
            valid_to="2026-03-26T12:00:00+00:00",
        )

        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "MATCH (m)-[r:ABOUT]->(e)" in cypher
        assert "SET r.valid_to = $valid_to" in cypher
        assert params["valid_to"] == "2026-03-26T12:00:00+00:00"

    def test_increment_contradiction_updates_counter_only(self):
        """increment_contradiction increments contradiction_count without touching valid_to."""
        writer, _, mock_session = _make_writer()

        writer.increment_contradiction(
            source_key="chat_mcp",
            content_hash="abc123",
            entity_name="agentic-memory",
            entity_type="project",
            rel_type="ABOUT",
        )

        cypher = mock_session.run.call_args[0][0]
        assert "MATCH (m)-[r:ABOUT]->(e)" in cypher
        assert "contradiction_count" in cypher
        assert "valid_to" not in cypher


class TestDedicatedRelationshipTemporalParameters:
    """Tests for temporal kwargs on dedicated relationship write methods."""

    def test_write_has_chunk_relationship_accepts_temporal_kwargs(self):
        """write_has_chunk_relationship adds temporal properties and support tracking."""
        writer, _, mock_session = _make_writer()

        writer.write_has_chunk_relationship(
            report_project_id="proj-1",
            report_session_id="sess-1",
            chunk_source_key="web_crawl4ai",
            chunk_content_hash="chunk-1",
            order=0,
            valid_from="2026-03-25T12:00:00+00:00",
            confidence=0.7,
        )

        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "ON CREATE SET" in cypher
        assert "rel.valid_from = $valid_from" in cypher
        assert "rel.confidence = $confidence" in cypher
        assert "rel.support_count = rel.support_count + 1" in cypher
        assert params["confidence"] == 0.7

    def test_write_part_of_relationship_accepts_temporal_kwargs(self):
        """write_part_of_relationship adds temporal properties and support tracking."""
        writer, _, mock_session = _make_writer()

        writer.write_part_of_relationship(
            chunk_source_key="web_crawl4ai",
            chunk_content_hash="chunk-1",
            report_project_id="proj-1",
            report_session_id="sess-1",
            valid_from="2026-03-25T12:00:00+00:00",
            confidence=0.7,
        )

        cypher = mock_session.run.call_args[0][0]
        assert "ON CREATE SET" in cypher
        assert "rel.valid_from = $valid_from" in cypher
        assert "rel.support_count = rel.support_count + 1" in cypher

    def test_write_cites_relationship_accepts_temporal_kwargs(self):
        """write_cites_relationship adds temporal properties and support tracking."""
        writer, _, mock_session = _make_writer()

        writer.write_cites_relationship(
            finding_source_key="deep_research_agent",
            finding_content_hash="finding-1",
            source_url="https://example.com",
            rel_props={
                "url": "https://example.com",
                "title": "Example",
                "snippet": "snippet",
                "accessed_at": "2026-03-25T12:00:00+00:00",
                "source_agent": "claude",
            },
            valid_from="2026-03-25T12:00:00+00:00",
            confidence=0.7,
        )

        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "ON CREATE SET r += $rel_props" in cypher
        assert "r.support_count = r.support_count + 1" in cypher
        assert params["rel_props"]["valid_from"] == "2026-03-25T12:00:00+00:00"
        assert params["rel_props"]["confidence"] == 0.7

    def test_write_has_turn_relationship_accepts_generated_valid_from(self):
        """write_has_turn_relationship generates valid_from when omitted."""
        writer, _, mock_session = _make_writer()

        writer.write_has_turn_relationship(
            session_id="sess-abc",
            turn_source_key="chat_mcp",
            turn_content_hash="turn-1",
            order=2,
        )

        params = mock_session.run.call_args[1]
        cypher = mock_session.run.call_args[0][0]
        assert isinstance(params["valid_from"], str)
        assert "rel.valid_from = $valid_from" in cypher
        assert "rel.support_count = rel.support_count + 1" in cypher

    def test_write_part_of_turn_relationship_accepts_temporal_kwargs(self):
        """write_part_of_turn_relationship adds temporal properties and support tracking."""
        writer, _, mock_session = _make_writer()

        writer.write_part_of_turn_relationship(
            turn_source_key="chat_mcp",
            turn_content_hash="turn-1",
            session_id="sess-abc",
            valid_from="2026-03-25T12:00:00+00:00",
            confidence=0.6,
        )

        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "ON CREATE SET" in cypher
        assert "rel.valid_from = $valid_from" in cypher
        assert "rel.support_count = rel.support_count + 1" in cypher
        assert params["confidence"] == 0.6


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
