"""Focused contract tests for the `/openclaw/*` REST surface.

This file complements `tests/test_am_server.py` by treating the OpenClaw routes
as one public API surface with a stable auth, error, and metrics contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from am_server import dependencies
from am_server.app import create_app
from am_server.routes import openclaw


def _assert_error_envelope(
    response,
    *,
    code: str,
    status_code: int,
    message_contains: str | None = None,
):
    body = response.json()
    assert response.status_code == status_code
    assert "error" in body
    assert body["error"]["code"] == code
    assert body["error"]["request_id"]
    if message_contains:
        assert message_contains in body["error"]["message"]
    return body["error"]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Return a test client with rotated auth keys and mocked pipelines."""

    monkeypatch.delenv("AM_SERVER_API_KEY", raising=False)
    monkeypatch.setenv("AM_SERVER_API_KEYS", "old-key,new-key")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))

    mock_research_pipeline = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda *args, **kwargs: mock_research_pipeline,
    )

    mock_conversation_pipeline = MagicMock()
    mock_conversation_pipeline.ingest.return_value = {"stored": True}
    monkeypatch.setattr(
        "am_server.dependencies.ConversationIngestionPipeline",
        lambda *args, **kwargs: mock_conversation_pipeline,
    )

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_openclaw_contract_accepts_rotated_keys(client):
    """Both currently configured API keys should authenticate the same route."""

    payload = {
        "workspace_id": "workspace-1",
        "device_id": "device-1",
        "agent_id": "agent-1",
        "session_id": "session-1",
    }

    for key in ("old-key", "new-key"):
        response = client.post(
            "/openclaw/session/register",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
        )
        assert response.status_code == 200
        assert response.json()["identity"]["session_id"] == "session-1"


def test_openclaw_contract_missing_auth_returns_error_envelope_and_header(client):
    """Missing auth should return the shared error body and request-id header."""

    response = client.post(
        "/openclaw/session/register",
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
        },
    )

    _assert_error_envelope(
        response,
        code="auth_missing_api_key",
        status_code=401,
        message_contains="Missing API key.",
    )
    assert response.headers["X-Request-ID"]


def test_openclaw_contract_validation_errors_are_machine_readable(client):
    """OpenClaw request validation should use the shared 422 envelope."""

    response = client.post(
        "/openclaw/session/register",
        headers={"Authorization": "Bearer new-key"},
        json={
          "workspace_id": "workspace-1",
          "device_id": "device-1",
          "agent_id": "agent-1",
        },
    )

    error = _assert_error_envelope(
        response,
        code="validation_error",
        status_code=422,
        message_contains="Request validation failed.",
    )
    assert error["details"]
    assert response.headers["X-Request-ID"]


def test_openclaw_contract_runtime_failures_are_machine_readable(client, monkeypatch):
    """Unexpected route failures should normalize to the shared 500 envelope."""

    monkeypatch.setattr(openclaw, "get_graph", lambda: object())
    monkeypatch.setattr(openclaw, "get_pipeline", lambda: "research")
    monkeypatch.setattr(openclaw, "get_conversation_pipeline", lambda: "conversation")

    def blow_up(**kwargs):
        raise RuntimeError("search failed")

    monkeypatch.setattr(openclaw, "search_all_memory_sync", blow_up)

    response = client.post(
        "/openclaw/memory/search",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "query": "memory",
        },
    )

    error = _assert_error_envelope(
        response,
        code="internal_server_error",
        status_code=500,
        message_contains="Internal server error.",
    )
    assert error["details"]["exception_type"] == "RuntimeError"
    assert response.headers["X-Request-ID"]


def test_openclaw_contract_metrics_include_openclaw_route_labels(client):
    """Authenticated `/metrics` should expose OpenClaw request series."""

    client.post(
        "/openclaw/session/register",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
        },
    )

    metrics_response = client.get(
        "/metrics",
        headers={"Authorization": "Bearer new-key"},
    )

    assert metrics_response.status_code == 200
    assert 'path="/openclaw/session/register"' in metrics_response.text
    assert "am_http_requests_total" in metrics_response.text


def test_openclaw_dashboard_summary_is_authenticated_and_machine_readable(client):
    """Dashboard summary should stay behind auth and expose a stable response shape."""

    unauthorized = client.get("/openclaw/metrics/summary")
    _assert_error_envelope(
        unauthorized,
        code="auth_missing_api_key",
        status_code=401,
        message_contains="Missing API key.",
    )

    authorized = client.get(
        "/openclaw/metrics/summary",
        headers={"Authorization": "Bearer new-key"},
    )

    assert authorized.status_code == 200
    body = authorized.json()
    assert body["status"] == "ok"
    assert "summary" in body
    assert "cards" in body["summary"]


def test_openclaw_dashboard_recent_searches_returns_openclaw_search_activity(client, monkeypatch):
    """Recent-search route should expose search activity once OpenClaw calls search."""

    monkeypatch.setattr(openclaw, "get_graph", lambda: object())
    monkeypatch.setattr(openclaw, "get_pipeline", lambda: "research")
    monkeypatch.setattr(openclaw, "get_conversation_pipeline", lambda: "conversation")
    monkeypatch.setattr(
        openclaw,
        "search_all_memory_sync",
        lambda **kwargs: {"results": []},
    )

    search_response = client.post(
        "/openclaw/memory/search",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "query": "memory",
        },
    )
    assert search_response.status_code == 200

    recent_response = client.get(
        "/openclaw/search/recent?limit=5",
        headers={"Authorization": "Bearer new-key"},
    )

    assert recent_response.status_code == 200
    body = recent_response.json()
    assert body["status"] == "ok"
    assert body["recent_searches"]
    assert body["recent_searches"][0]["event_type"] == "openclaw_memory_search"
