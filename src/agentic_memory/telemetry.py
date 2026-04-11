"""
SQLite-backed telemetry store for MCP tool-call tracking and manual annotation.

Provides lightweight, local observability for the Agentic Memory MCP server:
every tool invocation is recorded with timing, success/failure, and client
identity so usage can be audited and annotated for prompted/unprompted labeling.

Extended:
    Two SQLite tables power the telemetry system:
    - ``tool_calls``: One row per MCP tool invocation with duration, success flag,
      error type, and an optional back-reference to a ``manual_annotations`` row.
    - ``manual_annotations``: Records user-driven annotations that classify a burst
      of tool calls as "prompted" (user asked for it) or "unprompted" (agent acted
      autonomously).  Annotations move from status ``pending`` → ``applied`` once
      they are matched to actual call rows.

    The annotation workflow is:
    1. User runs ``agentic-memory --prompted "my prompt"`` immediately after an
       agent response.
    2. ``create_pending_annotation`` records the intent.
    3. ``get_latest_unannotated_burst`` identifies the contiguous block of recent
       tool calls that belong to this interaction.
    4. ``apply_annotation_to_calls`` back-fills the annotation onto those rows and
       marks the annotation as ``applied``.

Role:
    Used by ``server/app.py`` (``log_tool_call`` decorator) to record every tool
    invocation at runtime, and by ``cli.py`` (``cmd_annotate_interaction``) to
    apply manual annotations.

Dependencies:
    - sqlite3 (stdlib — no external database required)
    - CODEMEMORY_TELEMETRY_DB environment variable (optional path override)
    - CODEMEMORY_TELEMETRY_ENABLED (set to "0" to disable)

Key Technologies:
    SQLite with WAL journal mode, threading.Lock for write serialization.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _epoch_ms_now() -> int:
    return int(time.time() * 1000)


def resolve_telemetry_db_path(repo_root: Optional[Path] = None) -> Path:
    """
    Resolve telemetry database path.

    Priority:
    1) CODEMEMORY_TELEMETRY_DB
    2) <repo_root>/.agentic-memory/telemetry.sqlite3
    3) <cwd>/.agentic-memory/telemetry.sqlite3
    """
    env_path = os.getenv("CODEMEMORY_TELEMETRY_DB")
    if env_path:
        return Path(env_path).expanduser().resolve()

    base = repo_root.resolve() if repo_root else Path.cwd().resolve()
    return base / ".agentic-memory" / "telemetry.sqlite3"


class TelemetryStore:
    """Simple SQLite-backed telemetry store."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @staticmethod
    def new_annotation_id() -> str:
        """Generate a short random annotation identifier.

        Returns:
            A 12-character lowercase hex string derived from a UUID4, suitable
            as a human-readable but collision-resistant annotation key.
        """
        return uuid.uuid4().hex[:12]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS tool_calls (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts_utc TEXT NOT NULL,
                        epoch_ms INTEGER NOT NULL,
                        tool_name TEXT NOT NULL,
                        duration_ms REAL NOT NULL,
                        success INTEGER NOT NULL,
                        error_type TEXT,
                        client_id TEXT NOT NULL,
                        repo_root TEXT,
                        annotation_id TEXT,
                        annotation_mode TEXT,
                        prompt_prefix TEXT
                    );

                    CREATE TABLE IF NOT EXISTS manual_annotations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        annotation_id TEXT NOT NULL UNIQUE,
                        prompt_prefix TEXT NOT NULL,
                        annotation_mode TEXT NOT NULL,
                        client_id TEXT,
                        created_ts_utc TEXT NOT NULL,
                        created_epoch_ms INTEGER NOT NULL,
                        applied_ts_utc TEXT,
                        applied_epoch_ms INTEGER,
                        matched_call_count INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_tool_calls_epoch
                    ON tool_calls(epoch_ms DESC);

                    CREATE INDEX IF NOT EXISTS idx_tool_calls_client_epoch
                    ON tool_calls(client_id, epoch_ms DESC);

                    CREATE INDEX IF NOT EXISTS idx_tool_calls_annotation
                    ON tool_calls(annotation_id);
                    """
                )

    def record_tool_call(
        self,
        *,
        tool_name: str,
        duration_ms: float,
        success: bool,
        error_type: Optional[str],
        client_id: str,
        repo_root: Optional[str],
    ) -> int:
        """Insert one tool-call record into the ``tool_calls`` table.

        Called by the ``log_tool_call`` decorator in ``server/app.py`` on both
        successful and failed tool invocations.  The inserted row starts with
        ``annotation_id = NULL``; it is back-filled later by
        ``apply_annotation_to_calls`` when a user runs the annotation workflow.

        Args:
            tool_name: The MCP tool function name (e.g. ``"search_code"``).
            duration_ms: Wall-clock duration of the call in milliseconds.
            success: True if the tool returned normally; False if it raised.
            error_type: Exception class name on failure, or None on success.
            client_id: Value of the ``CODEMEMORY_CLIENT`` env var at call time,
                used to associate calls with a specific agent/session.
            repo_root: Absolute path of the repository root at call time, or None.

        Returns:
            The SQLite rowid of the newly inserted row (useful for direct
            reference in ``apply_annotation_to_calls``).
        """
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO tool_calls (
                        ts_utc, epoch_ms, tool_name, duration_ms, success, error_type, client_id, repo_root
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _utc_now_iso(),
                        _epoch_ms_now(),
                        tool_name,
                        float(duration_ms),
                        1 if success else 0,
                        error_type,
                        client_id,
                        repo_root,
                    ),
                )
                return int(cur.lastrowid)

    def create_pending_annotation(
        self,
        *,
        annotation_id: str,
        prompt_prefix: str,
        annotation_mode: str,
        client_id: Optional[str],
    ) -> None:
        """Insert a pending annotation intent into ``manual_annotations``.

        Called at the start of the annotation workflow (``cmd_annotate_interaction``
        in cli.py) before the system waits for a tool-use burst to settle.  The
        row starts in ``status='pending'`` and transitions to ``status='applied'``
        via ``apply_annotation_to_calls``, or is deleted by
        ``delete_pending_annotation`` if no matching burst is found.

        This two-phase design (create-then-match) ensures the annotation intent is
        persisted even if the process is interrupted before the burst is matched.

        Args:
            annotation_id: Unique identifier for this annotation (from
                ``new_annotation_id()`` or a user-supplied value).
            prompt_prefix: The start of the user's prompt text used to identify
                the interaction window being annotated.
            annotation_mode: ``"prompted"`` or ``"unprompted"``.
            client_id: Optional client filter to scope the burst search.
        """
        now_iso = _utc_now_iso()
        now_epoch = _epoch_ms_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO manual_annotations (
                        annotation_id, prompt_prefix, annotation_mode, client_id,
                        created_ts_utc, created_epoch_ms, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        annotation_id,
                        prompt_prefix,
                        annotation_mode,
                        client_id,
                        now_iso,
                        now_epoch,
                    ),
                )

    def delete_pending_annotation(self, annotation_id: str) -> None:
        """Remove a pending annotation that could not be matched to any tool calls.

        Called as a cleanup step when the annotation workflow times out without
        finding a suitable burst, or when the burst changes between detection and
        the final update attempt.  Only deletes rows with ``status='pending'`` to
        avoid accidentally removing already-applied annotations.

        Args:
            annotation_id: The identifier of the pending annotation to remove.
        """
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    DELETE FROM manual_annotations
                    WHERE annotation_id = ? AND status = 'pending'
                    """,
                    (annotation_id,),
                )

    def _recent_unannotated_calls(
        self,
        *,
        lookback_seconds: int,
        client_id: Optional[str],
        limit: int = 500,
    ) -> List[sqlite3.Row]:
        lower_epoch = _epoch_ms_now() - max(1, int(lookback_seconds)) * 1000
        with self._lock:
            with self._connect() as conn:
                if client_id:
                    rows = conn.execute(
                        """
                        SELECT *
                        FROM tool_calls
                        WHERE annotation_id IS NULL
                          AND epoch_ms >= ?
                          AND client_id = ?
                        ORDER BY epoch_ms DESC
                        LIMIT ?
                        """,
                        (lower_epoch, client_id, int(limit)),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT *
                        FROM tool_calls
                        WHERE annotation_id IS NULL
                          AND epoch_ms >= ?
                        ORDER BY epoch_ms DESC
                        LIMIT ?
                        """,
                        (lower_epoch, int(limit)),
                    ).fetchall()
        return rows

    def get_latest_unannotated_burst(
        self,
        *,
        lookback_seconds: int,
        idle_seconds: int,
        client_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Return the newest unannotated burst of tool calls.

        Burst logic: starting from the most recent call, include older calls
        while each adjacent gap is <= idle_seconds.
        """
        rows_desc = self._recent_unannotated_calls(
            lookback_seconds=lookback_seconds,
            client_id=client_id,
        )
        if not rows_desc:
            return []

        idle_ms = max(1, int(idle_seconds)) * 1000
        burst_desc = [rows_desc[0]]
        previous_epoch = int(rows_desc[0]["epoch_ms"])

        for row in rows_desc[1:]:
            epoch = int(row["epoch_ms"])
            if previous_epoch - epoch <= idle_ms:
                burst_desc.append(row)
                previous_epoch = epoch
                continue
            break

        # Return in ascending order for readability and stable processing.
        burst = [dict(row) for row in reversed(burst_desc)]
        return burst

    def apply_annotation_to_calls(
        self,
        *,
        annotation_id: str,
        prompt_prefix: str,
        annotation_mode: str,
        call_ids: List[int],
    ) -> int:
        """Back-fill annotation fields onto matched tool-call rows (atomic).

        Updates the ``tool_calls`` rows identified by ``call_ids`` with the
        annotation identity and mode, then marks the corresponding
        ``manual_annotations`` row as ``status='applied'``.  Both updates run
        in a single SQLite transaction under the write lock.

        If none of the provided ``call_ids`` match existing rows (e.g., they were
        already annotated or deleted), the pending annotation is cleaned up rather
        than left in a dangling ``pending`` state.

        Args:
            annotation_id: The identifier created by ``create_pending_annotation``.
            prompt_prefix: User's prompt text to persist alongside each call row.
            annotation_mode: ``"prompted"`` or ``"unprompted"``.
            call_ids: List of ``tool_calls.id`` primary keys to annotate.

        Returns:
            Number of ``tool_calls`` rows actually updated.  Returns 0 if no
            rows matched (caller should handle the no-op case).
        """
        if not call_ids:
            return 0

        placeholders = ",".join("?" for _ in call_ids)
        params: List[Any] = [annotation_id, annotation_mode, prompt_prefix, *call_ids]

        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    f"""
                    UPDATE tool_calls
                    SET
                        annotation_id = ?,
                        annotation_mode = ?,
                        prompt_prefix = ?
                    WHERE id IN ({placeholders})
                    """,
                    params,
                )
                updated = int(cur.rowcount or 0)
                if updated > 0:
                    conn.execute(
                        """
                        UPDATE manual_annotations
                        SET
                            status = 'applied',
                            matched_call_count = ?,
                            applied_ts_utc = ?,
                            applied_epoch_ms = ?
                        WHERE annotation_id = ?
                        """,
                        (
                            updated,
                            _utc_now_iso(),
                            _epoch_ms_now(),
                            annotation_id,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        DELETE FROM manual_annotations
                        WHERE annotation_id = ? AND status = 'pending'
                        """,
                        (annotation_id,),
                    )
                return updated
