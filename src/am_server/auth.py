"""Bearer token authentication dependency for am_server."""

from __future__ import annotations

import os

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Use ``auto_error=False`` so the dependency can normalize both missing and
# invalid bearer tokens into the same explicit 401 contract expected by the
# public API and test suite.
_bearer = HTTPBearer(auto_error=False)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
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
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
