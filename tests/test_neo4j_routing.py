"""Tests for OpenClaw operator vs shared Neo4j routing."""

from am_server.neo4j_routing import (
    operator_neo4j_configured,
    operator_workspace_ids,
    use_operator_neo4j,
)


def test_operator_routing_off_by_default(monkeypatch):
    monkeypatch.delenv("AM_OPERATOR_WORKSPACE_IDS", raising=False)
    monkeypatch.delenv("NEO4J_OPERATOR_URI", raising=False)
    operator_workspace_ids.cache_clear()
    assert not operator_neo4j_configured()
    assert not use_operator_neo4j("any-workspace")


def test_operator_routing_matches_workspace(monkeypatch):
    monkeypatch.setenv("NEO4J_OPERATOR_URI", "bolt://127.0.0.1:7667")
    monkeypatch.setenv("AM_OPERATOR_WORKSPACE_IDS", "ws-alpha, ws-beta")
    operator_workspace_ids.cache_clear()
    assert operator_neo4j_configured()
    assert use_operator_neo4j("ws-alpha")
    assert use_operator_neo4j("ws-beta")
    assert not use_operator_neo4j("other")
