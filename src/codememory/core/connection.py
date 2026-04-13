"""Neo4j driver lifecycle, sessions, and schema DDL for vector search.

`ConnectionManager` owns one `neo4j` driver (connection pool + timeouts), exposes
short-lived `session` contexts for Cypher execution, and applies vector indexes plus
constraints so embeddings stored on Memory nodes match Neo4j's expected dimensions
(see also `codememory.core.config_validator`).
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

import neo4j

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Wraps the Neo4j Bolt driver: pooling, sessions, and index/constraint setup.

    Graph reads/writes should obtain a session via `session` rather than holding
    long-lived sessions on the hot path.
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        """Create a Neo4j driver with standard pool settings.

        Args:
            uri: Bolt URI for the Neo4j instance.
            user: Neo4j username.
            password: Neo4j password.
        """
        # Driver-level pool and timeout tuning; transactional retries are handled here for
        # Neo4j's built-in transient errors when using write transactions (not used in all paths).
        self.driver = neo4j.GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=50,
            connection_acquisition_timeout=60,
            connection_timeout=30,
            max_transaction_retry_time=30.0,
        )
        logger.debug("Neo4j driver created for %s", uri)

    @contextmanager
    def session(self) -> Generator[neo4j.Session, None, None]:
        """Yield a Neo4j session as a context manager.

        Yields:
            An open neo4j.Session.
        """
        with self.driver.session() as s:
            yield s

    def setup_database(self) -> None:
        """Create vector indexes and entity uniqueness constraint if they don't exist.

        Runs all four Cypher DDL statements in a single session:
        - code_embeddings vector index (Memory:Code nodes)
        - research_embeddings vector index (Memory:Research nodes)
        - chat_embeddings vector index (Memory:Conversation nodes)
        - entity_unique uniqueness constraint (Entity nodes)
        """
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
        """Drop and recreate research/chat vector indexes at the default 3072d.

        This repairs databases that were provisioned with the wrong research/chat
        dimensions. IF NOT EXISTS prevents setup_database() from correcting an
        already-existing index, so this method drops first then creates
        unconditionally.

        Safe to call on fresh databases (DROP IF EXISTS is a no-op when index absent).
        """
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
        """Close the underlying Neo4j driver."""
        self.driver.close()
        logger.debug("Neo4j driver closed.")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ConnectionManager":
        """Build a ConnectionManager from a config dict with env var fallbacks.

        Env var priority: NEO4J_URI, NEO4J_USER / NEO4J_USERNAME, NEO4J_PASSWORD
        override the corresponding config values.

        Args:
            config: Dict with a "neo4j" sub-dict containing uri, user, password.

        Returns:
            Configured ConnectionManager instance.
        """
        neo4j_cfg = config["neo4j"]
        uri = os.getenv("NEO4J_URI", neo4j_cfg["uri"])
        user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME") or neo4j_cfg["user"]
        password = os.getenv("NEO4J_PASSWORD", neo4j_cfg["password"])
        return cls(uri, user, password)
