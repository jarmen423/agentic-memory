"""Registry and Codex adapter selection."""

from __future__ import annotations

from pathlib import Path

from am_codex_watch.adapters.codex_rollout import CodexRolloutAdapter
from am_codex_watch.adapters.registry import adapter_for_path, resolve_enabled


def test_resolve_enabled_skips_unknown() -> None:
    adapters = resolve_enabled(["codex_rollout", "no_such_adapter"])
    assert len(adapters) == 1
    assert adapters[0].adapter_id == "codex_rollout"


def test_adapter_matches_rollout_jsonl_only() -> None:
    ad = CodexRolloutAdapter()
    assert ad.matches_file(Path("/x/rollout-2025-01-01-uuid.jsonl")) is True
    assert ad.matches_file(Path("/x/other.jsonl")) is False
    assert ad.matches_file(Path("/x/rollout-foo.txt")) is False


def test_adapter_for_path_first_match() -> None:
    adapters = resolve_enabled(["codex_rollout"])
    p = Path("/home/u/.codex/sessions/rollout-2025-01-01-00000000-0000-0000-0000-000000000001.jsonl")
    chosen = adapter_for_path(p, adapters)
    assert chosen is not None
    assert chosen.adapter_id == "codex_rollout"


def test_codex_adapter_uses_stable_artifact_key_across_archive_move() -> None:
    ad = CodexRolloutAdapter()
    session_hint = "00000000-0000-0000-0000-000000000001"
    sessions_key = ad.artifact_state_key(
        f"/home/u/.codex/sessions/rollout-2025-01-01-{session_hint}.jsonl",
        session_hint,
    )
    archived_key = ad.artifact_state_key(
        f"/home/u/.codex/archived_sessions/rollout-2025-01-01-{session_hint}.jsonl",
        session_hint,
    )
    assert sessions_key == archived_key == f"codex_rollout:{session_hint}"
