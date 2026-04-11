"""Failure-injection harnesses for OpenClaw routes.

These tests are intentionally narrow: they inject transient failures at the
route boundary and verify that the API recovers without corrupting local state
or poisoning later successful requests.
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
    """Return the shared auth header used by the chaos harness."""

    return {"Authorization": "Bearer test-key"}


def _reset_metrics() -> None:
    """Clear in-process metrics so chaos assertions see only current failures."""

    with server_metrics._LOCK:  # type: ignore[attr-defined]
        server_metrics._REQUEST_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._REQUEST_DURATION_SUMS.clear()  # type: ignore[attr-defined]
        server_metrics._REQUEST_DURATION_COUNTS.clear()  # type: ignore[attr-defined]
        server_metrics._ERROR_COUNTS.clear()  # type: ignore[attr-defined]


@pytest.fixture()
def openclaw_chaos_harness(monkeypatch, tmp_path):
    """Return a client plus mutable state for transient-failure injection."""

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

    turn_records: list[dict[str, object]] = []

    def fake_ingest(payload: dict[str, object]) -> dict[str, object]:
        if "reject" in str(payload["content"]).lower():
            raise ValueError("turn rejected by harness")
        turn_records.append(dict(payload))
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

    search_attempts = {"count": 0}

    def flaky_search_all_memory_sync(
        *,
        query: str,
        limit: int,
        **_: object,
    ) -> dict[str, object]:
        search_attempts["count"] += 1
        if search_attempts["count"] == 1:
            raise RuntimeError("temporary search failure")
        return {
            "results": [
                {
                    "source_id": "workspace-chaos:laptop-01:agent-chaos:1",
                    "title": "Recovered turn",
                    "content": f"Recovered search result for {query}",
                    "score": 0.77,
                    "module": "conversation",
                    "metadata": {"turn_index": 1},
                }
            ][:limit]
        }

    monkeypatch.setattr(openclaw, "search_all_memory_sync", flaky_search_all_memory_sync)

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield {
            "client": client,
            "turn_records": turn_records,
            "search_attempts": search_attempts,
        }

    dependencies.get_pipeline.cache_clear()
    dependencies.get_conversation_pipeline.cache_clear()
    dependencies.get_product_store.cache_clear()


def _register_identity(client: TestClient) -> None:
    """Create one OpenClaw session + active project for the chaos scenarios."""

    headers = _auth_headers()
    register_response = client.post(
        "/openclaw/session/register",
        headers=headers,
        json={
            "workspace_id": "workspace-chaos",
            "device_id": "laptop-01",
            "agent_id": "agent-chaos",
            "session_id": "workspace-chaos:laptop-01:agent-chaos",
        },
    )
    assert register_response.status_code == 200

    activate_response = client.post(
        "/openclaw/project/activate",
        headers=headers,
        json={
            "workspace_id": "workspace-chaos",
            "device_id": "laptop-01",
            "agent_id": "agent-chaos",
            "project_id": "project-chaos",
        },
    )
    assert activate_response.status_code == 200


def test_openclaw_chaos_search_recovers_after_transient_failure(openclaw_chaos_harness):
    """A transient search failure should not prevent later successful requests."""

    client = openclaw_chaos_harness["client"]
    headers = _auth_headers()
    _register_identity(client)

    failed_search = client.post(
        "/openclaw/memory/search",
        headers=headers,
        json={
            "workspace_id": "workspace-chaos",
            "device_id": "laptop-01",
            "agent_id": "agent-chaos",
            "session_id": "workspace-chaos:laptop-01:agent-chaos",
            "query": "recovery",
        },
    )
    assert failed_search.status_code == 500
    assert failed_search.json()["error"]["code"] == "internal_server_error"

    recovered_search = client.post(
        "/openclaw/memory/search",
        headers=headers,
        json={
            "workspace_id": "workspace-chaos",
            "device_id": "laptop-01",
            "agent_id": "agent-chaos",
            "session_id": "workspace-chaos:laptop-01:agent-chaos",
            "query": "recovery",
        },
    )
    assert recovered_search.status_code == 200
    assert recovered_search.json()["results"][0]["content"].startswith("Recovered search result")

    context_response = client.post(
        "/openclaw/context/resolve",
        headers=headers,
        json={
            "workspace_id": "workspace-chaos",
            "device_id": "laptop-01",
            "agent_id": "agent-chaos",
            "session_id": "workspace-chaos:laptop-01:agent-chaos",
            "query": "recovery",
        },
    )
    assert context_response.status_code == 200
    assert context_response.json()["context_blocks"]

    summary_response = client.get("/openclaw/metrics/summary", headers=headers)
    assert summary_response.status_code == 200
    summary = summary_response.json()["summary"]
    assert summary["searches_total"] == 1
    assert summary["context_resolves_total"] == 1
    assert summary["error_responses_total"] >= 1

    recent_response = client.get("/openclaw/search/recent?limit=5", headers=headers)
    assert recent_response.status_code == 200
    recent_events = recent_response.json()["recent_searches"]
    assert recent_events[0]["event_type"] == "openclaw_context_resolve"
    assert sum(event["event_type"] == "openclaw_memory_search" for event in recent_events) == 2


def test_openclaw_chaos_ingest_validation_failure_does_not_block_followup(openclaw_chaos_harness):
    """A rejected turn should not poison later successful ingest requests."""

    client = openclaw_chaos_harness["client"]
    headers = _auth_headers()
    _register_identity(client)

    rejected_turn = client.post(
        "/openclaw/memory/ingest-turn",
        headers=headers,
        json={
            "workspace_id": "workspace-chaos",
            "device_id": "laptop-01",
            "agent_id": "agent-chaos",
            "session_id": "workspace-chaos:laptop-01:agent-chaos",
            "turn_index": 0,
            "role": "user",
            "content": "reject this turn",
        },
    )
    assert rejected_turn.status_code == 422
    assert rejected_turn.json()["error"]["code"] == "validation_error"

    accepted_turn = client.post(
        "/openclaw/memory/ingest-turn",
        headers=headers,
        json={
            "workspace_id": "workspace-chaos",
            "device_id": "laptop-01",
            "agent_id": "agent-chaos",
            "session_id": "workspace-chaos:laptop-01:agent-chaos",
            "turn_index": 1,
            "role": "assistant",
            "content": "accepted follow-up turn",
        },
    )
    assert accepted_turn.status_code == 202
    assert accepted_turn.json()["effective_project_id"] == "project-chaos"

    summary_response = client.get("/openclaw/metrics/summary", headers=headers)
    assert summary_response.status_code == 200
    summary = summary_response.json()["summary"]
    assert summary["turns_ingested"] == 1
    assert summary["error_responses_total"] >= 1
