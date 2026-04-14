"""Shared reranking helpers and hosted backend integrations.

This module provides a small domain-agnostic reranking foundation for
code/search/conversation retrieval. It keeps the backend pluggable, defaults to
no-op when disabled or unconfigured, and exposes enough structured metadata for
callers to preserve provenance and fall back cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from typing import Any, Iterable, Sequence

import httpx

logger = logging.getLogger(__name__)

DEFAULT_RERANK_PROVIDER = "cohere"
DEFAULT_RERANK_MODEL = "rerank-v4.0-fast"
DEFAULT_RERANK_TIMEOUT_MS = 2500
DEFAULT_RERANK_MAX_TOKENS_PER_DOC = 2048
DEFAULT_RERANK_ABSTAIN_THRESHOLD = 0.35
DEFAULT_RERANK_FALLBACK_PROVIDER = "none"

_DOMAIN_LIMIT_ENVS = {
    "code": "AM_CODE_RERANK_TOP_K",
    "web": "AM_WEB_RERANK_TOP_K",
    "research": "AM_WEB_RERANK_TOP_K",
    "conversation": "AM_CONVERSATION_RERANK_TOP_K",
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", name, raw, default)
        return default


@dataclass(slots=True)
class RerankSettings:
    """Runtime settings for the shared reranking layer."""

    enabled: bool
    provider: str
    fallback_provider: str
    model: str
    fallback_model: str | None
    timeout_ms: int
    max_tokens_per_doc: int
    abstain_threshold: float
    client_name: str = "agentic-memory"


@dataclass(slots=True)
class RerankScore:
    """One reranked candidate reference."""

    index: int
    relevance_score: float


@dataclass(slots=True)
class RerankResponse:
    """Structured rerank result with graceful fallback metadata."""

    applied: bool
    provider: str | None = None
    model: str | None = None
    fallback_reason: str | None = None
    scores: list[RerankScore] = field(default_factory=list)
    abstained: bool = False
    high_stakes: bool = False
    top_score: float | None = None


class RerankUnavailableError(RuntimeError):
    """Raised when a rerank backend cannot be used."""


class RerankRequestError(RuntimeError):
    """Raised when a hosted rerank request fails with retryability metadata."""

    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class CohereReranker:
    """Minimal Cohere Rerank API v2 client."""

    endpoint = "https://api.cohere.com/v2/rerank"
    provider = "cohere"

    def rerank(
        self,
        *,
        query: str,
        documents: Sequence[str],
        settings: RerankSettings,
    ) -> list[RerankScore]:
        api_key = os.getenv("COHERE_API_KEY", "").strip()
        if not api_key:
            raise RerankUnavailableError("missing_api_key")

        payload = {
            "model": settings.model,
            "query": query,
            "documents": list(documents),
            "top_n": len(documents),
            "max_tokens_per_doc": settings.max_tokens_per_doc,
        }
        return _post_rerank_request(
            endpoint=self.endpoint,
            api_key=api_key,
            client_name=settings.client_name,
            payload=payload,
            timeout_ms=settings.timeout_ms,
        )


class OpenRouterReranker:
    """OpenRouter fallback that targets the rerank-compatible endpoint."""

    endpoint = "https://openrouter.ai/api/v1/rerank"
    provider = "openrouter"

    def rerank(
        self,
        *,
        query: str,
        documents: Sequence[str],
        settings: RerankSettings,
    ) -> list[RerankScore]:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RerankUnavailableError("missing_openrouter_api_key")
        model = (settings.fallback_model or "").strip()
        if not model:
            raise RerankUnavailableError("missing_fallback_model")

        payload = {
            "model": model,
            "query": query,
            "documents": list(documents),
            "top_n": len(documents),
        }
        return _post_rerank_request(
            endpoint=self.endpoint,
            api_key=api_key,
            client_name=settings.client_name,
            payload=payload,
            timeout_ms=settings.timeout_ms,
        )


def _post_rerank_request(
    *,
    endpoint: str,
    api_key: str,
    client_name: str,
    payload: dict[str, Any],
    timeout_ms: int,
) -> list[RerankScore]:
    """Execute one hosted rerank request and classify failures for failover."""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Client-Name": client_name,
    }
    timeout_seconds = max(timeout_ms / 1000.0, 0.1)
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(endpoint, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise RerankRequestError("timeout", retryable=True) from exc
    except httpx.NetworkError as exc:
        raise RerankRequestError(type(exc).__name__, retryable=True) from exc
    except httpx.HTTPError as exc:
        raise RerankRequestError(type(exc).__name__, retryable=False) from exc

    if response.status_code >= 400:
        retryable = response.status_code == 429 or response.status_code >= 500
        raise RerankRequestError(
            f"http_{response.status_code}",
            retryable=retryable,
        )
    body = response.json()

    return [
        RerankScore(
            index=int(item["index"]),
            relevance_score=float(item["relevance_score"]),
        )
        for item in (body.get("results") or [])
    ]


def load_rerank_settings() -> RerankSettings:
    """Load reranking settings from environment variables."""

    return RerankSettings(
        enabled=_env_flag("AM_RERANK_ENABLED", False),
        provider=(os.getenv("AM_RERANK_PROVIDER") or DEFAULT_RERANK_PROVIDER).strip().lower(),
        fallback_provider=(
            os.getenv("AM_RERANK_FALLBACK_PROVIDER") or DEFAULT_RERANK_FALLBACK_PROVIDER
        )
        .strip()
        .lower(),
        model=(os.getenv("AM_RERANK_MODEL") or DEFAULT_RERANK_MODEL).strip(),
        fallback_model=(os.getenv("AM_RERANK_FALLBACK_MODEL") or "").strip() or None,
        timeout_ms=_env_int("AM_RERANK_TIMEOUT_MS", DEFAULT_RERANK_TIMEOUT_MS),
        max_tokens_per_doc=_env_int(
            "AM_RERANK_MAX_TOKENS_PER_DOC",
            DEFAULT_RERANK_MAX_TOKENS_PER_DOC,
        ),
        abstain_threshold=_env_float(
            "AM_RERANK_ABSTAIN_THRESHOLD",
            DEFAULT_RERANK_ABSTAIN_THRESHOLD,
        ),
        client_name=(os.getenv("AM_RERANK_CLIENT_NAME") or "agentic-memory").strip(),
    )


def is_reranking_enabled() -> bool:
    """Return whether the shared reranker is enabled."""

    return load_rerank_settings().enabled


def candidate_limit_for_domain(domain: str, *, default: int) -> int:
    """Return a widened candidate limit when reranking is enabled."""

    if not is_reranking_enabled():
        return default
    env_name = _DOMAIN_LIMIT_ENVS.get(domain.strip().lower())
    if not env_name:
        return default
    return max(default, _env_int(env_name, default))


def _coerce_backend(provider: str) -> CohereReranker | OpenRouterReranker:
    normalized = provider.strip().lower()
    if normalized == "cohere":
        return CohereReranker()
    if normalized == "openrouter":
        return OpenRouterReranker()
    raise RerankUnavailableError(f"unsupported_provider:{normalized}")


def _should_attempt_fallback(
    *,
    primary_provider: str,
    fallback_provider: str,
    error: Exception,
) -> bool:
    """Allow fallback only for retryable provider-side failures."""

    if not fallback_provider or fallback_provider in {"none", primary_provider}:
        return False
    if isinstance(error, RerankRequestError):
        return error.retryable
    return False


def _execute_rerank_with_provider(
    *,
    provider: str,
    query: str,
    documents: Sequence[str],
    settings: RerankSettings,
) -> list[RerankScore]:
    backend = _coerce_backend(provider)
    return backend.rerank(query=query, documents=documents, settings=settings)


def rerank_documents(
    query: str,
    documents: Sequence[str],
    *,
    high_stakes: bool = False,
) -> RerankResponse:
    """Rerank one list of serialized candidate documents.

    Returns a structured fallback response instead of raising so callers can keep
    serving baseline results when the hosted backend is disabled or unavailable.
    """

    settings = load_rerank_settings()
    if not settings.enabled:
        return RerankResponse(applied=False, fallback_reason="disabled", high_stakes=high_stakes)
    if len(documents) < 2:
        return RerankResponse(
            applied=False,
            provider=settings.provider,
            model=settings.model,
            fallback_reason="too_few_candidates",
            high_stakes=high_stakes,
        )
    if not query.strip():
        return RerankResponse(
            applied=False,
            provider=settings.provider,
            model=settings.model,
            fallback_reason="empty_query",
            high_stakes=high_stakes,
        )

    try:
        scores = _execute_rerank_with_provider(
            provider=settings.provider,
            query=query,
            documents=documents,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rerank backend failure: %s", exc)
        if _should_attempt_fallback(
            primary_provider=settings.provider,
            fallback_provider=settings.fallback_provider,
            error=exc,
        ):
            fallback_reason = str(exc)
            try:
                scores = _execute_rerank_with_provider(
                    provider=settings.fallback_provider,
                    query=query,
                    documents=documents,
                    settings=settings,
                )
                provider = settings.fallback_provider
                model = settings.fallback_model if settings.fallback_provider == "openrouter" else settings.model
            except Exception as fallback_exc:  # noqa: BLE001
                logger.warning("Rerank fallback backend failure: %s", fallback_exc)
                return RerankResponse(
                    applied=False,
                    provider=settings.fallback_provider,
                    model=settings.fallback_model if settings.fallback_provider == "openrouter" else settings.model,
                    fallback_reason=f"{fallback_reason}|fallback:{fallback_exc}",
                    high_stakes=high_stakes,
                )
            else:
                top_score = scores[0].relevance_score if scores else None
                abstained = bool(
                    high_stakes and top_score is not None and top_score < settings.abstain_threshold
                )
                return RerankResponse(
                    applied=True,
                    provider=provider,
                    model=model,
                    fallback_reason=f"primary_failed:{fallback_reason}",
                    scores=scores,
                    abstained=abstained,
                    high_stakes=high_stakes,
                    top_score=top_score,
                )
        return RerankResponse(
            applied=False,
            provider=settings.provider,
            model=settings.model,
            fallback_reason=str(exc),
            high_stakes=high_stakes,
        )

    top_score = scores[0].relevance_score if scores else None
    abstained = bool(high_stakes and top_score is not None and top_score < settings.abstain_threshold)
    return RerankResponse(
        applied=True,
        provider=settings.provider,
        model=settings.model,
        scores=scores,
        abstained=abstained,
        high_stakes=high_stakes,
        top_score=top_score,
    )


def build_yaml_card(fields: Iterable[tuple[str, Any]]) -> str:
    """Serialize structured candidate fields into a YAML-like string.

    Cohere recommends YAML strings for structured documents. This helper keeps
    serialization dependency-free and stable enough for ranking use.
    """

    lines: list[str] = []
    for key, value in fields:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            if "\n" in text:
                lines.append(f"{key}: |-")
                lines.extend(f"  {line}" for line in text.splitlines())
            else:
                lines.append(f"{key}: {text}")
            continue
        if isinstance(value, (list, tuple, set)):
            items = [str(item).strip() for item in value if str(item).strip()]
            if not items:
                continue
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in items)
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines).strip()
