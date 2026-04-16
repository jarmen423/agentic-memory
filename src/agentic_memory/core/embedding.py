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
    Google documents a model-specific text formatting pattern for
    ``gemini-embedding-2-preview`` retrieval tasks. For text-only code
    retrieval, the recommended query shape is:

    ``task: code retrieval | query: {content}``

    and the recommended document shape is:

    ``title: {title} | text: {content}``

    Agentic Memory therefore treats ``task_instruction`` as a format template
    for Gemini Embedding 2 preview rather than a bare prefix. Templates can
    interpolate ``{content}`` and optionally ``{title}``. This keeps the
    repo-local configuration aligned with the official model guidance while
    remaining explicit and easy to inspect.

Gemini quota (sliding 60s window, defaults 3000 RPM / 1M TPM):

    * ``AGENTIC_MEMORY_GEMINI_MAX_RPM`` — max HTTP embedding requests per minute
    * ``AGENTIC_MEMORY_GEMINI_MAX_TPM`` — max estimated input tokens per minute
"""

from dataclasses import dataclass
import logging
import os
import time
from typing import Any

from google import genai
from google.genai import types as genai_types
from openai import OpenAI

logger = logging.getLogger(__name__)

# Default Gemini API ceilings (overridable for different billing tiers).
_ENV_MAX_RPM = "AGENTIC_MEMORY_GEMINI_MAX_RPM"
_ENV_MAX_TPM = "AGENTIC_MEMORY_GEMINI_MAX_TPM"
_DEFAULT_MAX_RPM = 3000
_DEFAULT_MAX_TPM = 1_000_000
_QUOTA_WINDOW_S = 60.0

# Google Generative Language API: BatchEmbedContents allows at most 100 inputs
# per HTTP request (error: "at most 100 requests can be in one batch").
GEMINI_BATCH_EMBED_MAX_TEXTS = 100


class _GeminiQuotaGate:
    """Sliding-window guard for Gemini RPM and TPM (one HTTP call = one request).

    Defaults match a typical paid tier style ceiling (3k requests/min,
    1M input tokens/min). Override with:

    * ``AGENTIC_MEMORY_GEMINI_MAX_RPM``
    * ``AGENTIC_MEMORY_GEMINI_MAX_TPM``

    We approximate pre-call input size for waits; after each response we record
    actual prompt token counts when the API returns them.
    """

    __slots__ = ("_calls", "max_rpm", "max_tpm", "window_s")

    def __init__(
        self,
        *,
        max_rpm: int = _DEFAULT_MAX_RPM,
        max_tpm: int = _DEFAULT_MAX_TPM,
        window_s: float = _QUOTA_WINDOW_S,
    ) -> None:
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self.window_s = window_s
        self._calls: list[tuple[float, int]] = []

    @staticmethod
    def from_environment() -> "_GeminiQuotaGate":
        """Build a gate using optional env overrides (invalid values fall back)."""
        rpm = _DEFAULT_MAX_RPM
        tpm = _DEFAULT_MAX_TPM
        raw_rpm = os.environ.get(_ENV_MAX_RPM)
        raw_tpm = os.environ.get(_ENV_MAX_TPM)
        if raw_rpm:
            try:
                rpm = max(1, int(raw_rpm.strip()))
            except ValueError:
                logger.warning("Invalid %s=%r; using %s", _ENV_MAX_RPM, raw_rpm, rpm)
        if raw_tpm:
            try:
                tpm = max(1, int(raw_tpm.strip()))
            except ValueError:
                logger.warning("Invalid %s=%r; using %s", _ENV_MAX_TPM, raw_tpm, tpm)
        return _GeminiQuotaGate(max_rpm=rpm, max_tpm=tpm, window_s=_QUOTA_WINDOW_S)

    @staticmethod
    def estimate_chars_as_tokens(texts: list[str]) -> int:
        """Rough input-token estimate for quota waits (chars / 4, minimum 1)."""
        total = sum(len(s) for s in texts)
        return max(1, total // 4)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        self._calls = [(t, n) for t, n in self._calls if t > cutoff]

    def wait_before_request(self, *, estimated_input_tokens: int) -> None:
        """Block until this request fits under RPM and TPM for the rolling window."""
        est = max(1, estimated_input_tokens)
        while True:
            now = time.monotonic()
            self._prune(now)
            n_req = len(self._calls)
            tok_sum = sum(toks for _, toks in self._calls)
            if n_req < self.max_rpm and tok_sum + est <= self.max_tpm:
                return
            sleep_s = 0.05
            if self._calls:
                oldest = self._calls[0][0]
                sleep_s = max(sleep_s, oldest + self.window_s - now + 0.001)
            logger.debug(
                "Gemini quota gate: sleeping %.2fs (requests %s/%s, tokens %s/%s, est +%s)",
                sleep_s,
                n_req,
                self.max_rpm,
                tok_sum,
                self.max_tpm,
                est,
            )
            time.sleep(min(sleep_s, 15.0))

    def record_completed_request(self, *, prompt_tokens: int | None, fallback_tokens: int) -> None:
        """Record one HTTP embed after it finishes (drives the next wait)."""
        recorded = prompt_tokens if prompt_tokens is not None else fallback_tokens
        self._calls.append((time.monotonic(), max(1, int(recorded))))


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
        self._gemini_quota: _GeminiQuotaGate | None = None

        if provider == "gemini":
            self._gemini_quota = _GeminiQuotaGate.from_environment()
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
            task_instruction: Optional Gemini Embedding 2 text-format template
                such as ``task: code retrieval | query: {content}`` or
                ``title: none | text: {content}``.

        Returns:
            Text payload to send to Gemini.

        Why this helper exists:
            The Embeddings 2 docs recommend formatting query/document text
            directly for text-only retrieval tasks. We therefore keep the
            formatting logic in one place so repo config can store the canonical
            template string and callers do not have to hand-roll it.
        """
        if not task_instruction:
            return text
        cleaned_instruction = task_instruction.strip()
        if not cleaned_instruction:
            return text
        if "{content}" in cleaned_instruction or "{title}" in cleaned_instruction:
            return cleaned_instruction.format(content=text, title="none")
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
            assert self._gemini_quota is not None
            prepared = self._prepare_gemini_content(
                text,
                task_instruction=task_instruction,
            )
            est = _GeminiQuotaGate.estimate_chars_as_tokens([prepared])
            self._gemini_quota.wait_before_request(estimated_input_tokens=est)
            response = self._client.models.embed_content(
                model=self.model,
                contents=prepared,
                config={"output_dimensionality": self.dimensions},
            )
            if not response.embeddings:
                raise RuntimeError("Gemini embed_content returned no embeddings")
            meta = self._build_gemini_metadata(response)
            self._gemini_quota.record_completed_request(
                prompt_tokens=meta.prompt_tokens or meta.total_tokens,
                fallback_tokens=est,
            )
            return list(response.embeddings[0].values), meta
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

    def embed_batch(
        self,
        texts: list[str],
        *,
        task_instruction: str | None = None,
    ) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts.

        Gemini ``batchEmbedContents`` accepts at most 100 texts per call, so we
        chunk the input list accordingly and send one API call per chunk.
        OpenAI/Nemotron use a single batched API call.

        For Gemini, optional ``task_instruction`` applies the same
        :meth:`_prepare_gemini_content` formatting as :meth:`embed_with_metadata`
        to each text so batched code indexing matches single-text behavior.

        Args:
            texts: List of input texts to embed.
            task_instruction: Optional Gemini Embedding 2 template; ignored by
                non-Gemini providers.

        Returns:
            List of embedding vectors (one per input text).
        """
        vectors, _ = self.embed_batch_with_metadata(
            texts,
            task_instruction=task_instruction,
        )
        return vectors

    def embed_batch_with_metadata(
        self,
        texts: list[str],
        *,
        task_instruction: str | None = None,
    ) -> tuple[list[list[float]], EmbeddingMetadata | None]:
        """Generate many embeddings plus aggregated usage metadata.

        Used by code ingestion to embed all chunks for one file in one or a few
        API calls instead of one request per function/class.

        Args:
            texts: Input texts (already truncated/normalized by the caller).
            task_instruction: Same semantics as :meth:`embed_with_metadata`.

        Returns:
            One vector per input text, and usage metadata when the provider
            returns it (Gemini/OpenAI aggregate per HTTP response; multiple
            Gemini sub-batches are summed).
        """
        if not texts:
            return [], None

        if self.provider == "gemini":
            assert self._gemini_quota is not None
            MAX_BATCH = GEMINI_BATCH_EMBED_MAX_TEXTS
            all_embeddings: list[list[float]] = []
            agg_prompt: int | None = None
            agg_total: int | None = None
            agg_cost: float = 0.0
            for i in range(0, len(texts), MAX_BATCH):
                chunk = texts[i : i + MAX_BATCH]
                prepared = [
                    self._prepare_gemini_content(t, task_instruction=task_instruction)
                    for t in chunk
                ]
                est = _GeminiQuotaGate.estimate_chars_as_tokens(prepared)
                self._gemini_quota.wait_before_request(estimated_input_tokens=est)
                result = self._client.models.embed_content(
                    model=self.model,
                    contents=prepared,
                    config={"output_dimensionality": self.dimensions},
                )
                # Some google-genai / API combinations return fewer embedding objects than
                # inputs (e.g. 1 for 4) while still HTTP 200 — fall back to one HTTP call
                # per text so Pass 2 always gets len(vectors) == len(chunk).
                emb_in = result.embeddings
                batch_metas: list[EmbeddingMetadata] = []
                if emb_in is not None and len(emb_in) == len(prepared):
                    for e in emb_in:
                        if e.values is None:
                            raise RuntimeError("Gemini returned an embedding without values")
                        all_embeddings.append(list(e.values))
                    meta = self._build_gemini_metadata(result)
                    batch_metas.append(meta)
                    self._gemini_quota.record_completed_request(
                        prompt_tokens=meta.prompt_tokens or meta.total_tokens,
                        fallback_tokens=est,
                    )
                else:
                    logger.warning(
                        "Gemini batchEmbedContents returned %s embedding object(s) for %s inputs; "
                        "falling back to sequential embeds for this chunk.",
                        len(emb_in) if emb_in is not None else 0,
                        len(prepared),
                    )
                    for p in prepared:
                        est1 = _GeminiQuotaGate.estimate_chars_as_tokens([p])
                        self._gemini_quota.wait_before_request(estimated_input_tokens=est1)
                        r1 = self._client.models.embed_content(
                            model=self.model,
                            contents=[p],
                            config={"output_dimensionality": self.dimensions},
                        )
                        if not r1.embeddings:
                            raise RuntimeError("Gemini returned no embeddings for sequential embed")
                        all_embeddings.append(list(r1.embeddings[0].values))
                        m1 = self._build_gemini_metadata(r1)
                        batch_metas.append(m1)
                        self._gemini_quota.record_completed_request(
                            prompt_tokens=m1.prompt_tokens or m1.total_tokens,
                            fallback_tokens=est1,
                        )

                for meta in batch_metas:
                    if meta.prompt_tokens is not None:
                        agg_prompt = (agg_prompt or 0) + meta.prompt_tokens
                    if meta.total_tokens is not None:
                        agg_total = (agg_total or 0) + meta.total_tokens
                    if meta.estimated_cost_usd is not None:
                        agg_cost += meta.estimated_cost_usd
            combined: EmbeddingMetadata | None = None
            if agg_prompt is not None or agg_total is not None or agg_cost > 0:
                combined = EmbeddingMetadata(
                    provider=self.provider,
                    model=self.model,
                    prompt_tokens=agg_prompt,
                    total_tokens=agg_total,
                    estimated_cost_usd=agg_cost if agg_cost > 0 else None,
                    transport="vertex_ai" if self.vertexai else "developer_api",
                )
            return all_embeddings, combined

        response = self._client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )
        vectors = [d.embedding for d in response.data]
        return vectors, self._build_openai_metadata(response)

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
