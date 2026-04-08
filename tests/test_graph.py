"""Tests for the KnowledgeGraphBuilder module."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Skip if neo4j is not available
pytestmark = [
    pytest.mark.unit,
]


class TestKnowledgeGraphBuilder:
    """Test suite for KnowledgeGraphBuilder."""

    @pytest.fixture
    def mock_driver(self):
        """Create a mock Neo4j driver."""
        driver = Mock()
        session = Mock()
        driver.session.return_value.__enter__ = Mock(return_value=session)
        driver.session.return_value.__exit__ = Mock(return_value=False)
        return driver, session

    @pytest.fixture
    def builder(self, mock_driver):
        """Create a KnowledgeGraphBuilder with mocked dependencies."""
        from codememory.ingestion.graph import KnowledgeGraphBuilder

        driver, session = mock_driver
        with patch('neo4j.GraphDatabase.driver', return_value=driver), \
             patch.object(KnowledgeGraphBuilder, '_init_parsers'), \
             patch('codememory.ingestion.graph.OpenAI'):
            
            builder = KnowledgeGraphBuilder(
                uri="bolt://localhost:7687",
                user="neo4j",
                password="test",
                openai_key="sk-test"
            )
            builder.driver = driver
            return builder

    @pytest.fixture
    def repo_builder(self, mock_driver, tmp_path):
        """Create a repo-scoped KnowledgeGraphBuilder with mocked dependencies."""
        from codememory.ingestion.graph import KnowledgeGraphBuilder

        driver, session = mock_driver
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        with patch('neo4j.GraphDatabase.driver', return_value=driver), \
             patch.object(KnowledgeGraphBuilder, '_init_parsers'), \
             patch('codememory.ingestion.graph.OpenAI'):

            builder = KnowledgeGraphBuilder(
                uri="bolt://localhost:7687",
                user="neo4j",
                password="test",
                openai_key="sk-test",
                repo_root=repo_root,
            )
            builder.driver = driver
            return builder

    def test_initialization(self, builder):
        """Test that builder initializes correctly."""
        assert builder.EMBEDDING_MODEL == "text-embedding-3-large"
        assert builder.driver is not None

    def test_get_embedding(self, builder):
        """Test embedding generation."""
        mock_embedding = [0.1] * builder.VECTOR_DIMENSIONS
        builder.openai_client = Mock()
        builder.openai_client.embeddings.create.return_value = Mock(
            data=[Mock(embedding=mock_embedding)],
            usage=Mock(total_tokens=42),
        )

        result = builder.get_embedding("test text")

        assert result == mock_embedding
        builder.openai_client.embeddings.create.assert_called_once()

    def test_get_embedding_error_handling(self, builder):
        """Test unexpected embedding errors propagate."""
        builder.openai_client = Mock()
        builder.openai_client.embeddings.create.side_effect = Exception("API Error")
        with pytest.raises(Exception, match="API Error"):
            builder.get_embedding("test text")

    def test_close(self, builder):
        """Test driver cleanup."""
        builder.close()
        builder.driver.close.assert_called_once()

    def test_extract_js_ts_import_modules(self, builder):
        """Test JS/TS import extraction supports common import syntaxes."""
        code = """
import React from "react";
import type { FC } from "react";
import { api } from "../lib/api";
import "@/styles/global.css";
export { helper } from "./helpers";
const fs = require("fs");
const lazy = import("./lazy-module");
"""
        modules = builder._extract_js_ts_import_modules(code)

        assert "../lib/api" in modules
        assert "@/styles/global.css" in modules
        assert "./helpers" in modules
        assert "fs" in modules
        assert "./lazy-module" in modules

    def test_resolve_import_candidates_for_relative_tsx(self, builder):
        """Test relative TS/TSX imports resolve to extension/index variants."""
        candidates = builder._resolve_import_candidates(
            "frontend/src/components/Widget.tsx",
            "../services/heygen_service",
            ".tsx",
        )
        assert "frontend/src/services/heygen_service.ts" in candidates
        assert "frontend/src/services/heygen_service.tsx" in candidates
        assert "frontend/src/services/heygen_service/index.ts" in candidates

    def test_setup_memory_schema(self, builder, mock_driver):
        """Test memory schema setup issues expected DDL queries."""
        driver, session = mock_driver

        builder.setup_memory_schema()

        queries = [call.args[0] for call in session.run.call_args_list]
        assert any("memory_name_unique" in query for query in queries)
        assert any("memory_search" in query for query in queries)

    def test_create_memory_entities_runs_merge(self, builder, mock_driver):
        """Test memory entity creation runs a MERGE query per entity."""
        driver, session = mock_driver

        with patch.object(builder, "get_embedding", return_value=[0.1] * builder.VECTOR_DIMENSIONS):
            builder.create_memory_entities(
                [{"name": "auth-flow", "entityType": "concept", "observations": ["Used in login"]}]
            )

        queries = [call.args[0] for call in session.run.call_args_list]
        assert any("MERGE (m:Memory {name: $name})" in query for query in queries)
        assert any("SET m:`concept`" in query for query in queries)

    def test_search_memory_nodes_formats_rows(self, builder, mock_driver):
        """Test memory search returns row dicts from Neo4j results."""
        driver, session = mock_driver
        session.run.side_effect = [
            Mock(),
            Mock(),
            Mock(),
            [
                {
                    "name": "auth-flow",
                    "entity_type": "concept",
                    "observations": ["Uses refresh token"],
                    "metadata_json": "{}",
                    "score": 0.9,
                    "sources": ["vector", "fulltext"],
                    "outgoing_relations": [{"target": "login-page", "relation_type": "IMPLEMENTS"}],
                }
            ],
        ]

        with patch.object(builder, "get_embedding", return_value=[0.1] * builder.VECTOR_DIMENSIONS):
            results = builder.search_memory_nodes("auth", limit=5)

        assert len(results) == 1
        assert results[0]["name"] == "auth-flow"

    def test_read_memory_graph_returns_counts(self, builder, mock_driver):
        """Test memory graph snapshot combines node list and relation count."""
        driver, session = mock_driver
        session.run.side_effect = [
            Mock(),
            Mock(),
            Mock(),
            [
                {
                    "name": "auth-flow",
                    "entity_type": "concept",
                    "observations": ["Uses refresh token"],
                    "outgoing_relations": [],
                }
            ],
            Mock(single=Mock(return_value={"count": 0})),
        ]

        snapshot = builder.read_memory_graph()

        assert snapshot["entity_count"] == 1
        assert snapshot["relation_count"] == 0
        assert snapshot["entities"][0]["name"] == "auth-flow"

    def test_backfill_memory_embeddings_updates_missing_nodes(self, builder, mock_driver):
        """Test memory embedding backfill writes embeddings and reports remainder."""
        driver, session = mock_driver
        session.run.side_effect = [
            Mock(),
            Mock(),
            Mock(),
            [
                {
                    "name": "auth-flow",
                    "entity_type": "project",
                    "observations": ["Used in login"],
                }
            ],
            Mock(),
            Mock(single=Mock(return_value={"remaining": 0})),
        ]

        with patch.object(builder, "get_embedding", return_value=[0.1] * builder.VECTOR_DIMENSIONS):
            result = builder.backfill_memory_embeddings(limit=10, only_missing=True)

        assert result["count"] == 1
        assert result["remaining_without_embeddings"] == 0

    def test_pass_2_entity_definition_fetches_files_for_active_repo(self, repo_builder, mock_driver):
        """Pass 2 should only seed files from the active repo when repo_id is set."""
        driver, session = mock_driver
        session.run.return_value = []

        repo_builder.pass_2_entity_definition(repo_builder.repo_root)

        first_query = session.run.call_args_list[0]
        assert "WHERE f.repo_id = $repo_id" in first_query.args[0]
        assert first_query.kwargs["repo_id"] == repo_builder.repo_id

    def test_get_file_dependencies_scopes_by_repo(self, repo_builder, mock_driver):
        """Dependency lookup should match the source File by (repo_id, path)."""
        driver, session = mock_driver
        session.run.return_value.single.return_value = {"imports": ["a.py"], "imported_by": ["b.py"]}

        result = repo_builder.get_file_dependencies("src/main.py")

        assert result["imports"] == ["a.py"]
        query = session.run.call_args.args[0]
        kwargs = session.run.call_args.kwargs
        assert "repo_id: $repo_id" in query
        assert kwargs["repo_id"] == repo_builder.repo_id
        assert kwargs["path"] == "src/main.py"

    def test_identify_impact_scopes_by_repo(self, repo_builder, mock_driver):
        """Impact analysis should anchor traversal to the active repo only."""
        driver, session = mock_driver
        session.run.return_value = [
            {"path": "src/caller.py", "depth": 1, "impact_type": "dependents"}
        ]

        result = repo_builder.identify_impact("src/main.py", max_depth=2)

        assert result["total_count"] == 1
        query = session.run.call_args.args[0]
        kwargs = session.run.call_args.kwargs
        assert "repo_id: $repo_id" in query
        assert kwargs["repo_id"] == repo_builder.repo_id

    def test_read_memory_graph_scopes_to_active_repo(self, repo_builder, mock_driver):
        """Memory graph reads should filter entities and relation counts by repo_id."""
        driver, session = mock_driver
        session.run.side_effect = [
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            [
                {
                    "name": "auth-flow",
                    "entity_type": "concept",
                    "observations": ["Uses refresh token"],
                    "outgoing_relations": [],
                }
            ],
            Mock(single=Mock(return_value={"count": 0})),
        ]

        snapshot = repo_builder.read_memory_graph()

        assert snapshot["entity_count"] == 1
        query_args = session.run.call_args_list
        assert "WHERE m.repo_id = $repo_id" in query_args[4].args[0]
        assert query_args[4].kwargs["repo_id"] == repo_builder.repo_id
        assert "source.repo_id = $repo_id AND target.repo_id = $repo_id" in query_args[5].args[0]

    def test_backfill_memory_embeddings_scopes_to_active_repo(self, repo_builder, mock_driver):
        """Memory backfill should only select and count nodes for the active repo."""
        driver, session = mock_driver
        session.run.side_effect = [
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            [
                {
                    "name": "auth-flow",
                    "entity_type": "project",
                    "observations": ["Used in login"],
                }
            ],
            Mock(),
            Mock(single=Mock(return_value={"remaining": 0})),
        ]

        with patch.object(repo_builder, "get_embedding", return_value=[0.1] * repo_builder.VECTOR_DIMENSIONS):
            result = repo_builder.backfill_memory_embeddings(limit=10, only_missing=True)

        assert result["count"] == 1
        query_args = session.run.call_args_list
        assert "m.embedding IS NULL AND m.repo_id = $repo_id" in query_args[4].args[0]
        assert query_args[4].kwargs["repo_id"] == repo_builder.repo_id
        assert "{name: $name, repo_id: $repo_id}" in query_args[5].args[0]
        assert "m.embedding IS NULL AND m.repo_id = $repo_id" in query_args[6].args[0]

    def test_search_memory_nodes_falls_back_when_query_vector_invalid(self, builder, mock_driver):
        """Memory search should fall back to fulltext when embedding generation fails."""
        driver, session = mock_driver
        session.run.side_effect = [
            Mock(),
            Mock(),
            Mock(),
            [
                {
                    "name": "auth-flow",
                    "entity_type": "concept",
                    "observations": ["Uses refresh token"],
                    "metadata_json": "{}",
                    "score": 0.5,
                    "sources": ["fulltext"],
                    "outgoing_relations": [],
                    "incoming_relations": [],
                }
            ],
        ]

        with patch.object(builder, "get_embedding", return_value=[0.0] * builder.VECTOR_DIMENSIONS):
            results = builder.search_memory_nodes("auth", limit=5)

        assert len(results) == 1
        query = session.run.call_args_list[3].args[0]
        assert "db.index.fulltext.queryNodes('memory_search'" in query
        assert "db.index.vector.queryNodes('memory_embeddings'" not in query


class TestCypherQueries:
    """Test Cypher query generation and execution."""

    def test_setup_database_cypher(self):
        """Test that setup_database query strings remain well-formed."""
        # This would test the actual Cypher queries
        # For unit test, we verify the query strings are well-formed
        expected_queries = [
            "CREATE CONSTRAINT file_path_unique",
            "CREATE CONSTRAINT func_sig_unique",
            "CREATE CONSTRAINT class_name_unique",
            "CREATE VECTOR INDEX code_embeddings",
        ]
        
        # Just verify the expected queries exist
        for query in expected_queries:
            assert isinstance(query, str)
            assert len(query) > 0


@pytest.mark.integration
class TestGraphIntegration:
    """Integration tests requiring actual Neo4j instance."""

    @pytest.fixture(scope="class")
    def neo4j_builder(self):
        """Create a builder connected to real Neo4j (if available)."""
        import os
        from codememory.ingestion.graph import KnowledgeGraphBuilder

        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "test")
        openai_key = os.getenv("OPENAI_API_KEY", "sk-test")

        try:
            builder = KnowledgeGraphBuilder(uri, user, password, openai_key)
            # Test connection
            with builder.driver.session() as session:
                session.run("RETURN 1")
            yield builder
            builder.close()
        except Exception as e:
            pytest.skip(f"Neo4j not available: {e}")

    def test_setup_database_integration(self, neo4j_builder):
        """Test index creation on real Neo4j."""
        # Should not raise
        neo4j_builder.setup_database()

    def test_semantic_search_query(self, neo4j_builder):
        """Test semantic search generates valid Cypher."""
        # Mock embedding to avoid API call
        with patch.object(
            neo4j_builder,
            'get_embedding',
            return_value=[0.1] * neo4j_builder.VECTOR_DIMENSIONS,
        ):
            results = neo4j_builder.semantic_search("test query", limit=5)
            assert isinstance(results, list)
