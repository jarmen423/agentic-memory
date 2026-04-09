"""
SQLite telemetry utilities for MCP tool-call tracking and manual annotation.
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
    2) <repo_root>/.codememory/telemetry.sqlite3
    3) <cwd>/.codememory/telemetry.sqlite3
    """
    env_path = os.getenv("CODEMEMORY_TELEMETRY_DB")
    if env_path:
        return Path(env_path).expanduser().resolve()

    base = repo_root.resolve() if repo_root else Path.cwd().resolve()
    return base / ".codememory" / "telemetry.sqlite3"


class TelemetryStore:
    """SQLite-backed store for MCP tool-call telemetry and manual annotations.

    Records every MCP tool invocation (name, duration, success/failure, client
    identity) in a local ``tool_calls`` table and supports an annotation
    workflow where a caller can "tag" a burst of recent calls with a prompt
    prefix and annotation mode after the fact.

    Designed to run inside the MCP server process (same machine as the repo).
    Uses WAL mode and a threading lock to be safe when multiple threads share
    one store instance, as FastMCP may call tools concurrently.

    The annotation workflow:
      1. Caller calls ``create_pending_annotation`` with a unique ID and
         descriptive metadata — this creates a ``pending`` row in
         ``manual_annotations``.
      2. Caller calls ``get_latest_unannotated_burst`` to find which tool_call
         IDs should receive the annotation.
      3. Caller calls ``apply_annotation_to_calls`` to stamp those rows and
         flip the annotation status to ``applied``.
      4. If no calls matched, the pending annotation is deleted automatically.

    The DB path is resolved by ``resolve_telemetry_db_path`` and defaults to
    ``<repo_root>/.codememory/telemetry.sqlite3``.

    Attributes:
        db_path: Resolved absolute path to the SQLite database file.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @staticmethod
    def new_annotation_id() -> str:
        """Generate a short, unique annotation ID.

        Returns:
            A 12-character lowercase hex string derived from a UUID4, suitable
            for use as an ``annotation_id`` in ``manual_annotations``.
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

        Called by the ``log_tool_call`` decorator in ``server/app.py`` after
        every MCP tool invocation, whether it succeeded or failed.

        Args:
            tool_name: Name of the MCP tool function that was called.
            duration_ms: Wall-clock elapsed time for the call in milliseconds.
            success: True if the tool returned without raising an exception.
            error_type: ``type(exc).__name__`` when success=False, else None.
            client_id: Identifier of the calling agent/client, read from the
                ``CODEMEMORY_CLIENT`` environment variable.
            repo_root: Absolute path of the repository root at call time, or
                None when running outside a repo context.

        Returns:
            The auto-incremented integer ``id`` of the newly inserted row.
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
        """Create a pending annotation record in ``manual_annotations``.

        Step 1 of the annotation workflow. The annotation starts in
        ``status='pending'`` and is later promoted to ``'applied'`` by
        ``apply_annotation_to_calls``, or deleted if no matching calls exist.

        Args:
            annotation_id: Unique identifier for this annotation (use
                ``new_annotation_id()`` to generate one).
            prompt_prefix: Human-readable label or prompt fragment describing
                the context of the annotated tool calls.
            annotation_mode: Categorisation tag for the annotation type
                (e.g., "manual", "auto", "review").
            client_id: Optional identifier of the client creating the
                annotation; stored for filtering and audit purposes.
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
        """Delete a pending annotation that was never applied.

        Only deletes rows where ``status = 'pending'`` — applied annotations
        are permanent and cannot be removed via this method. Used to clean up
        when a caller aborts the annotation workflow before calling
        ``apply_annotation_to_calls``.

        Args:
            annotation_id: The ID of the pending annotation to delete.
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
        """Stamp a set of tool-call rows with an annotation and mark it applied.

        Step 3 of the annotation workflow. Updates the ``annotation_id``,
        ``annotation_mode``, and ``prompt_prefix`` columns on the specified
        ``tool_calls`` rows, then flips the ``manual_annotations`` row to
        ``status='applied'`` with the matched count and timestamp.

        If ``call_ids`` is empty, returns 0 immediately without touching the
        database. If the UPDATE matches zero rows (e.g., all IDs were already
        annotated), the pending annotation row is deleted instead of being
        left in a ``pending`` state.

        Args:
            annotation_id: The annotation ID created by
                ``create_pending_annotation``.
            prompt_prefix: Label/context string to stamp on each matched row
                (must match what was passed to ``create_pending_annotation``).
            annotation_mode: Mode tag to stamp on each matched row.
            call_ids: List of ``tool_calls.id`` integers to annotate.

        Returns:
            Number of ``tool_calls`` rows actually updated. Returns 0 if no
            rows were updated or ``call_ids`` was empty.
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
