"""Turn counter namespacing per source_key."""

from __future__ import annotations

import json
from pathlib import Path

from am_codex_watch.state import WatchState


def test_turn_index_namespaced_by_source_key(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    st = WatchState(p)
    assert st.next_turn_index("chat_codex_rollout", "sess-a") == 0
    assert st.next_turn_index("chat_cli", "sess-a") == 0
    assert st.next_turn_index("chat_codex_rollout", "sess-a") == 1


def test_peek_does_not_consume_turn_index(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    st = WatchState(p)
    assert st.peek_turn_index("chat_codex_rollout", "sess-a") == 0
    assert st.peek_turn_index("chat_codex_rollout", "sess-a") == 0
    st.commit_turn_index("chat_codex_rollout", "sess-a", 0)
    assert st.peek_turn_index("chat_codex_rollout", "sess-a") == 1


def test_adopt_offset_reuses_legacy_alias(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps({"file_offsets": {"legacy-path": 42}, "session_turns": {}}),
        encoding="utf-8",
    )
    st = WatchState(p)
    assert st.adopt_offset("codex_rollout:sess-1", ["legacy-path"]) == 42
    assert st.get_offset("codex_rollout:sess-1") == 42


def test_adopt_matching_offset_reuses_legacy_key(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps(
            {
                "file_offsets": {
                    "/tmp/.codex/archived_sessions/rollout-2025-01-01-sess-1.jsonl": 99,
                },
                "session_turns": {},
            }
        ),
        encoding="utf-8",
    )
    st = WatchState(p)
    assert st.adopt_matching_offset("codex_rollout:sess-1", lambda key: "sess-1" in key) == 99
    assert st.get_offset("codex_rollout:sess-1") == 99
