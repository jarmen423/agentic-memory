"""Tests for the MCP server and tools."""

import pytest
from unittest.mock import Mock, patch

pytestmark = [pytest.mark.unit]


class TestToolkit:
    """Test suite for the Toolkit class."""

    @pytest.fixture
    def mock_graph(self):
        """Create a mock graph builder."""
        return Mock()

    @pytest.fixture
    def toolkit(self, mock_graph):
        """Create a Toolkit with mocked graph."""
        from codememory.server.tools import Toolkit
        return Toolkit(graph=mock_graph)

    def test_semantic_search(self, toolkit, mock_graph):
        """Test semantic search returns formatted results."""
        mock_results = [
            {
                "text": "def test(): pass",
                "score": 0.95,
                "name": "test",
                "sig": "test.py:test",
            }
        ]
        mock_graph.semantic_search.return_value = mock_results

        result = toolkit.semantic_search("test function")

        assert "test" in result
        assert "0.95" in result
        mock_graph.semantic_search.assert_called_once_with("test function", 5)

    def test_semantic_search_empty_results(self, toolkit, mock_graph):
        """Test semantic search with no results."""
        mock_graph.semantic_search.return_value = []

        result = toolkit.semantic_search("nonexistent")

        assert "No relevant code found in the graph." == result

    def test_get_file_dependencies_found(self, toolkit, mock_graph):
        """Test getting dependencies for existing file."""
        mock_imports = [{"target_path": "other.py"}]
        mock_dependents = [{"source_path": "caller.py"}]
        
        mock_graph.driver.session.return_value.__enter__ = Mock(
            return_value=Mock(run=Mock(return_value=Mock(
                single=Mock(return_value={"imports": mock_imports, "dependents": mock_dependents})
            )))
        )
        mock_graph.driver.session.return_value.__exit__ = Mock(return_value=False)

        result = toolkit.get_file_dependencies("test.py")

        assert isinstance(result, str)

    def test_get_file_dependencies_not_found(self, toolkit, mock_graph):
        """Test getting dependencies for non-existent file."""
        mock_graph.driver.session.return_value.__enter__ = Mock(
            return_value=Mock(run=Mock(return_value=Mock(
                single=Mock(return_value=None)
            )))
        )
        mock_graph.driver.session.return_value.__exit__ = Mock(return_value=False)

        result = toolkit.get_file_dependencies("nonexistent.py")

        assert "Dependency Report" in result


class TestMCPServerTools:
    """Test MCP server tool decorators and setup."""

    def test_mcp_initialization(self):
        """Test that MCP server can be initialized."""
        from codememory.server.app import mcp, graph
        
        assert mcp is not None
        assert graph is not None

    def test_tool_registration(self):
        """Test that all tools are registered."""
        # This would test that the @mcp.tool() decorator was applied
        # In a real test, we'd inspect the mcp object's tools
        pass


class TestIdentifyImpact:
    """Test the identify_impact tool."""

    @pytest.fixture
    def mock_graph(self):
        """Create mock graph with impact analysis."""
        graph = Mock()
        graph.identify_impact.return_value = {
            "affected_files": [{"path": "caller.py", "depth": 1, "impact_type": "dependents"}],
            "total_count": 1,
        }
        return graph

    def test_identify_impact_basic(self, mock_graph):
        """Test basic impact analysis."""
        from codememory.server.app import identify_impact
        
        with patch('codememory.server.app.graph', mock_graph):
            result = identify_impact("file.py", max_depth=3)
            
            assert isinstance(result, str)
            mock_graph.identify_impact.assert_called_once_with("file.py", max_depth=3)

    def test_identify_impact_not_found(self, mock_graph):
        """Test impact analysis for non-existent file."""
        mock_graph.identify_impact.return_value = {"affected_files": [], "total_count": 0}
        
        with patch('codememory.server.app.graph', mock_graph):
            result = identify_impact("nonexistent.py")
            
            assert "no impact" in result.lower() or "not found" in result.lower()

    def test_identify_impact_error(self, mock_graph):
        """Test impact analysis error handling."""
        mock_graph.identify_impact.side_effect = Exception("Graph error")
        
        with patch('codememory.server.app.graph', mock_graph):
            result = identify_impact("file.py")
            
            assert "error" in result.lower()


class TestSearchCodebase:
    """Test the search_codebase tool."""

    @pytest.fixture
    def mock_toolkit(self):
        """Create mock toolkit."""
        return Mock()

    def test_search_codebase_success(self, mock_toolkit):
        """Test successful search."""
        mock_graph = Mock()
        mock_graph.semantic_search.return_value = [
            {"name": "fn", "score": 0.9, "text": "def fn(): pass", "sig": "a.py:fn"}
        ]

        with patch('codememory.server.app.graph', mock_graph):
            from codememory.server.app import search_codebase
            result = search_codebase("test query", limit=10)

            assert "Found 1 relevant code result(s)" in result
            mock_graph.semantic_search.assert_called_once_with("test query", limit=10)

    def test_search_codebase_error(self, mock_toolkit):
        """Test search error handling."""
        mock_graph = Mock()
        mock_graph.semantic_search.side_effect = Exception("Search failed")

        with patch('codememory.server.app.graph', mock_graph):
            from codememory.server.app import search_codebase
            with pytest.raises(Exception, match="Search failed"):
                search_codebase("test")
