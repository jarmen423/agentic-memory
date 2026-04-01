"""App-surface integration tests for unified search and fallback behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from codememory.server.result_types import UnifiedMemoryHit
from tests.integration.conftest import result_data, result_iter

pytestmark = [pytest.mark.integration]


def test_search_all_returns_code_and_temporal_web_results(
    integration_client,
    integration_auth_headers,
    monkeypatch,
):
    """GET /search/all merges code and temporal web hits through the live app surface."""
    mock_graph = MagicMock()
    mock_graph.semantic_search.return_value = [
        {
            "name": "GraphBuilder",
            "score": 0.44,
            "text": "class GraphBuilder handles Neo4j writes",
            "sig": "src/codememory/graph.py:GraphBuilder",
        }
    ]

    mock_research = MagicMock()

    mock_conversation = MagicMock()

    monkeypatch.setattr("am_server.routes.search.get_graph", lambda: mock_graph)
    monkeypatch.setattr("am_server.routes.search.get_pipeline", lambda: mock_research)
    monkeypatch.setattr(
        "am_server.routes.search.get_conversation_pipeline", lambda: mock_conversation
    )
    monkeypatch.setattr(
        "codememory.server.unified_search._search_research_structured",
        lambda pipeline, query, limit, as_of: [
            UnifiedMemoryHit(
                module="web",
                source_kind="research_finding",
                source_id="finding:phase8",
                title="Phase 8 -[INTRODUCED]-> SpacetimeDB",
                excerpt="Phase 8 introduced SpacetimeDB beside Neo4j.",
                score=0.72,
                baseline_score=None,
                temporal_score=0.72,
                temporal_applied=True,
                metadata={},
            )
        ],
    )
    monkeypatch.setattr(
        "codememory.server.unified_search.search_conversation_turns_sync",
        lambda *args, **kwargs: [],
    )

    response = integration_client.get(
        "/search/all?q=phase%208&project_id=proj-smoke",
        headers=integration_auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert {row["module"] for row in body["results"]} == {"web", "code"}
    web_hit = next(row for row in body["results"] if row["module"] == "web")
    code_hit = next(row for row in body["results"] if row["module"] == "code")
    assert web_hit["temporal_applied"] is True
    assert web_hit["source_id"] == "finding:phase8"
    assert code_hit["module"] == "code"
    assert body["errors"] == []


def test_search_all_surfaces_partial_module_failures(
    integration_client,
    integration_auth_headers,
    monkeypatch,
):
    """GET /search/all keeps healthy module hits when another module fails."""
    mock_graph = MagicMock()
    mock_graph.semantic_search.side_effect = RuntimeError("code unavailable")

    mock_research = MagicMock()
    mock_research._embedder.embed.return_value = [0.1] * 8
    mock_research._temporal_bridge.is_available.return_value = False
    research_session = MagicMock()
    research_session.run.return_value = result_data(
        [
            {
                "text": "Research result",
                "score": 0.81,
                "source_agent": "manual",
                "research_question": "What changed?",
                "confidence": "high",
                "source_key": "deep_research_agent",
                "content_hash": "finding:1",
                "project_id": "proj-smoke",
                "ingested_at": "2026-03-28T18:28:00+00:00",
                "entities": [],
                "entity_types": [],
                "node_labels": ["Memory", "Research", "Finding"],
            }
        ]
    )
    research_ctx = MagicMock()
    research_ctx.__enter__.return_value = research_session
    research_ctx.__exit__.return_value = False
    mock_research._conn.session.return_value = research_ctx

    mock_conversation = MagicMock()
    monkeypatch.setattr("am_server.routes.search.get_graph", lambda: mock_graph)
    monkeypatch.setattr("am_server.routes.search.get_pipeline", lambda: mock_research)
    monkeypatch.setattr(
        "am_server.routes.search.get_conversation_pipeline", lambda: mock_conversation
    )
    monkeypatch.setattr(
        "codememory.server.unified_search.search_conversation_turns_sync",
        lambda *args, **kwargs: [],
    )

    response = integration_client.get("/search/all?q=neo4j", headers=integration_auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["module"] == "web"
    assert body["errors"] == [{"module": "code", "message": "code unavailable"}]


def test_search_conversations_fallback_keeps_response_shape(
    integration_client,
    integration_auth_headers,
    monkeypatch,
):
    """GET /search/conversations keeps stable JSON shape when the temporal bridge is unavailable."""
    mock_pipeline = MagicMock()
    mock_pipeline._temporal_bridge.is_available.return_value = False
    mock_pipeline._embedder.provider = "gemini"
    mock_pipeline._embedder.embed.return_value = [0.1] * 8
    mock_pipeline._extractor.extract.return_value = [{"name": "Neo4j", "type": "technology"}]

    session = MagicMock()
    session.run.side_effect = [
        result_iter(
            [
                {
                    "session_id": "sess-002",
                    "turn_index": 0,
                    "role": "user",
                    "content": "phase 8 introduced spacetimedb beside neo4j",
                    "source_agent": "manual",
                    "timestamp": "2026-03-28T18:28:00.156342+00:00",
                    "ingested_at": "2026-03-28T18:28:00.156342+00:00",
                    "entities": ["spacetimedb", "neo4j"],
                    "entity_types": ["technology", "technology"],
                    "score": 1.0,
                }
            ]
        )
    ]
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = session
    session_ctx.__exit__.return_value = False
    mock_pipeline._conn.session.return_value = session_ctx

    monkeypatch.setattr(
        "am_server.routes.conversation.get_conversation_pipeline", lambda: mock_pipeline
    )

    response = integration_client.get(
        "/search/conversations?q=phase%208&project_id=proj-smoke",
        headers=integration_auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert list(body.keys()) == ["results"]
    assert body["results"][0]["session_id"] == "sess-002"
    assert body["results"][0]["content"] == "phase 8 introduced spacetimedb beside neo4j"
