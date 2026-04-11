"""Bearer token authentication dependency for am_server."""

from __future__ import annotations

import os

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Use ``auto_error=False`` so the dependency can normalize both missing and
# invalid bearer tokens into the same explicit 401 contract expected by the
# public API and test suite.
_bearer = HTTPBearer(auto_error=False)


def _expected_api_keys() -> set[str]:
    """Return the configured valid API keys for the backend.

    `AM_SERVER_API_KEYS` is the new multi-key contract used for safe rotation.
    `AM_SERVER_API_KEY` remains supported for backward compatibility.
    """

    raw_multi = os.environ.get("AM_SERVER_API_KEYS", "")
    keys = {item.strip() for item in raw_multi.split(",") if item.strip()}
    if keys:
        return keys

    raw_single = os.environ.get("AM_SERVER_API_KEY", "").strip()
    return {raw_single} if raw_single else set()


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str:
    """Validate Bearer token against the configured backend API key set.

    Raises:
        HTTPException 503: If no backend API key is configured.
        HTTPException 401: If the caller omitted or supplied an invalid key.
    Returns:
        The valid credentials token string.
    """
    expected_keys = _expected_api_keys()
    if not expected_keys:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "auth_not_configured",
                "message": "No backend API key is configured.",
            },
        )
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "auth_missing_api_key",
                "message": "Missing API key.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials not in expected_keys:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "auth_invalid_api_key",
                "message": "Invalid API key.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
