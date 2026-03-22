"""TDD test suite for am_server FastAPI REST API.

Covers all must-have truths from 02-04-PLAN.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from am_server import dependencies
from am_server.app import create_app


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

    dependencies.get_pipeline.cache_clear()
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


def test_ingest_no_auth(client):
    """POST /ingest/research without Authorization header returns 403."""
    payload = {
        "type": "report",
        "content": "Test content",
        "project_id": "proj-1",
        "session_id": "sess-1",
        "source_agent": "claude",
    }
    resp = client.post("/ingest/research", json=payload)
    assert resp.status_code == 403


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


def test_search_research_ok(client, auth_headers):
    """GET /search/research returns 200 with results list."""
    resp = client.get("/search/research?q=test&limit=5", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert isinstance(body["results"], list)


def test_search_no_auth(client):
    """GET /search/research without auth returns 403."""
    resp = client.get("/search/research?q=test")
    assert resp.status_code == 403


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
