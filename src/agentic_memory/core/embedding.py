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
from typing import Any, Protocol

from google import genai
from google.genai import types as genai_types
from openai import OpenAI

logger = logging.getLogger(__name__)


# Environment variables for the local-GPU provider (nemotron_local). Kept as
# module-level constants so tests and Colab notebooks can reference them by
# symbol rather than magic strings.
_ENV_LOCAL_EMBED_MODEL = "AM_LOCAL_EMBED_MODEL"
_ENV_LOCAL_EMBED_MAX_SEQ = "AM_LOCAL_EMBED_MAX_SEQ"
_ENV_LOCAL_EMBED_BATCH_SIZE = "AM_LOCAL_EMBED_BATCH_SIZE"
_ENV_LOCAL_EMBED_POOLING = "AM_LOCAL_EMBED_POOLING"  # 'mean' (default) | 'cls'

# Default local model. Chosen because:
#   - Publicly available on HuggingFace without gated access.
#   - Known-good GPU footprint on Colab T4/G4 (fits comfortably in fp16 VRAM).
#   - Strong retrieval benchmarks (top of MTEB for its size class).
# Override via ``AM_LOCAL_EMBED_MODEL`` to swap in an NVIDIA Nemotron
# retriever or any other HuggingFace text encoder once the scale experiments
# settle on a specific checkpoint. The actual output dimension is detected
# at load time from a probe forward pass, so this default is decoupled from
# the Neo4j vector index dimension.
_DEFAULT_LOCAL_EMBED_MODEL = "intfloat/multilingual-e5-large-instruct"

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
            ``developer_api`` or ``vertex_ai`` for Gemini, or ``local_gpu``
            for the in-process HuggingFace provider.
    """

    provider: str
    model: str
    prompt_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    transport: str | None = None


class _LocalEmbedder(Protocol):
    """Minimal interface any local-inference embedder must satisfy.

    The scale-experiments pipeline talks to the local model through this
    Protocol so the concrete implementation (HuggingFace transformers today,
    possibly vLLM or a quantized runtime later) can be swapped without
    changing :class:`EmbeddingService`.
    """

    dimensions: int
    model_name: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalized embedding per input text."""
        ...


class _LocalGPUEmbedder:
    """Local HuggingFace encoder wrapped for the ``nemotron_local`` provider.

    Responsibilities:
        - Lazy-import ``torch`` and ``transformers`` so the wider
          ``agentic_memory`` import path does not force these heavy deps on
          callers who only use cloud providers.
        - Place the model on CUDA (half-precision) when available, otherwise
          fall back to CPU ``float32`` so local dev still works without a GPU.
        - Run mean (or CLS) pooling over the final hidden states and L2
          normalize the resulting vectors. Normalization is required because
          the Neo4j vector index is configured with cosine similarity: with
          unit-length vectors, cosine becomes a simple inner product and
          retrieval scores stay in [-1, 1].
        - Expose ``self.dimensions`` detected from a warm-up probe call so
          :class:`EmbeddingService` can reconcile against the Neo4j index
          dimension before the first write.

    Args:
        model_name: HuggingFace model id (e.g. ``nvidia/NV-Embed-v2``).
            Read from ``AM_LOCAL_EMBED_MODEL`` env var by the caller when
            not passed explicitly.
        max_seq_length: Input truncation length in tokens. Longer inputs are
            right-truncated. 512 is a safe default for retrieval encoders.
        batch_size: Number of texts per forward pass. Tune down to 4 or 8
            for Colab T4's 15 GB VRAM when using 7B-class models.
        pooling: ``'mean'`` (default) or ``'cls'``. Mean-pooling weighted by
            the attention mask matches the convention used by most modern
            retrieval encoders (e5, gte, BGE, NV-Embed).

    Raises:
        ImportError: If ``torch`` or ``transformers`` is not installed.
        RuntimeError: If the model produces no output on the probe call.
    """

    def __init__(
        self,
        model_name: str,
        *,
        max_seq_length: int = 512,
        batch_size: int = 16,
        pooling: str = "mean",
    ) -> None:
        try:
            import torch  # type: ignore[import-not-found]
            from transformers import (  # type: ignore[import-not-found]
                AutoModel,
                AutoTokenizer,
            )
        except ImportError as exc:  # pragma: no cover — environment check
            raise ImportError(
                "Local-GPU embedding provider requires 'torch' and "
                "'transformers'. Install with: "
                "pip install torch transformers accelerate"
            ) from exc

        # Hold the torch module so pooling code can reach it without a second
        # import that might cost 100+ ms on Colab first-run.
        self._torch = torch

        self.model_name = model_name
        self.max_seq_length = max_seq_length
        self.batch_size = batch_size
        self.pooling = pooling.lower()
        if self.pooling not in {"mean", "cls"}:
            raise ValueError(
                f"Unsupported pooling={pooling!r}; expected 'mean' or 'cls'."
            )

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # fp16 on CUDA keeps VRAM usage near the floor for 1–7B-class
        # encoders. On CPU we stick with fp32 because some architectures
        # emit NaNs in fp16 without specialized kernels.
        self._dtype = torch.float16 if self._device.type == "cuda" else torch.float32

        logger.info(
            "Loading local embedder %s on %s (dtype=%s)...",
            model_name, self._device.type, self._dtype,
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=True
        )
        self.model = AutoModel.from_pretrained(
            model_name,
            torch_dtype=self._dtype,
            trust_remote_code=True,
        ).to(self._device)
        self.model.eval()

        # Warm-up probe: establishes output dimensionality and triggers any
        # lazy kernel compilation (e.g. flash-attn) so first real batch does
        # not pay that cost.
        probe_vectors = self.encode(["probe"])
        if not probe_vectors or not probe_vectors[0]:
            raise RuntimeError(
                f"Local embedder {model_name!r} returned no vectors on warm-up."
            )
        self.dimensions = len(probe_vectors[0])
        logger.info(
            "Local embedder ready: model=%s dim=%d batch_size=%d max_seq=%d",
            model_name, self.dimensions, self.batch_size, self.max_seq_length,
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Tokenize, run the model, pool, L2-normalize, return Python lists.

        Operates in ``torch.inference_mode`` to skip autograd bookkeeping
        entirely — this is faster than ``torch.no_grad`` for pure forward
        inference and avoids tracker allocation on every call.

        Args:
            texts: Raw input strings. Any prefixing expected by retrieval
                models (e.g. ``"query: "`` for e5) must be applied by the
                caller before passing the string in; this method is prefix-
                agnostic.

        Returns:
            One list[float] per input, already L2-normalized.
        """
        if not texts:
            return []

        torch = self._torch
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i : i + self.batch_size]
            inputs = self.tokenizer(
                chunk,
                padding=True,
                truncation=True,
                max_length=self.max_seq_length,
                return_tensors="pt",
            ).to(self._device)

            with torch.inference_mode():
                outputs = self.model(**inputs)
                # Most encoders expose ``last_hidden_state``; some (e.g.
                # sentence-bert variants with a pooler head) expose a
                # pooled output on ``pooler_output``. We prefer explicit
                # pooling over last_hidden_state for reproducibility
                # across model families.
                hidden = outputs.last_hidden_state  # [batch, seq, hidden]

                if self.pooling == "cls":
                    pooled = hidden[:, 0]
                else:
                    # Mask-aware mean pooling: zero out padding positions
                    # before averaging so sequence length does not bias
                    # the magnitude of short inputs.
                    mask = inputs["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                    summed = (hidden * mask).sum(dim=1)
                    counts = mask.sum(dim=1).clamp(min=1e-9)
                    pooled = summed / counts

                # Cosine similarity == inner product for unit vectors, so
                # normalize here and the Neo4j index lookup stays simple.
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=-1)

            # Move to CPU fp32 for JSON-safe transport back to callers.
            all_vectors.extend(pooled.float().cpu().tolist())

        return all_vectors


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
        # NVIDIA hosted embedding API (OpenAI-compatible HTTP at
        # integrate.api.nvidia.com). Use when remote inference is preferred.
        "nemotron": {"model": "nvidia/nv-embedqa-e5-v5", "dimensions": 4096},
        # In-process local GPU inference via HuggingFace transformers. The
        # ``dimensions`` value here is only used when the caller does not
        # override via ``output_dimensions``; the actual dim is detected from
        # the loaded model's warm-up probe. Model id is read from the
        # ``AM_LOCAL_EMBED_MODEL`` env var or the ``model`` kwarg.
        "nemotron_local": {
            "model": _DEFAULT_LOCAL_EMBED_MODEL,
            "dimensions": 1024,
        },
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
            provider: One of 'openai', 'gemini', 'nemotron', 'nemotron_local'.
                The ``nemotron_local`` provider loads a HuggingFace encoder on
                the local GPU (or CPU) and does not require an API key.
            api_key: API key for the selected provider. Gemini-on-Vertex can use
                Application Default Credentials instead of an API key.
                Ignored by ``nemotron_local``.
            model: Optional model override for the selected provider. For
                ``nemotron_local``, this is the HuggingFace model id and
                takes precedence over the ``AM_LOCAL_EMBED_MODEL`` env var.
            base_url: Optional base URL override (for Nemotron custom endpoints).
                Ignored by ``nemotron_local``.
            output_dimensions: Optional dimension override. Defaults to provider
                standard. For ``nemotron_local`` this acts as an assertion: the
                loaded model must produce vectors of this dimensionality, or
                ``__init__`` raises ``ValueError``.
            vertexai: Whether Gemini traffic should use the Vertex AI transport.
            project: Google Cloud project for Vertex AI usage.
            location: Vertex AI location. Defaults to ``global`` when omitted.
            api_version: Optional Gen AI SDK API version override for Vertex AI.

        Raises:
            ValueError: If provider is not supported, or if ``output_dimensions``
                contradicts the actual dimensionality of a local model.
            ImportError: When ``provider='nemotron_local'`` and the optional
                ``torch``/``transformers`` stack is not installed.
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

        # The local embedder is only constructed for ``nemotron_local``. The
        # other branches leave it as None so ``_client`` remains the primary
        # handle for remote providers.
        self._local_embedder: _LocalEmbedder | None = None

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
        elif provider == "nemotron_local":
            # Resolve model id and runtime knobs, preferring explicit kwargs
            # over environment variables over the PROVIDERS default. This
            # mirrors the override chain used elsewhere in agentic_memory so
            # ops docs can stay simple: "set AM_LOCAL_EMBED_MODEL" is enough
            # for Colab, and unit tests can still pass ``model=`` directly.
            resolved_model = (
                model
                or os.environ.get(_ENV_LOCAL_EMBED_MODEL)
                or self.PROVIDERS["nemotron_local"]["model"]
            )
            max_seq = int(os.environ.get(_ENV_LOCAL_EMBED_MAX_SEQ, "512"))
            batch = int(os.environ.get(_ENV_LOCAL_EMBED_BATCH_SIZE, "16"))
            pooling = os.environ.get(_ENV_LOCAL_EMBED_POOLING, "mean")

            self._local_embedder = _LocalGPUEmbedder(
                resolved_model,
                max_seq_length=max_seq,
                batch_size=batch,
                pooling=pooling,
            )
            self._client = None
            # The warm-up probe in ``_LocalGPUEmbedder.__init__`` determined
            # the true output dimensionality. Reconcile against any caller
            # expectation so we fail loudly rather than silently writing
            # mismatched vectors into the Neo4j index.
            detected = self._local_embedder.dimensions
            if output_dimensions is not None and output_dimensions != detected:
                raise ValueError(
                    f"output_dimensions={output_dimensions} was requested for "
                    f"nemotron_local, but model {resolved_model!r} produces "
                    f"{detected}-dim vectors. Update Neo4j index or choose a "
                    "model whose output dimensionality matches."
                )
            self.dimensions = detected
            self.model = resolved_model
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

    @staticmethod
    def _apply_task_instruction(text: str, task_instruction: str | None) -> str:
        """Apply an optional retrieval task instruction to a raw text.

        Shared between the local-GPU and Gemini branches. The same format
        template conventions used for Gemini Embedding 2 (``{content}``,
        ``{title}``) also work for retrieval models like e5 and bge that
        expect a ``"query: ..."`` or ``"passage: ..."`` prefix on the
        input. Unifying the logic avoids drift between provider branches.

        Args:
            text: Raw input text.
            task_instruction: Optional template or literal prefix. ``None``
                or empty string → return ``text`` unchanged.

        Returns:
            The formatted text, ready for tokenization.
        """
        if not task_instruction:
            return text
        cleaned = task_instruction.strip()
        if not cleaned:
            return text
        if "{content}" in cleaned or "{title}" in cleaned:
            return cleaned.format(content=text, title="none")
        return f"{cleaned}\n\n{text}"

    def _local_gpu_metadata(self, texts: list[str]) -> EmbeddingMetadata:
        """Build an :class:`EmbeddingMetadata` record for a local GPU call.

        Local inference has no billable-token concept, so we report a
        character-based token estimate (chars/4) for observability parity
        with the remote providers. ``estimated_cost_usd`` is explicitly
        ``0.0`` because the GPU time is already paid for upstream.
        """
        tokens_approx = sum(max(1, len(t) // 4) for t in texts)
        return EmbeddingMetadata(
            provider=self.provider,
            model=self.model,
            prompt_tokens=tokens_approx,
            total_tokens=tokens_approx,
            estimated_cost_usd=0.0,
            transport="local_gpu",
        )

    def embed_with_metadata(
        self,
        text: str,
        *,
        task_instruction: str | None = None,
    ) -> tuple[list[float], EmbeddingMetadata]:
        """Generate one embedding vector plus normalized provider metadata.

        Args:
            text: Input text to embed.
            task_instruction: Optional retrieval task instruction. Applied
                for Gemini (per the Embeddings 2 format) and for the
                local-GPU provider (as a prefix template). Ignored by the
                remote NVIDIA and OpenAI providers.

        Returns:
            Tuple of ``(embedding_vector, normalized_metadata)``.
        """
        if self.provider == "nemotron_local":
            assert self._local_embedder is not None, (
                "Local embedder not initialized for nemotron_local provider."
            )
            prepared = self._apply_task_instruction(text, task_instruction)
            vectors = self._local_embedder.encode([prepared])
            return vectors[0], self._local_gpu_metadata([prepared])

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

        if self.provider == "nemotron_local":
            assert self._local_embedder is not None, (
                "Local embedder not initialized for nemotron_local provider."
            )
            # Apply the task instruction once per text up-front. The local
            # embedder's own batching then controls GPU memory use — we do
            # not need a second-level batch loop here because
            # ``_LocalGPUEmbedder.encode`` already chunks by ``batch_size``.
            prepared = [
                self._apply_task_instruction(t, task_instruction) for t in texts
            ]
            vectors = self._local_embedder.encode(prepared)
            return vectors, self._local_gpu_metadata(prepared)

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
