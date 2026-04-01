"""Tests for transient retry helpers."""

from __future__ import annotations

import pytest

from codememory.core.retry import retry_transient


def test_retry_transient_retries_timeout_then_succeeds():
    """Transient timeout errors are retried."""
    attempts = {"count": 0}

    def op():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("slow")
        return "ok"

    assert retry_transient(op, attempts=2) == "ok"
    assert attempts["count"] == 2


def test_retry_transient_does_not_retry_validation_errors():
    """Non-transient errors surface immediately."""
    attempts = {"count": 0}

    def op():
        attempts["count"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        retry_transient(op, attempts=3)

    assert attempts["count"] == 1
