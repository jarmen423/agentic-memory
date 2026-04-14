"""Unit tests for conversation retrieval plus learned reranking."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from agentic_memory.server import tools
from agentic_memory.server.reranking import RerankResponse, RerankScore

pytestmark = [pytest.mark.unit]


def test_search_conversation_turns_sync_applies_reranking(monkeypatch):
    pipeline = Mock()
    pipeline._conn = Mock()
    pipeline._embedder = Mock()
    pipeline._extractor = Mock()
    pipeline._temporal_bridge = Mock()
    pipeline._temporal_bridge.is_available.return_value = False

    monkeypatch.setattr(
        tools,
        "_vector_conversation_search",
        lambda *args, **kwargs: [
            {
                "session_id": "s1",
                "turn_index": 0,
                "role": "assistant",
                "content": "baseline alpha",
                "source_agent": "claude",
                "timestamp": "2026-03-01T00:00:00+00:00",
                "ingested_at": "2026-03-01T00:00:00+00:00",
                "entities": ["alpha"],
                "score": 0.91,
            },
            {
                "session_id": "s1",
                "turn_index": 1,
                "role": "assistant",
                "content": "baseline beta",
                "source_agent": "claude",
                "timestamp": "2026-03-01T00:01:00+00:00",
                "ingested_at": "2026-03-01T00:01:00+00:00",
                "entities": ["beta"],
                "score": 0.73,
            },
        ],
    )
    monkeypatch.setattr(
        tools,
        "rerank_documents",
        lambda query, documents, high_stakes=False: RerankResponse(
            applied=True,
            provider="cohere",
            model="rerank-v4.0-fast",
            scores=[
                RerankScore(index=1, relevance_score=0.98),
                RerankScore(index=0, relevance_score=0.11),
            ],
        ),
    )

    rows = tools.search_conversation_turns_sync(
        pipeline,
        query="beta turn",
        project_id=None,
        role=None,
        limit=2,
        as_of=None,
        log_prefix="test.conversation",
    )

    assert [row["content"] for row in rows] == ["baseline beta", "baseline alpha"]
    assert rows[0]["rerank_score"] == pytest.approx(0.98)
    assert rows[0]["retrieval_provenance"]["reranker_applied"] is True
    assert rows[0]["retrieval_provenance"]["mode"] == "dense_only"
