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
from agentic_memory.server.result_types import UnifiedMemoryHit, UnifiedSearchResponse
from agentic_memory.server.temporal_contract import TemporalRetrievalRequiredError


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
    with openclaw._CACHE_LOCK:  # type: ignore[attr-defined]
        openclaw._PROJECT_STATUS_CACHE.clear()  # type: ignore[attr-defined]
        openclaw._SEARCH_CACHE.clear()  # type: ignore[attr-defined]

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


def test_openclaw_onboarding_contract_is_public_and_matches_locked_identity(client):
    """Plugin doctor should be able to inspect the onboarding contract pre-auth."""

    response = client.get("/health/onboarding")

    assert response.status_code == 200
    body = response.json()
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
    assert any(service["service_id"] == "openclaw_memory" for service in body["required_services"])
    assert any(service["service_id"] == "temporal_stack" for service in body["optional_services"])


def test_openclaw_openapi_includes_tool_bridge_routes():
    """The generated OpenAPI spec should advertise every plugin-facing tool route.

    This catches a specific failure mode from the OpenClaw integration work:
    the plugin can register tools successfully, but if the deployed backend is
    still on an older revision the `/openclaw/tools/*` handlers are missing and
    every tool call fails with `404 Not Found`.
    """

    spec = create_app().openapi()
    paths = spec["paths"]

    assert "/openclaw/memory/search" in paths
    assert "/openclaw/tools/search-codebase" in paths
    assert "/openclaw/tools/get-file-dependencies" in paths
    assert "/openclaw/tools/trace-execution-path" in paths
    assert "/openclaw/tools/search-conversations" in paths
    assert "/openclaw/tools/get-conversation-context" in paths


def test_openclaw_contract_managed_workspace_keys_are_workspace_scoped(monkeypatch, tmp_path):
    """Managed hosted keys should only authorize requests for their bound workspace."""

    monkeypatch.delenv("AM_SERVER_API_KEY", raising=False)
    monkeypatch.delenv("AM_SERVER_API_KEYS", raising=False)
    monkeypatch.setenv("AGENTIC_MEMORY_DEPLOYMENT_MODE", "managed")
    monkeypatch.setenv("AGENTIC_MEMORY_HOSTED_BASE_URL", "https://memory.example.com")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "managed-product-state.json"))

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
    with openclaw._CACHE_LOCK:  # type: ignore[attr-defined]
        openclaw._PROJECT_STATUS_CACHE.clear()  # type: ignore[attr-defined]
        openclaw._SEARCH_CACHE.clear()  # type: ignore[attr-defined]

    store = dependencies.get_product_store()
    store.issue_hosted_workspace_api_key(
        workspace_id="workspace-1",
        label="managed beta key",
        raw_token="workspace-managed-key",
    )

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        allowed = test_client.post(
            "/openclaw/session/register",
            headers={"Authorization": "Bearer workspace-managed-key"},
            json={
                "workspace_id": "workspace-1",
                "device_id": "device-1",
                "agent_id": "agent-1",
                "session_id": "session-1",
            },
        )
        assert allowed.status_code == 200

        denied = test_client.post(
            "/openclaw/session/register",
            headers={"Authorization": "Bearer workspace-managed-key"},
            json={
                "workspace_id": "workspace-2",
                "device_id": "device-1",
                "agent_id": "agent-1",
                "session_id": "session-1",
            },
        )

    _assert_error_envelope(
        denied,
        code="workspace_access_denied",
        status_code=403,
        message_contains="bound to a different workspace",
    )


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

    monkeypatch.setattr(openclaw, "graph_for_openclaw_workspace", lambda workspace_id: object())
    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", "conversation"),
    )

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


def test_openclaw_memory_search_serializes_unified_response_dataclass(client, monkeypatch):
    """OpenClaw memory search should handle dataclass responses without 500s.

    The unified search service returns a ``UnifiedSearchResponse`` dataclass, not
    a raw dict. This test protects the adapter layer that serializes that object
    before it normalizes individual hits for the OpenClaw plugin shape.
    """

    monkeypatch.setattr(openclaw, "graph_for_openclaw_workspace", lambda workspace_id: object())
    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", "conversation"),
    )
    monkeypatch.setattr(
        openclaw,
        "search_all_memory_sync",
        lambda **kwargs: UnifiedSearchResponse(
            results=[
                UnifiedMemoryHit(
                    module="conversation",
                    source_kind="conversation_turn",
                    source_id="session-1:0",
                    title="Assistant turn",
                    excerpt="hello from memory",
                    score=0.9,
                    metadata={"turn_index": 0},
                )
            ],
            errors=[],
        ),
    )

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

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["path"] == "session-1:0"
    assert body["results"][0]["citation"] == "session-1:0#L1"
    assert body["response"]["results"][0]["source_id"] == "session-1:0"


def test_openclaw_tool_bridge_awaits_decorated_tool_results(client, monkeypatch):
    """Tool bridge routes should await MCP-wrapped tool functions before returning.

    The Agentic Memory MCP layer wraps tool functions in an async telemetry
    decorator. Importing those callables directly into FastAPI routes means the
    route must await them, even when the underlying tool logic is synchronous.
    """

    async def fake_search_codebase(**kwargs):
        return "## Code Search\n\nAwaited successfully."

    monkeypatch.setattr(
        "agentic_memory.server.app.search_codebase",
        fake_search_codebase,
    )

    response = client.post(
        "/openclaw/tools/search-codebase",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "query": "memory",
            "repo_id": "agentic-memory",
        },
    )

    assert response.status_code == 200
    assert "Awaited successfully." in response.json()["text"]


def test_openclaw_conversation_tool_temporal_failures_return_503(client, monkeypatch):
    """Temporal contract failures should stay explicit on OpenClaw conversation routes."""

    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", MagicMock()),
    )

    def raise_temporal(*args, **kwargs):
        raise TemporalRetrievalRequiredError(
            module="conversation",
            reason="project_scope_missing",
            message="Temporal-first conversation retrieval requires a project scope.",
        )

    monkeypatch.setattr(
        "agentic_memory.server.tools.search_conversation_turns_sync",
        raise_temporal,
    )

    response = client.post(
        "/openclaw/tools/search-conversations",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "project_id": "agentic-memory",
            "query": "memory",
        },
    )

    error = _assert_error_envelope(
        response,
        code="temporal_retrieval_unavailable",
        status_code=503,
        message_contains="requires a project scope",
    )
    assert error["details"]["module"] == "conversation"


def test_openclaw_tool_project_lookup_falls_back_to_latest_registered_session(
    client,
    monkeypatch,
):
    """Tool routes should recover project scope when the SDK only exposes a synthetic session id.

    The OpenClaw tool bridge currently falls back to session ids such as
    ``alfred:tools`` when the SDK omits the live runtime session id. The backend
    should re-resolve the latest registered session for that workspace/agent/device
    tuple before it gives up on active-project lookup.
    """

    store = dependencies.get_product_store()
    store.upsert_integration(
        surface="openclaw",
        target="workspace-1:agent-1:device-1",
        status="connected",
        config={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-real",
        },
    )
    store.activate_project_for_openclaw_identity(
        workspace_id="workspace-1",
        device_id="device-1",
        agent_id="agent-1",
        session_id="session-real",
        project_id="agentic-memory",
    )

    captured: dict[str, object] = {}

    def fake_search(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", MagicMock()),
    )
    monkeypatch.setattr(
        "agentic_memory.server.tools.search_conversation_turns_sync",
        fake_search,
    )

    response = client.post(
        "/openclaw/tools/search-conversations",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "agent-1:tools",
            "query": "memory",
        },
    )

    assert response.status_code == 200
    assert response.json()["identity"]["project_id"] == "agentic-memory"
    assert captured["project_id"] == "agentic-memory"


def test_openclaw_tool_conversation_search_without_project_stays_best_effort(
    client,
    monkeypatch,
):
    """General conversation search should not require an active project.

    OpenClaw can accumulate free-form chat memory outside any project. Those
    searches should still use dense/text baselines instead of failing closed on
    the temporal graph contract.
    """

    captured: dict[str, object] = {}

    def fake_search(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", MagicMock()),
    )
    monkeypatch.setattr(
        "agentic_memory.server.tools.search_conversation_turns_sync",
        fake_search,
    )

    response = client.post(
        "/openclaw/tools/search-conversations",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "query": "memory",
        },
    )

    assert response.status_code == 200
    assert response.json()["identity"]["project_id"] is None
    assert captured["project_id"] is None
    assert captured["temporal_required"] is False


def test_openclaw_tool_conversation_search_ignores_unknown_identity_shaped_project_id(
    client,
    monkeypatch,
):
    """Ignore LLM-invented project ids that only mirror the current identity.

    OpenClaw models sometimes guess ``project_id`` by copying ``workspace_id``
    or ``agent_id``. Those values should not force temporal retrieval unless
    the backend already knows them as real projects.
    """

    captured: dict[str, object] = {}

    def fake_search(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", MagicMock()),
    )
    monkeypatch.setattr(
        "agentic_memory.server.tools.search_conversation_turns_sync",
        fake_search,
    )

    response = client.post(
        "/openclaw/tools/search-conversations",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "project_id": "workspace-1",
            "query": "memory",
        },
    )

    assert response.status_code == 200
    assert response.json()["identity"]["project_id"] is None
    assert captured["project_id"] is None
    assert captured["temporal_required"] is False


def test_openclaw_tool_conversation_search_keeps_registered_identity_shaped_project_id(
    client,
    monkeypatch,
):
    """Honor identity-shaped project ids once the store knows they are real."""

    store = dependencies.get_product_store()
    store.upsert_project(project_id="workspace-1", title="Workspace One")

    captured: dict[str, object] = {}

    def fake_search(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", MagicMock()),
    )
    monkeypatch.setattr(
        "agentic_memory.server.tools.search_conversation_turns_sync",
        fake_search,
    )

    response = client.post(
        "/openclaw/tools/search-conversations",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "project_id": "workspace-1",
            "query": "memory",
        },
    )

    assert response.status_code == 200
    assert response.json()["identity"]["project_id"] == "workspace-1"
    assert captured["project_id"] == "workspace-1"
    assert captured["temporal_required"] is True


def test_openclaw_memory_search_without_project_avoids_temporal_fail_closed(
    client,
    monkeypatch,
):
    """Unified memory search should stay best-effort when no project is active."""

    captured: dict[str, object] = {}

    def fake_unified_search(**kwargs):
        captured.update(kwargs)
        return UnifiedSearchResponse(results=[], errors=[])

    monkeypatch.setattr(openclaw, "graph_for_openclaw_workspace", lambda workspace_id: object())
    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", "conversation"),
    )
    monkeypatch.setattr(openclaw, "search_all_memory_sync", fake_unified_search)

    response = client.post(
        "/openclaw/memory/search",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "query": "memory",
            "modules": ["conversation"],
        },
    )

    assert response.status_code == 200
    assert response.json()["identity"]["project_id"] is None
    assert captured["project_id"] is None
    assert captured["fail_on_temporal_errors"] is False


def test_openclaw_memory_search_ignores_unknown_identity_shaped_project_id(
    client,
    monkeypatch,
):
    """Unified search should not fail closed on a hallucinated project id."""

    captured: dict[str, object] = {}

    def fake_unified_search(**kwargs):
        captured.update(kwargs)
        return UnifiedSearchResponse(results=[], errors=[])

    monkeypatch.setattr(openclaw, "graph_for_openclaw_workspace", lambda workspace_id: object())
    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", "conversation"),
    )
    monkeypatch.setattr(openclaw, "search_all_memory_sync", fake_unified_search)

    response = client.post(
        "/openclaw/memory/search",
        headers={"Authorization": "Bearer new-key"},
        json={
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "project_id": "agent-1",
            "query": "memory",
            "modules": ["conversation"],
        },
    )

    assert response.status_code == 200
    assert response.json()["identity"]["project_id"] is None
    assert captured["project_id"] is None
    assert captured["fail_on_temporal_errors"] is False


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


def test_openclaw_contract_metrics_include_domain_series(client, monkeypatch):
    """Authenticated `/metrics` should expose the Phase 14 OpenClaw domain metrics."""

    mock_conversation_pipeline = dependencies.get_conversation_pipeline()
    mock_conversation_pipeline.ingest.return_value = {"stored": True}
    monkeypatch.setattr(openclaw, "graph_for_openclaw_workspace", lambda workspace_id: object())
    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", mock_conversation_pipeline),
    )
    monkeypatch.setattr(
        openclaw,
        "search_all_memory_sync",
        lambda **kwargs: {"results": []},
    )

    headers = {"Authorization": "Bearer new-key"}
    identity = {
        "workspace_id": "workspace-1",
        "device_id": "device-1",
        "agent_id": "agent-1",
        "session_id": "session-1",
    }

    register_response = client.post("/openclaw/session/register", headers=headers, json=identity)
    assert register_response.status_code == 200

    ingest_response = client.post(
        "/openclaw/memory/ingest-turn",
        headers=headers,
        json={
            **identity,
            "turn_index": 0,
            "role": "assistant",
            "content": "hello from the domain metrics test",
            "source_key": "chat_openclaw",
        },
    )
    assert ingest_response.status_code == 202

    search_response = client.post(
        "/openclaw/memory/search",
        headers=headers,
        json={
            **identity,
            "query": "hello",
            "modules": ["conversation"],
        },
    )
    assert search_response.status_code == 200

    context_response = client.post(
        "/openclaw/context/resolve",
        headers=headers,
        json={
            **identity,
            "query": "hello",
            "context_engine": "agentic-memory",
        },
    )
    assert context_response.status_code == 200

    metrics_response = client.get("/metrics", headers=headers)

    assert metrics_response.status_code == 200
    assert "am_ingest_turns_total" in metrics_response.text
    assert 'workspace_id="workspace-1"' in metrics_response.text
    assert 'agent_id="agent-1"' in metrics_response.text
    assert 'source_key="chat_openclaw"' in metrics_response.text
    assert "am_search_requests_total" in metrics_response.text
    assert 'module="conversation"' in metrics_response.text
    assert "am_search_latency_seconds_count" in metrics_response.text
    assert "am_context_resolve_latency_seconds_count" in metrics_response.text
    assert "am_active_sessions" in metrics_response.text


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

    monkeypatch.setattr(openclaw, "graph_for_openclaw_workspace", lambda workspace_id: object())
    monkeypatch.setattr(
        openclaw,
        "pipelines_for_openclaw_workspace",
        lambda workspace_id: ("research", "conversation"),
    )
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
