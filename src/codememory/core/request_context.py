"""Async-safe request correlation id via :mod:`contextvars`.

HTTP/MCP handlers call :func:`set_request_id` when a request starts and
:func:`reset_request_id` when done so logs and downstream code can read the same id
with :func:`get_request_id` without threading globals through every function.
"""

from __future__ import annotations

from contextvars import ContextVar

# Isolated per asyncio task / worker request; default None when outside a tracked request.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str | None) -> object:
    """Store the current request id and return the reset token."""
    return _request_id.set(request_id)


def get_request_id() -> str | None:
    """Return the current request-scoped correlation id, if any."""
    return _request_id.get()


def reset_request_id(token: object) -> None:
    """Reset the request id context to the previous value."""
    _request_id.reset(token)
