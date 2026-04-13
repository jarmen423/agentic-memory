"""Neo4j driver lifecycle and schema bootstrap for Agentic Memory.

This module provides :class:`ConnectionManager`, the central place to construct a
configured Neo4j driver, borrow short-lived sessions, and run idempotent DDL
for vector indexes and uniqueness constraints used by the memory graph.

Pool sizing and timeouts are driven by optional ``AM_NEO4J_*`` environment
variables so operators can tune concurrency and fail-fast behavior without
code changes. Credential resolution for file-based configs is handled by
:meth:`ConnectionManager.from_config`, which layers ``NEO4J_*`` overrides on
top of a ``config["neo4j"]`` dict.

Environment Variables:
    AM_NEO4J_MAX_CONNECTION_POOL_SIZE: Maximum pooled Bolt connections (default
        ``50``).
    AM_NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS: Seconds to wait for a free
        connection from the pool before failing (default ``10``). Lower values
        avoid long hangs when the pool is saturated.
    AM_NEO4J_CONNECTION_TIMEOUT_SECONDS: TCP connection timeout in seconds
        (default ``30``).
    AM_NEO4J_MAX_TRANSACTION_RETRY_SECONDS: Upper bound for the driver's
        automatic retries on transient failures (default ``30.0``).
    NEO4J_URI: When set, replaces ``config["neo4j"]["uri"]`` in
        :meth:`ConnectionManager.from_config`.
    NEO4J_USER: When set, replaces ``config["neo4j"]["user"]`` (checked before
        ``NEO4J_USERNAME``).
    NEO4J_USERNAME: Alternate user override if ``NEO4J_USER`` is unset.
    NEO4J_PASSWORD: When set, replaces ``config["neo4j"]["password"]``.

Note:
    Vector index definitions in :meth:`ConnectionManager.setup_database` use
    3072 dimensions for ``Memory:Code``, ``Memory:Research``, and
    ``Memory:Conversation`` embeddings; they must stay consistent with the
    embedding model dimensionality used when writing those nodes.
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

import neo4j

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages a single synchronous Neo4j driver and memory-layer graph DDL.

    The manager wraps :func:`neo4j.GraphDatabase.driver` with explicit pool
    limits and timeouts (see module docstring for ``AM_NEO4J_*`` variables),
    exposes a context-managed :meth:`session` for callers, and applies
    create-if-not-exists indexes plus an entity uniqueness constraint via
    :meth:`setup_database`. :meth:`fix_vector_index_dimensions` exists for the
    narrow case where research/chat vector indexes already exist at the wrong
    dimension and must be dropped before recreation.

    Attributes:
        pool_settings: Driver kwargs derived from environment (pool size,
            acquisition timeout, connection timeout, transaction retry budget).
        driver: The live ``neo4j`` driver instance; closed by :meth:`close`.
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        """Open a Neo4j driver using pool settings from env or documented defaults.

        Args:
            uri: Bolt URI (for example ``bolt://host:7687`` or ``neo4j+s://...``).
            user: Database username.
            password: Database password.

        Note:
            OpenClaw Phase 14 tightened the default acquisition timeout so an
            exhausted pool surfaces errors quickly instead of blocking
            user-facing work for up to a minute; overrides remain available via
            ``AM_NEO4J_*``.
        """
        # OpenClaw Phase 14 lowers the acquisition timeout so an exhausted pool
        # fails fast instead of making user-facing requests hang for up to a
        # minute. The values remain overridable for deployments that need
        # different tuning.
        self.pool_settings = {
            "max_connection_pool_size": int(os.getenv("AM_NEO4J_MAX_CONNECTION_POOL_SIZE", "50")),
            "connection_acquisition_timeout": int(
                os.getenv("AM_NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS", "10")
            ),
            "connection_timeout": int(os.getenv("AM_NEO4J_CONNECTION_TIMEOUT_SECONDS", "30")),
            "max_transaction_retry_time": float(
                os.getenv("AM_NEO4J_MAX_TRANSACTION_RETRY_SECONDS", "30.0")
            ),
        }
        self.driver = neo4j.GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=self.pool_settings["max_connection_pool_size"],
            connection_acquisition_timeout=self.pool_settings["connection_acquisition_timeout"],
            connection_timeout=self.pool_settings["connection_timeout"],
            max_transaction_retry_time=self.pool_settings["max_transaction_retry_time"],
        )
        logger.debug("Neo4j driver created for %s", uri)

    @contextmanager
    def session(self) -> Generator[neo4j.Session, None, None]:
        """Provide a Neo4j session scoped to the surrounding ``with`` block.

        Yields:
            An open :class:`neo4j.Session` that is closed when the context
            manager exits, delegating lifecycle to the driver's built-in session
            context manager.

        Note:
            Callers should keep session scope short—one logical unit of work per
            ``with``—so connections return to the pool promptly under load.
        """
        with self.driver.session() as s:
            yield s

    def setup_database(self) -> None:
        """Ensure required vector indexes and the entity uniqueness constraint exist.

        Executes four idempotent Cypher DDL statements in one session: three
        ``CREATE VECTOR INDEX ... IF NOT EXISTS`` definitions for
        ``Memory:Code``, ``Memory:Research``, and ``Memory:Conversation``
        embeddings (3072-dimensional cosine indexes), and
        ``CREATE CONSTRAINT ... IF NOT EXISTS`` enforcing uniqueness on
        ``(Entity.name, Entity.type)``.

        Safe to run at startup or deploy; existing objects are left unchanged.

        Note:
            ``IF NOT EXISTS`` means a wrong-dimension index that already exists
            will not be altered—use :meth:`fix_vector_index_dimensions` for the
            research/chat repair path.
        """
        # IF NOT EXISTS keeps startup safe under concurrent deploys and replays.
        statements = [
            (
                "CREATE VECTOR INDEX code_embeddings IF NOT EXISTS "
                "FOR (n:Memory:Code) ON n.embedding "
                "OPTIONS { indexConfig: { `vector.dimensions`: 3072, `vector.similarity_function`: 'cosine' }}"
            ),
            (
                "CREATE VECTOR INDEX research_embeddings IF NOT EXISTS "
                "FOR (n:Memory:Research) ON n.embedding "
                "OPTIONS { indexConfig: { `vector.dimensions`: 3072, `vector.similarity_function`: 'cosine' }}"
            ),
            (
                "CREATE VECTOR INDEX chat_embeddings IF NOT EXISTS "
                "FOR (n:Memory:Conversation) ON n.embedding "
                "OPTIONS { indexConfig: { `vector.dimensions`: 3072, `vector.similarity_function`: 'cosine' }}"
            ),
            (
                "CREATE CONSTRAINT entity_unique IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE"
            ),
        ]
        with self.session() as s:
            for stmt in statements:
                s.run(stmt)
        logger.info("Database setup complete: indexes and constraints created (if not existing).")

    def fix_vector_index_dimensions(self) -> None:
        """Drop and recreate research/chat vector indexes at the canonical 3072d.

        Repairs databases where ``research_embeddings`` or ``chat_embeddings``
        were created with incorrect ``vector.dimensions``. Because
        :meth:`setup_database` uses ``IF NOT EXISTS``, it cannot fix an existing
        index definition; this method issues ``DROP INDEX ... IF EXISTS`` first,
        then unconditional ``CREATE VECTOR INDEX`` for the two affected names.

        Note:
            ``DROP INDEX ... IF EXISTS`` is a no-op on empty or fresh databases,
            so the method remains safe to run when indexes are absent.
        """
        # DROP first; IF NOT EXISTS alone would never replace a wrong-dimension index.
        drop_statements = [
            "DROP INDEX research_embeddings IF EXISTS",
            "DROP INDEX chat_embeddings IF EXISTS",
        ]
        create_statements = [
            (
                "CREATE VECTOR INDEX research_embeddings "
                "FOR (n:Memory:Research) ON n.embedding "
                "OPTIONS { indexConfig: { `vector.dimensions`: 3072, `vector.similarity_function`: 'cosine' }}"
            ),
            (
                "CREATE VECTOR INDEX chat_embeddings "
                "FOR (n:Memory:Conversation) ON n.embedding "
                "OPTIONS { indexConfig: { `vector.dimensions`: 3072, `vector.similarity_function`: 'cosine' }}"
            ),
        ]
        with self.session() as s:
            for stmt in drop_statements:
                s.run(stmt)
            for stmt in create_statements:
                s.run(stmt)
        logger.info(
            "Vector index migration complete: research_embeddings and chat_embeddings reset to 3072d."
        )

    def close(self) -> None:
        """Close the underlying driver and release pooled connections.

        Idempotent with respect to driver shutdown semantics: after this call,
        :meth:`session` must not be used unless a new driver is constructed.
        """
        self.driver.close()
        logger.debug("Neo4j driver closed.")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ConnectionManager":
        """Construct a manager from a nested config dict with env overrides.

        Reads ``config["neo4j"]`` for ``uri``, ``user``, and ``password``, then
        applies ``NEO4J_URI``, ``NEO4J_USER`` or ``NEO4J_USERNAME``, and
        ``NEO4J_PASSWORD`` when those environment variables are set (empty string
        for user env vars still falls through to config because of ``or`` chaining
        with ``neo4j_cfg["user"]``).

        Args:
            config: Mapping containing a ``"neo4j"`` key whose value is a dict
                with at least ``uri``, ``user``, and ``password`` strings.

        Returns:
            A new :class:`ConnectionManager` instance.

        Raises:
            KeyError: If ``config`` lacks ``"neo4j"`` or required neo4j sub-keys.
        """
        neo4j_cfg = config["neo4j"]
        uri = os.getenv("NEO4J_URI", neo4j_cfg["uri"])
        user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME") or neo4j_cfg["user"]
        password = os.getenv("NEO4J_PASSWORD", neo4j_cfg["password"])
        return cls(uri, user, password)
