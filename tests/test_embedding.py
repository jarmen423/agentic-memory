"""Unit tests for EmbeddingService — all API clients mocked."""

from contextlib import nullcontext
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

from agentic_memory.core.embedding import (
    EmbeddingService,
    _LocalGPUEmbedder,
    _default_nemotron_local_max_seq_and_batch,
)


class TestNemotronLocalVramTiers:
    """VRAM-tier defaults for ``nemotron_local`` (no real GPU required)."""

    def test_tier_roughly_96_gib(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value = MagicMock(
            total_memory=int(96 * 1024**3)
        )
        monkeypatch.setitem(sys.modules, "torch", mock_torch)
        assert _default_nemotron_local_max_seq_and_batch() == (8192, 256)

    def test_tier_small_discrete_gpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value = MagicMock(
            total_memory=int(7 * 1024**3)
        )
        monkeypatch.setitem(sys.modules, "torch", mock_torch)
        assert _default_nemotron_local_max_seq_and_batch() == (512, 16)


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

    def test_gemini_vertex_provider_init(self) -> None:
        """Gemini can be routed through Vertex AI without a direct API key."""
        with patch("agentic_memory.core.embedding.genai") as mock_genai, patch(
            "agentic_memory.core.embedding.genai_types"
        ) as mock_types:
            mock_types.HttpOptions.return_value = "http-options"

            service = EmbeddingService(
                provider="gemini",
                api_key=None,
                vertexai=True,
                project="radiology-app-486607",
                location="us-central1",
                api_version="v1",
            )
            mock_genai.Client.assert_called_once_with(
                vertexai=True,
                project="radiology-app-486607",
                location="us-central1",
                http_options="http-options",
            )
            assert service.vertexai is True
            assert service.project == "radiology-app-486607"
            assert service.location == "us-central1"

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


class TestLocalNemotronVlCompatibility:
    """Compatibility coverage for the native Nemotron VL text API."""

    def test_local_gpu_embedder_uses_native_encode_documents_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nemotron VL-style models can return embeddings without last_hidden_state."""

        class FakeTensor:
            def __init__(self, data: list[list[float]] | list[float]) -> None:
                self.data = data

            @property
            def ndim(self) -> int:
                return 1 if self.data and isinstance(self.data[0], float) else 2

            def unsqueeze(self, dim: int) -> "FakeTensor":
                assert dim == 0
                return FakeTensor([self.data])  # type: ignore[list-item]

            def float(self) -> "FakeTensor":
                return self

            def cpu(self) -> "FakeTensor":
                return self

            def tolist(self) -> list[list[float]] | list[float]:
                return self.data

        class FakeInputs(dict):
            def to(self, device: object) -> "FakeInputs":
                return self

        class FakeTokenizer:
            def __call__(self, *args: object, **kwargs: object) -> FakeInputs:
                return FakeInputs()

        class FakeProcessor:
            def __init__(self) -> None:
                self.p_max_length: int | None = None

        class FakeModel:
            def __init__(self) -> None:
                self.processor = FakeProcessor()

            def to(self, device: object) -> "FakeModel":
                return self

            def eval(self) -> "FakeModel":
                return self

            def encode_documents(self, *, texts: list[str]) -> FakeTensor:
                return FakeTensor([[0.1, 0.2, 0.3] for _ in texts])

        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False
        fake_torch.device.side_effect = lambda name: MagicMock(type=name)
        fake_torch.float16 = "float16"
        fake_torch.float32 = "float32"
        fake_torch.Tensor = FakeTensor
        fake_torch.as_tensor.side_effect = lambda data, device=None: FakeTensor(data)
        fake_torch.inference_mode.side_effect = lambda: nullcontext()
        fake_torch.nn.functional.normalize.side_effect = lambda tensor, p, dim: tensor

        fake_transformers = MagicMock()
        fake_transformers.AutoTokenizer.from_pretrained.return_value = FakeTokenizer()
        fake_transformers.AutoModel.from_pretrained.return_value = FakeModel()

        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

        embedder = _LocalGPUEmbedder(
            "nvidia/llama-nemotron-embed-vl-1b-v2",
            max_seq_length=8192,
            batch_size=2,
        )

        assert embedder.dimensions == 3
        assert embedder.model.processor.p_max_length == 8192
        vectors = embedder.encode(["a", "b"])
        assert vectors == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]


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

    def test_embed_gemini_prefixes_custom_task_instruction(self) -> None:
        """Gemini Embedding 2 task instructions should be prepended to the content."""
        with patch("agentic_memory.core.embedding.genai") as mock_genai:
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_embedding_values = [0.1] * 3072
            mock_client.models.embed_content.return_value.embeddings = [
                MagicMock(values=mock_embedding_values)
            ]

            service = EmbeddingService(provider="gemini", api_key="test-key")
            result = service.embed(
                "hello world",
                task_instruction="task:code retrieval",
            )

            mock_client.models.embed_content.assert_called_once_with(
                model="gemini-embedding-2-preview",
                contents="task:code retrieval\n\nhello world",
                config={"output_dimensionality": 3072},
            )
            assert result == mock_embedding_values

    def test_embed_with_metadata_gemini_tracks_usage_and_estimated_cost(self) -> None:
        """Gemini metadata should expose billable tokens and estimated Vertex text cost."""
        with patch("agentic_memory.core.embedding.genai") as mock_genai:
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_response = MagicMock()
            mock_response.embeddings = [MagicMock(values=[0.1] * 3072)]
            mock_response.usage_metadata = MagicMock(
                prompt_token_count=1000,
                total_token_count=1000,
            )
            mock_client.models.embed_content.return_value = mock_response

            service = EmbeddingService(provider="gemini", api_key="test-key")
            vector, metadata = service.embed_with_metadata("hello world")

            assert len(vector) == 3072
            assert metadata.prompt_tokens == 1000
            assert metadata.total_tokens == 1000
            assert metadata.transport == "developer_api"
            assert metadata.estimated_cost_usd == pytest.approx(0.0002)

    def test_embed_with_metadata_openai_ignores_task_instruction(self) -> None:
        """OpenAI-compatible providers should ignore Gemini-only task instructions."""
        with patch("agentic_memory.core.embedding.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_embedding = [0.1] * 3072
            mock_client.embeddings.create.return_value.data = [
                MagicMock(embedding=mock_embedding)
            ]
            mock_client.embeddings.create.return_value.usage = MagicMock(total_tokens=42)

            service = EmbeddingService(provider="openai", api_key="test-key")
            vector, metadata = service.embed_with_metadata(
                "hello world",
                task_instruction="task:code retrieval",
            )

            mock_client.embeddings.create.assert_called_once_with(
                model="text-embedding-3-large",
                input="hello world",
                dimensions=3072,
            )
            assert vector == mock_embedding
            assert metadata.transport == "openai_compatible"


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

            embeddings = [[0.1] * 3072, [0.2] * 3072]

            def embed_side_effect(**kwargs: object) -> MagicMock:
                result = MagicMock()
                # One Gemini request carries all texts; SDK returns one entry per input.
                result.embeddings = [
                    MagicMock(values=embeddings[0]),
                    MagicMock(values=embeddings[1]),
                ]
                result.usage_metadata = MagicMock(
                    prompt_token_count=10, total_token_count=10
                )
                return result

            mock_client.models.embed_content.side_effect = embed_side_effect

            service = EmbeddingService(provider="gemini", api_key="test-key")
            result = service.embed_batch(["text1", "text2"])

            assert len(result) == 2
            mock_client.models.embed_content.assert_called_once()


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
                "vertexai": False,
                "project": None,
                "location": None,
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
                "vertexai": False,
                "project": None,
                "location": None,
            }
