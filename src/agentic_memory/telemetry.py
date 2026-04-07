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
    """Simple SQLite-backed telemetry store."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @staticmethod
    def new_annotation_id() -> str:
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
