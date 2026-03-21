"""Provider-dispatching embedding service.

Wraps OpenAI, Gemini, and Nemotron behind a single .embed() interface.
Each ingestion module instantiates its own EmbeddingService with the right provider.
"""

import logging
from typing import Any

from google import genai
from openai import OpenAI

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Provider-dispatching embedding service.

    Wraps OpenAI, Gemini, and Nemotron behind a single .embed() interface.
    Each ingestion module instantiates its own EmbeddingService with the right provider.

    Args:
        provider: One of 'openai', 'gemini', 'nemotron'.
        api_key: API key for the selected provider.
        base_url: Optional base URL override (used for Nemotron custom endpoints).
        output_dimensions: Optional dimension override. Defaults to provider's standard.

    Raises:
        ValueError: If provider is not one of the supported providers.
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
        base_url: str | None = None,
        output_dimensions: int | None = None,
    ) -> None:
        """Initialize the embedding service for the given provider.

        Args:
            provider: One of 'openai', 'gemini', 'nemotron'.
            api_key: API key for the selected provider.
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
        self.model: str = self.PROVIDERS[provider]["model"]
        self.dimensions: int = output_dimensions or self.PROVIDERS[provider]["dimensions"]

        if provider == "gemini":
            self._client = genai.Client(api_key=api_key)
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

        For Gemini, calls embed() individually (SDK does not support native batch).
        For OpenAI/Nemotron, uses a single batched API call.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of embedding vectors (one per input text).
        """
        if self.provider == "gemini":
            # Gemini SDK does not support batch embedding natively
            return [self.embed(text) for text in texts]
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
