"""Unit tests for the Python TemporalBridge JSON-lines client."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest


def _make_process(*responses: str) -> MagicMock:
    process = MagicMock()
    process.stdin = MagicMock()
    process.stdout = MagicMock()
    process.stdout.readline.side_effect = list(responses)
    process.stderr = io.StringIO("")
    process.poll.return_value = None
    process.wait.return_value = 0
    return process


def test_temporal_bridge_reuses_single_process(monkeypatch):
    """Bridge starts lazily and reuses one child process across requests."""
    from agentic_memory.temporal.bridge import TemporalBridge

    monkeypatch.setenv("STDB_BINDINGS_MODULE", "generated-bindings/index.ts")
    monkeypatch.setattr("agentic_memory.temporal.bridge.shutil.which", lambda _name: "npx")
    process = _make_process(
        '{"ok": true, "results": [], "timingsMs": {"total": 1.0}}\n',
        '{"ok": true, "subjectName": "Agentic Memory"}\n',
    )
    popen = MagicMock(return_value=process)
    monkeypatch.setattr("agentic_memory.temporal.bridge.subprocess.Popen", popen)

    bridge = TemporalBridge.from_env()
    assert bridge.is_available() is True

    bridge.retrieve(project_id="proj-1", seed_entities=[{"name": "Neo4j", "kind": "technology"}])
    bridge.ingest_claim(
        project_id="proj-1",
        subject_name="Agentic Memory",
        predicate="USES",
        object_name="Neo4j",
        evidence={"sourceKind": "research_finding", "sourceId": "deep_research_agent:abc"},
    )

    assert popen.call_count == 1
    assert process.stdin.write.call_count == 2

    bridge.close()


def test_temporal_bridge_raises_structured_error(monkeypatch):
    """Structured helper errors become TemporalBridgeError exceptions."""
    from agentic_memory.temporal.bridge import TemporalBridge, TemporalBridgeError

    monkeypatch.setenv("STDB_BINDINGS_MODULE", "generated-bindings/index.ts")
    monkeypatch.setattr("agentic_memory.temporal.bridge.shutil.which", lambda _name: "npx")
    process = _make_process(
        '{"ok": false, "error": {"message": "boom", "code": "bridge_error"}}\n',
    )
    monkeypatch.setattr(
        "agentic_memory.temporal.bridge.subprocess.Popen",
        MagicMock(return_value=process),
    )

    bridge = TemporalBridge.from_env()

    with pytest.raises(TemporalBridgeError, match="boom"):
        bridge.retrieve(project_id="proj-1", seed_entities=[{"name": "Neo4j"}])

    bridge.close()


def test_get_temporal_bridge_returns_cached_singleton(monkeypatch):
    """get_temporal_bridge returns one cached bridge instance."""
    import agentic_memory.temporal.bridge as bridge_module

    monkeypatch.setenv("STDB_BINDINGS_MODULE", "generated-bindings/index.ts")
    monkeypatch.setattr("agentic_memory.temporal.bridge.shutil.which", lambda _name: "npx")
    monkeypatch.setattr(
        "agentic_memory.temporal.bridge.subprocess.Popen",
        MagicMock(return_value=_make_process('{"ok": true}\n')),
    )
    monkeypatch.setattr(bridge_module, "_BRIDGE_SINGLETON", None)

    first = bridge_module.get_temporal_bridge()
    second = bridge_module.get_temporal_bridge()

    assert first is second
    first.close()
    monkeypatch.setattr(bridge_module, "_BRIDGE_SINGLETON", None)


def test_temporal_bridge_missing_env_is_unavailable(monkeypatch):
    """Missing STDB bindings config disables the bridge without crashing callers."""
    from agentic_memory.temporal.bridge import TemporalBridge, TemporalBridgeUnavailableError

    monkeypatch.delenv("STDB_BINDINGS_MODULE", raising=False)

    bridge = TemporalBridge.from_env()

    assert bridge.is_available() is False
    assert bridge.disabled_reason is not None
    with pytest.raises(TemporalBridgeUnavailableError):
        bridge.retrieve(project_id="proj-1", seed_entities=[{"name": "Neo4j"}])
