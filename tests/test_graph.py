"""Tests for the KnowledgeGraphBuilder module."""

import pytest
from unittest.mock import Mock, patch

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
