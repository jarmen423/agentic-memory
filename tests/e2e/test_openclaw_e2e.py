"""End-to-end OpenClaw workflow verification.

These tests intentionally exercise the public REST surface as a stitched user
flow instead of checking one route at a time. The goal for Phase 13 is to
prove that the OpenClaw identity contract, project binding, memory readback,
and dashboard read APIs all agree on the same state transitions.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from am_server import dependencies, metrics as server_metrics
from am_server.app import create_app
from am_server.routes import openclaw

pytestmark = [pytest.mark.unit, pytest.mark.slow]


def _auth_headers() -> dict[str, str]:
    """Return the shared auth header used by the OpenClaw test clients."""

    return {"Authorization": "Bearer test-key"}


def _reset_metrics() -> None:
    """Clear in-process metrics so each harness asserts its own request totals."""

    with server_metrics._LOCK:  # type: ignore[attr-defined]
        server_metrics._REQUEST_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._REQUEST_DURATION_SUMS.clear()  # type: ignore[attr-defined]
        server_metrics._REQUEST_DURATION_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._ERROR_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._MCP_SURFACE_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._OPENCLAW_INGEST_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._OPENCLAW_INGEST_ERROR_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._OPENCLAW_SEARCH_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._OPENCLAW_SEARCH_LATENCY_SUMS.clear()  # type: ignore[attr-defined]
        server_metrics._OPENCLAW_SEARCH_LATENCY_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._OPENCLAW_CONTEXT_RESOLVE_SUMS.clear()  # type: ignore[attr-defined]
        server_metrics._OPENCLAW_CONTEXT_RESOLVE_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._OPENCLAW_ACTIVE_SESSIONS.clear()  # type: ignore[attr-defined]


@pytest.fixture()
def openclaw_e2e_harness(monkeypatch, tmp_path):
    """Create a backend app with deterministic in-memory search/read behavior.

    The real product routes depend on Neo4j-backed pipelines. For this harness
    we replace those heavy integrations with small deterministic fakes so the
    test can focus on the end-to-end REST contract:

    1. OpenClaw registers a session.
    2. The operator activates a project for that live session.
    3. Turns are ingested through the public memory endpoint.
    4. Search, canonical read, and context resolution all point back to the
       same stored conversation data.
    """

    monkeypatch.delenv("AM_SERVER_API_KEY", raising=False)
    monkeypatch.setenv("AM_SERVER_API_KEYS", "test-key")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(tmp_path / "product-state.sqlite"))

    _reset_metrics()
    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()
    with openclaw._CACHE_LOCK:  # type: ignore[attr-defined]
        openclaw._PROJECT_STATUS_CACHE.clear()  # type: ignore[attr-defined]
        openclaw._SEARCH_CACHE.clear()  # type: ignore[attr-defined]

    stored_turns: list[dict[str, object]] = []
    turns_by_source_id: dict[str, dict[str, object]] = {}

    def fake_ingest(payload: dict[str, object]) -> dict[str, object]:
        source_id = f"{payload['session_id']}:{payload['turn_index']}"
        stored = {**payload, "source_id": source_id}
        stored_turns.append(stored)
        turns_by_source_id[source_id] = stored
        return {"stored": True, "source_id": source_id}

    conversation_pipeline = MagicMock()
    conversation_pipeline.ingest.side_effect = fake_ingest
    research_pipeline = MagicMock()

    monkeypatch.setattr(
        "am_server.dependencies.ResearchIngestionPipeline",
        lambda *args, **kwargs: research_pipeline,
    )
    monkeypatch.setattr(
        "am_server.dependencies.ConversationIngestionPipeline",
        lambda *args, **kwargs: conversation_pipeline,
    )
    monkeypatch.setattr(openclaw, "get_graph", lambda: object())

    def fake_search_all_memory_sync(
        *,
        query: str,
        limit: int,
        project_id: str | None,
        **_: object,
    ) -> dict[str, object]:
        lowered_query = query.lower()
        matched = [
            turn
            for turn in stored_turns
            if lowered_query in str(turn["content"]).lower()
            and (project_id is None or turn.get("project_id") == project_id)
        ][:limit]
        return {
            "results": [
                {
                    "source_id": str(turn["source_id"]),
                    "title": f"Turn {turn['turn_index']}",
                    "content": str(turn["content"]),
                    "score": 0.98,
                    "module": "conversation",
                    "metadata": {"turn_index": int(turn["turn_index"])},
                }
                for turn in matched
            ]
        }

    def fake_fetch_turn(
        _conversation_pipeline: object,
        *,
        source_id: str,
        **_: object,
    ) -> dict[str, object] | None:
        turn = turns_by_source_id.get(source_id)
        if turn is None:
            return None
        return {
            "session_id": str(turn["session_id"]),
            "turn_index": int(turn["turn_index"]),
            "role": str(turn["role"]),
            "content": str(turn["content"]),
            "project_id": turn.get("project_id"),
            "workspace_id": str(turn["workspace_id"]),
            "device_id": str(turn["device_id"]),
            "agent_id": str(turn["agent_id"]),
            "source_agent": str(turn.get("source_agent") or "openclaw"),
            "timestamp": turn.get("timestamp"),
            "ingested_at": None,
            "entities": [],
            "entity_types": [],
        }

    def fake_fetch_neighbors(
        _conversation_pipeline: object,
        *,
        session_id: str,
        turn_index: int,
        **_: object,
    ) -> list[dict[str, object]]:
        neighbors = [
            turn
            for turn in stored_turns
            if turn["session_id"] == session_id and abs(int(turn["turn_index"]) - turn_index) == 1
        ]
        neighbors.sort(key=lambda turn: int(turn["turn_index"]))
        return [
            {
                "turn_index": int(turn["turn_index"]),
                "role": str(turn["role"]),
                "content": str(turn["content"]),
            }
            for turn in neighbors
        ]

    monkeypatch.setattr(openclaw, "search_all_memory_sync", fake_search_all_memory_sync)
    monkeypatch.setattr(openclaw, "_fetch_conversation_turn_by_source_id", fake_fetch_turn)
    monkeypatch.setattr(openclaw, "_fetch_conversation_neighbors", fake_fetch_neighbors)

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield {"client": client, "stored_turns": stored_turns}

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()


def test_openclaw_e2e_flow_preserves_identity_and_canonical_readback(openclaw_e2e_harness):
    """The public OpenClaw workflow should preserve one coherent identity chain."""

    client = openclaw_e2e_harness["client"]
    headers = _auth_headers()

    register_response = client.post(
        "/openclaw/session/register",
        headers=headers,
        json={
            "workspace_id": "workspace-e2e",
            "device_id": "laptop-01",
            "agent_id": "agent-e2e",
            "session_id": "workspace-e2e:laptop-01:agent-e2e",
            "mode": "capture_only",
            "context_engine": "agentic-memory",
        },
    )
    assert register_response.status_code == 200

    activate_response = client.post(
        "/openclaw/project/activate",
        headers=headers,
        json={
            "workspace_id": "workspace-e2e",
            "device_id": "laptop-01",
            "agent_id": "agent-e2e",
            "project_id": "proj-e2e",
            "title": "OpenClaw auth investigation",
        },
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["binding"]["project_id"] == "proj-e2e"
    assert activate_response.json()["identity"]["session_id"] == "workspace-e2e:laptop-01:agent-e2e"

    first_turn = client.post(
        "/openclaw/memory/ingest-turn",
        headers=headers,
        json={
            "workspace_id": "workspace-e2e",
            "device_id": "laptop-01",
            "agent_id": "agent-e2e",
            "session_id": "workspace-e2e:laptop-01:agent-e2e",
            "turn_index": 0,
            "role": "user",
            "content": "Where does auth normalization happen in the server?",
            "source_agent": "openclaw",
        },
    )
    second_turn = client.post(
        "/openclaw/memory/ingest-turn",
        headers=headers,
        json={
            "workspace_id": "workspace-e2e",
            "device_id": "laptop-01",
            "agent_id": "agent-e2e",
            "session_id": "workspace-e2e:laptop-01:agent-e2e",
            "turn_index": 1,
            "role": "assistant",
            "content": "Auth normalization happens in the FastAPI exception middleware.",
            "source_agent": "openclaw",
        },
    )
    assert first_turn.status_code == 202
    assert second_turn.status_code == 202
    assert first_turn.json()["effective_project_id"] == "proj-e2e"

    search_response = client.post(
        "/openclaw/memory/search",
        headers=headers,
        json={
            "workspace_id": "workspace-e2e",
            "device_id": "laptop-01",
            "agent_id": "agent-e2e",
            "session_id": "workspace-e2e:laptop-01:agent-e2e",
            "query": "exception middleware",
            "limit": 5,
        },
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["identity"]["project_id"] == "proj-e2e"
    assert search_body["results"]
    canonical_path = search_body["results"][0]["path"]

    read_response = client.post(
        "/openclaw/memory/read",
        headers=headers,
        json={
            "workspace_id": "workspace-e2e",
            "device_id": "laptop-01",
            "agent_id": "agent-e2e",
            "session_id": "workspace-e2e:laptop-01:agent-e2e",
            "rel_path": canonical_path,
        },
    )
    assert read_response.status_code == 200
    read_body = read_response.json()
    assert "[matched assistant turn #1]" in read_body["text"]
    assert "[previous user turn #0]" in read_body["text"]

    context_response = client.post(
        "/openclaw/context/resolve",
        headers=headers,
        json={
            "workspace_id": "workspace-e2e",
            "device_id": "laptop-01",
            "agent_id": "agent-e2e",
            "session_id": "workspace-e2e:laptop-01:agent-e2e",
            "query": "auth normalization",
            "limit": 3,
            "context_engine": "agentic-memory",
        },
    )
    assert context_response.status_code == 200
    context_body = context_response.json()
    assert context_body["system_prompt_addition"]
    assert context_body["context_blocks"]
    assert context_body["search"]["identity"]["project_id"] == "proj-e2e"

    recent_response = client.get("/openclaw/search/recent?limit=5", headers=headers)
    assert recent_response.status_code == 200
    recent_events = recent_response.json()["recent_searches"]
    assert recent_events[0]["event_type"] == "openclaw_context_resolve"
    assert any(event["event_type"] == "openclaw_memory_search" for event in recent_events)

    sessions_response = client.get(
        "/openclaw/agents/agent-e2e/sessions?workspace_id=workspace-e2e",
        headers=headers,
    )
    assert sessions_response.status_code == 200
    assert sessions_response.json()["sessions"][0]["event_count"] >= 3

    workspaces_response = client.get("/openclaw/workspaces", headers=headers)
    assert workspaces_response.status_code == 200
    workspace = workspaces_response.json()["workspaces"][0]
    assert workspace["workspace_id"] == "workspace-e2e"
    assert workspace["active_projects"][0]["project_id"] == "proj-e2e"

    metrics_summary = client.get("/openclaw/metrics/summary", headers=headers)
    assert metrics_summary.status_code == 200
    summary = metrics_summary.json()["summary"]
    assert summary["active_agents"] == 1
    assert summary["active_sessions"] == 1
    assert summary["turns_ingested"] == 2
    assert summary["searches_total"] == 1
    assert summary["context_resolves_total"] == 1
