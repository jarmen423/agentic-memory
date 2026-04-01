"""TDD test suite for am_server FastAPI REST API.

Covers all must-have truths from 02-04-PLAN.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from am_server import dependencies
from am_server.app import create_app


def _iter_result(rows):
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    return result


def _single_result(payload):
    result = MagicMock()
    result.single.return_value = payload
    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    """TestClient with all env vars set and pipeline patched."""
    monkeypatch.setenv("AM_SERVER_API_KEY", "test-key-abc")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")

    mock_pipeline = MagicMock()
    mock_pipeline.ingest.return_value = {"stored": True}
    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda *args, **kwargs: mock_pipeline,
    )

    mock_conversation_pipeline = MagicMock()
    mock_conversation_pipeline.ingest.return_value = {"stored": True}
    mock_conversation_pipeline._embedder = MagicMock()
    mock_conversation_pipeline._embedder.embed.return_value = [0.1] * 768
    mock_conversation_pipeline._extractor = MagicMock()
    mock_conversation_pipeline._extractor.extract.return_value = [{"name": "Neo4j", "type": "technology"}]
    mock_conversation_pipeline._temporal_bridge = MagicMock()
    mock_conversation_pipeline._temporal_bridge.is_available.return_value = False
    mock_conversation_pipeline._conn = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ConversationIngestionPipeline",
        lambda *args, **kwargs: mock_conversation_pipeline,
    )

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def auth_headers() -> dict:
    """Valid Authorization header."""
    return {"Authorization": "Bearer test-key-abc"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health(client):
    """GET /health returns 200 and {'status': 'ok'} without auth."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_includes_request_id_header(client):
    """FastAPI middleware adds a stable request correlation header."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"]


def test_ingest_no_auth(client):
    """POST /ingest/research without Authorization header returns 401."""
    payload = {
        "type": "report",
        "content": "Test content",
        "project_id": "proj-1",
        "session_id": "sess-1",
        "source_agent": "claude",
    }
    resp = client.post("/ingest/research", json=payload)
    assert resp.status_code == 401


def test_ingest_bad_token(client):
    """POST /ingest/research with wrong Bearer token returns 401."""
    payload = {
        "type": "report",
        "content": "Test content",
        "project_id": "proj-1",
        "session_id": "sess-1",
        "source_agent": "claude",
    }
    resp = client.post(
        "/ingest/research",
        json=payload,
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


def test_ingest_research_ok(client, auth_headers):
    """POST /ingest/research with valid token returns 202."""
    payload = {
        "type": "report",
        "content": "Test content",
        "project_id": "proj-1",
        "session_id": "sess-1",
        "source_agent": "claude",
    }
    resp = client.post("/ingest/research", json=payload, headers=auth_headers)
    assert resp.status_code == 202


def test_ingest_conversation_invalid_source_key_returns_422(client, auth_headers):
    """POST /ingest/conversation rejects unknown source_key values."""
    pipeline = dependencies.get_conversation_pipeline()
    pipeline.ingest.side_effect = ValueError(
        "Invalid source_key 'manual_test'. Must be one of: ['chat_cli', 'chat_ext', 'chat_mcp', 'chat_proxy']"
    )
    payload = {
        "role": "user",
        "content": "Test content",
        "project_id": "proj-1",
        "session_id": "sess-1",
        "turn_index": 0,
        "source_key": "manual_test",
    }
    resp = client.post("/ingest/conversation", json=payload, headers=auth_headers)
    assert resp.status_code == 422
    assert "source_key" in resp.json()["detail"]


def test_ingest_delegates(client, auth_headers):
    """POST /ingest/research calls pipeline.ingest() with correct payload."""
    payload = {
        "type": "finding",
        "content": "Important finding",
        "project_id": "proj-42",
        "session_id": "sess-99",
        "source_agent": "perplexity",
    }
    resp = client.post("/ingest/research", json=payload, headers=auth_headers)
    assert resp.status_code == 202

    # Verify pipeline was called — get the mock pipeline instance
    pipeline = dependencies.get_pipeline()
    call_args = pipeline.ingest.call_args
    assert call_args is not None
    passed = call_args[0][0]
    assert passed["session_id"] == "sess-99"
    assert passed["project_id"] == "proj-42"
    assert passed["content"] == "Important finding"
    assert passed["type"] == "finding"
    assert passed["source_agent"] == "perplexity"


def test_get_pipeline_uses_web_embedding_runtime(monkeypatch):
    """Research pipeline factory resolves embedder via the shared web runtime."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")

    sentinel_embedder = object()
    captured = {}

    monkeypatch.setattr("am_server.dependencies.build_embedding_service", lambda module_name: (
        captured.setdefault("module_name", module_name), sentinel_embedder
    )[1])
    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda conn, embedder, extractor, temporal_bridge=None: {
            "embedder": embedder,
            "temporal_bridge": temporal_bridge,
        },
    )

    dependencies.get_pipeline.cache_clear()
    pipeline = dependencies.get_pipeline()

    assert captured["module_name"] == "web"
    assert pipeline["embedder"] is sentinel_embedder


def test_get_conversation_pipeline_uses_chat_embedding_runtime(monkeypatch):
    """Conversation pipeline factory resolves embedder via the shared chat runtime."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")

    sentinel_embedder = object()
    captured = {}

    monkeypatch.setattr("am_server.dependencies.build_embedding_service", lambda module_name: (
        captured.setdefault("module_name", module_name), sentinel_embedder
    )[1])
    monkeypatch.setattr(
        "am_server.dependencies.ConversationIngestionPipeline",
        lambda conn, embedder, extractor, temporal_bridge=None: {
            "embedder": embedder,
            "temporal_bridge": temporal_bridge,
        },
    )

    dependencies.get_conversation_pipeline.cache_clear()
    pipeline = dependencies.get_conversation_pipeline()

    assert captured["module_name"] == "chat"
    assert pipeline["embedder"] is sentinel_embedder


def test_search_research_ok(client, auth_headers):
    """GET /search/research returns 200 with results list."""
    resp = client.get("/search/research?q=test&limit=5", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert isinstance(body["results"], list)


def test_search_no_auth(client):
    """GET /search/research without auth returns 401."""
    resp = client.get("/search/research?q=test")
    assert resp.status_code == 401


def test_selectors_shape(client):
    """GET /ext/selectors.json returns 200 with correct shape."""
    resp = client.get("/ext/selectors.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 1
    assert "platforms" in body


def test_selectors_no_auth(client):
    """GET /ext/selectors.json without auth returns 200 (unauthenticated)."""
    resp = client.get("/ext/selectors.json")
    assert resp.status_code == 200


def test_auth_missing_key(monkeypatch):
    """When AM_SERVER_API_KEY is not set, authenticated endpoint returns 503."""
    # Ensure no API key in environment
    monkeypatch.delenv("AM_SERVER_API_KEY", raising=False)
    # Still need other env vars to avoid pipeline crash (lifespan is fault-tolerant)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")

    mock_pipeline = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda *args, **kwargs: mock_pipeline,
    )

    dependencies.get_pipeline.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        payload = {
            "type": "report",
            "content": "Test",
            "project_id": "proj-1",
            "session_id": "sess-1",
            "source_agent": "claude",
        }
        resp = c.post(
            "/ingest/research",
            json=payload,
            headers={"Authorization": "Bearer anything"},
        )
    assert resp.status_code == 503


def test_mcp_mounted(client):
    """GET /mcp returns non-404 (verifies FastMCP ASGI mount exists).

    The SSE app at /mcp issues a 307 redirect for bare /mcp requests.
    We check without following redirects so the mount itself is verified.
    """
    resp = client.get("/mcp", follow_redirects=False)
    assert resp.status_code != 404


def test_search_conversations_temporal_results_keep_shape(client, auth_headers):
    """Temporal-ranked conversation search preserves the REST response contract."""
    pipeline = dependencies.get_conversation_pipeline()
    pipeline._temporal_bridge.is_available.return_value = True
    pipeline._temporal_bridge.retrieve.return_value = {
        "results": [
            {
                "confidence": 0.8,
                "relevance": 0.9,
                "evidence": [{"sourceKind": "conversation_turn", "sourceId": "sess-1:0"}],
            }
        ]
    }

    session = MagicMock()
    session.run.side_effect = [
        _iter_result(
            [
                {
                    "session_id": "sess-1",
                    "turn_index": 0,
                    "role": "user",
                    "content": "baseline",
                    "source_agent": "claude",
                    "timestamp": "2026-03-01T00:00:00+00:00",
                    "ingested_at": "2026-03-01T00:00:00+00:00",
                    "entities": ["Neo4j"],
                    "entity_types": ["technology"],
                    "score": 0.9,
                }
            ]
        ),
        _single_result(
            {
                "session_id": "sess-1",
                "turn_index": 0,
                "role": "assistant",
                "content": "temporal result",
                "source_agent": "claude",
                "timestamp": "2026-03-01T00:00:00+00:00",
                "ingested_at": "2026-03-01T00:00:00+00:00",
                "entities": ["Neo4j"],
            }
        ),
    ]
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = session
    session_ctx.__exit__.return_value = False
    pipeline._conn.session.return_value = session_ctx

    resp = client.get(
        "/search/conversations?q=neo4j&project_id=proj1&as_of=2026-03-05T00:00:00+00:00",
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["content"] == "temporal result"
    assert body["results"][0]["session_id"] == "sess-1"


def test_search_conversations_temporal_failure_falls_back(client, auth_headers):
    """Temporal bridge errors fall back to the baseline vector result shape."""
    pipeline = dependencies.get_conversation_pipeline()
    pipeline._temporal_bridge.is_available.return_value = True
    pipeline._temporal_bridge.retrieve.side_effect = RuntimeError("bridge down")

    session = MagicMock()
    session.run.side_effect = [
        _iter_result(
            [
                {
                    "session_id": "sess-1",
                    "turn_index": 0,
                    "role": "user",
                    "content": "baseline result",
                    "source_agent": "claude",
                    "timestamp": "2026-03-01T00:00:00+00:00",
                    "ingested_at": "2026-03-01T00:00:00+00:00",
                    "entities": ["Neo4j"],
                    "entity_types": ["technology"],
                    "score": 0.9,
                }
            ]
        )
    ]
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = session
    session_ctx.__exit__.return_value = False
    pipeline._conn.session.return_value = session_ctx

    resp = client.get(
        "/search/conversations?q=neo4j&project_id=proj1",
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["content"] == "baseline result"


def test_search_conversations_temporal_failure_logs_structured_fallback(
    client, auth_headers, caplog
):
    """Conversation fallback logs emit consistent structured fields."""
    pipeline = dependencies.get_conversation_pipeline()
    pipeline._temporal_bridge.is_available.return_value = True
    pipeline._temporal_bridge.retrieve.side_effect = RuntimeError("bridge down")

    session = MagicMock()
    session.run.side_effect = [
        _iter_result(
            [
                {
                    "session_id": "sess-1",
                    "turn_index": 0,
                    "role": "user",
                    "content": "baseline result",
                    "source_agent": "claude",
                    "timestamp": "2026-03-01T00:00:00+00:00",
                    "ingested_at": "2026-03-01T00:00:00+00:00",
                    "entities": ["Neo4j"],
                    "entity_types": ["technology"],
                    "score": 0.9,
                }
            ]
        )
    ]
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = session
    session_ctx.__exit__.return_value = False
    pipeline._conn.session.return_value = session_ctx

    with caplog.at_level("WARNING"):
        resp = client.get("/search/conversations?q=neo4j&project_id=proj1", headers=auth_headers)

    assert resp.status_code == 200
    record = next(r for r in caplog.records if r.message == "conversation_search_fallback")
    assert record.event == "temporal_fallback"
    assert record.memory_module == "conversation"
    assert record.fallback == "temporal_retrieve_failed"
    assert record.error_type == "RuntimeError"
    assert record.request_id


def test_search_conversations_bridge_unavailable_falls_back(client, auth_headers):
    """Bridge-unavailable state falls back to the baseline vector result shape."""
    pipeline = dependencies.get_conversation_pipeline()
    pipeline._temporal_bridge.is_available.return_value = False

    session = MagicMock()
    session.run.side_effect = [
        _iter_result(
            [
                {
                    "session_id": "sess-1",
                    "turn_index": 0,
                    "role": "user",
                    "content": "baseline unavailable result",
                    "source_agent": "claude",
                    "timestamp": "2026-03-01T00:00:00+00:00",
                    "ingested_at": "2026-03-01T00:00:00+00:00",
                    "entities": ["Neo4j"],
                    "entity_types": ["technology"],
                    "score": 0.9,
                }
            ]
        )
    ]
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = session
    session_ctx.__exit__.return_value = False
    pipeline._conn.session.return_value = session_ctx

    resp = client.get(
        "/search/conversations?q=neo4j&project_id=proj1",
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["content"] == "baseline unavailable result"
    pipeline._temporal_bridge.retrieve.assert_not_called()


def test_search_all_endpoint_returns_unified_results(client, auth_headers, monkeypatch):
    """GET /search/all returns normalized unified search results."""
    monkeypatch.setattr(
        "am_server.routes.search.get_graph",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        "am_server.routes.search.search_all_memory_sync",
        lambda **kwargs: MagicMock(
            to_dict=lambda: {
                "results": [
                    {
                        "module": "web",
                        "source_kind": "research_finding",
                        "source_id": "finding:1",
                        "title": "Research Hit",
                        "excerpt": "research excerpt",
                        "score": 0.9,
                        "baseline_score": None,
                        "temporal_score": 0.9,
                        "temporal_applied": True,
                        "metadata": {},
                    }
                ],
                "errors": [],
            }
        ),
    )

    resp = client.get("/search/all?q=neo4j&project_id=proj1", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["module"] == "web"
    assert body["results"][0]["temporal_applied"] is True
