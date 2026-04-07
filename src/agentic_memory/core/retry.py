"""Shared retry helpers for transient provider and network failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import httpx
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

T = TypeVar("T")


def is_transient_provider_error(exc: Exception) -> bool:
    """Return whether an exception is likely transient and safe to retry."""
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
    """Retry one callable only when the thrown exception is transient."""
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
