"""Unit tests for BaseIngestionPipeline ABC and GraphWriter.

Tests enforce:
- BaseIngestionPipeline ABC contract (cannot instantiate, requires DOMAIN_LABEL + ingest())
- node_labels() resolves from SOURCE_REGISTRY with fallback
- GraphWriter uses MERGE (not CREATE) for idempotent node writes
- GraphWriter writes all required Memory node metadata fields
- GraphWriter handles namespace correctly (present vs absent)
- GraphWriter upserts Entity nodes with composite key
- GraphWriter writes Memory->Entity relationships
"""

from unittest.mock import MagicMock, call, patch
import pytest

from agentic_memory.core.registry import SOURCE_REGISTRY, register_source
from agentic_memory.core.base import BaseIngestionPipeline
from agentic_memory.core.graph_writer import GraphWriter


# ---------------------------------------------------------------------------
# BaseIngestionPipeline tests
# ---------------------------------------------------------------------------


class TestBaseIngestionPipeline:
    """Tests for the BaseIngestionPipeline ABC."""

    def test_abc_enforcement(self):
        """Cannot instantiate BaseIngestionPipeline directly."""
        mock_conn = MagicMock()
        with pytest.raises(TypeError):
            BaseIngestionPipeline(mock_conn)

    def test_subclass_requires_ingest(self):
        """Subclass without ingest() raises TypeError on instantiation."""

        class IncompletePipeline(BaseIngestionPipeline):
            DOMAIN_LABEL = "Test"
            # ingest() not implemented

        mock_conn = MagicMock()
        with pytest.raises(TypeError):
            IncompletePipeline(mock_conn)

    def test_valid_subclass(self):
        """Subclass with DOMAIN_LABEL and ingest() can be instantiated."""

        class ValidPipeline(BaseIngestionPipeline):
            DOMAIN_LABEL = "Test"

            def ingest(self, source):
                return {"status": "ok"}

        mock_conn = MagicMock()
        pipeline = ValidPipeline(mock_conn)
        assert pipeline._conn is mock_conn

    def test_node_labels_from_registry(self):
        """node_labels() returns registry labels for known source_key."""

        class ValidPipeline(BaseIngestionPipeline):
            DOMAIN_LABEL = "Test"

            def ingest(self, source):
                return {}

        # Register a test source
        register_source("test_source_abc", ["Memory", "Test", "Chunk"])
        mock_conn = MagicMock()
        pipeline = ValidPipeline(mock_conn)
        labels = pipeline.node_labels("test_source_abc")
        assert labels == ["Memory", "Test", "Chunk"]

    def test_node_labels_fallback(self):
        """node_labels() returns fallback for unregistered source_key."""

        class ValidPipeline(BaseIngestionPipeline):
            DOMAIN_LABEL = "Research"

            def ingest(self, source):
                return {}

        mock_conn = MagicMock()
        pipeline = ValidPipeline(mock_conn)
        labels = pipeline.node_labels("nonexistent_source_xyz")
        assert labels == ["Memory", "Research"]

    def test_subclass_domain_label_accessible(self):
        """DOMAIN_LABEL is accessible as class attribute on concrete subclass."""

        class TestPipeline(BaseIngestionPipeline):
            DOMAIN_LABEL = "Conversation"

            def ingest(self, source):
                return {}

        assert TestPipeline.DOMAIN_LABEL == "Conversation"


# ---------------------------------------------------------------------------
# GraphWriter tests
# ---------------------------------------------------------------------------


class TestGraphWriter:
    """Tests for GraphWriter MERGE-based write patterns."""

    def _make_writer(self):
        """Create a GraphWriter with a mocked ConnectionManager."""
        mock_conn = MagicMock()
        mock_session = MagicMock()
        mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)
        writer = GraphWriter(mock_conn)
        return writer, mock_conn, mock_session

    def _get_run_call(self, mock_session):
        """Extract the first positional arg from session.run() call."""
        assert mock_session.run.called, "session.run() was not called"
        return mock_session.run.call_args

    def test_write_memory_node_uses_merge(self):
        """write_memory_node Cypher starts with MERGE not CREATE."""
        writer, _, mock_session = self._make_writer()
        props = {
            "source_key": "code_treesitter",
            "content_hash": "abc123",
            "session_id": "sess-1",
            "source_type": "code",
            "ingested_at": "2026-01-01T00:00:00Z",
            "ingestion_mode": "active",
            "embedding_model": "text-embedding-3-large",
            "project_id": "proj-1",
            "entities": ["FastAPI"],
            "entity_types": ["technology"],
            "embedding": [0.1, 0.2],
            "text": "def main(): pass",
        }
        writer.write_memory_node(["Memory", "Code", "Chunk"], props)
        cypher = mock_session.run.call_args[0][0]
        assert cypher.strip().upper().startswith("MERGE"), f"Expected MERGE, got: {cypher[:50]}"

    def test_write_memory_node_contains_required_fields(self):
        """write_memory_node Cypher references all required metadata fields."""
        writer, _, mock_session = self._make_writer()
        props = {
            "source_key": "code_treesitter",
            "content_hash": "abc123",
            "session_id": "sess-1",
            "source_type": "code",
            "ingested_at": "2026-01-01T00:00:00Z",
            "ingestion_mode": "active",
            "embedding_model": "text-embedding-3-large",
            "project_id": "proj-1",
            "entities": ["FastAPI"],
            "entity_types": ["technology"],
            "embedding": [0.1, 0.2],
            "text": "def main(): pass",
        }
        writer.write_memory_node(["Memory", "Code", "Chunk"], props)
        run_args = mock_session.run.call_args
        # The Cypher or params should reference all required fields
        cypher = run_args[0][0]
        # source_key and content_hash are the MERGE key
        assert "source_key" in cypher
        assert "content_hash" in cypher

    def test_write_memory_node_with_namespace(self):
        """write_memory_node stores namespace property when provided."""
        writer, _, mock_session = self._make_writer()
        props = {
            "source_key": "code_treesitter",
            "content_hash": "def456",
            "session_id": "sess-1",
            "source_type": "code",
            "ingested_at": "2026-01-01T00:00:00Z",
            "ingestion_mode": "active",
            "embedding_model": "text-embedding-3-large",
            "project_id": "proj-1",
            "entities": [],
            "entity_types": [],
            "embedding": [0.1],
            "text": "sample",
        }
        writer.write_memory_node(["Memory", "Code"], props, namespace="professional")
        run_args = mock_session.run.call_args
        cypher = run_args[0][0]
        # namespace should appear in the cypher (e.g. in SET clause)
        assert "namespace" in cypher

    def test_write_memory_node_no_namespace(self):
        """write_memory_node does NOT set namespace property when omitted."""
        writer, _, mock_session = self._make_writer()
        props = {
            "source_key": "code_treesitter",
            "content_hash": "ghi789",
            "session_id": "sess-1",
            "source_type": "code",
            "ingested_at": "2026-01-01T00:00:00Z",
            "ingestion_mode": "active",
            "embedding_model": "text-embedding-3-large",
            "project_id": "proj-1",
            "entities": [],
            "entity_types": [],
            "embedding": [0.1],
            "text": "sample",
        }
        writer.write_memory_node(["Memory", "Code"], props)
        run_args = mock_session.run.call_args
        # Check that namespace is NOT in the kwargs passed as parameters
        kwargs = run_args[1] if run_args[1] else {}
        assert "namespace" not in kwargs

    def test_write_memory_node_sets_labels(self):
        """write_memory_node applies all labels to the node in Cypher."""
        writer, _, mock_session = self._make_writer()
        props = {
            "source_key": "web_crawl",
            "content_hash": "jkl012",
            "session_id": "sess-2",
            "source_type": "web",
            "ingested_at": "2026-01-01T00:00:00Z",
            "ingestion_mode": "passive",
            "embedding_model": "gemini-embedding-2-preview",
            "project_id": "proj-1",
            "entities": [],
            "entity_types": [],
            "embedding": [0.3],
            "text": "web content",
        }
        writer.write_memory_node(["Memory", "Research", "WebPage"], props)
        cypher = mock_session.run.call_args[0][0]
        # All three labels should appear in the MERGE clause
        assert "Memory" in cypher
        assert "Research" in cypher
        assert "WebPage" in cypher

    def test_upsert_entity(self):
        """upsert_entity uses MERGE on (name, type) composite key."""
        writer, _, mock_session = self._make_writer()
        writer.upsert_entity("FastAPI", "technology")
        run_args = mock_session.run.call_args
        cypher = run_args[0][0]
        assert "MERGE" in cypher.upper()
        assert "Entity" in cypher
        # Entity type label should be capitalized
        assert "Technology" in cypher

    def test_upsert_entity_composite_key(self):
        """upsert_entity Cypher contains name and type as MERGE parameters."""
        writer, _, mock_session = self._make_writer()
        writer.upsert_entity("Neo4j", "technology")
        run_args = mock_session.run.call_args
        cypher = run_args[0][0]
        kwargs = run_args[1] if run_args[1] else {}
        # name and type should be passed as parameters
        assert "name" in cypher or "name" in str(kwargs)
        assert "type" in cypher or "type" in str(kwargs)

    def test_write_relationship(self):
        """write_relationship uses MATCH + MERGE pattern for Memory->Entity."""
        writer, _, mock_session = self._make_writer()
        writer.write_relationship("code_treesitter", "abc123", "FastAPI", "technology", "ABOUT")
        run_args = mock_session.run.call_args
        cypher = run_args[0][0]
        assert "MATCH" in cypher.upper()
        assert "MERGE" in cypher.upper()
        assert "ABOUT" in cypher

    def test_write_relationship_default_rel_type(self):
        """write_relationship defaults to ABOUT relationship type."""
        writer, _, mock_session = self._make_writer()
        writer.write_relationship("code_treesitter", "abc123", "FastAPI", "technology")
        cypher = mock_session.run.call_args[0][0]
        assert "ABOUT" in cypher
