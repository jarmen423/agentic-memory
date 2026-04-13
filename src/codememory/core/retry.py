"""Small retry loop for embedding/LLM HTTP clients and similar call sites.

`openai` and `httpx` errors that represent timeouts, connection loss, or rate limits
are classified via `is_transient_provider_error` so `retry_transient` can re-run a
zero-argument callable without wrapping business logic in nested try/except.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import httpx
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

T = TypeVar("T")


def is_transient_provider_error(exc: Exception) -> bool:
    """True if ``exc`` looks like a network blip or provider throttle (safe to retry once or twice)."""
    if isinstance(
        exc,
        (
            TimeoutError,
            OSError,
            httpx.TimeoutException,
            httpx.NetworkError,
            APITimeoutError,
            APIConnectionError,
            InternalServerError,
            RateLimitError,
        ),
    ):
        return True
    return False


def retry_transient(
    operation: Callable[[], T],
    *,
    attempts: int = 2,
    delay_seconds: float = 0.0,
) -> T:
    """Run ``operation``; on failure, retry if :func:`is_transient_provider_error` agrees.

    Args:
        operation: Nullary callable (e.g. lambda embedding a single chunk).
        attempts: Total tries including the first; must be >= 1.
        delay_seconds: Optional sleep between attempts (only after a transient failure).

    Returns:
        The value returned by ``operation``.

    Raises:
        ValueError: If ``attempts`` < 1.
        Exception: The last exception if non-transient or retries exhausted.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= attempts or not is_transient_provider_error(exc):
                raise
            if delay_seconds > 0:
                time.sleep(delay_seconds)

    assert last_error is not None
    raise last_error
