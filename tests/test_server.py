"""Tests for the MCP server and tools."""

import asyncio

import pytest
from unittest.mock import Mock, patch


def _mcp_call(fn, /, **kwargs):
    """Invoke FastMCP tool (async after ``log_tool_call``) from synchronous tests."""
    return asyncio.run(fn(**kwargs))


pytestmark = [pytest.mark.unit]


class TestToolkit:
    """Test suite for the Toolkit class."""

    @pytest.fixture
    def mock_graph(self):
        """Create a mock graph builder."""
        graph = Mock()
        graph.repo_id = None
        return graph

    @pytest.fixture
    def toolkit(self, mock_graph):
        """Create a Toolkit with mocked graph."""
        from agentic_memory.server.tools import Toolkit
        return Toolkit(graph=mock_graph)

    def test_semantic_search(self, toolkit, mock_graph):
        """Test semantic search returns formatted results."""
        mock_results = [
            {
                "text": "def test(): pass",
                "score": 0.95,
                "name": "test",
                "sig": "test.py:test",
                "path": "test.py",
            }
        ]
        mock_graph.semantic_search.return_value = mock_results

        result = toolkit.semantic_search("test function")

        assert "test" in result
        assert "0.95" in result
        assert "Retrieval policy" in result
        assert "CALLS used for ranking" in result
        mock_graph.semantic_search.assert_called_once_with("test function", limit=5)

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


class TestTraceExecutionTool:
    """Test the MCP JIT trace tool."""

    def test_trace_execution_path_success(self):
        """Trace tool should format a resolved JIT trace result."""
        mock_graph = Mock()
        mock_service = Mock()
        mock_service.trace_execution_path.return_value = {
            "status": "resolved",
            "root": {"signature": "src/a.py:foo"},
            "max_depth": 2,
            "cache_hits": 1,
            "cache_misses": 0,
            "traces": [
                {
                    "depth": 1,
                    "root_signature": "src/a.py:foo",
                    "cache_hit": True,
                    "edges": [
                        {
                            "edge_type": "direct_call",
                            "callee_signature": "src/b.py:bar",
                            "confidence": 0.95,
                            "evidence": "bar()",
                        }
                    ],
                    "unresolved": [],
                }
            ],
        }

        with patch("agentic_memory.server.app.graph", mock_graph):
            with patch("agentic_memory.server.app.TraceExecutionService", return_value=mock_service):
                from agentic_memory.server.app import trace_execution_path

                result = _mcp_call(trace_execution_path, start_symbol="src/a.py:foo", max_depth=2)

                assert "Trace Execution" in result
                assert "src/b.py:bar" in result
                mock_service.trace_execution_path.assert_called_once_with(
                    start_symbol="src/a.py:foo",
                    repo_id=None,
                    max_depth=2,
                    force_refresh=False,
                )

    def test_trace_execution_path_ambiguity(self):
        """Trace tool should surface ambiguous symbol candidates instead of guessing."""
        mock_graph = Mock()
        mock_service = Mock()
        mock_service.trace_execution_path.return_value = {
            "status": "ambiguous",
            "candidates": [
                {
                    "signature": "src/a.py:run",
                    "path": "src/a.py",
                    "qualified_name": "run",
                }
            ],
        }

        with patch("agentic_memory.server.app.graph", mock_graph):
            with patch("agentic_memory.server.app.TraceExecutionService", return_value=mock_service):
                from agentic_memory.server.app import trace_execution_path

                result = _mcp_call(trace_execution_path, start_symbol="run")

                assert "ambiguous" in result.lower()
                assert "src/a.py:run" in result


class TestMCPServerTools:
    """Test MCP server tool decorators and setup."""

    def test_mcp_initialization(self):
        """Test that MCP server can be initialized."""
        from agentic_memory.server.app import mcp, graph
        
        assert mcp is not None
        assert graph is None

    def test_tool_registration(self):
        """Test that all tools are registered."""
        # This would test that the @mcp.tool() decorator was applied
        # In a real test, we'd inspect the mcp object's tools
        pass

    def test_public_tool_registration_matches_frozen_contract(self):
        """The public MCP surface exposes the frozen tool list with annotations."""

        from am_server.mcp_profiles import PUBLIC_MCP_TOOL_NAMES, public_tool_annotations
        from agentic_memory.server.public_mcp import public_mcp

        tools = asyncio.run(public_mcp.list_tools())

        assert tuple(tool.name for tool in tools) == PUBLIC_MCP_TOOL_NAMES
        for tool in tools:
            assert tool.annotations is not None
            assert tool.annotations.model_dump(exclude_none=True) == public_tool_annotations(
                tool.name
            ).model_dump(exclude_none=True)

    def test_search_all_memory_formats_unified_results(self, monkeypatch):
        """search_all_memory formats normalized service output for MCP callers."""
        from agentic_memory.server import app as app_module

        monkeypatch.setattr(
            app_module,
            "search_all_memory_sync",
            lambda **kwargs: Mock(
                to_dict=lambda: {
                    "results": [
                        {
                            "module": "web",
                            "source_kind": "research_finding",
                            "source_id": "finding:1",
                            "title": "Research Hit",
                            "excerpt": "research excerpt",
                            "score": 0.9,
                            "temporal_applied": True,
                        }
                    ],
                    "errors": [],
                }
            ),
        )
        monkeypatch.setattr(app_module, "get_graph", lambda: Mock())
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: Mock())
        monkeypatch.setattr(app_module, "_get_mcp_conversation_pipeline", lambda: Mock())

        result = _mcp_call(
            app_module.search_all_memory,
            query="neo4j",
            limit=5,
            project_id="proj1",
        )

        assert "Research Hit" in result
        assert "[web temporal]" in result


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
        from agentic_memory.server.app import identify_impact
        
        with patch('agentic_memory.server.app.graph', mock_graph):
            result = _mcp_call(identify_impact, file_path="file.py", max_depth=3)
            
            assert isinstance(result, str)
            mock_graph.identify_impact.assert_called_once_with("file.py", max_depth=3)

    def test_identify_impact_not_found(self, mock_graph):
        """Test impact analysis for non-existent file."""
        mock_graph.identify_impact.return_value = {"affected_files": [], "total_count": 0}

        from agentic_memory.server.app import identify_impact
        with patch('agentic_memory.server.app.graph', mock_graph):
            result = _mcp_call(identify_impact, file_path="nonexistent.py")
            
            assert "isolated" in result.lower() or "no files depend" in result.lower()

    def test_identify_impact_error(self, mock_graph):
        """Test impact analysis error handling."""
        mock_graph.identify_impact.side_effect = Exception("Graph error")

        from agentic_memory.server.app import identify_impact
        with patch('agentic_memory.server.app.graph', mock_graph):
            result = _mcp_call(identify_impact, file_path="file.py")
            
            assert "failed" in result.lower()


class TestSearchCodebase:
    """Test the search_codebase tool."""

    def test_search_codebase_success(self):
        """Test successful search."""
        mock_graph = Mock()
        mock_graph.repo_id = None
        fake_rows = [
            {
                "name": "fn",
                "score": 0.9,
                "text": "def fn(): pass",
                "sig": "a.py:fn",
                "path": "a.py",
                "labels": ["Function"],
                "retrieval_provenance": {
                    "policy": "safe",
                    "mode": "semantic_only",
                    "graph_reranking_applied": False,
                    "graph_edge_types_used": [],
                },
            }
        ]

        with (
            patch("agentic_memory.server.app.graph", mock_graph),
            patch("agentic_memory.server.app.search_code", return_value=fake_rows) as mock_search,
        ):
            from agentic_memory.server.app import search_codebase

            result = _mcp_call(search_codebase, query="test query", limit=10)

            assert "Found 1 relevant code result(s)" in result
            assert "Policy: `safe`" in result
            assert "`CALLS` edges used for ranking: `False`" in result
            mock_search.assert_called_once_with(
                mock_graph,
                query="test query",
                limit=10,
                repo_id=None,
                retrieval_policy="safe",
            )

    def test_search_codebase_uses_graph_repo_scope_when_repo_not_explicit(self):
        """Code search should inherit the active graph repo when repo_id is omitted."""
        mock_graph = Mock()
        mock_graph.repo_id = "repo-alpha"

        with (
            patch("agentic_memory.server.app.graph", mock_graph),
            patch("agentic_memory.server.app.search_code", return_value=[]) as mock_search,
        ):
            from agentic_memory.server.app import search_codebase

            _mcp_call(search_codebase, query="test query", limit=3)

            mock_search.assert_called_once_with(
                mock_graph,
                query="test query",
                limit=3,
                repo_id="repo-alpha",
                retrieval_policy="safe",
            )

    def test_search_codebase_error(self):
        """Test search error handling."""
        mock_graph = Mock()
        mock_graph.semantic_search.side_effect = Exception("Search failed")

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import search_codebase

            result = _mcp_call(search_codebase, query="test")
            assert "failed" in result.lower()

    def test_search_codebase_invalid_domain(self):
        """Test invalid domain validation for search routing."""
        from agentic_memory.server.app import search_codebase

        result = _mcp_call(search_codebase, query="test query", domain="invalid-domain")

        assert "invalid domain" in result.lower()
        assert "code|git|hybrid" in result

    def test_search_codebase_invalid_retrieval_policy(self):
        """Test code-domain retrieval policy validation."""
        mock_graph = Mock()

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import search_codebase

            result = _mcp_call(
                search_codebase, query="test query", retrieval_policy="calls-everywhere"
            )

            assert "invalid retrieval_policy" in result.lower()
            mock_graph.semantic_search.assert_not_called()

    def test_search_codebase_git_domain_requires_git_data(self):
        """Test git domain returns explicit error when git graph data is missing."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = False

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import search_codebase

            result = _mcp_call(search_codebase, query="src/main.py", domain="git")

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

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import search_codebase

            result = _mcp_call(search_codebase, query="src/main.py", domain="git", limit=3)

            assert "git history" in result.lower()
            assert "abcdef123456" in result
            mock_graph.get_git_file_history.assert_called_once_with("src/main.py", limit=3)

    def test_search_codebase_hybrid_domain_requires_git_data(self):
        """Test hybrid domain validation requires git graph data."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = False

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import search_codebase

            result = _mcp_call(search_codebase, query="test query", domain="hybrid")

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

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import get_git_file_history

            result = _mcp_call(
                get_git_file_history, file_path="src/codememory/server/app.py", limit=5
            )

            assert "Git History" in result
            assert "abcdef123456" in result
            mock_graph.get_git_file_history.assert_called_once_with(
                "src/codememory/server/app.py", limit=5
            )

    def test_get_git_file_history_missing_git_data(self):
        """Test missing git graph data is reported cleanly."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = False

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import get_git_file_history

            result = _mcp_call(get_git_file_history, file_path="src/codememory/server/app.py")

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

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import get_commit_context

            result = _mcp_call(
                get_commit_context, sha="abcdef1234567890", include_diff_stats=True
            )

            assert "Commit `abcdef1234567890`" in result
            assert "Diff Stats" in result
            mock_graph.get_commit_context.assert_called_once_with(
                "abcdef1234567890", include_diff_stats=True
            )

    def test_get_commit_context_missing_git_data(self):
        """Test commit context handles missing git graph data."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = False

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import get_commit_context

            result = _mcp_call(get_commit_context, sha="abcdef1234567890")

            assert "git graph data not found" in result.lower()
            mock_graph.get_commit_context.assert_not_called()

    def test_get_commit_context_invalid_sha(self):
        """Test commit context validates SHA format."""
        mock_graph = Mock()
        mock_graph.has_git_graph_data.return_value = True

        with patch("agentic_memory.server.app.graph", mock_graph):
            from agentic_memory.server.app import get_commit_context

            result = _mcp_call(get_commit_context, sha="not-a-sha")

            assert "invalid commit sha" in result.lower()
            mock_graph.get_commit_context.assert_not_called()


class TestTemporalSeedHelpers:
    """Tests for shared temporal seed-discovery helpers."""

    def test_collect_seed_entities_ranks_deterministically(self):
        """Entity seed collection combines row scores and preserves deterministic ordering."""
        from agentic_memory.temporal.seeds import collect_seed_entities

        rows = [
            {
                "entities": ["Neo4j", "Agentic Memory"],
                "entity_types": ["technology", "project"],
                "score": 0.9,
            },
            {
                "entities": ["Neo4j"],
                "entity_types": ["technology"],
                "score": 0.8,
            },
        ]

        seeds = collect_seed_entities(rows, limit=2)

        assert seeds[0]["name"] == "Neo4j"
        assert seeds[0]["kind"] == "technology"
        assert len(seeds) == 2

    def test_collect_seed_entities_empty_rows(self):
        """Empty search rows return no seed entities."""
        from agentic_memory.temporal.seeds import collect_seed_entities

        assert collect_seed_entities([], limit=5) == []

    def test_parse_as_of_to_micros_invalid_returns_none(self):
        """Invalid as_of strings do not crash temporal retrieval setup."""
        from agentic_memory.temporal.seeds import parse_as_of_to_micros

        assert parse_as_of_to_micros("definitely-not-a-date") is None

    def test_parse_conversation_source_id(self):
        """Conversation source ids parse into session and turn index."""
        from agentic_memory.temporal.seeds import parse_conversation_source_id

        session_id, turn_index = parse_conversation_source_id("sess-1:4")

        assert session_id == "sess-1"
        assert turn_index == 4
