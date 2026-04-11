"""Read new bytes from artifact files and emit ingests."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from am_codex_watch.adapters.base import SessionArtifactAdapter
from am_codex_watch.ingest import build_turn_payload, post_turn
from am_codex_watch.config import WatchConfig
from am_codex_watch.state import WatchState

logger = logging.getLogger(__name__)


def process_artifact_file(
    path: Path,
    adapter: SessionArtifactAdapter,
    *,
    config: WatchConfig,
    state: WatchState,
) -> None:
    """Append-read a single file from stored offset; POST new message lines."""
    key = str(path.resolve())
    if not path.is_file():
        return

    session_hint = adapter.session_hint_from_path(key)
    state_key = adapter.artifact_state_key(key, session_hint)
    if state_key == key:
        pos = state.get_offset(state_key)
    else:
        pos = state.adopt_offset(state_key, [key])
        if pos == 0 and not state.has_offset(state_key) and session_hint:
            pos = state.adopt_matching_offset(
                state_key,
                lambda legacy_key: session_hint in legacy_key,
            )

    try:
        data = path.read_bytes()
    except OSError as exc:
        if config.debug:
            logger.warning("read failed %s: %s", state_key, exc)
        return

    if pos > len(data):
        pos = 0
        state.set_offset(state_key, 0)

    file_session: str | None = session_hint
    committed_pos = pos

    while pos < len(data):
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        line_bytes = data[pos:nl]
        pos = nl + 1

        try:
            line = line_bytes.decode("utf-8")
        except UnicodeDecodeError:
            committed_pos = pos
            continue

        kind, value = adapter.parse_line(
            line,
            file_path=key,
            session_hint=session_hint,
            current_session_id=file_session,
        )
        if kind == "session_id" and value:
            file_session = value
            committed_pos = pos
        elif kind == "message" and value:
            sid = file_session or session_hint
            if not sid:
                if config.debug:
                    logger.warning("skip message (no session id): %s", state_key)
                committed_pos = pos
                continue
            try:
                env = json.loads(value)
            except json.JSONDecodeError:
                committed_pos = pos
                continue
            role = str(env.get("role", ""))
            content = str(env.get("content", ""))
            ts = env.get("timestamp")
            timestamp = ts if isinstance(ts, str) else None
            turn_index = state.peek_turn_index(adapter.source_key, sid)
            body = build_turn_payload(
                config=config,
                source_key=adapter.source_key,
                source_agent=adapter.source_agent,
                session_id=sid,
                turn_index=turn_index,
                role=role,
                content=content,
                timestamp=timestamp,
            )
            if not post_turn(config, body):
                break
            state.commit_turn_index(adapter.source_key, sid, turn_index)
            committed_pos = pos
        else:
            committed_pos = pos

    state.set_offset(state_key, committed_pos)
    state.save()


def process_rollout_file(
    path: Path,
    *,
    config: WatchConfig,
    state: WatchState,
) -> None:
    """Backward-compatible: process path with the Codex rollout adapter."""
    from am_codex_watch.adapters.codex_rollout import CodexRolloutAdapter

    process_artifact_file(path, CodexRolloutAdapter(), config=config, state=state)
