"""OAuth 2.0 authorization server routes for the public hosted MCP surface.

This module adds the smallest honest OAuth implementation that lets external MCP
clients authenticate to the hosted public surface without relying on a static
shared reviewer key.

What this file owns:

- OAuth Authorization Server Metadata
- OAuth Protected Resource Metadata
- Authorization code + PKCE (S256 only)
- Refresh-token rotation
- A simple operator-bootstrapped username/password login form

What this file intentionally does *not* own yet:

- Third-party identity providers
- User self-signup / password reset
- Rich consent screens or multi-tenant account management
- JWT signing / JWKS (tokens remain opaque and are stored in product state)

The current design keeps the surface standards-shaped for MCP clients while
reusing the repo's existing SQLite-backed product state store for durable token,
code, and user records.
"""

from __future__ import annotations

import base64
import hashlib
import html
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from am_server.auth import (
    oauth_authorization_endpoint,
    oauth_client_metadata_supported,
    oauth_issuer_url,
    oauth_resource_url,
    oauth_supported_scopes,
    oauth_token_endpoint,
    public_oauth_enabled,
    validate_https_client_metadata_url,
)
from am_server.dependencies import get_product_store

router = APIRouter(tags=["oauth"])

BOOTSTRAP_USERS_ENV_VAR = "AM_SERVER_OAUTH_BOOTSTRAP_USERS"
DEFAULT_SCOPE = "mcp:tools"


@dataclass(frozen=True)
class OAuthAuthorizationRequest:
    """Normalized authorization request after client and PKCE validation."""

    client_id: str
    redirect_uri: str
    resource: str
    scopes: tuple[str, ...]
    state: str | None
    code_challenge: str
    code_challenge_method: str


def _oauth_enabled_or_404() -> None:
    """Fail closed when the deployment has not enabled public OAuth."""

    if public_oauth_enabled():
        return
    raise HTTPException(
        status_code=404,
        detail={
            "code": "oauth_not_enabled",
            "message": "Public OAuth is not enabled on this deployment.",
        },
    )


def _supported_scopes() -> tuple[str, ...]:
    """Return the configured scope list with a stable fallback."""

    scopes = oauth_supported_scopes()
    return scopes or (DEFAULT_SCOPE,)


def _parse_scope(scope_value: str | None) -> tuple[str, ...]:
    """Normalize a query/body scope string into a deduplicated ordered tuple."""

    requested = tuple(
        item.strip()
        for item in str(scope_value or "").replace(",", " ").split()
        if item.strip()
    )
    if requested:
        return tuple(dict.fromkeys(requested))
    return _supported_scopes()


def _parse_bootstrap_users() -> list[dict[str, str]]:
    """Parse operator-defined bootstrap users from one environment variable.

    Format:
        ``username:password:workspace_id[:display_name],...``

    Example:
        ``reviewer:s3cret:ws_demo:Marketplace Reviewer``
    """

    raw = os.environ.get(BOOTSTRAP_USERS_ENV_VAR, "").strip()
    if not raw:
        return []

    users: list[dict[str, str]] = []
    for entry in [item.strip() for item in raw.split(",") if item.strip()]:
        parts = [item.strip() for item in entry.split(":")]
        if len(parts) < 3:
            continue
        username, password, workspace_id = parts[:3]
        display_name = ":".join(parts[3:]).strip() if len(parts) > 3 else username
        if not username or not password or not workspace_id:
            continue
        users.append(
            {
                "username": username,
                "password": password,
                "workspace_id": workspace_id,
                "display_name": display_name or username,
            }
        )
    return users


def _ensure_bootstrap_users() -> None:
    """Seed product-state OAuth users from env so operator setup stays simple."""

    store = get_product_store()
    for record in _parse_bootstrap_users():
        store.upsert_oauth_user(
            username=record["username"],
            password=record["password"],
            workspace_id=record["workspace_id"],
            display_name=record["display_name"],
        )


def _fetch_client_metadata_document(client_id: str) -> dict[str, Any]:
    """Fetch and minimally validate a Client ID Metadata Document."""

    normalized = validate_https_client_metadata_url(client_id)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_invalid_client_id",
                "message": "client_id must be an HTTPS metadata document URL.",
            },
        )

    try:
        response = httpx.get(
            normalized,
            timeout=10.0,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_client_metadata_fetch_failed",
                "message": "Unable to fetch the client metadata document.",
                "details": {
                    "client_id": normalized,
                    "exception_type": exc.__class__.__name__,
                },
            },
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_invalid_client_metadata",
                "message": "The client metadata document must be a JSON object.",
            },
        )
    return payload


def _lookup_registered_client(client_id: str) -> dict[str, Any] | None:
    """Return one previously registered dynamic OAuth client if present."""

    return get_product_store().lookup_oauth_client(client_id)


def _validate_client_metadata(
    *,
    client_id: str,
    redirect_uri: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate redirect URI membership and minimal grant/response compatibility."""

    payload = metadata or _lookup_registered_client(client_id) or _fetch_client_metadata_document(client_id)
    redirect_uris = payload.get("redirect_uris", [])
    if not isinstance(redirect_uris, list) or redirect_uri not in redirect_uris:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_invalid_redirect_uri",
                "message": "redirect_uri is not registered for this client.",
            },
        )

    grant_types = payload.get("grant_types", [])
    if isinstance(grant_types, list) and grant_types and "authorization_code" not in grant_types:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_unsupported_grant_type",
                "message": "Client metadata does not allow authorization_code.",
            },
        )

    response_types = payload.get("response_types", [])
    if isinstance(response_types, list) and response_types and "code" not in response_types:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_unsupported_response_type",
                "message": "Client metadata does not allow code responses.",
            },
        )
    return payload


def _validate_authorization_request(
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    scope: str | None,
    state: str | None,
    resource: str | None,
    code_challenge: str,
    code_challenge_method: str,
) -> OAuthAuthorizationRequest:
    """Validate one incoming authorization request."""

    if response_type.strip() != "code":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_unsupported_response_type",
                "message": "Only response_type=code is supported.",
            },
        )
    if code_challenge_method.strip().upper() != "S256":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_invalid_code_challenge_method",
                "message": "Only PKCE code_challenge_method=S256 is supported.",
            },
        )
    if not code_challenge.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_missing_code_challenge",
                "message": "code_challenge is required.",
            },
        )

    normalized_resource = (resource or oauth_resource_url() or "").strip()
    if not normalized_resource:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "oauth_resource_not_configured",
                "message": "OAuth resource URL is not configured on this server.",
            },
        )

    requested_scopes = _parse_scope(scope)
    unsupported = [item for item in requested_scopes if item not in _supported_scopes()]
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_invalid_scope",
                "message": "One or more requested scopes are not supported.",
                "details": {"unsupported_scopes": unsupported},
            },
        )

    _validate_client_metadata(client_id=client_id, redirect_uri=redirect_uri)
    return OAuthAuthorizationRequest(
        client_id=client_id.strip(),
        redirect_uri=redirect_uri.strip(),
        resource=normalized_resource,
        scopes=requested_scopes,
        state=state.strip() if state else None,
        code_challenge=code_challenge.strip(),
        code_challenge_method="S256",
    )


def _pkce_s256(verifier: str) -> str:
    """Return the PKCE S256 code challenge for one verifier string."""

    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _parse_form_body(body: bytes) -> dict[str, str]:
    """Parse a URL-encoded form body without adding multipart dependencies."""

    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items() if values}


def _authorization_form_html(request_data: OAuthAuthorizationRequest, message: str | None = None) -> str:
    """Render the minimal username/password login screen for OAuth review flows."""

    escaped_message = (
        f"<p style='color:#b42318;font-weight:600'>{html.escape(message)}</p>" if message else ""
    )
    hidden_inputs = "\n".join(
        [
            f"<input type='hidden' name='client_id' value='{html.escape(request_data.client_id)}' />",
            f"<input type='hidden' name='redirect_uri' value='{html.escape(request_data.redirect_uri)}' />",
            f"<input type='hidden' name='resource' value='{html.escape(request_data.resource)}' />",
            f"<input type='hidden' name='scope' value='{html.escape(' '.join(request_data.scopes))}' />",
            f"<input type='hidden' name='code_challenge' value='{html.escape(request_data.code_challenge)}' />",
            f"<input type='hidden' name='code_challenge_method' value='{html.escape(request_data.code_challenge_method)}' />",
            f"<input type='hidden' name='response_type' value='code' />",
            f"<input type='hidden' name='state' value='{html.escape(request_data.state or '')}' />",
        ]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Agentic Memory OAuth</title>
    <style>
      body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; background: #f7f7f5; color: #1f2937; }}
      main {{ max-width: 34rem; margin: 0 auto; background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 2rem; }}
      label {{ display: block; font-weight: 600; margin-top: 1rem; }}
      input {{ width: 100%; padding: 0.75rem; margin-top: 0.35rem; border: 1px solid #d1d5db; border-radius: 8px; }}
      button {{ margin-top: 1.25rem; width: 100%; padding: 0.85rem; border: 0; border-radius: 8px; background: #111827; color: white; font-weight: 700; }}
      code {{ background: #f3f4f6; padding: 0.15rem 0.35rem; border-radius: 6px; }}
    </style>
  </head>
  <body>
    <main>
      <h1>Agentic Memory Access</h1>
      <p>This sign-in issues an OAuth authorization code for the public MCP surface.</p>
      <p><strong>Client:</strong> <code>{html.escape(request_data.client_id)}</code></p>
      <p><strong>Scopes:</strong> <code>{html.escape(' '.join(request_data.scopes))}</code></p>
      {escaped_message}
      <form method="post" action="/oauth/authorize">
        {hidden_inputs}
        <label for="username">Username</label>
        <input id="username" name="username" autocomplete="username" required />
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required />
        <button type="submit">Continue</button>
      </form>
    </main>
  </body>
</html>"""


@router.post("/oauth/register")
async def oauth_register(request: Request) -> JSONResponse:
    """Register one dynamic OAuth client for MCP developer-mode flows."""

    _oauth_enabled_or_404()
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_invalid_client_metadata",
                "message": "Client registration requires a JSON object body.",
            },
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_invalid_client_metadata",
                "message": "Client registration requires a JSON object body.",
            },
        )

    redirect_uris = payload.get("redirect_uris", [])
    if not isinstance(redirect_uris, list) or not any(str(item).strip() for item in redirect_uris):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_invalid_redirect_uri",
                "message": "At least one redirect URI is required for client registration.",
            },
        )

    token_endpoint_auth_method = str(payload.get("token_endpoint_auth_method") or "none").strip()
    if token_endpoint_auth_method not in {"none"}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_unsupported_token_endpoint_auth_method",
                "message": "Only token_endpoint_auth_method=none is supported.",
            },
        )

    grant_types = payload.get("grant_types")
    if grant_types is not None and (
        not isinstance(grant_types, list)
        or "authorization_code" not in [str(item).strip() for item in grant_types]
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_unsupported_grant_type",
                "message": "Dynamic client registration requires authorization_code grant support.",
            },
        )

    response_types = payload.get("response_types")
    if response_types is not None and (
        not isinstance(response_types, list)
        or "code" not in [str(item).strip() for item in response_types]
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_unsupported_response_type",
                "message": "Dynamic client registration requires code response support.",
            },
        )

    client_record = get_product_store().register_oauth_client(
        client_name=str(payload.get("client_name") or "").strip() or None,
        redirect_uris=[str(item) for item in redirect_uris],
        grant_types=[str(item).strip() for item in grant_types] if isinstance(grant_types, list) else None,
        response_types=[str(item).strip() for item in response_types] if isinstance(response_types, list) else None,
        token_endpoint_auth_method=token_endpoint_auth_method,
        scope=str(payload.get("scope") or "").strip() or None,
        metadata=payload,
    )
    return JSONResponse(
        status_code=201,
        content={
            "client_id": client_record["client_id"],
            "client_name": client_record["client_name"],
            "redirect_uris": client_record["redirect_uris"],
            "grant_types": client_record["grant_types"],
            "response_types": client_record["response_types"],
            "token_endpoint_auth_method": client_record["token_endpoint_auth_method"],
            "scope": client_record["scope"],
            "client_id_issued_at": int(time.time()),
        },
    )


@router.get("/.well-known/oauth-protected-resource")
def oauth_protected_resource_metadata() -> JSONResponse:
    """Advertise the MCP surface as an OAuth-protected resource."""

    _oauth_enabled_or_404()
    resource = oauth_resource_url()
    issuer = oauth_issuer_url()
    if not resource or not issuer:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "oauth_not_configured",
                "message": "OAuth issuer/resource URLs are not configured.",
            },
        )

    return JSONResponse(
        {
            "resource": resource,
            "authorization_servers": [issuer],
            "scopes_supported": list(_supported_scopes()),
            "bearer_methods_supported": ["header"],
        }
    )


@router.get("/.well-known/oauth-authorization-server")
def oauth_authorization_server_metadata() -> JSONResponse:
    """Return OAuth Authorization Server Metadata for MCP clients."""

    _oauth_enabled_or_404()
    issuer = oauth_issuer_url()
    authorization_endpoint = oauth_authorization_endpoint()
    token_endpoint = oauth_token_endpoint()
    if not issuer or not authorization_endpoint or not token_endpoint:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "oauth_not_configured",
                "message": "OAuth issuer/resource URLs are not configured.",
            },
        )

    return JSONResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
            "registration_endpoint": f"{issuer}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": list(_supported_scopes()),
            "client_id_metadata_document_supported": oauth_client_metadata_supported(),
        }
    )


@router.get("/oauth/authorize", response_class=HTMLResponse)
def oauth_authorize_get(
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str | None = None,
    state: str | None = None,
    resource: str | None = None,
) -> HTMLResponse:
    """Render the login step for one authorization-code request."""

    _oauth_enabled_or_404()
    request_data = _validate_authorization_request(
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type=response_type,
        scope=scope,
        state=state,
        resource=resource,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )
    _ensure_bootstrap_users()
    return HTMLResponse(_authorization_form_html(request_data))


@router.post("/oauth/authorize")
async def oauth_authorize_post(request: Request):
    """Authenticate a bootstrap user and redirect back with an auth code."""

    _oauth_enabled_or_404()
    _ensure_bootstrap_users()
    form = _parse_form_body(await request.body())
    request_data = _validate_authorization_request(
        client_id=form.get("client_id", ""),
        redirect_uri=form.get("redirect_uri", ""),
        response_type=form.get("response_type", ""),
        scope=form.get("scope"),
        state=form.get("state"),
        resource=form.get("resource"),
        code_challenge=form.get("code_challenge", ""),
        code_challenge_method=form.get("code_challenge_method", ""),
    )

    username = form.get("username", "").strip()
    password = form.get("password", "")
    user_record = get_product_store().authenticate_oauth_user(username=username, password=password)
    if not user_record:
        return HTMLResponse(
            _authorization_form_html(request_data, message="Invalid username or password."),
            status_code=401,
        )

    code_record = get_product_store().issue_oauth_authorization_code(
        user_id=str(user_record.get("user_id") or ""),
        username=str(user_record.get("username") or username),
        workspace_id=str(user_record.get("workspace_id") or ""),
        client_id=request_data.client_id,
        redirect_uri=request_data.redirect_uri,
        resource=request_data.resource,
        scopes=list(request_data.scopes),
        code_challenge=request_data.code_challenge,
        code_challenge_method=request_data.code_challenge_method,
    )
    params = {"code": code_record["code"]}
    if request_data.state:
        params["state"] = request_data.state
    redirect_target = f"{request_data.redirect_uri}?{urlencode(params)}"
    return RedirectResponse(redirect_target, status_code=302)


@router.post("/oauth/token")
async def oauth_token(request: Request) -> JSONResponse:
    """Exchange an auth code for tokens or rotate one refresh token."""

    _oauth_enabled_or_404()
    form = _parse_form_body(await request.body())
    grant_type = form.get("grant_type", "").strip()
    client_id = form.get("client_id", "").strip()
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "oauth_missing_client_id",
                "message": "client_id is required.",
            },
        )

    resource = (form.get("resource") or oauth_resource_url() or "").strip()
    if not resource:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "oauth_resource_not_configured",
                "message": "OAuth resource URL is not configured on this server.",
            },
        )

    if grant_type == "authorization_code":
        redirect_uri = form.get("redirect_uri", "").strip()
        code = form.get("code", "").strip()
        code_verifier = form.get("code_verifier", "").strip()
        if not redirect_uri or not code or not code_verifier:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "oauth_invalid_request",
                    "message": "code, redirect_uri, and code_verifier are required.",
                },
            )
        _validate_client_metadata(client_id=client_id, redirect_uri=redirect_uri)
        code_record = get_product_store().consume_oauth_authorization_code(
            raw_code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            resource=resource,
        )
        if not code_record:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "oauth_invalid_grant",
                    "message": "The authorization code is invalid, expired, or already used.",
                },
            )
        if _pkce_s256(code_verifier) != str(code_record.get("code_challenge") or ""):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "oauth_invalid_grant",
                    "message": "The PKCE code_verifier does not match the authorization code.",
                },
            )
        token_pair = get_product_store().issue_oauth_token_pair(
            user_id=str(code_record.get("user_id") or ""),
            username=str(code_record.get("username") or ""),
            workspace_id=str(code_record.get("workspace_id") or ""),
            client_id=client_id,
            resource=resource,
            scopes=list(code_record.get("scopes", [])),
        )
        return JSONResponse(token_pair)

    if grant_type == "refresh_token":
        refresh_token = form.get("refresh_token", "").strip()
        if not refresh_token:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "oauth_invalid_request",
                    "message": "refresh_token is required.",
                },
            )
        normalized_client_id = validate_https_client_metadata_url(client_id)
        if not normalized_client_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "oauth_invalid_client_id",
                    "message": "client_id must be an HTTPS metadata document URL.",
                },
            )
        token_pair = get_product_store().rotate_oauth_refresh_token(
            raw_refresh_token=refresh_token,
            client_id=normalized_client_id,
            resource=resource,
        )
        if not token_pair:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "oauth_invalid_grant",
                    "message": "The refresh token is invalid, expired, or already rotated.",
                },
            )
        return JSONResponse(token_pair)

    raise HTTPException(
        status_code=400,
        detail={
            "code": "oauth_unsupported_grant_type",
            "message": "Only authorization_code and refresh_token grants are supported.",
        },
    )
