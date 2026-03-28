"""Unit tests for EntityExtractionService and build_embed_text."""

import json
import unittest
from unittest.mock import MagicMock, patch

import pytest

from codememory.core.entity_extraction import EntityExtractionService, build_embed_text


class TestEntityExtractionServiceInit:
    """Tests for EntityExtractionService constructor."""

    def test_default_allowed_types(self) -> None:
        """EntityExtractionService uses default allowed types when none provided."""
        with patch("codememory.core.entity_extraction.build_extraction_openai_client"):
            service = EntityExtractionService(api_key="test-key")
            assert service.allowed_types == [
                "project",
                "person",
                "business",
                "technology",
                "concept",
            ]

    def test_custom_allowed_types(self) -> None:
        """EntityExtractionService stores custom allowed_types and passes them in prompt."""
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client

            # Set up mock response with a custom type
            mock_response_content = json.dumps({"entities": [{"name": "CustomThing", "type": "custom"}]})
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=mock_response_content))
            ]

            service = EntityExtractionService(api_key="test-key", allowed_types=["custom"])
            assert service.allowed_types == ["custom"]

            # Verify prompt contains "custom" when calling extract
            service.extract("Some text mentioning CustomThing")
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs.get("messages") or call_args.args[0] if call_args.args else call_args.kwargs["messages"]
            system_content = messages[0]["content"]
            assert "custom" in system_content


class TestEntityExtractionServiceExtract:
    """Tests for EntityExtractionService.extract() method."""

    def _make_service_with_mock(
        self, response_content: str
    ) -> tuple[EntityExtractionService, MagicMock]:
        """Helper: create service with a mocked JSON-capable LLM client."""
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=response_content))
            ]
            service = EntityExtractionService(api_key="test-key")
            service._client = mock_client  # keep mock accessible after context exit
            return service, mock_client

    def test_extract_returns_entity_list(self) -> None:
        """extract() returns list of {name, type} dicts from the provider response."""
        response_json = json.dumps(
            {"entities": [{"name": "Python", "type": "technology"}]}
        )
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=response_json))
            ]
            service = EntityExtractionService(api_key="test-key")
            result = service.extract("We use Python for development.")

        assert result == [{"name": "Python", "type": "technology"}]

    def test_extract_filters_invalid_types(self) -> None:
        """extract() filters out entities whose type is not in allowed_types."""
        response_json = json.dumps(
            {
                "entities": [
                    {"name": "Python", "type": "technology"},
                    {"name": "Some Thing", "type": "invalid_type"},
                ]
            }
        )
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=response_json))
            ]
            service = EntityExtractionService(api_key="test-key")
            result = service.extract("Some text.")

        assert result == [{"name": "Python", "type": "technology"}]
        assert all(e["type"] in service.allowed_types for e in result)

    def test_extract_truncates_long_documents(self) -> None:
        """extract() truncates document_text to 8000 chars before sending to LLM."""
        long_text = "a" * 10000  # 10000 chars, should be truncated to 8000
        response_json = json.dumps({"entities": []})
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=response_json))
            ]
            service = EntityExtractionService(api_key="test-key")
            service.extract(long_text)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        user_message_content = messages[1]["content"]
        assert len(user_message_content) == 8000
        assert user_message_content == "a" * 8000

    def test_extract_handles_empty_response(self) -> None:
        """extract() returns [] when the provider returns {'entities': []}."""
        response_json = json.dumps({"entities": []})
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=response_json))
            ]
            service = EntityExtractionService(api_key="test-key")
            result = service.extract("Some text with no entities.")

        assert result == []

    def test_extract_handles_wrong_json_key(self) -> None:
        """extract() falls back to first list value when key is not 'entities'."""
        # LLM returns "results" instead of "entities" — Pitfall 4
        entities_list = [{"name": "OpenAI", "type": "technology"}]
        response_json = json.dumps({"results": entities_list})
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=response_json))
            ]
            service = EntityExtractionService(api_key="test-key")
            result = service.extract("OpenAI built GPT-4.")

        assert result == [{"name": "OpenAI", "type": "technology"}]

    def test_extract_uses_json_object_mode(self) -> None:
        """extract() passes response_format={'type': 'json_object'} to the provider."""
        response_json = json.dumps({"entities": []})
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=response_json))
            ]
            service = EntityExtractionService(api_key="test-key")
            service.extract("Some document text.")

        call_args = mock_client.chat.completions.create.call_args
        kwargs = call_args.kwargs if call_args.kwargs else call_args[1]
        assert kwargs.get("response_format") == {"type": "json_object"}

    def test_extract_uses_temperature_zero(self) -> None:
        """extract() passes temperature=0.0 to the provider for deterministic output."""
        response_json = json.dumps({"entities": []})
        with patch("codememory.core.entity_extraction.build_extraction_openai_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.chat.completions.create.return_value.choices = [
                MagicMock(message=MagicMock(content=response_json))
            ]
            service = EntityExtractionService(api_key="test-key")
            service.extract("Some document text.")

        call_args = mock_client.chat.completions.create.call_args
        kwargs = call_args.kwargs if call_args.kwargs else call_args[1]
        assert kwargs.get("temperature") == 0.0


class TestBuildEmbedText:
    """Tests for build_embed_text module-level function."""

    def test_build_embed_text_with_entities(self) -> None:
        """build_embed_text prepends entity context string before chunk text."""
        result = build_embed_text("hello", [{"name": "Py", "type": "tech"}])
        assert result == "Context: Py (tech)\n\nhello"

    def test_build_embed_text_empty_entities(self) -> None:
        """build_embed_text returns chunk_text unchanged when entities list is empty."""
        result = build_embed_text("hello", [])
        assert result == "hello"

    def test_build_embed_text_multiple_entities(self) -> None:
        """build_embed_text formats multiple entities as comma-separated list."""
        result = build_embed_text(
            "hello",
            [{"name": "A", "type": "t1"}, {"name": "B", "type": "t2"}],
        )
        assert result == "Context: A (t1), B (t2)\n\nhello"
