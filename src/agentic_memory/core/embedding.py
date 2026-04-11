"""Provider-dispatching embedding service.

Wraps OpenAI, Gemini, and Nemotron behind a single embedding interface while
also exposing a richer ``.embed_with_metadata()`` path for ingestion pipelines
that need provider usage and cost diagnostics.

Why this file matters:
    Agentic Memory indexes thousands of entities per repo. When that happens, the
    operator needs to know not only that embeddings were generated, but also how
    many billable input tokens were sent and which runtime was used. This module
    is where provider-specific response shapes are normalized into one internal
    metadata contract.

Gemini Embedding 2 note:
    Google's Gemini Embedding 2 preview docs describe "custom task
    instructions" such as ``task:code retrieval`` and ``task:search result`` as
    a way to optimize embeddings for a specific retrieval role. The public model
    page documents the feature, but the exact request wire shape is less
    explicit than older ``task_type``-based embedding APIs.

    Until Google publishes a clearer dedicated field for this preview model in
    the Gen AI SDK docs, Agentic Memory treats these task instructions as a
    Gemini-only input prefix. That keeps the behavior explicit and easy to
    inspect, and it lets us pair query/document embeddings intentionally for
    code search.
"""

from dataclasses import dataclass
import logging
from typing import Any

from google import genai
from google.genai import types as genai_types
from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingMetadata:
    """Normalized usage metadata returned by one embedding request.

    Attributes:
        provider: Logical provider name such as ``gemini`` or ``openai``.
        model: Concrete embedding model identifier.
        prompt_tokens: Input token count when the provider exposes it.
        total_tokens: Total token count when the provider exposes it.
        estimated_cost_usd: Best-effort input-side cost estimate for this call.
        transport: Operational path used to reach the provider, such as
            ``developer_api`` or ``vertex_ai`` for Gemini.
    """

    provider: str
    model: str
    prompt_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    transport: str | None = None


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
        api_key: str | None,
        model: str | None = None,
        base_url: str | None = None,
        output_dimensions: int | None = None,
        vertexai: bool = False,
        project: str | None = None,
        location: str | None = None,
        api_version: str | None = None,
    ) -> None:
        """Initialize the embedding service for the given provider.

        Args:
            provider: One of 'openai', 'gemini', 'nemotron'.
            api_key: API key for the selected provider. Gemini-on-Vertex can use
                Application Default Credentials instead of an API key.
            model: Optional model override for the selected provider.
            base_url: Optional base URL override (for Nemotron custom endpoints).
            output_dimensions: Optional dimension override. Defaults to provider standard.
            vertexai: Whether Gemini traffic should use the Vertex AI transport.
            project: Google Cloud project for Vertex AI usage.
            location: Vertex AI location. Defaults to ``global`` when omitted.
            api_version: Optional Gen AI SDK API version override for Vertex AI.

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
        self.vertexai = bool(vertexai)
        self.project = project
        self.location = location or ("global" if self.vertexai and provider == "gemini" else None)
        self.api_version = api_version

        if provider == "gemini":
            client_kwargs: dict[str, Any] = {}
            if self.vertexai:
                client_kwargs["vertexai"] = True
                if self.project:
                    client_kwargs["project"] = self.project
                if self.location:
                    client_kwargs["location"] = self.location
                if self.api_version:
                    client_kwargs["http_options"] = genai_types.HttpOptions(
                        api_version=self.api_version
                    )
                if api_key:
                    client_kwargs["api_key"] = api_key
            else:
                client_kwargs["api_key"] = api_key
            self._client = genai.Client(**client_kwargs)
        elif provider == "nemotron":
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url or "https://integrate.api.nvidia.com/v1",
            )
        else:
            # openai
            self._client = OpenAI(api_key=api_key)

        logger.debug(
            "EmbeddingService initialized: provider=%s model=%s dimensions=%d vertexai=%s",
            self.provider,
            self.model,
            self.dimensions,
            self.vertexai,
        )

    def _estimate_embedding_cost_usd(
        self,
        *,
        prompt_tokens: int | None,
    ) -> float | None:
        """Estimate input-side embedding cost for providers we can price safely.

        We only estimate costs when the pricing model is clear and the response
        exposes billable input tokens. This keeps the CLI honest: unknown pricing
        should stay unknown instead of silently showing ``$0.00``.
        """
        if prompt_tokens is None:
            return None

        if self.provider == "gemini" and self.model == "gemini-embedding-2-preview":
            # Vertex AI pricing for Gemini Embedding 2 preview text input is
            # $0.2 / 1M input tokens for online requests.
            return float(prompt_tokens) * (0.2 / 1_000_000.0)

        return None

    @staticmethod
    def _usage_value(usage: object, *names: str) -> int | None:
        """Read one usage field from object or dict-style SDK responses."""
        for name in names:
            if isinstance(usage, dict) and usage.get(name) is not None:
                return int(usage[name])
            value = getattr(usage, name, None)
            if value is not None:
                return int(value)
        return None

    def _build_openai_metadata(self, response: object) -> EmbeddingMetadata:
        """Normalize OpenAI-style embedding usage into the shared metadata shape."""
        usage = getattr(response, "usage", None)
        total_tokens = self._usage_value(usage, "total_tokens")
        prompt_tokens = self._usage_value(usage, "prompt_tokens", "input_tokens") or total_tokens
        return EmbeddingMetadata(
            provider=self.provider,
            model=self.model,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=None,
            transport="openai_compatible",
        )

    def _build_gemini_metadata(self, response: object) -> EmbeddingMetadata:
        """Normalize Gemini/Vertex usage metadata into one internal contract."""
        usage = getattr(response, "usage_metadata", None) or getattr(response, "usageMetadata", None)
        prompt_tokens = self._usage_value(usage, "prompt_token_count", "promptTokenCount")
        total_tokens = self._usage_value(usage, "total_token_count", "totalTokenCount")
        return EmbeddingMetadata(
            provider=self.provider,
            model=self.model,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=self._estimate_embedding_cost_usd(prompt_tokens=prompt_tokens),
            transport="vertex_ai" if self.vertexai else "developer_api",
        )

    def _prepare_gemini_content(
        self,
        text: str,
        *,
        task_instruction: str | None = None,
    ) -> str:
        """Build the Gemini Embedding 2 input payload for one text request.

        Args:
            text: Raw text content to embed.
            task_instruction: Optional Gemini Embedding 2 task instruction such
                as ``task:code retrieval`` or ``task:search result``.

        Returns:
            Text payload to send to Gemini.

        Why this helper exists:
            Gemini Embedding 2 preview introduces custom task instructions on the
            model card, but the surrounding SDK examples for this preview do not
            yet show a dedicated strongly-typed request field for them. We
            therefore keep the formatting in one place so it is easy to change if
            Google later documents a more explicit SDK parameter.
        """
        if not task_instruction:
            return text
        cleaned_instruction = task_instruction.strip()
        if not cleaned_instruction:
            return text
        return f"{cleaned_instruction}\n\n{text}"

    def embed_with_metadata(
        self,
        text: str,
        *,
        task_instruction: str | None = None,
    ) -> tuple[list[float], EmbeddingMetadata]:
        """Generate one embedding vector plus normalized provider metadata.

        Args:
            text: Input text to embed.
            task_instruction: Optional Gemini Embedding 2 custom task
                instruction. Ignored by non-Gemini providers.

        Returns:
            Tuple of ``(embedding_vector, normalized_metadata)``.
        """
        if self.provider == "gemini":
            # CRITICAL: Always pass output_dimensionality explicitly.
            # Gemini default is 3072d but we may need 768d for web/chat indexes.
            # Pitfall 2 from RESEARCH.md: never rely on the API default.
            response = self._client.models.embed_content(
                model=self.model,
                contents=self._prepare_gemini_content(
                    text,
                    task_instruction=task_instruction,
                ),
                config={"output_dimensionality": self.dimensions},
            )
            return list(response.embeddings[0].values), self._build_gemini_metadata(response)
        else:
            response = self._client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dimensions,
            )
            return response.data[0].embedding, self._build_openai_metadata(response)

    def embed(self, text: str, *, task_instruction: str | None = None) -> list[float]:
        """Generate embedding vector for a single text string.

        This remains the simple public API used by legacy callers. New ingestion
        code that needs cost/usage data should call ``embed_with_metadata``.
        """
        vector, _ = self.embed_with_metadata(text, task_instruction=task_instruction)
        return vector

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
            Dict with keys: provider, model, dimensions, and transport details.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "vertexai": self.vertexai,
            "project": self.project,
            "location": self.location,
        }
