"""Postgres connection pool for read-only dashboard queries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from healthcare_dashboard.config import database_url

_pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    """Create the global pool. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = ConnectionPool(
        conninfo=database_url(),
        min_size=1,
        max_size=10,
        open=True,
        kwargs={"connect_timeout": 10},
    )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


@contextmanager
def cursor() -> Iterator[psycopg.Cursor[Any]]:
    """Yield a dict-row cursor from the pool."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur
