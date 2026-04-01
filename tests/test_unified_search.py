"""Unit tests for the unified cross-module search service."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from codememory.server.result_types import UnifiedMemoryHit
from codememory.server.unified_search import search_all_memory_sync

pytestmark = [pytest.mark.unit]


def test_search_all_memory_merges_and_sorts_hits(monkeypatch):
    """Unified search merges hits and orders by normalized score."""
    monkeypatch.setattr(
        "codememory.server.unified_search._normalize_code_results",
        lambda graph, query, limit: [
            UnifiedMemoryHit(
                module="code",
                source_kind="code_entity",
                source_id="sig:1",
                title="Code Hit",
                excerpt="code excerpt",
                score=0.51,
            )
        ],
    )
    monkeypatch.setattr(
        "codememory.server.unified_search._search_research_structured",
        lambda pipeline, query, limit, as_of: [
            UnifiedMemoryHit(
                module="web",
                source_kind="research_finding",
                source_id="finding:1",
                title="Research Hit",
                excerpt="research excerpt",
                score=0.93,
                temporal_applied=True,
            )
        ],
    )
    monkeypatch.setattr(
        "codememory.server.unified_search._search_conversation_structured",
        lambda pipeline, query, project_id, limit, as_of: [
            UnifiedMemoryHit(
                module="conversation",
                source_kind="conversation_turn",
                source_id="sess:0",
                title="Conversation Hit",
                excerpt="conversation excerpt",
                score=0.74,
            )
        ],
    )

    payload = search_all_memory_sync(
        query="neo4j",
        graph=MagicMock(),
        research_pipeline=MagicMock(),
        conversation_pipeline=MagicMock(),
    )

    assert [hit.module for hit in payload.results] == ["web", "conversation", "code"]
    assert payload.errors == []


def test_search_all_memory_records_partial_module_failures(monkeypatch):
    """One module failure does not suppress healthy module results."""
    monkeypatch.setattr(
        "codememory.server.unified_search._normalize_code_results",
        lambda graph, query, limit: (_ for _ in ()).throw(RuntimeError("code down")),
    )
    monkeypatch.setattr(
        "codememory.server.unified_search._search_research_structured",
        lambda pipeline, query, limit, as_of: [
            UnifiedMemoryHit(
                module="web",
                source_kind="research_finding",
                source_id="finding:1",
                title="Research Hit",
                excerpt="research excerpt",
                score=0.9,
            )
        ],
    )

    payload = search_all_memory_sync(
        query="neo4j",
        graph=MagicMock(),
        research_pipeline=MagicMock(),
        conversation_pipeline=None,
    )

    assert len(payload.results) == 1
    assert payload.results[0].module == "web"
    assert payload.errors == [{"module": "code", "message": "code down"}]


def test_search_all_memory_honors_module_filters(monkeypatch):
    """Requested modules limit which backends run."""
    code_called = False
    web_called = False
    conv_called = False

    def _code(*args, **kwargs):
        nonlocal code_called
        code_called = True
        return []

    def _web(*args, **kwargs):
        nonlocal web_called
        web_called = True
        return []

    def _conv(*args, **kwargs):
        nonlocal conv_called
        conv_called = True
        return []

    monkeypatch.setattr("codememory.server.unified_search._normalize_code_results", _code)
    monkeypatch.setattr("codememory.server.unified_search._search_research_structured", _web)
    monkeypatch.setattr("codememory.server.unified_search._search_conversation_structured", _conv)

    search_all_memory_sync(
        query="neo4j",
        modules=["web", "conversation"],
        graph=MagicMock(),
        research_pipeline=MagicMock(),
        conversation_pipeline=MagicMock(),
    )

    assert code_called is False
    assert web_called is True
    assert conv_called is True
