"""Public HTTP surface for the ``am-ext`` browser extension.

Serves static configuration (DOM selectors) that the extension loads at runtime.
This endpoint is intentionally **unauthenticated** so installed clients can fetch
selectors without a user session; treat the JSON file as non-secret UI plumbing
only.

Extension hook:
    ``GET /ext/selectors.json`` reads ``am_server/data/selectors.json`` from disk.
    Replacing or templating that file is the supported way to change selector
    bundles without code changes (see product notes for Phase 6 platform-specific
    selectors).

Attributes:
    router: Unauthenticated APIRouter for extension-facing routes.
    _SELECTORS_PATH: Resolved path to the selectors JSON adjacent to package data.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_SELECTORS_PATH = Path(__file__).parent.parent / "data" / "selectors.json"


@router.get("/ext/selectors.json")
def get_selectors() -> dict:
    """Return parsed DOM selector configuration for the am-ext browser extension.

    The response body is the JSON object stored at ``_SELECTORS_PATH``. Missing
    files surface as HTTP 404 so the extension can distinguish "server has no
    bundle" from malformed JSON (which would raise during ``json.loads``).

    Returns:
        A dict matching the on-disk selectors schema (structure owned by the
        extension and ops; not validated here beyond JSON parsing).

    Raises:
        HTTPException: 404 if ``selectors.json`` is not present at the expected path.

    Note:
        No auth dependency — this route is part of the extension bootstrap path.
    """
    try:
        return json.loads(_SELECTORS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="selectors.json not found") from exc
