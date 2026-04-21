"""Unit tests for research retrieval plus learned reranking."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from agentic_memory.server import research_search
from agentic_memory.server.reranking import RerankResponse, RerankScore

pytestmark = [pytest.mark.unit]


def _make_pipeline(rows: list[dict[str, object]]) -> Mock:
    pipeline = Mock()
    pipeline._embedder = Mock()
    pipeline._embedder.embed.return_value = [0.1] * 768
    mock_run = Mock()
    mock_run.data.return_value = rows
    mock_session = Mock()
    mock_session.run.return_value = mock_run
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = mock_session
    session_ctx.__exit__.return_value = False
    pipeline._conn = Mock()
    pipeline._conn.session.return_value = session_ctx
    pipeline._extractor = Mock()
    pipeline._temporal_bridge = Mock()
    pipeline._temporal_bridge.is_available.return_value = False
    return pipeline


def test_search_research_applies_reranking_to_baseline_rows(monkeypatch):
    pipeline = _make_pipeline(
        [
            {
                "text": "Baseline alpha",
                "score": 0.91,
                "source_agent": "claude",
                "research_question": "Alpha?",
                "confidence": "high",
                "source_key": "deep_research_agent",
                "content_hash": "alpha",
                "project_id": "proj1",
                "node_labels": ["Memory", "Research", "Finding"],
            },
            {
                "text": "Baseline beta",
                "score": 0.82,
                "source_agent": "claude",
                "research_question": "Beta?",
                "confidence": "medium",
                "source_key": "deep_research_agent",
                "content_hash": "beta",
                "project_id": "proj1",
                "node_labels": ["Memory", "Research", "Finding"],
            },
        ]
    )

    monkeypatch.setattr(
        research_search,
        "rerank_documents",
        lambda query, documents, high_stakes=False: RerankResponse(
            applied=True,
            provider="cohere",
            model="rerank-v4.0-fast",
            scores=[
                RerankScore(index=1, relevance_score=0.96),
                RerankScore(index=0, relevance_score=0.25),
            ],
        ),
    )

    rows = research_search.search_research(
        pipeline,
        query="beta answer",
        limit=2,
        as_of=None,
    )

    assert [row["text"] for row in rows] == ["Baseline beta", "Baseline alpha"]
    assert rows[0]["rerank_score"] == pytest.approx(0.96)
    assert rows[0]["retrieval_provenance"]["reranker_applied"] is True
    assert rows[0]["retrieval_provenance"]["mode"] == "dense_only"
