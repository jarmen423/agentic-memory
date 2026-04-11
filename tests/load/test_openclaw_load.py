"""Load-style OpenClaw workflow verification.

This harness is not a benchmark. Its job is to simulate a denser OpenClaw
workspace shape than the focused contract tests do, then verify that the
dashboard summary and workspace topology stay coherent under many sessions and
turn ingests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from am_server import dependencies, metrics as server_metrics
from am_server.app import create_app
from am_server.routes import openclaw
from tests.openclaw_harness import build_openclaw_workload

pytestmark = [pytest.mark.unit, pytest.mark.slow]


def _auth_headers() -> dict[str, str]:
    """Return the shared auth header used by the load harness."""

    return {"Authorization": "Bearer test-key"}


def _reset_metrics() -> None:
    """Clear global in-process metrics so load assertions stay deterministic."""

    with server_metrics._LOCK:  # type: ignore[attr-defined]
        server_metrics._REQUEST_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._REQUEST_DURATION_SUMS.clear()  # type: ignore[attr-defined]
        server_metrics._REQUEST_DURATION_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._ERROR_COUNTS.clear()  # type: ignore[attr-defined]


@pytest.fixture()
def openclaw_load_client(monkeypatch, tmp_path):
    """Return a client whose search results are derived from ingested turns."""

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

    ingested_turns: list[dict[str, object]] = []

    def fake_ingest(payload: dict[str, object]) -> dict[str, object]:
        ingested_turns.append(dict(payload))
        return {
            "stored": True,
            "source_id": f"{payload['session_id']}:{payload['turn_index']}",
        }

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
        matching = [
            turn
            for turn in ingested_turns
            if lowered_query in str(turn["content"]).lower()
            and (project_id is None or turn.get("project_id") == project_id)
        ][:limit]
        return {
            "results": [
                {
                    "source_id": f"{turn['session_id']}:{turn['turn_index']}",
                    "title": f"Turn {turn['turn_index']}",
                    "content": str(turn["content"]),
                    "score": 0.8,
                    "module": "conversation",
                    "metadata": {"turn_index": int(turn["turn_index"])},
                }
                for turn in matching
            ]
        }

    monkeypatch.setattr(openclaw, "search_all_memory_sync", fake_search_all_memory_sync)

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield {"client": client, "ingested_turns": ingested_turns}

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()


def test_openclaw_load_harness_keeps_dashboard_counts_consistent(openclaw_load_client):
    """A larger workspace should still produce coherent summary and topology data."""

    client = openclaw_load_client["client"]
    headers = _auth_headers()
    workload = build_openclaw_workload(
        workspace_id="workspace-load",
        devices=3,
        agents_per_device=4,
        turns_per_agent=5,
    )

    registered_sessions: set[str] = set()
    project_by_session: dict[str, str] = {}

    for turn in workload:
        identity = turn.identity
        if identity.session_id not in registered_sessions:
            register_response = client.post(
                "/openclaw/session/register",
                headers=headers,
                json={
                    "workspace_id": identity.workspace_id,
                    "device_id": identity.device_id,
                    "agent_id": identity.agent_id,
                    "session_id": identity.session_id,
                    "mode": "capture_only",
                    "context_engine": "agentic-memory",
                },
            )
            assert register_response.status_code == 200

            project_id = f"project-{identity.device_id}-{identity.agent_id}"
            project_by_session[identity.session_id] = project_id
            activate_response = client.post(
                "/openclaw/project/activate",
                headers=headers,
                json={
                    "workspace_id": identity.workspace_id,
                    "device_id": identity.device_id,
                    "agent_id": identity.agent_id,
                    "project_id": project_id,
                },
            )
            assert activate_response.status_code == 200
            registered_sessions.add(identity.session_id)

        ingest_response = client.post(
            "/openclaw/memory/ingest-turn",
            headers=headers,
            json={
                "workspace_id": identity.workspace_id,
                "device_id": identity.device_id,
                "agent_id": identity.agent_id,
                "session_id": identity.session_id,
                "turn_index": turn.turn_index,
                "role": "assistant",
                "content": turn.content,
                "source_agent": "openclaw",
            },
        )
        assert ingest_response.status_code == 202
        assert ingest_response.json()["effective_project_id"] == project_by_session[identity.session_id]

    unique_sessions = sorted(registered_sessions)
    for session_id in unique_sessions:
        workspace_id, device_id, agent_id = session_id.split(":", 2)
        query = agent_id
        search_response = client.post(
            "/openclaw/memory/search",
            headers=headers,
            json={
                "workspace_id": workspace_id,
                "device_id": device_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "query": query,
                "limit": 10,
            },
        )
        assert search_response.status_code == 200
        search_body = search_response.json()
        assert search_body["results"]
        assert search_body["identity"]["project_id"] == project_by_session[session_id]

    summary_response = client.get("/openclaw/metrics/summary", headers=headers)
    assert summary_response.status_code == 200
    summary = summary_response.json()["summary"]
    assert summary["active_agents"] == 12
    assert summary["active_sessions"] == 12
    assert summary["turns_ingested"] == len(workload)
    assert summary["searches_total"] == len(unique_sessions)

    workspaces_response = client.get("/openclaw/workspaces", headers=headers)
    assert workspaces_response.status_code == 200
    workspaces_body = workspaces_response.json()
    assert workspaces_body["summary"]["workspace_count"] == 1
    assert workspaces_body["summary"]["device_count"] == 3
    assert workspaces_body["summary"]["agent_count"] == 12
    assert len(workspaces_body["workspaces"][0]["active_projects"]) == 12

    recent_response = client.get("/openclaw/search/recent?limit=5", headers=headers)
    assert recent_response.status_code == 200
    recent_body = recent_response.json()
    assert recent_body["summary"]["returned"] == 5
    assert all(item["workspace_id"] == "workspace-load" for item in recent_body["recent_searches"])
