"""Unit tests for the shared reranking foundation."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from agentic_memory.server import reranking

pytestmark = [pytest.mark.unit]


def test_rerank_documents_disabled_returns_noop(monkeypatch):
    monkeypatch.delenv("AM_RERANK_ENABLED", raising=False)

    response = reranking.rerank_documents("capital", ["doc-a", "doc-b"])

    assert response.applied is False
    assert response.fallback_reason == "disabled"


def test_rerank_documents_calls_cohere_v2_api(monkeypatch):
    monkeypatch.setenv("AM_RERANK_ENABLED", "1")
    monkeypatch.setenv("COHERE_API_KEY", "test-key")

    mock_http_response = Mock()
    mock_http_response.status_code = 200
    mock_http_response.raise_for_status = Mock()
    mock_http_response.json.return_value = {
        "results": [
            {"index": 1, "relevance_score": 0.97},
            {"index": 0, "relevance_score": 0.31},
        ]
    }
    mock_client = Mock()
    mock_client.post.return_value = mock_http_response
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_client
    mock_ctx.__exit__.return_value = False
    monkeypatch.setattr(reranking.httpx, "Client", Mock(return_value=mock_ctx))

    response = reranking.rerank_documents("capital", ["doc-a", "doc-b"])

    assert response.applied is True
    assert response.provider == "cohere"
    assert response.model == "rerank-v4.0-fast"
    assert [score.index for score in response.scores] == [1, 0]
    assert response.top_score == pytest.approx(0.97)
    mock_client.post.assert_called_once()
    assert mock_client.post.call_args.args[0] == reranking.CohereReranker.endpoint
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["model"] == "rerank-v4.0-fast"
    assert payload["query"] == "capital"
    assert payload["documents"] == ["doc-a", "doc-b"]


def test_rerank_documents_falls_back_to_openrouter_on_retryable_primary_failure(monkeypatch):
    monkeypatch.setenv("AM_RERANK_ENABLED", "1")
    monkeypatch.setenv("AM_RERANK_FALLBACK_PROVIDER", "openrouter")
    monkeypatch.setenv("AM_RERANK_FALLBACK_MODEL", "cohere/rerank-4-fast")
    monkeypatch.setenv("COHERE_API_KEY", "cohere-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")

    primary_response = Mock(status_code=429)
    primary_response.json.return_value = {"message": "rate limited"}

    fallback_response = Mock(status_code=200)
    fallback_response.json.return_value = {
        "results": [
            {"index": 0, "relevance_score": 0.88},
            {"index": 1, "relevance_score": 0.42},
        ]
    }

    first_client = Mock()
    first_client.post.return_value = primary_response
    first_ctx = MagicMock()
    first_ctx.__enter__.return_value = first_client
    first_ctx.__exit__.return_value = False

    second_client = Mock()
    second_client.post.return_value = fallback_response
    second_ctx = MagicMock()
    second_ctx.__enter__.return_value = second_client
    second_ctx.__exit__.return_value = False

    monkeypatch.setattr(reranking.httpx, "Client", Mock(side_effect=[first_ctx, second_ctx]))

    response = reranking.rerank_documents("capital", ["doc-a", "doc-b"])

    assert response.applied is True
    assert response.provider == "openrouter"
    assert response.model == "cohere/rerank-4-fast"
    assert response.fallback_reason == "primary_failed:http_429"
    assert [score.index for score in response.scores] == [0, 1]
    assert first_client.post.call_args.args[0] == reranking.CohereReranker.endpoint
    assert second_client.post.call_args.args[0] == reranking.OpenRouterReranker.endpoint
    assert second_client.post.call_args.kwargs["json"]["model"] == "cohere/rerank-4-fast"


def test_rerank_documents_does_not_fall_back_on_non_retryable_primary_failure(monkeypatch):
    monkeypatch.setenv("AM_RERANK_ENABLED", "1")
    monkeypatch.setenv("AM_RERANK_FALLBACK_PROVIDER", "openrouter")
    monkeypatch.setenv("AM_RERANK_FALLBACK_MODEL", "cohere/rerank-4-fast")
    monkeypatch.setenv("COHERE_API_KEY", "cohere-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")

    primary_response = Mock(status_code=401)
    primary_response.json.return_value = {"message": "unauthorized"}

    primary_client = Mock()
    primary_client.post.return_value = primary_response
    primary_ctx = MagicMock()
    primary_ctx.__enter__.return_value = primary_client
    primary_ctx.__exit__.return_value = False

    client_factory = Mock(return_value=primary_ctx)
    monkeypatch.setattr(reranking.httpx, "Client", client_factory)

    response = reranking.rerank_documents("capital", ["doc-a", "doc-b"])

    assert response.applied is False
    assert response.provider == "cohere"
    assert response.fallback_reason == "http_401"
    assert client_factory.call_count == 1
