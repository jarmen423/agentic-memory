"""Tests for local product-state storage used by CLI and am-server."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_memory.product.state import ProductStateStore

pytestmark = [pytest.mark.unit]


def test_product_state_defaults_and_touch(monkeypatch, tmp_path):
    """New stores return defaults and persist a last-seen timestamp on touch()."""
    state_path = tmp_path / "product-state.json"
    monkeypatch.setenv("CODEMEMORY_PRODUCT_STATE", str(state_path))

    store = ProductStateStore()
    state = store.load()

    assert state["schema_version"] == 1
    assert state["runtime"]["components"]["cli"]["status"] == "available"

    touched = store.touch()
    assert touched["app"]["last_seen_at"]
    assert state_path.exists()


def test_product_state_upsert_repo_tracks_initialized_repo(tmp_path):
    """Repo upserts resolve the path and capture codememory init status."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    codememory_dir = repo_root / ".codememory"
    codememory_dir.mkdir()
    (codememory_dir / "config.json").write_text("{}", encoding="utf-8")

    store = ProductStateStore(tmp_path / "state.json")
    repo = store.upsert_repo(str(repo_root), label="Main Repo", metadata={"source": "dogfood"})

    assert repo["path"] == str(repo_root.resolve())
    assert repo["label"] == "Main Repo"
    assert repo["initialized"] is True
    assert repo["metadata"] == {"source": "dogfood"}


def test_product_state_upsert_integration_updates_existing_record(tmp_path):
    """Integration records are keyed by surface+target and update in place."""
    store = ProductStateStore(tmp_path / "state.json")
    store.upsert_integration(
        surface="mcp",
        target="claude_desktop",
        status="configured",
        config={"command": "codememory"},
    )
    updated = store.upsert_integration(
        surface="mcp",
        target="claude_desktop",
        status="healthy",
        config={"command": "codememory", "repo": "demo"},
    )

    payload = store.load()
    assert len(payload["integrations"]) == 1
    assert updated["status"] == "healthy"
    assert updated["config"]["repo"] == "demo"


def test_product_state_records_events_with_cap(tmp_path):
    """Event storage is capped so install-loop logging cannot grow forever."""
    store = ProductStateStore(tmp_path / "state.json")
    for index in range(205):
        store.record_event(event_type=f"event_{index}", actor="cli")

    payload = store.load()
    assert len(payload["events"]) == 200
    assert payload["events"][0]["event_type"] == "event_5"


def test_product_state_rejects_unknown_component(tmp_path):
    """Component status updates validate component names."""
    store = ProductStateStore(tmp_path / "state.json")

    with pytest.raises(ValueError):
        store.set_component_status("unsupported", status="healthy")


def test_product_state_tracks_openclaw_active_project_by_session(tmp_path):
    """Active projects are session-scoped so one agent can switch tasks cleanly."""

    store = ProductStateStore(tmp_path / "state.json")
    binding = store.activate_project_for_openclaw_identity(
        workspace_id="work-home",
        agent_id="claw-main",
        session_id="sess-1",
        device_id="laptop-01",
        project_id="project-alpha",
        metadata={"source": "test"},
    )

    assert binding["project_id"] == "project-alpha"
    assert (
        store.get_active_project_for_openclaw_identity(
            workspace_id="work-home",
            agent_id="claw-main",
            session_id="sess-1",
        )["project_id"]
        == "project-alpha"
    )
    assert (
        store.get_active_project_for_openclaw_identity(
            workspace_id="work-home",
            agent_id="claw-main",
            session_id="sess-2",
        )
        is None
    )


def test_product_state_can_clear_active_project_binding(tmp_path):
    """Deactivation removes only the requested session binding."""

    store = ProductStateStore(tmp_path / "state.json")
    store.activate_project_for_openclaw_identity(
        workspace_id="work-home",
        agent_id="claw-main",
        session_id="sess-1",
        project_id="project-alpha",
    )
    removed = store.deactivate_project_for_openclaw_identity(
        workspace_id="work-home",
        agent_id="claw-main",
        session_id="sess-1",
    )

    assert removed["project_id"] == "project-alpha"
    assert (
        store.get_active_project_for_openclaw_identity(
            workspace_id="work-home",
            agent_id="claw-main",
            session_id="sess-1",
        )
        is None
    )


def test_product_state_tracks_workspace_scoped_project_automation(tmp_path):
    """Project automation records are keyed by workspace and reusable project id."""

    store = ProductStateStore(tmp_path / "state.json")
    automation = store.upsert_project_automation(
        workspace_id="work-home",
        project_id="project-alpha",
        enabled=True,
        metadata={"schedule": "daily"},
    )

    payload = store.load()
    assert automation["automation_kind"] == "research_ingestion"
    assert payload["project_automations"][0]["workspace_id"] == "work-home"
    assert payload["projects"][0]["project_id"] == "project-alpha"
