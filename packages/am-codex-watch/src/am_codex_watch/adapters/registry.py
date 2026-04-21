"""Built-in adapter registry."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from am_codex_watch.adapters.codex_rollout import CodexRolloutAdapter

if TYPE_CHECKING:
    from am_codex_watch.adapters.base import SessionArtifactAdapter

# All built-in adapters (id -> instance)
BUILTIN_ADAPTERS: dict[str, SessionArtifactAdapter] = {
    CodexRolloutAdapter.adapter_id: CodexRolloutAdapter(),
}


def get_adapter(adapter_id: str) -> SessionArtifactAdapter | None:
    """Return a built-in adapter by id, or None."""
    return BUILTIN_ADAPTERS.get(adapter_id)


def resolve_enabled(enabled_ids: list[str]) -> list[SessionArtifactAdapter]:
    """Return adapter instances in order; skip unknown ids."""
    out: list[SessionArtifactAdapter] = []
    for aid in enabled_ids:
        a = get_adapter(aid)
        if a is not None:
            out.append(a)
    return out


def adapter_for_path(path: Path, adapters: list[SessionArtifactAdapter]) -> SessionArtifactAdapter | None:
    """Pick the first adapter that matches this file (order matters)."""
    for ad in adapters:
        if ad.matches_file(path):
            return ad
    return None
