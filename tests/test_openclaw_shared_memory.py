"""Stress-oriented verification for OpenClaw-style shared memory behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_memory.product.state import ProductStateStore
from am_server import dependencies
from am_server.models import ProductEventRequest, ProductIntegrationUpsertRequest, ProductRepoUpsertRequest
from am_server.routes import product as product_routes
from tests.openclaw_harness import build_openclaw_workload

pytestmark = [pytest.mark.unit, pytest.mark.slow]


def test_openclaw_shared_workspace_stress_preserves_identity(tmp_path):
    """A shared workspace should retain device and agent identity under load."""
    store = ProductStateStore(tmp_path / "product-state.json")
    workload = build_openclaw_workload(
        workspace_id="workspace-alpha",
        devices=3,
        agents_per_device=4,
        turns_per_agent=5,
    )

    for turn in workload:
        store.record_event(
            event_type="openclaw_turn_received",
            actor="openclaw",
            details=turn.event_details(),
        )

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".agentic-memory").mkdir()
    (repo_root / ".agentic-memory" / "config.json").write_text("{}", encoding="utf-8")
    store.upsert_repo(str(repo_root), label="Workspace Repo", metadata=workload[0].repo_metadata())
    store.upsert_integration(
        surface="openclaw",
        target="memory",
        status="configured",
        config={
            "workspace_id": workload[0].identity.workspace_id,
            "device_id": workload[0].identity.device_id,
            "agent_id": workload[0].identity.agent_id,
            "mode": "memory-only",
        },
    )

    payload = store.status_payload(repo_root=repo_root)
    assert payload["summary"]["event_count"] == len(workload)
    assert payload["summary"]["repo_count"] == 1
    assert payload["summary"]["integration_count"] == 1
    assert payload["repo"]["record"]["metadata"]["workspace_id"] == "workspace-alpha"
    assert payload["repo"]["record"]["metadata"]["device_id"] == "device-1"
    assert payload["repo"]["record"]["metadata"]["agent_id"] == "agent-1-1"

    recorded = store.load()["events"]
    workspace_ids = {event["details"]["workspace_id"] for event in recorded}
    device_ids = {event["details"]["device_id"] for event in recorded}
    agent_ids = {event["details"]["agent_id"] for event in recorded}

    assert workspace_ids == {"workspace-alpha"}
    assert device_ids == {"device-1", "device-2", "device-3"}
    assert len(agent_ids) == 12
    assert recorded[-1]["details"]["device_id"] == "device-3"
    assert recorded[-1]["details"]["agent_id"] == "agent-3-4"


@pytest.mark.asyncio
async def test_openclaw_product_routes_preserve_identity_metadata(monkeypatch, tmp_path):
    """The current product routes must carry OpenClaw identity metadata through unchanged."""
    state_path = tmp_path / "product-state.json"
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))
    dependencies.get_product_store.cache_clear()

    store = ProductStateStore(state_path)
    monkeypatch.setattr(product_routes, "get_product_store", lambda: store)
    monkeypatch.setattr(product_routes, "get_graph", lambda: object())
    monkeypatch.setattr(product_routes, "_SELECTORS_PATH", tmp_path / "selectors.json")

    event_resp = await product_routes.record_product_event(
        ProductEventRequest(
            event_type="openclaw_turn_received",
            status="ok",
            actor="openclaw",
            details={
                "workspace_id": "workspace-beta",
                "device_id": "device-9",
                "agent_id": "agent-9-1",
                "session_id": "workspace-beta:device-9:agent-9-1",
            },
        )
    )
    assert event_resp["event"]["details"]["workspace_id"] == "workspace-beta"
    assert event_resp["event"]["details"]["device_id"] == "device-9"
    assert event_resp["event"]["details"]["agent_id"] == "agent-9-1"

    integration_resp = await product_routes.upsert_product_integration(
        ProductIntegrationUpsertRequest(
            surface="openclaw",
            target="context_engine",
            status="configured",
            config={
                "workspace_id": "workspace-beta",
                "device_id": "device-9",
                "agent_id": "agent-9-1",
                "enabled": True,
            },
        )
    )
    assert integration_resp["integration"]["config"]["enabled"] is True

    repo_root = tmp_path / "workspace"
    repo_root.mkdir()
    (repo_root / ".agentic-memory").mkdir()
    (repo_root / ".agentic-memory" / "config.json").write_text("{}", encoding="utf-8")
    repo_resp = await product_routes.upsert_product_repo(
        ProductRepoUpsertRequest(
            repo_path=str(repo_root),
            label="Workspace Beta",
            metadata={
                "workspace_id": "workspace-beta",
                "device_id": "device-9",
                "agent_id": "agent-9-1",
            },
        )
    )
    assert repo_resp["repo"]["metadata"]["workspace_id"] == "workspace-beta"

    status_resp = await product_routes.product_status(repo_path=str(repo_root))
    assert status_resp["summary"]["repo_count"] == 1
    assert status_resp["repo"]["record"]["metadata"]["workspace_id"] == "workspace-beta"
    assert status_resp["runtime"]["server"]["status"] == "healthy"
