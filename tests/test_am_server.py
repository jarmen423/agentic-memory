"""TDD test suite for am_server FastAPI REST API.

Covers all must-have truths from 02-04-PLAN.md.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agentic_memory.core.connection import ConnectionManager
from am_server import dependencies
from am_server.app import create_app
from am_server.mcp_profiles import FULL_MCP_TOOL_NAMES, PUBLIC_MCP_TOOL_NAMES
from am_server.routes import dashboard, oauth, openclaw


def _iter_result(rows):
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    return result


def _single_result(payload):
    result = MagicMock()
    result.single.return_value = payload
    return result


def _assert_error_envelope(
    response,
    *,
    code: str,
    status_code: int | None = None,
    message_contains: str | None = None,
):
    """Assert the shared am-server error envelope shape."""

    if status_code is not None:
        assert response.status_code == status_code

    body = response.json()
    assert "error" in body
    error = body["error"]
    assert error["code"] == code
    assert error["request_id"]
    if message_contains:
        assert message_contains in error["message"]
    return error


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient with all env vars set and pipeline patched."""
    monkeypatch.setenv("AM_SERVER_API_KEY", "test-key-abc")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))
    monkeypatch.setenv("AM_SERVER_PUBLIC_MCP_API_KEY", "public-mcp-key")
    monkeypatch.setenv("AM_SERVER_INTERNAL_MCP_API_KEY", "internal-mcp-key")

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
    dependencies.get_product_store.cache_clear()
    with openclaw._CACHE_LOCK:  # type: ignore[attr-defined]
        openclaw._PROJECT_STATUS_CACHE.clear()  # type: ignore[attr-defined]
        openclaw._SEARCH_CACHE.clear()  # type: ignore[attr-defined]
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def auth_headers() -> dict:
    """Valid Authorization header."""
    return {"Authorization": "Bearer test-key-abc"}


@pytest.fixture()
def public_mcp_headers() -> dict:
    """Valid Authorization header for hosted/public MCP surfaces."""
    return {"Authorization": "Bearer public-mcp-key"}


@pytest.fixture()
def internal_mcp_headers() -> dict:
    """Valid Authorization header for full/internal MCP surfaces."""
    return {"Authorization": "Bearer internal-mcp-key"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health(client):
    """GET /health returns 200 and {'status': 'ok'} without auth."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_onboarding_is_public_and_returns_locked_contract(client):
    """GET /health/onboarding stays public and exposes the doctor-first contract.

    This endpoint is the backend source of truth for whole-stack setup. The
    local shell and OpenClaw plugin doctor flow both depend on it before they
    can honestly claim the stack is ready.
    """

    resp = client.get("/health/onboarding")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["deployment_mode"] == "self_hosted"
    assert body["supported_deployment_modes"] == ["managed", "self_hosted"]
    assert body["auth_strategy"] == "shared_api_key"
    assert body["provider_key_mode"] == "operator_managed"
    assert body["plugin_package_name"] == "agentic-memory-openclaw"
    assert body["plugin_id"] == "agentic-memory"
    assert body["install_command"] == "openclaw plugin install agentic-memory-openclaw"
    assert body["doctor_command"] == "openclaw agentic-memory doctor"
    assert body["setup_command"] == "openclaw agentic-memory setup"
    assert body["readiness"]["setup_ready"] is True
    assert body["readiness"]["capture_only_ready"] is True
    assert body["readiness"]["augment_context_ready"] is True

    required = {service["service_id"]: service for service in body["required_services"]}
    optional = {service["service_id"]: service for service in body["optional_services"]}
    assert required["backend_http"]["required"] is True
    assert required["api_auth"]["details"]["configured"] is True
    assert required["openclaw_memory"]["required"] is True
    assert optional["public_mcp_oauth"]["status"] == "unknown"
    assert optional["public_mcp_oauth"]["details"]["enabled"] is False
    assert optional["temporal_stack"]["required"] is False
    assert optional["grafana"]["required"] is False


def test_health_onboarding_reports_blocking_memory_pipeline(client):
    """Onboarding health must distinguish reachable backend vs ready memory path."""

    store = dependencies.get_product_store()
    store.set_component_status(
        "openclaw_memory",
        status="degraded",
        details={"warmup_error": "RuntimeError"},
    )
    store.set_component_status(
        "openclaw_context_engine",
        status="degraded",
        details={"warmup_error": "RuntimeError"},
    )

    resp = client.get("/health/onboarding")

    assert resp.status_code == 200
    body = resp.json()
    assert body["readiness"]["setup_ready"] is True
    assert body["readiness"]["capture_only_ready"] is False
    assert body["readiness"]["augment_context_ready"] is False
    assert "openclaw_memory" in body["readiness"]["blocking_services"]
    assert "openclaw_context_engine" in body["readiness"]["degraded_optional_services"]

    required = {service["service_id"]: service for service in body["required_services"]}
    optional = {service["service_id"]: service for service in body["optional_services"]}
    assert required["openclaw_memory"]["status"] == "degraded"
    assert optional["openclaw_context_engine"]["status"] == "degraded"


def test_health_onboarding_reports_public_oauth_readiness(monkeypatch, tmp_path):
    """Onboarding truth distinguishes plugin readiness from public OAuth publication readiness."""

    monkeypatch.setenv("AM_SERVER_API_KEY", "test-key-abc")
    monkeypatch.setenv("AM_SERVER_PUBLIC_OAUTH_ENABLED", "1")
    monkeypatch.setenv("AM_PUBLIC_BASE_URL", "https://mcp.agentmemorylabs.com")
    monkeypatch.setenv("AM_SERVER_OAUTH_BOOTSTRAP_USERS", "reviewer:secret-pass:ws_demo:Marketplace Reviewer")
    monkeypatch.setenv("AM_SERVER_PUBLIC_MCP_API_KEY", "public-reviewer-key")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))

    mock_pipeline = MagicMock()
    mock_pipeline.ingest.return_value = {"stored": True}
    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda *args, **kwargs: mock_pipeline,
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
    with openclaw._CACHE_LOCK:  # type: ignore[attr-defined]
        openclaw._PROJECT_STATUS_CACHE.clear()  # type: ignore[attr-defined]
        openclaw._SEARCH_CACHE.clear()  # type: ignore[attr-defined]

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as oauth_health_client:
        resp = oauth_health_client.get("/health/onboarding")

    assert resp.status_code == 200
    body = resp.json()
    optional = {service["service_id"]: service for service in body["optional_services"]}
    oauth_service = optional["public_mcp_oauth"]
    assert oauth_service["status"] == "healthy"
    assert oauth_service["details"]["enabled"] is True
    assert oauth_service["details"]["publication_ready"] is True
    assert oauth_service["details"]["bootstrap_oauth_user_count"] == 1
    assert oauth_service["details"]["current_reviewer_fallback"] == "dedicated_public_mcp_key"


def test_health_includes_request_id_header(client):
    """FastAPI middleware adds a stable request correlation header."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"]


def test_publication_root_redirects_to_overview(client):
    """GET /publication redirects to the stable product overview page."""

    resp = client.get("/publication", follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"] == "/publication/agentic-memory"


def test_publication_pages_are_public_and_linked(client):
    """Legal/support publication pages stay public and cross-link correctly."""

    expected_pages = {
        "/publication/agentic-memory": "Agentic Memory",
        "/publication/privacy": "Privacy Policy",
        "/publication/terms": "Terms of Service",
        "/publication/support": "Support",
        "/publication/dpa": "Data Processing Addendum",
    }

    for path, marker in expected_pages.items():
        resp = client.get(path)
        assert resp.status_code == 200
        assert marker in resp.text
        assert "/publication/privacy" in resp.text
        assert "/publication/terms" in resp.text
        assert "/publication/support" in resp.text
        assert "/publication/dpa" in resp.text


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
    _assert_error_envelope(resp, code="auth_missing_api_key", status_code=401)


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
    _assert_error_envelope(resp, code="auth_invalid_api_key", status_code=401)


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
        "Invalid source_key 'manual_test'. Must be one of: ['chat_cli', 'chat_codex_rollout', 'chat_ext', 'chat_mcp', 'chat_openclaw', 'chat_proxy']"
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
    error = _assert_error_envelope(
        resp,
        code="validation_error",
        status_code=422,
        message_contains="Invalid source_key",
    )
    assert "source_key" in error["message"]


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


def test_ingest_conversation_accepts_openclaw_identity_fields(client, auth_headers):
    """POST /ingest/conversation forwards OpenClaw workspace/device identity intact."""
    payload = {
        "role": "user",
        "content": "Need context from another device",
        "project_id": "proj-openclaw",
        "session_id": "sess-openclaw",
        "turn_index": 2,
        "source_key": "chat_openclaw",
        "workspace_id": "workspace-alpha",
        "device_id": "device-phone",
        "agent_id": "agent-openclaw-1",
    }
    resp = client.post("/ingest/conversation", json=payload, headers=auth_headers)
    assert resp.status_code == 202

    pipeline = dependencies.get_conversation_pipeline()
    passed = pipeline.ingest.call_args[0][0]
    assert passed["source_key"] == "chat_openclaw"
    assert passed["workspace_id"] == "workspace-alpha"
    assert passed["device_id"] == "device-phone"
    assert passed["agent_id"] == "agent-openclaw-1"


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
    _assert_error_envelope(resp, code="auth_missing_api_key", status_code=401)


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
    monkeypatch.delenv("AM_SERVER_API_KEYS", raising=False)
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
    _assert_error_envelope(resp, code="auth_not_configured", status_code=503)


def test_metrics_requires_auth(client):
    """GET /metrics stays authenticated even though /health is public."""

    resp = client.get("/metrics")
    _assert_error_envelope(resp, code="auth_missing_api_key", status_code=401)


def test_metrics_returns_prometheus_payload(client, auth_headers):
    """GET /metrics returns Prometheus-style text with request and error series."""

    client.get("/health")
    client.get("/search/research?q=test")

    resp = client.get("/metrics", headers=auth_headers)

    assert resp.status_code == 200
    assert "am_http_requests_total" in resp.text
    assert "am_http_request_duration_seconds_count" in resp.text
    assert "am_api_error_responses_total" in resp.text


def test_rotated_api_keys_accept_any_configured_key(monkeypatch):
    """AM_SERVER_API_KEYS supports key rotation without breaking clients."""

    monkeypatch.delenv("AM_SERVER_API_KEY", raising=False)
    monkeypatch.setenv("AM_SERVER_API_KEYS", "old-key,new-key")
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
        for key in ("old-key", "new-key"):
            resp = c.post(
                "/ingest/research",
                json={
                    "type": "report",
                    "content": "Test",
                    "project_id": "proj-1",
                    "session_id": "sess-1",
                    "source_agent": "claude",
                },
                headers={"Authorization": f"Bearer {key}"},
            )
            assert resp.status_code == 202


def test_connection_manager_uses_phase14_fail_fast_defaults(monkeypatch):
    """Neo4j pool acquisition now fails fast by default for user-facing routes."""

    captured = {}

    def fake_driver(uri, *, auth, max_connection_pool_size, connection_acquisition_timeout, connection_timeout, max_transaction_retry_time):
        captured.update(
            {
                "uri": uri,
                "auth": auth,
                "max_connection_pool_size": max_connection_pool_size,
                "connection_acquisition_timeout": connection_acquisition_timeout,
                "connection_timeout": connection_timeout,
                "max_transaction_retry_time": max_transaction_retry_time,
            }
        )
        return MagicMock()

    monkeypatch.delenv("AM_NEO4J_MAX_CONNECTION_POOL_SIZE", raising=False)
    monkeypatch.delenv("AM_NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AM_NEO4J_CONNECTION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AM_NEO4J_MAX_TRANSACTION_RETRY_SECONDS", raising=False)
    monkeypatch.setattr("agentic_memory.core.connection.neo4j.GraphDatabase.driver", fake_driver)

    manager = ConnectionManager("bolt://localhost:7687", "neo4j", "test")

    assert manager.pool_settings["connection_acquisition_timeout"] == 10
    assert captured["connection_acquisition_timeout"] == 10
    assert captured["max_connection_pool_size"] == 50


def test_public_mcp_requires_auth(client):
    """Hosted/public MCP mount is not anonymously accessible."""
    resp = client.get("/mcp", follow_redirects=False)
    _assert_error_envelope(resp, code="auth_missing_api_key", status_code=401)
    assert resp.headers["X-Agentic-Memory-MCP-Surface"] == "public"
    assert resp.headers["X-Agentic-Memory-MCP-Auth-Surface"] == "mcp_public"


def test_public_mcp_mounted(client, public_mcp_headers):
    """GET /mcp returns non-404 with valid public MCP auth."""
    resp = client.get("/mcp", follow_redirects=False, headers=public_mcp_headers)
    assert resp.status_code != 404
    assert resp.headers["X-Agentic-Memory-MCP-Surface"] == "public"
    assert resp.headers["X-Agentic-Memory-MCP-Auth-Surface"] == "mcp_public"


def test_internal_mcp_mount_uses_separate_auth_surface(client, public_mcp_headers):
    """Public MCP keys must not unlock the full/internal MCP surface."""
    resp = client.get("/mcp-full", follow_redirects=False, headers=public_mcp_headers)
    _assert_error_envelope(resp, code="auth_invalid_api_key", status_code=401)
    assert resp.headers["X-Agentic-Memory-MCP-Surface"] == "full"
    assert resp.headers["X-Agentic-Memory-MCP-Auth-Surface"] == "mcp_internal"


def test_internal_mcp_mounted(client, internal_mcp_headers):
    """GET /mcp/full returns non-404 with the internal MCP key."""
    resp = client.get("/mcp-full", follow_redirects=False, headers=internal_mcp_headers)
    assert resp.status_code != 404
    assert resp.headers["X-Agentic-Memory-MCP-Surface"] == "full"
    assert resp.headers["X-Agentic-Memory-MCP-Auth-Surface"] == "mcp_internal"


def test_public_and_internal_mcp_can_fallback_to_rest_api_key(monkeypatch, tmp_path):
    """Hosted MCP surfaces fall back to the REST API key when surface keys are unset."""

    monkeypatch.setenv("AM_SERVER_API_KEY", "shared-api-key")
    monkeypatch.delenv("AM_SERVER_API_KEYS", raising=False)
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEYS", raising=False)
    monkeypatch.delenv("AM_SERVER_INTERNAL_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_INTERNAL_MCP_API_KEYS", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))

    mock_pipeline = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda *args, **kwargs: mock_pipeline,
    )

    mock_conversation_pipeline = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ConversationIngestionPipeline",
        lambda *args, **kwargs: mock_conversation_pipeline,
    )

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as fallback_client:
        headers = {"Authorization": "Bearer shared-api-key"}
        public_response = fallback_client.get("/mcp", follow_redirects=False, headers=headers)
        internal_response = fallback_client.get("/mcp-full", follow_redirects=False, headers=headers)

    assert public_response.status_code != 404
    assert internal_response.status_code != 404


def test_strict_mcp_auth_disables_rest_api_key_fallback(monkeypatch, tmp_path):
    """Hosted MCP surfaces can require dedicated keys in production-like config."""

    monkeypatch.setenv("AM_SERVER_API_KEY", "shared-api-key")
    monkeypatch.setenv("AM_SERVER_STRICT_MCP_AUTH", "1")
    monkeypatch.delenv("AM_SERVER_API_KEYS", raising=False)
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEYS", raising=False)
    monkeypatch.delenv("AM_SERVER_INTERNAL_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_INTERNAL_MCP_API_KEYS", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))

    mock_pipeline = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda *args, **kwargs: mock_pipeline,
    )

    mock_conversation_pipeline = MagicMock()
    mock_conversation_pipeline.ingest.return_value = {"stored": True}
    mock_conversation_pipeline._embedder = MagicMock()
    mock_conversation_pipeline._embedder.embed.return_value = [0.1] * 768
    mock_conversation_pipeline._extractor = MagicMock()
    mock_conversation_pipeline._extractor.extract.return_value = []
    mock_conversation_pipeline._temporal_bridge = MagicMock()
    mock_conversation_pipeline._temporal_bridge.is_available.return_value = False
    mock_conversation_pipeline._conn = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ConversationIngestionPipeline",
        lambda *args, **kwargs: mock_conversation_pipeline,
    )

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as strict_client:
        public_resp = strict_client.get(
            "/mcp",
            follow_redirects=False,
            headers={"Authorization": "Bearer shared-api-key"},
        )
        internal_resp = strict_client.get(
            "/mcp-full",
            follow_redirects=False,
            headers={"Authorization": "Bearer shared-api-key"},
        )

    public_error = _assert_error_envelope(
        public_resp,
        code="auth_not_configured",
        status_code=503,
        message_contains="mcp_public",
    )
    assert public_error["details"]["surface"] == "public"

    internal_error = _assert_error_envelope(
        internal_resp,
        code="auth_not_configured",
        status_code=503,
        message_contains="mcp_internal",
    )
    assert internal_error["details"]["surface"] == "full"


def test_public_mcp_supports_surface_specific_rotated_keys(monkeypatch, tmp_path):
    """Public MCP can rotate keys independently from the REST API surface."""

    monkeypatch.setenv("AM_SERVER_API_KEY", "rest-key")
    monkeypatch.setenv("AM_SERVER_PUBLIC_MCP_API_KEYS", "public-old,public-new")
    monkeypatch.setenv("AM_SERVER_INTERNAL_MCP_API_KEY", "internal-key")
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_INTERNAL_MCP_API_KEYS", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))

    mock_pipeline = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda *args, **kwargs: mock_pipeline,
    )

    mock_conversation_pipeline = MagicMock()
    monkeypatch.setattr(
        "am_server.dependencies.ConversationIngestionPipeline",
        lambda *args, **kwargs: mock_conversation_pipeline,
    )

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as rotated_client:
        for key in ("public-old", "public-new"):
            response = rotated_client.get(
                "/mcp",
                follow_redirects=False,
                headers={"Authorization": f"Bearer {key}"},
            )
            assert response.status_code != 404

        wrong_surface = rotated_client.get(
            "/mcp-full",
            follow_redirects=False,
            headers={"Authorization": "Bearer public-new"},
        )

    _assert_error_envelope(wrong_surface, code="auth_invalid_api_key", status_code=401)


def test_health_mcp_surfaces_reports_frozen_public_contract(client, auth_headers):
    """Operator health route exposes mounted MCP surface inventory and annotations."""

    resp = client.get("/health/mcp-surfaces", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["strict_mcp_auth"] is False
    assert "https://chatgpt.com" in body["cors_allow_origins"]

    surfaces = {surface["name"]: surface for surface in body["surfaces"]}
    assert surfaces["public"]["tool_names_match"] is True
    assert surfaces["openai"]["tool_names_match"] is True
    assert surfaces["codex"]["tool_names_match"] is True
    assert surfaces["claude"]["tool_names_match"] is True
    assert surfaces["public"]["annotation_coverage_complete"] is True
    assert surfaces["openai"]["annotations"]["search_codebase"]["readOnlyHint"] is True
    assert surfaces["public"]["annotations"]["memory_ingest_research"]["destructiveHint"] is True


def test_public_mcp_preflight_allows_configured_browser_origin(client):
    """Hosted MCP mounts answer browser preflight requests for approved origins."""

    resp = client.options(
        "/mcp",
        headers={
            "Origin": "https://chatgpt.com",
            "Access-Control-Request-Method": "POST",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://chatgpt.com"


def test_metrics_include_mcp_surface_series(client, auth_headers, public_mcp_headers, internal_mcp_headers):
    """Prometheus metrics expose per-surface MCP traffic counters for hosted mounts."""

    client.get("/mcp", follow_redirects=False, headers=public_mcp_headers)
    client.get("/mcp-full", follow_redirects=False, headers=internal_mcp_headers)

    resp = client.get("/metrics", headers=auth_headers)

    assert resp.status_code == 200
    assert "am_mcp_surface_requests_total" in resp.text
    assert 'surface="public"' in resp.text
    assert 'surface="full"' in resp.text
    assert 'auth_surface="mcp_public"' in resp.text
    assert 'auth_surface="mcp_internal"' in resp.text


def test_openclaw_health_detailed_includes_runtime_component_statuses(client, auth_headers):
    """Detailed health exposes backend component records published at startup."""

    resp = client.get("/openclaw/health/detailed", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    components = {component["component"]: component for component in body["components"]}

    assert components["server"]["status"] == "healthy"
    assert components["server"]["details"]["app"] == "am-server"
    assert components["mcp"]["status"] == "available"
    assert components["mcp"]["details"]["surface_count"] >= 2
    assert any(surface["name"] == "public" for surface in components["mcp"]["details"]["surfaces"])
    assert any(surface["name"] == "full" for surface in components["mcp"]["details"]["surfaces"])
    assert components["openclaw_memory"]["status"] in {"healthy", "degraded"}
    assert components["openclaw_context_engine"]["status"] in {"healthy", "degraded"}


def test_public_mcp_tool_allowlist_excludes_internal_admin_tools():
    """Hosted/public plugin surfaces expose only the bounded public tool set."""
    assert "search_codebase" in PUBLIC_MCP_TOOL_NAMES
    assert "trace_execution_path" in PUBLIC_MCP_TOOL_NAMES
    assert "add_message" in PUBLIC_MCP_TOOL_NAMES
    assert "schedule_research" not in PUBLIC_MCP_TOOL_NAMES
    assert "get_git_file_history" not in PUBLIC_MCP_TOOL_NAMES
    assert "brave_search" not in PUBLIC_MCP_TOOL_NAMES


def test_full_mcp_tool_allowlist_keeps_internal_tooling():
    """Self-hosted/internal MCP surface keeps the broader tool contract."""
    assert "schedule_research" in FULL_MCP_TOOL_NAMES
    assert "get_git_file_history" in FULL_MCP_TOOL_NAMES
    assert "brave_search" in FULL_MCP_TOOL_NAMES


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


def test_product_status_returns_local_control_plane_summary(
    client, auth_headers, monkeypatch, tmp_path
):
    """GET /product/status returns persisted state plus runtime facts."""
    state_path = tmp_path / "product-state.json"
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))
    dependencies.get_product_store.cache_clear()

    resp = client.get("/product/status", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["state_path"] == str(state_path)
    assert body["summary"]["repo_count"] == 0
    assert body["runtime"]["server"]["status"] == "healthy"
    assert "connected" in body["runtime"]["graph"]


def test_product_repo_upsert_endpoint_tracks_repo(client, auth_headers, monkeypatch, tmp_path):
    """POST /product/repos stores a repo record and returns it."""
    state_path = tmp_path / "product-state.json"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_dir = repo_root / ".agentic-memory"
    config_dir.mkdir()
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))
    dependencies.get_product_store.cache_clear()

    resp = client.post(
        "/product/repos",
        json={"repo_path": str(repo_root), "label": "Dogfood Repo", "metadata": {"source": "cli"}},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["repo"]["label"] == "Dogfood Repo"
    assert body["repo"]["initialized"] is True


def test_product_integration_endpoint_tracks_integration(
    client, auth_headers, monkeypatch, tmp_path
):
    """POST /product/integrations stores an integration record."""
    state_path = tmp_path / "product-state.json"
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))
    dependencies.get_product_store.cache_clear()

    resp = client.post(
        "/product/integrations",
        json={
            "surface": "browser_extension",
            "target": "chatgpt",
            "status": "configured",
            "config": {"platform": "chatgpt"},
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["integration"]["surface"] == "browser_extension"
    assert body["integration"]["status"] == "configured"


class _FakeOpenClawStore:
    def __init__(self) -> None:
        self.integrations: list[dict] = []
        self.events: list[dict] = []
        self.bindings: dict[tuple[str, str, str], dict] = {}
        self.automations: list[dict] = []
        self.runtime_components = {
            "server": {"status": "healthy", "details": {}, "updated_at": "2026-04-11T20:00:00+00:00"},
            "openclaw_memory": {
                "status": "healthy",
                "details": {"mode": "capture_only"},
                "updated_at": "2026-04-11T20:00:00+00:00",
            },
        }

    def upsert_integration(self, *, surface, target, status, config, last_error=None):
        record = {
            "surface": surface,
            "target": target,
            "status": status,
            "config": config,
            "last_error": last_error,
        }
        self.integrations.append(record)
        return record

    def resolve_openclaw_session_id(
        self,
        *,
        workspace_id,
        agent_id,
        explicit_session_id=None,
        device_id=None,
    ):
        if explicit_session_id:
            return explicit_session_id

        for integration in reversed(self.integrations):
            config = integration.get("config", {})
            if config.get("workspace_id") != workspace_id:
                continue
            if config.get("agent_id") != agent_id:
                continue
            if device_id and config.get("device_id") != device_id:
                continue
            session_id = config.get("session_id")
            if session_id:
                return session_id
        return None

    def record_event(self, *, event_type, status="ok", actor="api", details=None):
        record = {
            "event_type": event_type,
            "status": status,
            "actor": actor,
            "details": details or {},
            "timestamp": "2026-04-11T20:00:00+00:00",
        }
        self.events.append(record)
        return record

    def activate_project_for_openclaw_identity(
        self,
        *,
        workspace_id,
        agent_id,
        session_id,
        project_id,
        device_id=None,
        title=None,
        metadata=None,
    ):
        record = {
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "device_id": device_id,
            "project_id": project_id,
            "title": title or project_id,
            "metadata": metadata or {},
        }
        self.bindings[(workspace_id, agent_id, session_id)] = record
        return record

    def deactivate_project_for_openclaw_identity(self, *, workspace_id, agent_id, session_id):
        return self.bindings.pop((workspace_id, agent_id, session_id), None)

    def get_active_project_for_openclaw_identity(self, *, workspace_id, agent_id, session_id):
        return self.bindings.get((workspace_id, agent_id, session_id))

    def upsert_project_automation(
        self,
        *,
        workspace_id,
        project_id,
        automation_kind,
        enabled,
        metadata=None,
    ):
        record = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "automation_kind": automation_kind,
            "enabled": enabled,
            "metadata": metadata or {},
        }
        self.automations.append(record)
        return record

    def status_payload(self, *, repo_root=None):
        return {
            "integrations": list(self.integrations),
            "active_projects": list(self.bindings.values()),
            "project_automations": list(self.automations),
            "events": list(self.events),
            "runtime": {"components": dict(self.runtime_components)},
            "summary": {
                "integration_count": len(self.integrations),
                "active_project_count": len(self.bindings),
                "project_automation_count": len(self.automations),
                "event_count": len(self.events),
            },
        }


def test_openclaw_session_register_updates_store_and_echoes_identity(
    client, auth_headers, monkeypatch
):
    """POST /openclaw/session/register records the shared identity contract."""
    fake_store = _FakeOpenClawStore()
    monkeypatch.setattr(openclaw, "get_product_store", lambda: fake_store)

    resp = client.post(
        "/openclaw/session/register",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "project_id": "project-1",
            "metadata": {"platform": "macos"},
            "context_engine": "agentic-memory",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["identity"]["workspace_id"] == "workspace-1"
    assert body["integration"]["target"] == "workspace-1:device-a:agent-x"
    assert body["event"]["event_type"] == "openclaw_session_registered"
    assert body["integration"]["config"]["mode"] == "capture_only"


def test_openclaw_project_endpoints_manage_session_scoped_binding(
    client, auth_headers, monkeypatch
):
    """Project activation and status are scoped to one session identity."""

    fake_store = _FakeOpenClawStore()
    fake_store.upsert_integration(
        surface="openclaw",
        target="workspace-1:device-a:agent-x",
        status="connected",
        config={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
        },
    )
    monkeypatch.setattr(openclaw, "get_product_store", lambda: fake_store)

    activate = client.post(
        "/openclaw/project/activate",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "project_id": "project-1",
            "metadata": {"source": "test"},
        },
    )
    assert activate.status_code == 200
    assert activate.json()["binding"]["project_id"] == "project-1"

    status = client.post(
        "/openclaw/project/status",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
        },
    )
    assert status.status_code == 200
    assert status.json()["active_project"]["project_id"] == "project-1"

    deactivate = client.post(
        "/openclaw/project/deactivate",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
        },
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["binding"]["project_id"] == "project-1"


def test_openclaw_project_endpoints_can_infer_session_id(client, auth_headers, monkeypatch):
    """Project lifecycle routes infer session id from the latest OpenClaw registration."""

    fake_store = _FakeOpenClawStore()
    fake_store.upsert_integration(
        surface="openclaw",
        target="workspace-1:device-a:agent-x",
        status="connected",
        config={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-inferred",
        },
    )
    monkeypatch.setattr(openclaw, "get_product_store", lambda: fake_store)

    activate = client.post(
        "/openclaw/project/activate",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "project_id": "project-1",
        },
    )

    assert activate.status_code == 200
    body = activate.json()
    assert body["identity"]["session_id"] == "session-inferred"
    assert body["binding"]["session_id"] == "session-inferred"


def test_openclaw_project_status_uses_cache_until_project_change(client, auth_headers, monkeypatch):
    """Repeated status lookups reuse the cached binding until mutation invalidates it."""

    fake_store = _FakeOpenClawStore()
    fake_store.upsert_integration(
        surface="openclaw",
        target="workspace-1:device-a:agent-x",
        status="connected",
        config={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
        },
    )
    fake_store.activate_project_for_openclaw_identity(
        workspace_id="workspace-1",
        agent_id="agent-x",
        session_id="session-1",
        device_id="device-a",
        project_id="project-1",
    )

    lookup_count = {"count": 0}
    original_lookup = fake_store.get_active_project_for_openclaw_identity

    def counting_lookup(**kwargs):
        lookup_count["count"] += 1
        return original_lookup(**kwargs)

    fake_store.get_active_project_for_openclaw_identity = counting_lookup  # type: ignore[method-assign]
    monkeypatch.setattr(openclaw, "get_product_store", lambda: fake_store)

    payload = {
        "workspace_id": "workspace-1",
        "device_id": "device-a",
        "agent_id": "agent-x",
        "session_id": "session-1",
    }

    first = client.post("/openclaw/project/status", headers=auth_headers, json=payload)
    second = client.post("/openclaw/project/status", headers=auth_headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["active_project"]["project_id"] == "project-1"
    assert second.json()["active_project"]["project_id"] == "project-1"
    assert lookup_count["count"] == 1

    deactivate = client.post("/openclaw/project/deactivate", headers=auth_headers, json=payload)
    assert deactivate.status_code == 200

    third = client.post("/openclaw/project/status", headers=auth_headers, json=payload)
    assert third.status_code == 200
    assert third.json()["active_project"] is None
    assert lookup_count["count"] == 2


def test_dashboard_metrics_summary_returns_cards_and_counts(client, auth_headers, monkeypatch):
    """Dashboard summary exposes operator-friendly counters from state + metrics."""

    fake_store = _FakeOpenClawStore()
    fake_store.upsert_integration(
        surface="openclaw",
        target="workspace-1:device-a:agent-x",
        status="connected",
        config={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "mode": "capture_only",
            "context_engine": "agentic-memory",
        },
    )
    monkeypatch.setattr(dashboard, "get_product_store", lambda: fake_store)
    monkeypatch.setattr(
        dashboard,
        "snapshot_metrics",
        lambda: {
            "request_counts": [
                {"method": "POST", "path": "/openclaw/memory/ingest-turn", "status_code": 202, "count": 3},
                {"method": "POST", "path": "/openclaw/memory/search", "status_code": 200, "count": 2},
                {"method": "POST", "path": "/openclaw/context/resolve", "status_code": 200, "count": 1},
            ],
            "duration_summaries": [
                {"method": "POST", "path": "/openclaw/memory/ingest-turn", "count": 3, "sum_seconds": 0.9, "avg_seconds": 0.3},
                {"method": "POST", "path": "/openclaw/memory/search", "count": 2, "sum_seconds": 0.6, "avg_seconds": 0.3},
                {"method": "POST", "path": "/openclaw/context/resolve", "count": 1, "sum_seconds": 0.4, "avg_seconds": 0.4},
            ],
            "error_counts": [
                {"code": "internal_server_error", "path": "/openclaw/memory/search", "status_code": 500, "count": 1}
            ],
        },
    )

    resp = client.get("/openclaw/metrics/summary", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["active_agents"] == 1
    assert body["summary"]["active_sessions"] == 1
    assert body["summary"]["turns_ingested"] == 3
    assert body["summary"]["searches_total"] == 2
    assert body["summary"]["context_resolves_total"] == 1
    assert body["summary"]["error_responses_total"] == 1
    assert body["summary"]["health_score"] == 95
    assert {card["key"] for card in body["summary"]["cards"]} == {
        "active_agents",
        "turns_ingested",
        "searches_total",
        "health_score",
    }


def test_dashboard_recent_searches_returns_latest_search_events(client, auth_headers, monkeypatch):
    """Recent-search endpoint reads the bounded OpenClaw event log in reverse order."""

    fake_store = _FakeOpenClawStore()
    fake_store.record_event(
        event_type="openclaw_memory_search",
        actor="openclaw",
        details={
            "workspace_id": "workspace-1",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "query": "first query",
            "result_count": 2,
        },
    )
    fake_store.record_event(
        event_type="openclaw_context_resolve",
        actor="openclaw",
        details={
            "workspace_id": "workspace-1",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "query": "second query",
            "result_count": 3,
            "project_id": "project-1",
        },
    )
    monkeypatch.setattr(dashboard, "get_product_store", lambda: fake_store)

    resp = client.get("/openclaw/search/recent?limit=2", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["returned"] == 2
    assert body["recent_searches"][0]["event_type"] == "openclaw_context_resolve"
    assert body["recent_searches"][0]["query"] == "second query"
    assert body["recent_searches"][1]["event_type"] == "openclaw_memory_search"


def test_dashboard_agent_sessions_and_workspaces_group_topology(client, auth_headers, monkeypatch):
    """Dashboard routes group OpenClaw registrations by agent and workspace/device tree."""

    fake_store = _FakeOpenClawStore()
    fake_store.upsert_integration(
        surface="openclaw",
        target="workspace-1:device-a:agent-x",
        status="connected",
        config={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "context_engine": "agentic-memory",
            "mode": "capture_only",
        },
    )
    fake_store.upsert_integration(
        surface="openclaw",
        target="workspace-1:device-b:agent-y",
        status="connected",
        config={
            "workspace_id": "workspace-1",
            "device_id": "device-b",
            "agent_id": "agent-y",
            "session_id": "session-2",
            "context_engine": "agentic-memory",
            "mode": "augment_context",
        },
    )
    fake_store.activate_project_for_openclaw_identity(
        workspace_id="workspace-1",
        agent_id="agent-x",
        session_id="session-1",
        project_id="project-1",
        device_id="device-a",
    )
    fake_store.upsert_project_automation(
        workspace_id="workspace-1",
        project_id="project-1",
        automation_kind="research_ingestion",
        enabled=True,
    )
    fake_store.record_event(
        event_type="openclaw_memory_search",
        actor="openclaw",
        details={
            "workspace_id": "workspace-1",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "query": "hello",
            "result_count": 1,
        },
    )
    monkeypatch.setattr(dashboard, "get_product_store", lambda: fake_store)

    sessions_resp = client.get(
        "/openclaw/agents/agent-x/sessions?workspace_id=workspace-1",
        headers=auth_headers,
    )
    assert sessions_resp.status_code == 200
    sessions = sessions_resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["project_id"] == "project-1"
    assert sessions[0]["event_count"] == 1

    workspaces_resp = client.get("/openclaw/workspaces", headers=auth_headers)
    assert workspaces_resp.status_code == 200
    body = workspaces_resp.json()
    assert body["summary"]["workspace_count"] == 1
    assert body["summary"]["device_count"] == 2
    assert body["summary"]["agent_count"] == 2
    assert body["workspaces"][0]["workspace_id"] == "workspace-1"
    assert len(body["workspaces"][0]["devices"]) == 2
    assert body["workspaces"][0]["active_projects"][0]["project_id"] == "project-1"
    assert body["workspaces"][0]["automations"][0]["automation_kind"] == "research_ingestion"


def test_openclaw_memory_ingest_turn_resolves_active_project(client, auth_headers, monkeypatch):
    """Turn ingest resolves the active session project server-side when omitted."""

    fake_store = _FakeOpenClawStore()
    fake_store.activate_project_for_openclaw_identity(
        workspace_id="workspace-1",
        agent_id="agent-x",
        session_id="session-1",
        device_id="device-a",
        project_id="project-1",
    )
    monkeypatch.setattr(openclaw, "get_product_store", lambda: fake_store)

    pipeline = dependencies.get_conversation_pipeline()
    pipeline.ingest.return_value = {"stored": True}

    resp = client.post(
        "/openclaw/memory/ingest-turn",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "role": "user",
            "content": "remember this under the active project",
            "turn_index": 4,
        },
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["effective_project_id"] == "project-1"
    passed = pipeline.ingest.call_args[0][0]
    assert passed["project_id"] == "project-1"
    assert passed["source_key"] == "chat_openclaw"


def test_openclaw_memory_search_uses_unified_search_contract(client, auth_headers, monkeypatch):
    """POST /openclaw/memory/search forwards the unified search inputs."""
    captured = {}
    fake_store = _FakeOpenClawStore()
    fake_store.activate_project_for_openclaw_identity(
        workspace_id="workspace-1",
        agent_id="agent-x",
        session_id="session-1",
        project_id="project-server-side",
    )
    monkeypatch.setattr(openclaw, "get_product_store", lambda: fake_store)

    monkeypatch.setattr(openclaw, "get_graph", lambda: object())
    monkeypatch.setattr(openclaw, "get_pipeline", lambda: "research-pipeline")
    monkeypatch.setattr(openclaw, "get_conversation_pipeline", lambda: "conversation-pipeline")

    def fake_search_all_memory_sync(**kwargs):
        captured.update(kwargs)
        return {
            "results": [
                {
                    "module": "conversation",
                    "source_id": "session-1:4",
                    "source_kind": "conversation_turn",
                    "title": "Relevant turn",
                    "score": 0.91,
                    "excerpt": "workspace memory hit",
                    "metadata": {"turn_index": 4},
                }
            ]
        }

    monkeypatch.setattr(openclaw, "search_all_memory_sync", fake_search_all_memory_sync)

    resp = client.post(
        "/openclaw/memory/search",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "query": "where did we leave off?",
            "limit": 7,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["identity"]["workspace_id"] == "workspace-1"
    assert body["results"][0]["title"] == "Relevant turn"
    assert body["results"][0]["path"] == "session-1:4"
    assert body["results"][0]["citation"] == "session-1:4#L5"
    assert captured["query"] == "where did we leave off?"
    assert captured["limit"] == 7
    assert captured["project_id"] == "project-server-side"


def test_openclaw_memory_search_reuses_cache_until_turn_ingest_invalidates(
    client, auth_headers, monkeypatch
):
    """Identical OpenClaw searches reuse the TTL cache until new memory arrives."""

    fake_store = _FakeOpenClawStore()
    fake_store.activate_project_for_openclaw_identity(
        workspace_id="workspace-1",
        agent_id="agent-x",
        session_id="session-1",
        device_id="device-a",
        project_id="project-cache",
    )
    monkeypatch.setattr(openclaw, "get_product_store", lambda: fake_store)
    monkeypatch.setattr(openclaw, "get_graph", lambda: object())
    monkeypatch.setattr(openclaw, "get_pipeline", lambda: "research-pipeline")

    pipeline = dependencies.get_conversation_pipeline()
    pipeline.ingest.return_value = {"stored": True}
    monkeypatch.setattr(openclaw, "get_conversation_pipeline", lambda: pipeline)

    search_call_count = {"count": 0}

    def fake_search_all_memory_sync(**kwargs):
        search_call_count["count"] += 1
        return {
            "results": [
                {
                    "module": "conversation",
                    "source_id": "session-1:4",
                    "source_kind": "conversation_turn",
                    "title": "Relevant turn",
                    "score": 0.91,
                    "excerpt": "workspace memory hit",
                    "metadata": {"turn_index": 4},
                }
            ]
        }

    monkeypatch.setattr(openclaw, "search_all_memory_sync", fake_search_all_memory_sync)

    search_payload = {
        "workspace_id": "workspace-1",
        "device_id": "device-a",
        "agent_id": "agent-x",
        "session_id": "session-1",
        "query": "where did we leave off?",
        "limit": 7,
    }

    first = client.post("/openclaw/memory/search", headers=auth_headers, json=search_payload)
    second = client.post("/openclaw/memory/search", headers=auth_headers, json=search_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True
    assert search_call_count["count"] == 1

    ingest = client.post(
        "/openclaw/memory/ingest-turn",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "turn_index": 5,
            "role": "assistant",
            "content": "new memory arrived",
        },
    )
    assert ingest.status_code == 202

    third = client.post("/openclaw/memory/search", headers=auth_headers, json=search_payload)
    assert third.status_code == 200
    assert third.json()["cache_hit"] is False
    assert search_call_count["count"] == 2


def test_openclaw_context_resolve_formats_context_blocks(client, auth_headers, monkeypatch):
    """POST /openclaw/context/resolve returns memory blocks plus prompt guidance."""
    monkeypatch.setattr(openclaw, "get_graph", lambda: object())
    monkeypatch.setattr(openclaw, "get_pipeline", lambda: "research-pipeline")
    monkeypatch.setattr(openclaw, "get_conversation_pipeline", lambda: "conversation-pipeline")
    monkeypatch.setattr(
        openclaw,
        "search_all_memory_sync",
        lambda **kwargs: {
            "results": [
                {
                    "module": "code",
                    "path": "src/example.py",
                    "score": 0.84,
                    "snippet": "useful memory snippet",
                }
            ]
        },
    )

    resp = client.post(
        "/openclaw/context/resolve",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "query": "find the relevant memory",
            "limit": 3,
            "context_engine": "agentic-memory",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["context_engine"] == "agentic-memory"
    assert body["context_blocks"][0]["title"] == "src/example.py"
    assert body["system_prompt_addition"]


def test_openclaw_validation_errors_use_machine_readable_envelope(client, auth_headers):
    """OpenClaw payload validation failures expose stable error metadata."""

    resp = client.post(
        "/openclaw/project/activate",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
        },
    )

    error = _assert_error_envelope(
        resp,
        code="validation_error",
        status_code=422,
        message_contains="Request validation failed.",
    )
    assert error["details"]


def test_openclaw_runtime_failures_use_machine_readable_envelope(
    client, auth_headers, monkeypatch
):
    """Unexpected OpenClaw backend failures are normalized by the app layer."""

    monkeypatch.setattr(openclaw, "get_graph", lambda: object())
    monkeypatch.setattr(openclaw, "get_pipeline", lambda: "research-pipeline")
    monkeypatch.setattr(openclaw, "get_conversation_pipeline", lambda: "conversation-pipeline")
    monkeypatch.setattr(
        openclaw,
        "search_all_memory_sync",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    resp = client.post(
        "/openclaw/memory/search",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "query": "where did we leave off?",
        },
    )

    error = _assert_error_envelope(
        resp,
        code="internal_server_error",
        status_code=500,
        message_contains="Internal server error.",
    )
    assert error["details"]["exception_type"] == "RuntimeError"


def test_openclaw_memory_read_returns_canonical_conversation_text(
    client, auth_headers, monkeypatch
):
    """POST /openclaw/memory/read hydrates a conversation turn by source id."""

    session = MagicMock()
    session.run.side_effect = [
        _single_result(
            {
                "session_id": "session-1",
                "turn_index": 4,
                "role": "assistant",
                "content": "Here is the canonical answer.",
                "project_id": "project-1",
                "workspace_id": "workspace-1",
                "device_id": "device-a",
                "agent_id": "agent-x",
                "source_agent": "openclaw",
                "timestamp": "2026-04-07T00:00:00+00:00",
                "ingested_at": "2026-04-07T00:00:00+00:00",
                "entities": ["OpenClaw"],
                "entity_types": ["technology"],
            }
        ),
        _iter_result(
            [
                {"turn_index": 3, "role": "user", "content": "What did we decide?"},
                {"turn_index": 5, "role": "assistant", "content": "We should ship the plugin."},
            ]
        ),
    ]
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = session
    session_ctx.__exit__.return_value = False

    fake_pipeline = MagicMock()
    fake_pipeline._conn.session.return_value = session_ctx
    monkeypatch.setattr(openclaw, "get_conversation_pipeline", lambda: fake_pipeline)

    resp = client.post(
        "/openclaw/memory/read",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "project_id": "project-1",
            "rel_path": "session-1:4#L5",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "session-1:4"
    assert body["source_kind"] == "conversation_turn"
    assert "[previous user turn #3]" in body["text"]
    assert "[matched assistant turn #4]" in body["text"]
    assert "[next assistant turn #5]" in body["text"]


def test_openclaw_memory_read_rejects_unsupported_paths(client, auth_headers):
    """POST /openclaw/memory/read rejects non-conversation canonical paths for now."""

    resp = client.post(
        "/openclaw/memory/read",
        headers=auth_headers,
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-a",
            "agent_id": "agent-x",
            "session_id": "session-1",
            "project_id": "project-1",
            "rel_path": "src/example.py",
        },
    )

    _assert_error_envelope(
        resp,
        code="not_found",
        status_code=404,
        message_contains="conversation-turn",
    )


def test_public_oauth_metadata_and_mcp_challenge(monkeypatch, tmp_path):
    """OAuth-enabled public MCP advertises metadata and a resource-aware Bearer challenge."""

    monkeypatch.setenv("AM_SERVER_API_KEY", "shared-api-key")
    monkeypatch.setenv("AM_SERVER_PUBLIC_OAUTH_ENABLED", "1")
    monkeypatch.setenv("AM_PUBLIC_BASE_URL", "https://mcp.agentmemorylabs.com")
    monkeypatch.setenv("AM_SERVER_OAUTH_BOOTSTRAP_USERS", "reviewer:secret-pass:ws_demo:Marketplace Reviewer")
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEYS", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))

    monkeypatch.setattr(
        oauth,
        "_fetch_client_metadata_document",
        lambda client_id: {
            "client_id": client_id,
            "redirect_uris": ["https://client.example/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as oauth_client:
        protected_resource = oauth_client.get("/.well-known/oauth-protected-resource")
        assert protected_resource.status_code == 200
        assert protected_resource.json()["resource"] == "https://mcp.agentmemorylabs.com"

        authorization_server = oauth_client.get("/.well-known/oauth-authorization-server")
        assert authorization_server.status_code == 200
        assert authorization_server.json()["authorization_endpoint"] == (
            "https://mcp.agentmemorylabs.com/oauth/authorize"
        )
        assert authorization_server.json()["registration_endpoint"] == (
            "https://mcp.agentmemorylabs.com/oauth/register"
        )

        missing_token = oauth_client.get("/mcp", follow_redirects=False)
        error = _assert_error_envelope(
            missing_token,
            code="auth_missing_api_key",
            status_code=401,
        )
        assert error["details"]["surface"] == "public"
        assert (
            missing_token.headers["WWW-Authenticate"]
            == 'Bearer realm="mcp", resource_metadata="https://mcp.agentmemorylabs.com/.well-known/oauth-protected-resource", scope="mcp:tools"'
        )


def test_public_oauth_authorization_code_flow_and_refresh(monkeypatch, tmp_path):
    """OAuth login, token exchange, refresh rotation, and MCP access all work end to end."""

    client_id = "https://client.example/metadata.json"
    redirect_uri = "https://client.example/callback"
    code_verifier = "reviewer-demo-verifier-123456789"
    code_challenge = oauth._pkce_s256(code_verifier)

    monkeypatch.setenv("AM_SERVER_API_KEY", "shared-api-key")
    monkeypatch.setenv("AM_SERVER_PUBLIC_OAUTH_ENABLED", "1")
    monkeypatch.setenv("AM_PUBLIC_BASE_URL", "https://mcp.agentmemorylabs.com")
    monkeypatch.setenv("AM_SERVER_OAUTH_BOOTSTRAP_USERS", "reviewer:secret-pass:ws_demo:Marketplace Reviewer")
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEYS", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))

    monkeypatch.setattr(
        oauth,
        "_fetch_client_metadata_document",
        lambda requested_client_id: {
            "client_id": requested_client_id,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as oauth_client:
        authorize_get = oauth_client.get(
            "/oauth/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "mcp:tools",
                "state": "opaque-state",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        assert authorize_get.status_code == 200
        assert "Agentic Memory Access" in authorize_get.text

        authorize_post = oauth_client.post(
            "/oauth/authorize",
            content=urlencode(
                {
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "mcp:tools",
                    "state": "opaque-state",
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "username": "reviewer",
                    "password": "secret-pass",
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert authorize_post.status_code == 302

        redirect_target = urlparse(authorize_post.headers["location"])
        redirect_query = parse_qs(redirect_target.query)
        assert redirect_target.scheme == "https"
        assert redirect_target.netloc == "client.example"
        assert redirect_query["state"] == ["opaque-state"]
        authorization_code = redirect_query["code"][0]

        token_response = oauth_client.post(
            "/oauth/token",
            content=urlencode(
                {
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "code": authorization_code,
                    "code_verifier": code_verifier,
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert token_response.status_code == 200
        token_payload = token_response.json()
        assert token_payload["token_type"] == "Bearer"
        assert token_payload["scope"] == "mcp:tools"

        public_mcp_response = oauth_client.get(
            "/mcp",
            follow_redirects=False,
            headers={"Authorization": f"Bearer {token_payload['access_token']}"},
        )
        assert public_mcp_response.status_code != 401
        assert public_mcp_response.headers["x-agentic-memory-mcp-auth-surface"] == "mcp_public"

        refresh_response = oauth_client.post(
            "/oauth/token",
            content=urlencode(
                {
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": token_payload["refresh_token"],
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert refresh_response.status_code == 200
        refresh_payload = refresh_response.json()
        assert refresh_payload["access_token"] != token_payload["access_token"]
        assert refresh_payload["refresh_token"] != token_payload["refresh_token"]

        old_refresh_response = oauth_client.post(
            "/oauth/token",
            content=urlencode(
                {
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": token_payload["refresh_token"],
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _assert_error_envelope(
            old_refresh_response,
            code="oauth_invalid_grant",
            status_code=400,
        )


def test_public_oauth_dynamic_client_registration_and_flow(monkeypatch, tmp_path):
    """Dynamic client registration issues a client id that works in the OAuth flow."""

    redirect_uri = "https://chatgpt.com/aip/example/oauth/callback"
    code_verifier = "chatgpt-dcr-verifier-987654321"

    monkeypatch.setenv("AM_SERVER_API_KEY", "shared-api-key")
    monkeypatch.setenv("AM_SERVER_PUBLIC_OAUTH_ENABLED", "1")
    monkeypatch.setenv("AM_PUBLIC_BASE_URL", "https://mcp.agentmemorylabs.com")
    monkeypatch.setenv("AM_SERVER_OAUTH_BOOTSTRAP_USERS", "reviewer:secret-pass:ws_demo:Marketplace Reviewer")
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_PUBLIC_MCP_API_KEYS", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.json"))

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()
    app = create_app()
    with TestClient(
        app,
        raise_server_exceptions=False,
        base_url="https://mcp.agentmemorylabs.com",
    ) as oauth_client:
        registration_response = oauth_client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT Developer Mode",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "mcp:tools",
            },
        )
        assert registration_response.status_code == 201
        registration_payload = registration_response.json()
        client_id = registration_payload["client_id"]
        assert client_id.startswith("oauth_client_")

        code_challenge = oauth._pkce_s256(code_verifier)
        authorize_post = oauth_client.post(
            "/oauth/authorize",
            content=urlencode(
                {
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "mcp:tools",
                    "state": "openai-state",
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "username": "reviewer",
                    "password": "secret-pass",
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert authorize_post.status_code == 302
        authorization_code = parse_qs(urlparse(authorize_post.headers["location"]).query)["code"][0]

        token_response = oauth_client.post(
            "/oauth/token",
            content=urlencode(
                {
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "code": authorization_code,
                    "code_verifier": code_verifier,
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert token_response.status_code == 200
        token_payload = token_response.json()
        assert token_payload["token_type"] == "Bearer"

        public_mcp_response = oauth_client.post(
            "/mcp-openai/",
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {token_payload['access_token']}",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "chatgpt-dev-mode", "version": "0.1.0"},
                },
            },
        )
        assert public_mcp_response.status_code == 200
        assert public_mcp_response.headers.get("mcp-session-id")
        assert "Agentic Memory Public" in public_mcp_response.text

        tools_list_response = oauth_client.post(
            "/mcp-openai/",
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {token_payload['access_token']}",
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": str(public_mcp_response.headers["mcp-session-id"]),
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools_list_response.status_code == 200
        assert "search_codebase" in tools_list_response.text
