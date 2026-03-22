"""Extension selectors endpoint — unauthenticated."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_SELECTORS_PATH = Path(__file__).parent.parent / "data" / "selectors.json"


@router.get("/ext/selectors.json")
def get_selectors() -> dict:
    """Return DOM selector configuration for the am-ext browser extension.

    No authentication required — selectors are public configuration.
    Phase 6 will populate real platform-specific selectors.
    """
    try:
        return json.loads(_SELECTORS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="selectors.json not found") from exc
