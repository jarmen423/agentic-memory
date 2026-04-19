"""Tests for web research MCP tools: memory_ingest_research, search_web_memory, brave_search."""

import os
import json
from unittest.mock import Mock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pipeline():
    """Create a mock ResearchIngestionPipeline."""
    pipeline = Mock()
    pipeline.ingest.return_value = {
        "type": "report",
        "chunks": 2,
        "entities": 1,
        "findings": 0,
        "project_id": "test_project",
        "session_id": "test_session",
    }
    pipeline._embedder = Mock()
    pipeline._embedder.embed.return_value = [0.1] * 768
    pipeline._extractor = Mock()
    pipeline._extractor.extract.return_value = [{"name": "Neo4j", "type": "technology"}]
    pipeline._temporal_bridge = Mock()
    pipeline._temporal_bridge.is_available.return_value = False
    pipeline._conn = Mock()
    return pipeline


def _make_session_results(rows):
    """Return a mock Neo4j session that returns given rows from session.run().data()."""
    mock_run = Mock()
    mock_run.data.return_value = rows
    session_ctx = MagicMock()
    session_ctx.__enter__ = Mock(return_value=Mock(run=Mock(return_value=mock_run)))
    session_ctx.__exit__ = Mock(return_value=False)
    return session_ctx


# ---------------------------------------------------------------------------
# memory_ingest_research tests
# ---------------------------------------------------------------------------


class TestMemoryIngestResearch:
    """Tests for the memory_ingest_research MCP tool."""

    def test_memory_ingest_research_report_calls_ingest(self, monkeypatch):
        """memory_ingest_research with type='report' calls pipeline.ingest() with type='report'."""
        mock_pipeline = _make_mock_pipeline()

        # Patch _get_research_pipeline to return mock
        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.memory_ingest_research(
            type="report",
            content="Some research content",
            project_id="proj1",
            session_id="sess1",
            source_agent="claude",
            title="Test Report",
        )

        mock_pipeline.ingest.assert_called_once()
        call_args = mock_pipeline.ingest.call_args[0][0]
        assert call_args["type"] == "report"
        assert call_args["content"] == "Some research content"
        assert call_args["project_id"] == "proj1"
        assert "status" in result or "ok" in result  # JSON string contains status

    def test_memory_ingest_research_report_returns_ok_json(self, monkeypatch):
        """memory_ingest_research returns JSON string with status=ok."""
        mock_pipeline = _make_mock_pipeline()

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.memory_ingest_research(
            type="report",
            content="Content",
            project_id="proj1",
            session_id="sess1",
            source_agent="claude",
        )

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["status"] == "ok"

    def test_memory_ingest_research_finding_calls_ingest(self, monkeypatch):
        """memory_ingest_research with type='finding' calls pipeline.ingest() with type='finding'."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline.ingest.return_value = {
            "type": "finding",
            "content_hash": "abc123",
            "citations": 0,
            "entities": 0,
            "project_id": "proj1",
            "session_id": "sess1",
        }

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.memory_ingest_research(
            type="finding",
            content="An atomic fact",
            project_id="proj1",
            session_id="sess1",
            source_agent="claude",
            confidence="high",
        )

        mock_pipeline.ingest.assert_called_once()
        call_args = mock_pipeline.ingest.call_args[0][0]
        assert call_args["type"] == "finding"

    def test_memory_ingest_research_finding_returns_content_hash(self, monkeypatch):
        """memory_ingest_research with finding returns JSON with content_hash."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline.ingest.return_value = {
            "type": "finding",
            "content_hash": "deadbeef",
            "citations": 0,
            "entities": 0,
            "project_id": "proj1",
            "session_id": "sess1",
        }

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.memory_ingest_research(
            type="finding",
            content="Atomic fact",
            project_id="proj1",
            session_id="sess1",
            source_agent="claude",
        )

        parsed = json.loads(result)
        assert parsed["content_hash"] == "deadbeef"

    def test_memory_ingest_research_missing_api_keys_returns_error(self, monkeypatch):
        """memory_ingest_research returns error string when pipeline unavailable."""
        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: None)

        result = app_module.memory_ingest_research(
            type="report",
            content="Content",
            project_id="proj1",
            session_id="sess1",
            source_agent="claude",
        )

        assert isinstance(result, str)
        assert "Error" in result

    def test_memory_ingest_research_has_always_call_description(self):
        """memory_ingest_research tool docstring contains 'ALWAYS call this tool'."""
        from agentic_memory.server import app as app_module
        assert "ALWAYS call this tool" in app_module.memory_ingest_research.__doc__

    def test_memory_ingest_research_normalizes_string_findings(self, monkeypatch):
        """String findings are coerced into finding objects before ingest."""
        mock_pipeline = _make_mock_pipeline()

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        app_module.memory_ingest_research(
            type="report",
            content="Report body",
            project_id="proj1",
            session_id="sess1",
            source_agent="claude",
            confidence="high",
            findings=["First takeaway", "Second takeaway"],
        )

        call_args = mock_pipeline.ingest.call_args[0][0]
        assert call_args["findings"] == [
            {"text": "First takeaway", "confidence": "high", "citations": []},
            {"text": "Second takeaway", "confidence": "high", "citations": []},
        ]

    def test_memory_ingest_research_normalizes_url_string_citations(self, monkeypatch):
        """URL-string citations are coerced into citation objects before ingest."""
        mock_pipeline = _make_mock_pipeline()

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        app_module.memory_ingest_research(
            type="finding",
            content="Atomic fact",
            project_id="proj1",
            session_id="sess1",
            source_agent="claude",
            citations=["https://example.com/article"],
        )

        call_args = mock_pipeline.ingest.call_args[0][0]
        assert call_args["citations"] == [
            {"url": "https://example.com/article", "title": None, "snippet": None}
        ]

    def test_memory_ingest_research_rejects_non_url_string_citations(self, monkeypatch):
        """Malformed citation strings fail fast with a contract error."""
        mock_pipeline = _make_mock_pipeline()

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.memory_ingest_research(
            type="finding",
            content="Atomic fact",
            project_id="proj1",
            session_id="sess1",
            source_agent="claude",
            citations=["not-a-url"],
        )

        assert result == (
            "Error: citations[0] must be an object with url/title/snippet or an http(s) URL string."
        )
        mock_pipeline.ingest.assert_not_called()


# ---------------------------------------------------------------------------
# search_web_memory tests
# ---------------------------------------------------------------------------


class TestSearchWebMemory:
    """Tests for the search_web_memory MCP tool."""

    def test_search_web_memory_returns_results(self, monkeypatch):
        """search_web_memory calls vector search and returns formatted results."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline._embedder.embed.return_value = [0.1] * 768

        rows = [
            {
                "text": "Neo4j is a graph database",
                "score": 0.92,
                "source_agent": "claude",
                "research_question": "What is Neo4j?",
                "confidence": "high",
                "source_key": "deep_research_agent",
                "project_id": "proj1",
                "node_labels": ["Memory", "Research", "Finding"],
            }
        ]
        mock_run = Mock()
        mock_run.data.return_value = rows
        mock_session = Mock()
        mock_session.run.return_value = mock_run
        session_ctx = MagicMock()
        session_ctx.__enter__ = Mock(return_value=mock_session)
        session_ctx.__exit__ = Mock(return_value=False)
        mock_pipeline._conn.session.return_value = session_ctx

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.search_web_memory(query="graph database", limit=5)

        assert isinstance(result, str)
        assert "Neo4j is a graph database" in result
        assert "0.92" in result
        mock_pipeline._embedder.embed.assert_called_once()

    def test_search_web_memory_empty_returns_no_results_message(self, monkeypatch):
        """search_web_memory returns 'No relevant research found.' when empty."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline._embedder.embed.return_value = [0.1] * 768

        mock_run = Mock()
        mock_run.data.return_value = []
        mock_session = Mock()
        mock_session.run.return_value = mock_run
        session_ctx = MagicMock()
        session_ctx.__enter__ = Mock(return_value=mock_session)
        session_ctx.__exit__ = Mock(return_value=False)
        mock_pipeline._conn.session.return_value = session_ctx

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.search_web_memory(query="nothing here", limit=5)

        assert "No relevant research found" in result

    def test_search_web_memory_calls_research_embeddings_index(self, monkeypatch):
        """search_web_memory uses the 'research_embeddings' vector index."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline._embedder.embed.return_value = [0.1] * 768

        mock_run = Mock()
        mock_run.data.return_value = []
        mock_session = Mock()
        mock_session.run.return_value = mock_run
        session_ctx = MagicMock()
        session_ctx.__enter__ = Mock(return_value=mock_session)
        session_ctx.__exit__ = Mock(return_value=False)
        mock_pipeline._conn.session.return_value = session_ctx

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        app_module.search_web_memory(query="test query", limit=5)

        # Check that the Cypher query included research_embeddings
        cypher_call = mock_session.run.call_args[0][0]
        assert "research_embeddings" in cypher_call

    def test_search_web_memory_pipeline_unavailable_returns_error(self, monkeypatch):
        """search_web_memory returns error string when pipeline unavailable."""
        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: None)

        result = app_module.search_web_memory(query="test", limit=5)

        assert "Error" in result

    def test_search_web_memory_falls_back_when_temporal_bridge_unavailable(self, monkeypatch):
        """Bridge-unavailable state keeps the baseline result shape and content."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline._temporal_bridge.is_available.return_value = False

        rows = [
            {
                "text": "Baseline web result",
                "score": 0.91,
                "source_agent": "claude",
                "research_question": "What is fallback behavior?",
                "confidence": "high",
                "source_key": "deep_research_agent",
                "project_id": "proj1",
                "node_labels": ["Memory", "Research", "Finding"],
            }
        ]
        mock_run = Mock()
        mock_run.data.return_value = rows
        mock_session = Mock()
        mock_session.run.return_value = mock_run
        session_ctx = MagicMock()
        session_ctx.__enter__ = Mock(return_value=mock_session)
        session_ctx.__exit__ = Mock(return_value=False)
        mock_pipeline._conn.session.return_value = session_ctx

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.search_web_memory(query="fallback", limit=5)

        assert "Baseline web result" in result
        mock_pipeline._temporal_bridge.retrieve.assert_not_called()

    def test_search_web_memory_logs_structured_fallback(self, monkeypatch, caplog):
        """Web fallback logs emit consistent structured fields."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline._temporal_bridge.is_available.return_value = True
        mock_pipeline._temporal_bridge.retrieve.side_effect = RuntimeError("bridge down")

        rows = [
            {
                "text": "Baseline web result",
                "score": 0.91,
                "source_agent": "claude",
                "research_question": "What changed?",
                "confidence": "high",
                "source_key": "deep_research_agent",
                "project_id": "proj1",
                "node_labels": ["Memory", "Research", "Finding"],
            }
        ]
        mock_run = Mock()
        mock_run.data.return_value = rows
        mock_session = Mock()
        mock_session.run.return_value = mock_run
        session_ctx = MagicMock()
        session_ctx.__enter__ = Mock(return_value=mock_session)
        session_ctx.__exit__ = Mock(return_value=False)
        mock_pipeline._conn.session.return_value = session_ctx

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        with caplog.at_level("WARNING"):
            result = app_module.search_web_memory(query="graph database", limit=5)

        assert "Baseline web result" in result
        record = next(r for r in caplog.records if r.message == "web_search_fallback")
        assert record.event == "temporal_fallback"
        assert record.memory_module == "web"
        assert record.fallback == "temporal_retrieve_failed"
        assert record.error_type == "RuntimeError"

    def test_search_web_memory_as_of_filters_future_results(self, monkeypatch):
        """search_web_memory applies the Phase 7 ingested_at cutoff when as_of is provided."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline._embedder.embed.return_value = [0.1] * 768

        rows = [
            {
                "text": "Old research",
                "score": 0.92,
                "source_agent": "claude",
                "research_question": "What changed?",
                "confidence": "high",
                "source_key": "deep_research_agent",
                "project_id": "proj1",
                "ingested_at": "2026-03-01T00:00:00+00:00",
                "node_labels": ["Memory", "Research", "Finding"],
            },
            {
                "text": "Future research",
                "score": 0.88,
                "source_agent": "claude",
                "research_question": "What changed later?",
                "confidence": "medium",
                "source_key": "deep_research_agent",
                "project_id": "proj1",
                "ingested_at": "2026-03-20T00:00:00+00:00",
                "node_labels": ["Memory", "Research", "Finding"],
            },
        ]
        mock_run = Mock()
        mock_run.data.return_value = rows
        mock_session = Mock()
        mock_session.run.return_value = mock_run
        session_ctx = MagicMock()
        session_ctx.__enter__ = Mock(return_value=mock_session)
        session_ctx.__exit__ = Mock(return_value=False)
        mock_pipeline._conn.session.return_value = session_ctx

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.search_web_memory(
            query="graph database",
            limit=5,
            as_of="2026-03-05T00:00:00+00:00",
        )

        assert "Old research" in result
        assert "Future research" not in result

    def test_search_web_memory_uses_temporal_results_when_available(self, monkeypatch):
        """Temporal retrieval becomes the primary formatting path when seeds and bridge data exist."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline._temporal_bridge.is_available.return_value = True
        mock_pipeline._temporal_bridge.retrieve.return_value = {
            "results": [
                {
                    "subject": {"name": "Agentic Memory"},
                    "predicate": "USES",
                    "object": {"name": "Neo4j"},
                    "confidence": 0.8,
                    "relevance": 0.9,
                    "evidence": [
                        {
                            "sourceKind": "research_finding",
                            "sourceId": "deep_research_agent:abc",
                            "rawExcerpt": "Temporal snippet",
                        }
                    ],
                }
            ]
        }

        rows = [
            {
                "text": "Baseline research",
                "score": 0.92,
                "source_agent": "claude",
                "research_question": "What is Neo4j?",
                "confidence": "high",
                "source_key": "deep_research_agent",
                "content_hash": "abc",
                "project_id": "proj1",
                "ingested_at": "2026-03-01T00:00:00+00:00",
                "entities": ["Neo4j"],
                "entity_types": ["technology"],
                "node_labels": ["Memory", "Research", "Finding"],
            }
        ]
        mock_run = Mock()
        mock_run.data.return_value = rows
        mock_session = Mock()
        mock_session.run.return_value = mock_run
        session_ctx = MagicMock()
        session_ctx.__enter__ = Mock(return_value=mock_session)
        session_ctx.__exit__ = Mock(return_value=False)
        mock_pipeline._conn.session.return_value = session_ctx

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.search_web_memory(query="graph database", limit=5)

        assert "[Temporal]" in result
        assert "Temporal snippet" in result
        mock_pipeline._temporal_bridge.retrieve.assert_called_once()

    def test_search_web_memory_falls_back_when_temporal_bridge_fails(self, monkeypatch):
        """Temporal bridge errors keep the baseline result shape and content."""
        mock_pipeline = _make_mock_pipeline()
        mock_pipeline._temporal_bridge.is_available.return_value = True
        mock_pipeline._temporal_bridge.retrieve.side_effect = RuntimeError("bridge down")

        rows = [
            {
                "text": "Baseline research",
                "score": 0.92,
                "source_agent": "claude",
                "research_question": "What is Neo4j?",
                "confidence": "high",
                "source_key": "deep_research_agent",
                "content_hash": "abc",
                "project_id": "proj1",
                "ingested_at": "2026-03-01T00:00:00+00:00",
                "entities": ["Neo4j"],
                "entity_types": ["technology"],
                "node_labels": ["Memory", "Research", "Finding"],
            }
        ]
        mock_run = Mock()
        mock_run.data.return_value = rows
        mock_session = Mock()
        mock_session.run.return_value = mock_run
        session_ctx = MagicMock()
        session_ctx.__enter__ = Mock(return_value=mock_session)
        session_ctx.__exit__ = Mock(return_value=False)
        mock_pipeline._conn.session.return_value = session_ctx

        from agentic_memory.server import app as app_module
        monkeypatch.setattr(app_module, "_get_research_pipeline", lambda: mock_pipeline)

        result = app_module.search_web_memory(query="graph database", limit=5)

        assert "Baseline research" in result
        assert "[Temporal]" not in result


# ---------------------------------------------------------------------------
# brave_search tests
# ---------------------------------------------------------------------------


class TestBraveSearch:
    """Tests for the brave_search MCP tool."""

    def test_brave_search_missing_api_key_returns_error(self, monkeypatch):
        """brave_search returns error string when BRAVE_SEARCH_API_KEY not set."""
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

        from agentic_memory.server import app as app_module

        result = app_module.brave_search(query="python neo4j", count=5)

        assert isinstance(result, str)
        assert "BRAVE_SEARCH_API_KEY" in result or "Error" in result

    def test_brave_search_returns_formatted_results(self, monkeypatch):
        """brave_search calls Brave API and returns formatted results."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-api-key")

        mock_response = Mock()
        mock_response.json.return_value = {
            "web": {
                "results": [
                    {"title": "Neo4j Tutorial", "url": "https://neo4j.com/docs", "description": "Learn Neo4j"},
                    {"title": "Graph Databases", "url": "https://graphdbs.com", "description": "All about graphs"},
                ]
            }
        }
        mock_response.raise_for_status = Mock()

        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_ctx = MagicMock()
        mock_client_ctx.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_ctx.__exit__ = Mock(return_value=False)

        with patch("agentic_memory.server.app.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client_ctx

            from agentic_memory.server import app as app_module
            result = app_module.brave_search(query="neo4j", count=5)

        assert isinstance(result, str)
        assert "Neo4j Tutorial" in result
        assert "neo4j.com" in result

    def test_brave_search_calls_correct_api_endpoint(self, monkeypatch):
        """brave_search POSTs to the correct Brave Search API endpoint."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "my-key")

        mock_response = Mock()
        mock_response.json.return_value = {"web": {"results": []}}
        mock_response.raise_for_status = Mock()

        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_ctx = MagicMock()
        mock_client_ctx.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_ctx.__exit__ = Mock(return_value=False)

        with patch("agentic_memory.server.app.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client_ctx

            from agentic_memory.server import app as app_module
            app_module.brave_search(query="test query", count=3)

        # Verify the GET call used the correct URL and auth header
        call_kwargs = mock_client_instance.get.call_args
        url = call_kwargs[0][0]
        headers = call_kwargs[1]["headers"]
        params = call_kwargs[1]["params"]

        assert "api.search.brave.com" in url
        assert headers["X-Subscription-Token"] == "my-key"
        assert params["q"] == "test query"

    def test_brave_search_does_not_touch_neo4j(self, monkeypatch):
        """brave_search does NOT call ResearchIngestionPipeline (no auto-ingest)."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        mock_response = Mock()
        mock_response.json.return_value = {
            "web": {"results": [{"title": "T", "url": "https://x.com", "description": "D"}]}
        }
        mock_response.raise_for_status = Mock()

        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_ctx = MagicMock()
        mock_client_ctx.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_ctx.__exit__ = Mock(return_value=False)

        with patch("agentic_memory.server.app.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client_ctx
            with patch("agentic_memory.server.app._get_research_pipeline") as mock_get_pipeline:
                from agentic_memory.server import app as app_module
                app_module.brave_search(query="test", count=5)

                # brave_search must NOT call the research pipeline
                mock_get_pipeline.assert_not_called()

    def test_brave_search_no_results_returns_message(self, monkeypatch):
        """brave_search returns informative message when no results found."""
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

        mock_response = Mock()
        mock_response.json.return_value = {"web": {"results": []}}
        mock_response.raise_for_status = Mock()

        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_ctx = MagicMock()
        mock_client_ctx.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_ctx.__exit__ = Mock(return_value=False)

        with patch("agentic_memory.server.app.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client_ctx

            from agentic_memory.server import app as app_module
            result = app_module.brave_search(query="xyzzy impossible query", count=5)

        assert isinstance(result, str)
        assert len(result) > 0  # Returns something, not empty
