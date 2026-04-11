"""Tests for tail ingestion with mocked HTTP."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from am_codex_watch.adapters.codex_rollout import CodexRolloutAdapter
from am_codex_watch.config import WatchConfig
from am_codex_watch.state import WatchState
from am_codex_watch.tail import process_artifact_file, process_rollout_file


def test_process_rollout_file_posts_user_message(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-2025-05-07T17-24-21-5973b6c0-94b8-487b-a530-2aeb6098ae0e.jsonl"
    lines = [
        '{"timestamp":"t0","type":"session_meta","payload":{"id":"5973b6c0-94b8-487b-a530-2aeb6098ae0e",'
        '"cwd":"/","timestamp":"","originator":"cli","cli_version":"1"}}',
        '{"timestamp":"t1","type":"response_item","payload":{"type":"message","role":"user",'
        '"content":[{"type":"input_text","text":"Hi"}]}}',
    ]
    rollout.write_text("\n".join(lines) + "\n", encoding="utf-8")

    state_path = tmp_path / "state.json"
    cfg = WatchConfig(
        endpoint="http://127.0.0.1:9",
        api_key="",
        state_path=state_path,
        roots=[],
    )
    state = WatchState(state_path)

    posted: list[dict] = []

    def capture(_cfg, body: dict) -> bool:
        posted.append(body)
        return True

    with patch("am_codex_watch.tail.post_turn", side_effect=capture):
        process_rollout_file(rollout, config=cfg, state=state)

    assert len(posted) == 1
    assert posted[0]["role"] == "user"
    assert posted[0]["content"] == "Hi"
    assert posted[0]["session_id"] == "5973b6c0-94b8-487b-a530-2aeb6098ae0e"
    assert posted[0]["source_key"] == "chat_codex_rollout"
    assert posted[0]["ingestion_mode"] == "passive"
    assert posted[0]["turn_index"] == 0

    posted.clear()
    with patch("am_codex_watch.tail.post_turn", side_effect=capture):
        process_rollout_file(rollout, config=cfg, state=state)
    assert posted == []


def test_process_artifact_file_failed_post_keeps_unread_bytes(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-2025-05-07T17-24-21-5973b6c0-94b8-487b-a530-2aeb6098ae0e.jsonl"
    lines = [
        '{"timestamp":"t0","type":"session_meta","payload":{"id":"5973b6c0-94b8-487b-a530-2aeb6098ae0e"}}',
        '{"timestamp":"t1","type":"response_item","payload":{"type":"message","role":"user",'
        '"content":[{"type":"input_text","text":"Hi"}]}}',
    ]
    rollout.write_text("\n".join(lines) + "\n", encoding="utf-8")

    state_path = tmp_path / "state.json"
    cfg = WatchConfig(state_path=state_path)
    state = WatchState(state_path)
    adapter = CodexRolloutAdapter()

    calls: list[dict] = []

    def fail_once(_cfg, body: dict) -> bool:
        calls.append(body)
        return False

    with patch("am_codex_watch.tail.post_turn", side_effect=fail_once):
        process_artifact_file(rollout, adapter, config=cfg, state=state)

    stable_key = adapter.artifact_state_key(
        str(rollout.resolve()),
        adapter.session_hint_from_path(str(rollout.resolve())),
    )
    first_line_end = rollout.read_bytes().find(b"\n") + 1
    assert len(calls) == 1
    assert state.get_offset(stable_key) == first_line_end
    assert state.peek_turn_index("chat_codex_rollout", "5973b6c0-94b8-487b-a530-2aeb6098ae0e") == 0


def test_process_artifact_file_retry_reuses_same_turn_index(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-2025-05-07T17-24-21-5973b6c0-94b8-487b-a530-2aeb6098ae0e.jsonl"
    lines = [
        '{"timestamp":"t0","type":"session_meta","payload":{"id":"5973b6c0-94b8-487b-a530-2aeb6098ae0e"}}',
        '{"timestamp":"t1","type":"response_item","payload":{"type":"message","role":"user",'
        '"content":[{"type":"input_text","text":"Hi"}]}}',
    ]
    rollout.write_text("\n".join(lines) + "\n", encoding="utf-8")

    state_path = tmp_path / "state.json"
    cfg = WatchConfig(state_path=state_path)
    state = WatchState(state_path)
    adapter = CodexRolloutAdapter()
    posted: list[dict] = []
    outcomes = iter([False, True])

    def flaky(_cfg, body: dict) -> bool:
        posted.append(body)
        return next(outcomes)

    with patch("am_codex_watch.tail.post_turn", side_effect=flaky):
        process_artifact_file(rollout, adapter, config=cfg, state=state)
        process_artifact_file(rollout, adapter, config=cfg, state=state)

    assert [turn["turn_index"] for turn in posted] == [0, 0]
    assert state.peek_turn_index("chat_codex_rollout", "5973b6c0-94b8-487b-a530-2aeb6098ae0e") == 1


def test_process_artifact_file_archive_move_does_not_replay(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    archived = tmp_path / ".codex" / "archived_sessions"
    sessions.mkdir(parents=True)
    archived.mkdir(parents=True)

    name = "rollout-2025-05-07T17-24-21-5973b6c0-94b8-487b-a530-2aeb6098ae0e.jsonl"
    active_path = sessions / name
    archived_path = archived / name
    lines = [
        '{"timestamp":"t0","type":"session_meta","payload":{"id":"5973b6c0-94b8-487b-a530-2aeb6098ae0e"}}',
        '{"timestamp":"t1","type":"response_item","payload":{"type":"message","role":"user",'
        '"content":[{"type":"input_text","text":"Hi"}]}}',
    ]
    active_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    state_path = tmp_path / "state.json"
    cfg = WatchConfig(state_path=state_path)
    state = WatchState(state_path)
    adapter = CodexRolloutAdapter()
    posted: list[dict] = []

    def capture(_cfg, body: dict) -> bool:
        posted.append(body)
        return True

    with patch("am_codex_watch.tail.post_turn", side_effect=capture):
        process_artifact_file(active_path, adapter, config=cfg, state=state)
        archived_path.write_bytes(active_path.read_bytes())
        process_artifact_file(archived_path, adapter, config=cfg, state=state)

    assert len(posted) == 1
    assert posted[0]["content"] == "Hi"
