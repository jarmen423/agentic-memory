"""Local SQLite telemetry for MCP tool calls and manual prompted/unprompted labels.

The MCP server records each tool invocation (timing, outcome, client id); the
CLI can later attach human labels to bursts of calls for research or quality
analysis. All state lives in a single SQLite file on disk.

Database layout:
    * ``tool_calls``: One row per invocation; annotation columns start null and
      are filled when a burst is matched.
    * ``manual_annotations``: Pending intents created by the CLI, then marked
      ``applied`` when rows are updated (or deleted if no match).

Annotation workflow (CLI + store):
    #. Operator runs ``agentic-memory --prompted`` / ``--unprompted`` after a turn.
    #. :meth:`TelemetryStore.create_pending_annotation` persists the intent.
    #. :meth:`TelemetryStore.get_latest_unannotated_burst` finds recent unlabeled calls.
    #. :meth:`TelemetryStore.apply_annotation_to_calls` writes labels and closes the loop.

Lifecycle notes:
    * :class:`TelemetryStore` creation ensures the parent directory exists, opens
      (or creates) the DB file, and runs idempotent ``CREATE TABLE`` DDL under a
      lock.
    * Connections use WAL and a busy timeout so concurrent readers (MCP) and
      the CLI do not deadlock on Windows or slow disks.

Environment:
    * ``CODEMEMORY_TELEMETRY_DB``: optional absolute path override for the DB file.
    * ``CODEMEMORY_TELEMETRY_ENABLED``: documented for callers (e.g. server) to
      short-circuit recording when set to ``"0"``.

See Also:
    ``agentic_memory.server.app`` (instrumentation) and
    ``agentic_memory.cli.cmd_annotate_interaction`` (annotation UX).
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
    """UTC timestamp string for human-readable columns (``ts_utc``)."""
    return datetime.now(timezone.utc).isoformat()


def _epoch_ms_now() -> int:
    """Unix epoch milliseconds for ordering and burst detection."""
    return int(time.time() * 1000)


def resolve_telemetry_db_path(repo_root: Optional[Path] = None) -> Path:
    """Choose the SQLite file path used by :class:`TelemetryStore`.

    Resolution order:
        #. ``CODEMEMORY_TELEMETRY_DB`` if set (expanded and resolved).
        #. Else ``<repo_root>/.agentic-memory/telemetry.sqlite3`` when
           ``repo_root`` is provided.
        #. Else ``<cwd>/.agentic-memory/telemetry.sqlite3``.

    Args:
        repo_root: Optional repository root; when omitted, the current working
            directory is used as the base for the default relative path.

    Returns:
        Absolute :class:`~pathlib.Path` to the database file (file may not exist
        yet until the store is constructed).
    """
    env_path = os.getenv("CODEMEMORY_TELEMETRY_DB")
    if env_path:
        return Path(env_path).expanduser().resolve()

    # Default: co-locate with other Agentic Memory control-plane files under .agentic-memory/
    base = repo_root.resolve() if repo_root else Path.cwd().resolve()
    return base / ".agentic-memory" / "telemetry.sqlite3"


class TelemetryStore:
    """Thread-safe SQLite persistence for tool calls and annotation state.

    Construction lifecycle:
        #. Normalize ``db_path`` and create parent directories if missing.
        #. Allocate a process-wide ``threading.Lock`` so writes serialize.
        #. Run :meth:`_init_schema` once to ensure tables and indexes exist.

    Runtime lifecycle:
        Each mutating method acquires the lock, opens a short-lived connection via
        :meth:`_connect`, runs SQL, and returns. Readers and writers rely on WAL +
        ``busy_timeout`` for stability under concurrent MCP traffic.
    """

    def __init__(self, db_path: Path):
        """Open (or create) the store at ``db_path`` and ensure schema exists."""
        self.db_path = Path(db_path)
        # Ensure .agentic-memory/ (or custom parent) exists before sqlite connects.
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Idempotent DDL: safe on every process start.
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
        """Create a connection with Row factory and durability-friendly pragmas."""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        # WAL: better concurrent read/write than default rollback journal.
        conn.execute("PRAGMA journal_mode=WAL;")
        # Wait up to 5s when the DB is locked instead of failing immediately.
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_schema(self) -> None:
        """Create tables and indexes if absent (no-op when already provisioned)."""
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
