"""Bearer token authentication dependency for am_server."""

from __future__ import annotations

import os

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer()


def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    """Validate Bearer token against AM_SERVER_API_KEY env var.

    Raises:
        HTTPException 503: If AM_SERVER_API_KEY is not configured.
        HTTPException 401: If the provided token does not match.
    Returns:
        The valid credentials token string.
    """
    expected = os.environ.get("AM_SERVER_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="AM_SERVER_API_KEY not configured",
        )
    if credentials.credentials != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
