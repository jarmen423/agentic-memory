"""Multi-provider text embeddings (OpenAI, Gemini, Nemotron).

`EmbeddingService` normalizes single/batch embedding calls and dimension parameters
so ingestion code matches Neo4j vector index widths from `ConnectionManager.setup_database`.
"""

import logging
from typing import Any

from google import genai
from openai import OpenAI

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Dispatch ``embed`` / ``embed_batch`` to the configured provider SDK.

    Provider defaults (model + vector width) live in ``PROVIDERS`` and must stay
    aligned with Neo4j vector index definitions and :mod:`codememory.core.config_validator`.
    """

    PROVIDERS: dict[str, dict[str, Any]] = {
        "openai": {"model": "text-embedding-3-large", "dimensions": 3072},
        "gemini": {"model": "gemini-embedding-2-preview", "dimensions": 3072},
        "nemotron": {"model": "nvidia/nv-embedqa-e5-v5", "dimensions": 4096},
    }

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        output_dimensions: int | None = None,
    ) -> None:
        """Initialize the embedding service for the given provider.

        Args:
            provider: One of 'openai', 'gemini', 'nemotron'.
            api_key: API key for the selected provider.
            model: Optional model override for the selected provider.
            base_url: Optional base URL override (for Nemotron custom endpoints).
            output_dimensions: Optional dimension override. Defaults to provider standard.

        Raises:
            ValueError: If provider is not supported.
        """
        if provider not in self.PROVIDERS:
            supported = ", ".join(self.PROVIDERS.keys())
            raise ValueError(
                f"Unsupported provider '{provider}'. Must be one of: {supported}"
            )

        self.provider = provider
        self.model: str = model or self.PROVIDERS[provider]["model"]
        self.dimensions: int = output_dimensions or self.PROVIDERS[provider]["dimensions"]

        self._rate_limiter: _GeminiRateLimiter | None = None
        if provider == "gemini":
            self._client = genai.Client(api_key=api_key)
            self._rate_limiter = _GeminiRateLimiter()
        elif provider == "nemotron":
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url or "https://integrate.api.nvidia.com/v1",
            )
        else:
            # openai
            self._client = OpenAI(api_key=api_key)

        logger.debug(
            "EmbeddingService initialized: provider=%s model=%s dimensions=%d",
            self.provider,
            self.model,
            self.dimensions,
        )

    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for a single text string.

        Args:
            text: Input text to embed.

        Returns:
            Embedding vector as a list of floats.
        """
        if self.provider == "gemini":
            # CRITICAL: Always pass output_dimensionality explicitly.
            # Gemini default is 3072d but we may need 768d for web/chat indexes.
            # Pitfall 2 from RESEARCH.md: never rely on the API default.
            self._rate_limiter.wait_if_needed()
            result = self._client.models.embed_content(
                model=self.model,
                contents=text,
                config={"output_dimensionality": self.dimensions},
            )
            return list(result.embeddings[0].values)
        else:
            response = self._client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dimensions,
            )
            return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts.

        Gemini batch embed accepts at most 100 texts per call; we chunk accordingly.
        OpenAI/Nemotron use a single batched API call.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of embedding vectors (one per input text).
        """
        if self.provider == "gemini":
            # Gemini BatchEmbedContents: at most 100 requests per batch.
            MAX_BATCH = 100
            all_embeddings: list[list[float]] = []
            for i in range(0, len(texts), MAX_BATCH):
                chunk = texts[i : i + MAX_BATCH]
                self._rate_limiter.wait_if_needed()
                result = self._client.models.embed_content(
                    model=self.model,
                    contents=chunk,
                    config={"output_dimensionality": self.dimensions},
                )
                all_embeddings.extend(list(e.values) for e in result.embeddings)
            return all_embeddings
        else:
            response = self._client.embeddings.create(
                model=self.model,
                input=texts,
                dimensions=self.dimensions,
            )
            return [d.embedding for d in response.data]

    @property
    def model_info(self) -> dict[str, Any]:
        """Return metadata about the configured embedding model.

        Returns:
            Dict with keys: provider, model, dimensions.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
        }
