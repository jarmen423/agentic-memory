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
        mock_graph.get_file_dependencies.return_value = {
            "imports": ["other.py"],
            "imported_by": ["caller.py"],
        }

        result = toolkit.get_file_dependencies("test.py")

        assert isinstance(result, str)
        assert "other.py" in result
        assert "caller.py" in result

    def test_get_file_dependencies_not_found(self, toolkit, mock_graph):
        """Test getting dependencies for non-existent file."""
        mock_graph.get_file_dependencies.return_value = {"imports": [], "imported_by": []}

        result = toolkit.get_file_dependencies("nonexistent.py")

        assert "Dependency Report" in result

    def test_get_git_file_history(self, toolkit, mock_graph):
        """Test toolkit git history formatting."""
        mock_graph.has_git_graph_data.return_value = True
        mock_graph.get_git_file_history.return_value = [
            {"sha": "abcdef123456", "message_subject": "Update file history"}
        ]

        result = toolkit.get_git_file_history("src/main.py")

        assert "abcdef123456"[:12] in result
        assert "Update file history" in result
        mock_graph.get_git_file_history.assert_called_once_with("src/main.py", limit=20)

    def test_get_commit_context(self, toolkit, mock_graph):
        """Test toolkit commit context formatting."""
        mock_graph.has_git_graph_data.return_value = True
        mock_graph.get_commit_context.return_value = {
            "sha": "abcdef123456",
            "message_subject": "Refactor parser",
            "author_name": "Dev",
            "committed_at": "2026-02-24T10:00:00Z",
            "stats": {"files_changed": 2, "additions": 5, "deletions": 1},
        }

        result = toolkit.get_commit_context("abcdef123456")

        assert "Refactor parser" in result
        assert "Files Changed: 2" in result
        mock_graph.get_commit_context.assert_called_once_with(
            "abcdef123456", include_diff_stats=True
        )


class TestMCPServerTools:
    """Test MCP server tool decorators and setup."""

    def test_mcp_initialization(self):
        """Test that MCP server can be initialized."""
        from codememory.server.app import mcp, graph
        
        assert mcp is not None
        assert graph is None

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

        from codememory.server.app import identify_impact
        with patch('codememory.server.app.graph', mock_graph):
            result = identify_impact("nonexistent.py")
            
            assert "isolated" in result.lower() or "no files depend" in result.lower()

    def test_identify_impact_error(self, mock_graph):
        """Test impact analysis error handling."""
        mock_graph.identify_impact.side_effect = Exception("Graph error")

        from codememory.server.app import identify_impact
        with patch('codememory.server.app.graph', mock_graph):
            result = identify_impact("file.py")
            
            assert "failed" in result.lower()


class TestSearchCodebase:
    """Test the search_codebase tool."""

    def test_search_codebase_success(self):
        """Test successful search."""
        mock_graph = Mock()
        mock_graph.semantic_search.return_value = [
            {"name": "fn", "score": 0.9, "text": "def fn(): pass", "sig": "a.py:fn"}
        ]

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import search_codebase

            result = search_codebase("test query", limit=10)

            assert "Found 1 relevant code result(s)" in result
            mock_graph.semantic_search.assert_called_once_with("test query", limit=10)

    def test_search_codebase_error(self):
        """Test search error handling."""
        mock_graph = Mock()
        mock_graph.semantic_search.side_effect = Exception("Search failed")

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import search_codebase

            result = search_codebase("test")
            assert "failed" in result.lower()

    def test_search_codebase_invalid_domain(self):
        """Test invalid domain validation for search routing."""
        from codememory.server.app import search_codebase

        result = search_codebase("test query", domain="invalid-domain")

        assert "invalid domain" in result.lower()
        assert "code|git|hybrid" in result

    def test_search_codebase_git_domain_requires_git_data(self):
        """Test git domain returns explicit error when git graph data is missing."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = False

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import search_codebase

            result = search_codebase("src/main.py", domain="git")

            assert "git graph data not found" in result.lower()
            mock_graph.get_git_file_history.assert_not_called()

    def test_search_codebase_git_domain_file_history_route(self):
        """Test git domain routing for file path query."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = True
        mock_graph.get_git_file_history.return_value = [
            {
                "sha": "abcdef1234567890",
                "message_subject": "Touch file",
                "committed_at": "2026-02-24T09:00:00Z",
                "author_name": "Dev",
                "change_type": "M",
                "additions": 5,
                "deletions": 2,
            }
        ]

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import search_codebase

            result = search_codebase("src/main.py", domain="git", limit=3)

            assert "git history" in result.lower()
            assert "abcdef123456" in result
            mock_graph.get_git_file_history.assert_called_once_with("src/main.py", limit=3)

    def test_search_codebase_hybrid_domain_requires_git_data(self):
        """Test hybrid domain validation requires git graph data."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = False

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import search_codebase

            result = search_codebase("test query", domain="hybrid")

            assert "git graph data not found" in result.lower()
            mock_graph.semantic_search.assert_not_called()


class TestGitMCPTools:
    """Test git-specific MCP tools."""

    def test_get_git_file_history_success(self):
        """Test git file history tool success path."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = True
        mock_graph.get_git_file_history.return_value = [
            {
                "sha": "abcdef1234567890",
                "message_subject": "Add parser support",
                "committed_at": "2026-02-24T12:00:00Z",
                "author_name": "Dev",
                "change_type": "M",
                "additions": 10,
                "deletions": 3,
            }
        ]

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import get_git_file_history

            result = get_git_file_history("src/codememory/server/app.py", limit=5)

            assert "Git History" in result
            assert "abcdef123456" in result
            mock_graph.get_git_file_history.assert_called_once_with(
                "src/codememory/server/app.py", limit=5
            )

    def test_get_git_file_history_missing_git_data(self):
        """Test missing git graph data is reported cleanly."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = False

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import get_git_file_history

            result = get_git_file_history("src/codememory/server/app.py")

            assert "git graph data not found" in result.lower()
            mock_graph.get_git_file_history.assert_not_called()

    def test_get_commit_context_success(self):
        """Test commit context tool success path."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = True
        mock_graph.get_commit_context.return_value = {
            "sha": "abcdef1234567890",
            "message_subject": "Refactor MCP tools",
            "message_body": "Move formatting helpers and add routing",
            "author_name": "Dev",
            "author_email": "dev@example.com",
            "authored_at": "2026-02-24T12:00:00Z",
            "committed_at": "2026-02-24T12:05:00Z",
            "is_merge": False,
            "parent_shas": ["1111111"],
            "pull_requests": [],
            "issues": [],
            "files": [{"path": "src/codememory/server/app.py", "change_type": "M"}],
            "stats": {"files_changed": 1, "additions": 20, "deletions": 5},
        }

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import get_commit_context

            result = get_commit_context("abcdef1234567890", include_diff_stats=True)

            assert "Commit `abcdef1234567890`" in result
            assert "Diff Stats" in result
            mock_graph.get_commit_context.assert_called_once_with(
                "abcdef1234567890", include_diff_stats=True
            )

    def test_get_commit_context_missing_git_data(self):
        """Test commit context handles missing git graph data."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = False

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import get_commit_context

            result = get_commit_context("abcdef1234567890")

            assert "git graph data not found" in result.lower()
            mock_graph.get_commit_context.assert_not_called()

    def test_get_commit_context_invalid_sha(self):
        """Test commit context validates SHA format."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = True

        with patch("codememory.server.app.graph", mock_graph):
            from codememory.server.app import get_commit_context

            result = get_commit_context("not-a-sha")

            assert "invalid commit sha" in result.lower()
            mock_graph.get_commit_context.assert_not_called()
