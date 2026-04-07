"""Unit tests for EmbeddingService — all API clients mocked."""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from agentic_memory.core.embedding import EmbeddingService


class TestEmbeddingServiceInit:
    """Tests for EmbeddingService constructor and provider dispatch."""

    def test_openai_provider_init(self) -> None:
        """EmbeddingService(provider='openai') creates OpenAI client with correct defaults."""
        with patch("agentic_memory.core.embedding.OpenAI") as mock_openai_cls:
            service = EmbeddingService(provider="openai", api_key="test-key")
            mock_openai_cls.assert_called_once_with(api_key="test-key")
            assert service.provider == "openai"
            assert service.model == "text-embedding-3-large"
            assert service.dimensions == 3072

    def test_gemini_provider_init(self) -> None:
        """EmbeddingService(provider='gemini') creates genai.Client with correct defaults."""
        with patch("agentic_memory.core.embedding.genai") as mock_genai:
            service = EmbeddingService(provider="gemini", api_key="test-key")
            mock_genai.Client.assert_called_once_with(api_key="test-key")
            assert service.provider == "gemini"
            assert service.model == "gemini-embedding-2-preview"
            assert service.dimensions == 3072

    def test_nemotron_provider_init(self) -> None:
        """EmbeddingService(provider='nemotron') creates OpenAI client with Nvidia base_url."""
        with patch("agentic_memory.core.embedding.OpenAI") as mock_openai_cls:
            service = EmbeddingService(provider="nemotron", api_key="test-key")
            mock_openai_cls.assert_called_once_with(
                api_key="test-key",
                base_url="https://integrate.api.nvidia.com/v1",
            )
            assert service.provider == "nemotron"

    def test_invalid_provider(self) -> None:
        """EmbeddingService with unknown provider raises ValueError."""
        with pytest.raises(ValueError, match="invalid"):
            EmbeddingService(provider="invalid", api_key="test-key")

    def test_custom_base_url_for_nemotron(self) -> None:
        """Nemotron provider uses custom base_url if provided."""
        with patch("agentic_memory.core.embedding.OpenAI") as mock_openai_cls:
            service = EmbeddingService(
                provider="nemotron",
                api_key="test-key",
                base_url="https://custom.endpoint/v1",
            )
            mock_openai_cls.assert_called_once_with(
                api_key="test-key",
                base_url="https://custom.endpoint/v1",
            )

    def test_custom_model_override_is_preserved(self) -> None:
        """EmbeddingService accepts an explicit model override."""
        with patch("agentic_memory.core.embedding.OpenAI"):
            service = EmbeddingService(
                provider="openai",
                api_key="test-key",
                model="text-embedding-3-small",
            )
            assert service.model == "text-embedding-3-small"


class TestEmbedMethod:
    """Tests for EmbeddingService.embed() method."""

    def test_embed_openai(self) -> None:
        """embed() for openai provider calls embeddings.create and returns list[float]."""
        with patch("agentic_memory.core.embedding.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_embedding = [0.1, 0.2, 0.3] * 1024  # 3072 floats
            mock_client.embeddings.create.return_value.data = [
                MagicMock(embedding=mock_embedding)
            ]

            service = EmbeddingService(provider="openai", api_key="test-key")
            result = service.embed("hello world")

            mock_client.embeddings.create.assert_called_once_with(
                model="text-embedding-3-large",
                input="hello world",
                dimensions=3072,
            )
            assert result == mock_embedding
            assert len(result) == 3072

    def test_embed_gemini(self) -> None:
        """embed() for gemini provider ALWAYS passes output_dimensionality explicitly."""
        with patch("agentic_memory.core.embedding.genai") as mock_genai:
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_embedding_values = [0.1, 0.2] * 1536  # 3072 floats (default)
            mock_client.models.embed_content.return_value.embeddings = [
                MagicMock(values=mock_embedding_values)
            ]

            service = EmbeddingService(provider="gemini", api_key="test-key")
            result = service.embed("hello world")

            # output_dimensionality MUST always be passed (never rely on API default)
            mock_client.models.embed_content.assert_called_once_with(
                model="gemini-embedding-2-preview",
                contents="hello world",
                config={"output_dimensionality": 3072},
            )
            assert result == mock_embedding_values

    def test_embed_gemini_custom_dimensions(self) -> None:
        """EmbeddingService(provider='gemini', output_dimensions=256) passes 256 to Gemini."""
        with patch("agentic_memory.core.embedding.genai") as mock_genai:
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_embedding_values = [0.5] * 256
            mock_client.models.embed_content.return_value.embeddings = [
                MagicMock(values=mock_embedding_values)
            ]

            service = EmbeddingService(
                provider="gemini", api_key="test-key", output_dimensions=256
            )
            assert service.dimensions == 256
            result = service.embed("test text")

            mock_client.models.embed_content.assert_called_once_with(
                model="gemini-embedding-2-preview",
                contents="test text",
                config={"output_dimensionality": 256},
            )
            assert result == mock_embedding_values


class TestEmbedBatch:
    """Tests for EmbeddingService.embed_batch() method."""

    def test_embed_batch_openai(self) -> None:
        """embed_batch() for openai provider makes a single batched API call."""
        with patch("agentic_memory.core.embedding.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            embedding1 = [0.1] * 3072
            embedding2 = [0.2] * 3072
            mock_client.embeddings.create.return_value.data = [
                MagicMock(embedding=embedding1),
                MagicMock(embedding=embedding2),
            ]

            service = EmbeddingService(provider="openai", api_key="test-key")
            result = service.embed_batch(["text1", "text2"])

            mock_client.embeddings.create.assert_called_once_with(
                model="text-embedding-3-large",
                input=["text1", "text2"],
                dimensions=3072,
            )
            assert len(result) == 2
            assert result[0] == embedding1
            assert result[1] == embedding2

    def test_embed_batch_returns_list_of_two(self) -> None:
        """embed_batch(['text1', 'text2']) returns list of 2 embeddings."""
        with patch("agentic_memory.core.embedding.genai") as mock_genai:
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client

            call_count = 0
            embeddings = [[0.1] * 3072, [0.2] * 3072]

            def embed_side_effect(**kwargs: object) -> MagicMock:
                nonlocal call_count
                result = MagicMock()
                result.embeddings = [MagicMock(values=embeddings[call_count])]
                call_count += 1
                return result

            mock_client.models.embed_content.side_effect = embed_side_effect

            service = EmbeddingService(provider="gemini", api_key="test-key")
            result = service.embed_batch(["text1", "text2"])

            assert len(result) == 2


class TestModelInfo:
    """Tests for EmbeddingService.model_info property."""

    def test_model_info_property(self) -> None:
        """service.model_info returns dict with provider, model, dimensions."""
        with patch("agentic_memory.core.embedding.OpenAI"):
            service = EmbeddingService(provider="openai", api_key="test-key")
            info = service.model_info
            assert info == {
                "provider": "openai",
                "model": "text-embedding-3-large",
                "dimensions": 3072,
            }

    def test_model_info_gemini(self) -> None:
        """model_info for gemini provider reflects correct model and dimensions."""
        with patch("agentic_memory.core.embedding.genai"):
            service = EmbeddingService(
                provider="gemini", api_key="test-key", output_dimensions=768
            )
            info = service.model_info
            assert info == {
                "provider": "gemini",
                "model": "gemini-embedding-2-preview",
                "dimensions": 768,
            }
