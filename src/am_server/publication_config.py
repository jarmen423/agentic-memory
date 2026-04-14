"""Shared publication URL and path configuration for hosted public surfaces.

This module keeps the public publication/documentation URLs in one place so the
repo does not hardcode a single hostname across docs, plugin scaffolds, and the
FastAPI publication routes. Route paths remain stable, while the absolute public
base URL can be injected at deploy time.
"""

from __future__ import annotations

import os
from urllib.parse import urljoin

PUBLICATION_ROOT = "/publication"
PUBLICATION_WEBSITE_PATH = f"{PUBLICATION_ROOT}/agentic-memory"
PUBLICATION_PRIVACY_PATH = f"{PUBLICATION_ROOT}/privacy"
PUBLICATION_TERMS_PATH = f"{PUBLICATION_ROOT}/terms"
PUBLICATION_SUPPORT_PATH = f"{PUBLICATION_ROOT}/support"
PUBLICATION_DPA_PATH = f"{PUBLICATION_ROOT}/dpa"

MCP_OPENAI_PATH = "/mcp-openai"
MCP_CODEX_PATH = "/mcp-codex"
MCP_CLAUDE_PATH = "/mcp-claude"


def public_base_url() -> str | None:
    """Return the configured public HTTPS base URL for publication surfaces.

    ``AM_PUBLIC_BASE_URL`` is the deploy-time source of truth for externally
    visible URLs used in marketplace submissions and legal/support pages.
    """

    raw = os.environ.get("AM_PUBLIC_BASE_URL", "").strip()
    if not raw:
        return None
    return raw.rstrip("/")


def absolute_public_url(path: str) -> str:
    """Return an absolute external URL for one hosted public path.

    When no public base URL is configured yet, return the relative path so local
    development and tests continue to work without a fake hostname.
    """

    base = public_base_url()
    if not base:
        return path
    return urljoin(f"{base}/", path.lstrip("/"))

