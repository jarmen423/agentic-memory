"""TDD test suite for am_server FastAPI REST API.

Covers all must-have truths from 02-04-PLAN.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from am_server import dependencies
from am_server.app import create_app
from am_server.routes import openclaw


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
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", "/tmp/am-product-state.json")

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
        "Invalid source_key 'manual_test'. Must be one of: ['chat_cli', 'chat_ext', 'chat_mcp', 'chat_openclaw', 'chat_proxy']"
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

    assert resp.status_code == 404
    assert "conversation-turn" in resp.json()["detail"]
