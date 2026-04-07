"""Unit tests for ClaimExtractionService."""

from unittest.mock import Mock, patch

import pytest

from agentic_memory.core.claim_extraction import ClaimExtractionService


def _mock_response(payload: str) -> Mock:
    """Build a chat-completions-style response wrapper for a JSON payload string."""
    message = Mock(content=payload)
    choice = Mock(message=message)
    response = Mock()
    response.choices = [choice]
    return response


def test_extract_returns_normalized_claims():
    """extract returns normalized claim dicts with the required keys."""
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = _mock_response(
        '{"claims":[{"subject":"Alice","predicate":"KNOWS","object":"Bob","valid_from":null,"valid_to":null,"confidence":0.9}]}'
    )

    with patch(
        "agentic_memory.core.claim_extraction.build_extraction_openai_client",
        Mock(return_value=mock_client),
    ):
        service = ClaimExtractionService(api_key="test-key")
        claims = service.extract("Alice knows Bob.")

    assert claims == [
        {
            "subject": "Alice",
            "predicate": "KNOWS",
            "object": "Bob",
            "valid_from": None,
            "valid_to": None,
            "confidence": 0.9,
        }
    ]


def test_extract_remaps_unknown_predicates_to_references():
    """Unknown predicates are normalized to REFERENCES."""
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = _mock_response(
        '{"claims":[{"subject":"Alice","predicate":"LIKES","object":"Bob","valid_from":null,"valid_to":null,"confidence":0.4}]}'
    )

    with patch(
        "agentic_memory.core.claim_extraction.build_extraction_openai_client",
        Mock(return_value=mock_client),
    ):
        service = ClaimExtractionService(api_key="test-key")
        claims = service.extract("Alice likes Bob.")

    assert claims[0]["predicate"] == "REFERENCES"


def test_extract_truncates_input_to_8000_characters():
    """Only the first 8000 characters are sent to the provider."""
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = _mock_response('{"claims":[]}')

    with patch(
        "agentic_memory.core.claim_extraction.build_extraction_openai_client",
        Mock(return_value=mock_client),
    ):
        service = ClaimExtractionService(api_key="test-key")
        service.extract("x" * 9000)

    user_message = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert len(user_message) == 8000


def test_extract_returns_empty_list_for_empty_claims():
    """An empty claims array produces an empty list without raising."""
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = _mock_response('{"claims":[]}')

    with patch(
        "agentic_memory.core.claim_extraction.build_extraction_openai_client",
        Mock(return_value=mock_client),
    ):
        service = ClaimExtractionService(api_key="test-key")
        claims = service.extract("No claims here.")

    assert claims == []


def test_extract_wraps_provider_errors():
    """Provider client failures are re-raised as RuntimeError."""
    mock_client = Mock()
    mock_client.chat.completions.create.side_effect = ValueError("bad request")

    with patch(
        "agentic_memory.core.claim_extraction.build_extraction_openai_client",
        Mock(return_value=mock_client),
    ):
        service = ClaimExtractionService(api_key="test-key")
        with pytest.raises(RuntimeError, match="Claim extraction failed"):
            service.extract("Text")


def test_extract_uses_json_object_mode_and_zero_temperature():
    """The request uses deterministic json_object mode."""
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = _mock_response('{"claims":[]}')

    with patch(
        "agentic_memory.core.claim_extraction.build_extraction_openai_client",
        Mock(return_value=mock_client),
    ):
        service = ClaimExtractionService(api_key="test-key")
        service.extract("Text")

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.0
