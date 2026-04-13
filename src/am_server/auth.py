"""Bearer token authentication and per-surface API key resolution for ``am_server``.

This module wires FastAPI's HTTP Bearer security to environment-backed API keys.
Callers choose a *surface* (REST ``api``, hosted public MCP, or internal/full MCP);
each surface can use its own key set so public plugin traffic never shares keys with
the general backend or self-hosted mounts.

**Token resolution:** :func:`resolve_bearer_token` reads ``Authorization`` as a
case-insensitive ``Bearer <token>`` prefix. :func:`require_auth` uses FastAPI's
``HTTPBearer(auto_error=False)`` so missing and malformed headers both become explicit
401 responses with a consistent JSON body (and ``WWW-Authenticate``), matching the
public API contract and tests.

**Surface validation:** :func:`validate_surface_token` compares the extracted token
to the set from :func:`expected_api_keys_for_surface` and returns HTTP status,
machine ``code``, and human message—useful for MCP or middleware that cannot raise
``HTTPException`` inline.

**Strict MCP mode:** When ``AM_SERVER_STRICT_MCP_AUTH`` is truthy, public and
internal MCP surfaces require dedicated keys; if those env vars are empty, validation
returns 503 ``auth_not_configured`` instead of falling back to the general API keys.

Environment variables (see :func:`expected_api_keys_for_surface`):

* General REST/API: ``AM_SERVER_API_KEYS`` (comma-separated), else ``AM_SERVER_API_KEY``.
* Public MCP: ``AM_SERVER_PUBLIC_MCP_API_KEYS`` / ``AM_SERVER_PUBLIC_MCP_API_KEY``.
* Internal MCP: ``AM_SERVER_INTERNAL_MCP_API_KEYS`` / ``AM_SERVER_INTERNAL_MCP_API_KEY``.
* Flag: ``AM_SERVER_STRICT_MCP_AUTH`` — enable dedicated MCP key requirement.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Use ``auto_error=False`` so the dependency can normalize both missing and
# invalid bearer tokens into the same explicit 401 contract expected by the
# public API and test suite.
_bearer = HTTPBearer(auto_error=False)


def _truthy_env(value: str | None) -> bool:
    """Interpret common truthy env-var values."""

    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def strict_mcp_auth_enabled() -> bool:
    """Return whether MCP surfaces must use dedicated keys (no fallback to general API keys).

    Reads ``AM_SERVER_STRICT_MCP_AUTH``. Truthy values are ``1``, ``true``, ``yes``, ``on``
    (case-insensitive, after strip).

    Returns:
        ``True`` if strict MCP auth is enabled; otherwise ``False``.
    """

    return _truthy_env(os.environ.get("AM_SERVER_STRICT_MCP_AUTH"))


def _parse_api_keys(raw_multi: str, raw_single: str) -> set[str]:
    """Parse one multi-key env var plus one single-key env var."""

    keys = {item.strip() for item in raw_multi.split(",") if item.strip()}
    if keys:
        return keys

    return {raw_single} if raw_single else set()


def expected_api_keys_for_surface(surface: str = "api") -> set[str]:
    """Resolve the set of valid API keys for an auth surface from the environment.

    **Surfaces:**

    * ``"api"`` (default): ``AM_SERVER_API_KEYS`` (comma-separated, trimmed) if non-empty;
      otherwise the single ``AM_SERVER_API_KEY``.
    * ``"mcp_public"``: ``AM_SERVER_PUBLIC_MCP_API_KEYS`` / ``AM_SERVER_PUBLIC_MCP_API_KEY``,
      with the same multi-then-single rule. If empty and :func:`strict_mcp_auth_enabled`
      is true, returns an empty set (callers should treat as misconfiguration).
    * ``"mcp_internal"``: ``AM_SERVER_INTERNAL_MCP_API_KEYS`` /
      ``AM_SERVER_INTERNAL_MCP_API_KEY``, same strict behavior as public when strict
      mode is on.
    * Any other ``surface`` value falls through to the general API key env vars (same
      as ``"api"``).

    Args:
        surface: Logical auth surface name (e.g. ``"api"``, ``"mcp_public"``).

    Returns:
        Set of valid raw key strings. May be empty if nothing is configured or strict
        MCP surfaces have no dedicated keys.
    """

    if surface == "mcp_public":
        keys = _parse_api_keys(
            os.environ.get("AM_SERVER_PUBLIC_MCP_API_KEYS", ""),
            os.environ.get("AM_SERVER_PUBLIC_MCP_API_KEY", "").strip(),
        )
        if keys:
            return keys
        if strict_mcp_auth_enabled():
            return set()
    elif surface == "mcp_internal":
        keys = _parse_api_keys(
            os.environ.get("AM_SERVER_INTERNAL_MCP_API_KEYS", ""),
            os.environ.get("AM_SERVER_INTERNAL_MCP_API_KEY", "").strip(),
        )
        if keys:
            return keys
        if strict_mcp_auth_enabled():
            return set()

    return _parse_api_keys(
        os.environ.get("AM_SERVER_API_KEYS", ""),
        os.environ.get("AM_SERVER_API_KEY", "").strip(),
    )


def _expected_api_keys() -> set[str]:
    """Return the configured valid API keys for the REST API surface."""

    return expected_api_keys_for_surface("api")


def resolve_bearer_token(request: Request) -> str | None:
    """Extract the bearer credential from ``Authorization`` without validating it.

    Expects ``Authorization: Bearer <token>``. The ``bearer`` prefix match is
    case-insensitive; leading/trailing whitespace around the token is stripped.
    Missing header, wrong scheme, or empty token after strip yields ``None``.

    Args:
        request: Incoming FastAPI request.

    Returns:
        The token string, or ``None`` if no usable Bearer token is present.
    """

    auth_header = request.headers.get("Authorization", "")
    prefix = "bearer "
    if auth_header.lower().startswith(prefix):
        token = auth_header[len(prefix):].strip()
        return token or None
    return None


def validate_surface_token(token: str | None, surface: str) -> tuple[int, str, str]:
    """Validate a bearer token against the configured keys for ``surface``.

    Uses membership in the set from :func:`expected_api_keys_for_surface`. When no keys
    are configured, returns 503 with ``auth_not_configured`` (dedicated message for
    strict MCP surfaces vs generic backend message).

    Args:
        token: Raw secret from the client, or ``None`` if missing.
        surface: Same surface names as :func:`expected_api_keys_for_surface`.

    Returns:
        A triple ``(http_status, code, message)``. ``http_status`` is 200 with
        ``("ok", "ok")`` on success; 401 for missing/invalid key; 503 when the backend
        has no keys for this surface. ``code`` is a stable machine identifier
        (``auth_missing_api_key``, ``auth_invalid_api_key``, ``auth_not_configured``).
    """

    expected_keys = expected_api_keys_for_surface(surface)
    if not expected_keys:
        if surface in {"mcp_public", "mcp_internal"} and strict_mcp_auth_enabled():
            return (
                503,
                "auth_not_configured",
                f"No dedicated API key is configured for MCP auth surface `{surface}`.",
            )
        return 503, "auth_not_configured", "No backend API key is configured."
    if token is None:
        return 401, "auth_missing_api_key", "Missing API key."
    # Plain set membership; not constant-time (acceptable for configured API keys).
    if token not in expected_keys:
        return 401, "auth_invalid_api_key", "Invalid API key."
    return 200, "ok", "ok"


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str:
    """FastAPI dependency: validate Bearer credentials against the general API key set.

    Uses only the REST/API surface keys (``AM_SERVER_API_KEYS`` / ``AM_SERVER_API_KEY``),
    not MCP-specific env vars. For route-level MCP auth, use
    :func:`validate_surface_token` with the profile's ``auth_surface``.

    Args:
        credentials: Injected by FastAPI from ``Authorization: Bearer ...``; ``None``
            when the header is missing or not Bearer-shaped (because ``HTTPBearer`` is
            configured with ``auto_error=False``).

    Returns:
        The validated raw token string.

    Raises:
        HTTPException: 503 with ``detail.code`` ``auth_not_configured`` if no API keys
            are set. 401 with ``auth_missing_api_key`` or ``auth_invalid_api_key``;
            401 responses include ``WWW-Authenticate: Bearer``.
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
