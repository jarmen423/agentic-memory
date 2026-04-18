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
    Vector index definitions in :meth:`ConnectionManager.setup_database`
    default to 3072 dimensions for ``Memory:Code``, ``Memory:Research``,
    ``Memory:Conversation``, and ``Memory:Healthcare`` embeddings, matching
    OpenAI ``text-embedding-3-large`` and Gemini Embedding 2 preview.
    ``setup_database`` now accepts an ``embedding_dim`` keyword so
    experiments using different embedding models (for example Nemotron at
    2048d) can reconcile index dimensionality without hand-written DDL.
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

    # Vector index targets used by :meth:`setup_database`.
    # Each tuple is (index_name, node_label, embedding_property).
    # Kept as a class-level constant so tests and migrations can reuse it.
    _VECTOR_INDEX_TARGETS: tuple[tuple[str, str, str], ...] = (
        ("code_embeddings", "Code", "embedding"),
        ("research_embeddings", "Research", "embedding"),
        ("chat_embeddings", "Conversation", "embedding"),
        # Healthcare vector index — cosine similarity over Synthea embeddings.
        ("healthcare_embeddings", "Healthcare", "embedding"),
    )

    def setup_database(self, *, embedding_dim: int = 3072) -> None:
        """Ensure required vector indexes and the entity uniqueness constraint exist.

        Creates (or, when the stored dimensionality has drifted from
        ``embedding_dim``, drops and recreates) the four memory-layer vector
        indexes — ``code_embeddings``, ``research_embeddings``,
        ``chat_embeddings``, ``healthcare_embeddings`` — and applies the
        ``entity_unique`` uniqueness constraint on ``(Entity.name, Entity.type)``
        plus ``memory_unique`` on ``(Memory.source_key, Memory.content_hash)``.

        Safe to run at startup or deploy; existing, correctly-dimensioned
        objects are left unchanged. This is a change from the older plain
        ``CREATE ... IF NOT EXISTS`` behaviour: we now actively reconcile
        dimensionality, so a healthcare experiment switching from a 3072d
        provider (Gemini) to a 2048d provider (Nemotron) no longer silently
        writes vectors that the existing index cannot accept.

        Args:
            embedding_dim: Target dimensionality for all four vector indexes.
                Defaults to 3072 to preserve historical behaviour. Pass the
                value that matches your configured :class:`EmbeddingService`
                (for example 2048 for Nemotron multimodal, 3072 for OpenAI
                ``text-embedding-3-large`` or Gemini Embedding 2 preview).

        Reconciliation rules per index:
            - Index missing → ``CREATE`` with the target dimension.
            - Index present with the same dimension → no-op.
            - Index present with a different dimension → ``DROP`` then
              ``CREATE`` with the target dimension. A warning is logged so
              the drop is visible in operator logs.

        Note:
            Dropping a vector index deletes its HNSW graph but does **not**
            delete the node-level ``embedding`` properties. Re-ingest (or
            run ``db.awaitIndex``) after a recreate to have the new index
            fully populated.
        """
        # Resolve the current dimensionality of each vector index that exists.
        # Missing indexes return no row; mismatched ones drive a drop+create.
        existing = self._existing_vector_index_dims()
        to_drop: list[str] = []
        to_create: list[tuple[str, str, str, int]] = []

        for name, label, prop in self._VECTOR_INDEX_TARGETS:
            current = existing.get(name)
            if current is None:
                to_create.append((name, label, prop, embedding_dim))
            elif current != embedding_dim:
                logger.warning(
                    "Vector index %s exists at %dd but target is %dd; "
                    "dropping and recreating.",
                    name, current, embedding_dim,
                )
                to_drop.append(name)
                to_create.append((name, label, prop, embedding_dim))
            # else: dimension already correct, leave the index alone

        with self.session() as s:
            for name in to_drop:
                s.run(f"DROP INDEX {name} IF EXISTS")
            for name, label, prop, dim in to_create:
                # Index/label/property names are hard-coded in
                # ``_VECTOR_INDEX_TARGETS`` so we control the interpolated
                # identifiers here; ``dim`` is an int. No injection surface.
                s.run(
                    f"CREATE VECTOR INDEX {name} IF NOT EXISTS "
                    f"FOR (n:{label}) ON n.{prop} "
                    "OPTIONS { indexConfig: { "
                    f"`vector.dimensions`: {int(dim)}, "
                    "`vector.similarity_function`: 'cosine' "
                    "}}"
                )
            s.run(
                "CREATE CONSTRAINT entity_unique IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE"
            )
            # Healthcare and other memory-domain writers MERGE on
            # ``(source_key, content_hash)``. Enforcing that identity in the
            # graph speeds up the hottest write path and makes later importer
            # parallelism safer because concurrent workers cannot create
            # duplicate Memory nodes with the same logical key.
            try:
                s.run(
                    "CREATE CONSTRAINT memory_unique IF NOT EXISTS "
                    "FOR (m:Memory) REQUIRE (m.source_key, m.content_hash) IS UNIQUE"
                )
            except neo4j.exceptions.DatabaseError as exc:
                # Existing experiment databases may already contain duplicate
                # Memory nodes from earlier importer iterations. We still want
                # schema bootstrap to succeed for the batched importer so long
                # as the rest of the graph is usable. The importer/parity plan
                # still treats this as a data-quality issue to clean up before
                # parallel scale runs.
                if "ConstraintCreationFailed" in str(exc) or "memory_unique" in str(exc):
                    logger.warning(
                        "Skipping memory_unique constraint because existing Memory "
                        "duplicates prevent creation. Clean the graph before "
                        "treating parallel importer runs as production-safe. "
                        "Original error: %s",
                        exc,
                    )
                    # Even when the graph is too dirty for a uniqueness
                    # constraint, the importer still benefits from a composite
                    # lookup index for the hot ``MATCH/MERGE (:Memory
                    # {source_key, content_hash})`` path.
                    s.run(
                        "CREATE INDEX memory_lookup IF NOT EXISTS "
                        "FOR (m:Memory) ON (m.source_key, m.content_hash)"
                    )
                else:
                    raise

        logger.info(
            "Database setup complete (embedding_dim=%d): "
            "%d existing indexes, %d recreated, %d created.",
            embedding_dim, len(existing), len(to_drop),
            len(to_create) - len(to_drop),
        )

    def _existing_vector_index_dims(self) -> dict[str, int]:
        """Return ``{index_name: current_dimensions}`` for existing vector indexes.

        Queries Neo4j's system information (``SHOW INDEXES``) and reads
        ``options.indexConfig["vector.dimensions"]`` for each vector index.
        Indexes that are still building or lack an options map are skipped —
        we only report indexes whose dimensionality is known.

        Returns:
            A dict keyed by index name. Empty when no vector indexes exist
            (fresh database) or when the current Neo4j version does not
            expose vector index metadata in the expected shape.
        """
        result: dict[str, int] = {}
        query = "SHOW INDEXES YIELD name, type, options WHERE type = 'VECTOR'"
        try:
            with self.session() as s:
                for record in s.run(query):
                    name = record.get("name")
                    options = record.get("options") or {}
                    index_config = options.get("indexConfig") or {}
                    # Neo4j reports this key with a literal dot in the name.
                    dim = index_config.get("vector.dimensions")
                    if isinstance(name, str) and isinstance(dim, (int, float)):
                        result[name] = int(dim)
        except Exception as exc:  # pragma: no cover — version/compat fallback
            # Older Neo4j versions or locked-down permissions may not expose
            # this query. Falling back to an empty dict means ``setup_database``
            # behaves like the pre-reconciliation implementation: ``CREATE ...
            # IF NOT EXISTS`` for everything, no drops. That preserves the
            # strictly-additive legacy behaviour when introspection fails.
            logger.debug(
                "Could not introspect existing vector index dimensions (%s); "
                "falling back to CREATE IF NOT EXISTS semantics.",
                exc,
            )
        return result

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
                "FOR (n:Research) ON n.embedding "
                "OPTIONS { indexConfig: { `vector.dimensions`: 3072, `vector.similarity_function`: 'cosine' }}"
            ),
            (
                "CREATE VECTOR INDEX chat_embeddings "
                "FOR (n:Conversation) ON n.embedding "
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
