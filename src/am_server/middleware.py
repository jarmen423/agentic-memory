"""ASGI middleware that binds a per-request correlation id.

Runs early in the FastAPI/Starlette stack so downstream handlers, exception
handlers, and structured logs can read the same id via
``agentic_memory.core.request_context`` (contextvars). The same value is echoed
on the HTTP response as ``X-Request-ID`` for client ↔ server log correlation.
"""

from __future__ import annotations

import uuid

from fastapi import Request

from agentic_memory.core.request_context import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"


async def request_id_middleware(request: Request, call_next):
    """Propagate or mint ``X-Request-ID`` through context, state, and response.

    Starlette invokes ``call_next`` to run the rest of the middleware stack and
    the route. The ``try``/``finally`` ensures the contextvar is reset even when
    ``call_next`` raises, so later tasks in the same worker do not inherit a
    stale id.

    Args:
        request: Incoming request; may already carry ``X-Request-ID``.
        call_next: Next ASGI application in the chain (standard middleware
            signature used by ``app.middleware("http")``).

    Returns:
        The downstream response with ``X-Request-ID`` set to the resolved id.

    Note:
        ``request.state.request_id`` duplicates the value for handlers that read
        ``Request`` directly; error payloads should still prefer the context
        helper so exception paths stay consistent.
    """
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    # Contextvar: logging and error formatters read this without threading Request.
    token = set_request_id(request_id)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
