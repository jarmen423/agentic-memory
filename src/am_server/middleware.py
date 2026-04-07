"""FastAPI middleware for request correlation ids."""

from __future__ import annotations

import uuid

from fastapi import Request

from agentic_memory.core.request_context import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"


async def request_id_middleware(request: Request, call_next):
    """Attach a stable request id to request state, logs, and response headers."""
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    token = set_request_id(request_id)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
