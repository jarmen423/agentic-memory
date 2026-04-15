"""Neo4j ingestion and hybrid retrieval for the code-memory domain.

This module hosts :class:`KnowledgeGraphBuilder`, which runs the multi-pass
GraphRAG pipeline (structure scan, entities/chunks, imports, optional call
graph) and exposes semantic search and dependency queries for agents.

Embeddings are resolved through the shared runtime embedding configuration
(:mod:`agentic_memory.core.runtime_embedding`) so code chunks use the same
provider strategy as the rest of Agentic Memory (Gemini by default; OpenAI or
other supported providers when configured). The builder does not assume a
single vendor for vectors.
"""

import os
import json
import hashlib
import logging
import sys
import time
import fnmatch
import math
import posixpath
import re
from collections import Counter
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple, Set
from functools import wraps

import neo4j
import openai
from tree_sitter import Parser

from agentic_memory.core.base import BaseIngestionPipeline
from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.embedding import EmbeddingService
from agentic_memory.core.registry import register_source
from agentic_memory.core.runtime_embedding import EmbeddingRuntimeConfig, resolve_embedding_runtime
from agentic_memory.ingestion.parser import CodeParser
from agentic_memory.ingestion.python_call_analyzer import (
    PythonCallAnalyzer,
    PythonCallAnalyzerError,
    PythonFileCallAnalysis,
)
from agentic_memory.ingestion.typescript_call_analyzer import (
    TypeScriptCallAnalyzer,
    TypeScriptCallAnalyzerError,
    TypeScriptFileCallAnalysis,
    TypeScriptOutgoingCall,
)

logger = logging.getLogger(__name__)

# Register code ingestion source at module load time
register_source("code_treesitter", ["Memory", "Code", "Chunk"])


def _safe_console_text(text: str) -> str:
    """Return text that can be written to the active terminal encoding.

    Why this helper exists:

    - The ingestion pipeline uses a few human-friendly progress glyphs such as
      emoji and symbols.
    - On Windows, a shell can still be attached to a legacy code page that
      cannot encode those characters.
    - When that happens, a normal ``print(...)`` can crash an otherwise healthy
      ingest run before the indexing logic itself fails.

    This helper preserves the original text when the terminal can encode it and
    degrades unsupported characters with replacement markers when it cannot.

    Args:
        text: Human-facing status text intended for stdout.

    Returns:
        A version of ``text`` that is safe to emit to the current stdout
        encoding without raising ``UnicodeEncodeError``.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding)


def _safe_print(text: str = "", *, end: str = "\n") -> None:
    """Write one line of progress text without crashing on terminal encoding.

    The code-memory pipeline is allowed to be verbose for operators, but it
    should never fail merely because the shell cannot render a decorative glyph.
    """
    print(_safe_console_text(text), end=end)


class CircuitBreaker:
    """
    Circuit breaker pattern for handling repeated Neo4j connection failures.
    
    After a threshold of failures, the circuit opens and subsequent calls
    fail fast until a timeout period passes.
    """
    
    def __init__(self, failure_threshold=5, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        
    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("Circuit breaker entering HALF_OPEN state")
            else:
                raise neo4j.exceptions.ServiceUnavailable(
                    "Circuit breaker is OPEN - Neo4j connection temporarily disabled"
                )
        
        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info("Circuit breaker reset to CLOSED")
            return result
        except neo4j.exceptions.ServiceUnavailable as e:
            self._record_failure()
            raise e
            
    def _record_failure(self):
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            if self.state != "OPEN":
                self.state = "OPEN"
                logger.error(f"Circuit breaker OPENED after {self.failure_count} failures")


def retry_on_openai_error(max_retries=3, delay=1.0):
    """Decorator factory that retries OpenAI API calls on transient errors.

    Wraps embedding and completion calls inside ``KnowledgeGraphBuilder`` to
    handle rate limits and transient connectivity failures without surfacing them
    to callers.  Uses exponential backoff: each retry waits ``delay * 2^attempt``
    seconds.  After ``max_retries`` exhausted attempts, the last exception is
    re-raised so the caller can decide how to handle the failure.

    Applied to: any method that calls OpenAI APIs (embeddings, completions).
    Not applied to: Neo4j calls — those use the ``CircuitBreaker`` instead.

    Args:
        max_retries: Maximum number of retry attempts before re-raising.
        delay: Base delay in seconds between retries (doubles each attempt).

    Returns:
        A decorator that wraps the target function with retry logic.

    Example:
        @retry_on_openai_error(max_retries=5, delay=0.5)
        def embed(self, text: str) -> list[float]: ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"OpenAI API error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time:.1f}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"OpenAI API failed after {max_retries} attempts: {e}")
                        raise
            raise last_exception
        return wrapper
    return decorator


class KnowledgeGraphBuilder(BaseIngestionPipeline):
    """Build and query a repo-scoped hybrid graph of code structure and embeddings.

    Coordinates the end-to-end flow from disk to Neo4j: optional schema setup,
    scanning the tree for supported sources, parsing through
    :class:`~agentic_memory.ingestion.parser.CodeParser`, writing ``File`` /
    ``Function`` / ``Class`` / ``Chunk`` nodes and ``IMPORTS`` / ``DEFINES`` /
    ``DESCRIBES`` relationships, and (when invoked) import resolution and
    semantic call analysis. Incremental paths such as :meth:`reindex_file` and
    :meth:`delete_file` keep the graph aligned with filesystem watchers without
    always replaying the full repo.

    Retrieval helpers (for example :meth:`semantic_search`,
    :meth:`get_file_dependencies`) read the same graph and vector indexes built
    during ingestion.

    Attributes:
        driver: Active Neo4j driver (also available via the base pipeline
            connection manager).
        embedding_runtime: Resolved provider, model, and dimensionality for
            code embeddings.
        embedding_service: Dispatches embed requests to the configured provider;
            ``None`` when no credentials or Vertex path is available, in which
            case vector steps degrade where the code allows.
        embedding_document_task_instruction: Optional Gemini Embedding 2 task
            text for document (stored chunk) vectors.
        embedding_query_task_instruction: Optional Gemini Embedding 2 task text
            for query vectors used in semantic search.
        parsers: Extension-to-Tree-sitter ``Parser`` map from the shared
            :class:`~agentic_memory.ingestion.parser.CodeParser` cache.
        repo_root: Current repository root used for relative paths and
            ``repo_id`` derivation.
        token_usage: Running counters for embedding calls and best-effort cost
            estimates during pipeline runs.
    """

    # Class-level defaults remain for callers/tests that introspect these
    # attributes before initialization, but __init__ resolves per-instance
    # values from the repo config / environment.
    EMBEDDING_MODEL = "gemini-embedding-2-preview"
    VECTOR_DIMENSIONS = 3072
    DOMAIN_LABEL = "Code"
    MEMORY_ENTITY_LABEL = "MemoryEntity"
    MEMORY_VECTOR_INDEX = "memory_entity_embeddings"
    MEMORY_FULLTEXT_INDEX = "memory_entity_search"

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        openai_key: Optional[str],
        repo_root: Optional[Path] = None,
        ignore_dirs: Optional[Set[str]] = None,
        ignore_files: Optional[Set[str]] = None,
        ignore_patterns: Optional[Set[str]] = None,
        *,
        config: Any | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        embedding_api_key: str | None = None,
        embedding_base_url: str | None = None,
        embedding_dimensions: int | None = None,
    ):
        """
        Initialize the KnowledgeGraphBuilder.

        Args:
            uri: Neo4j connection URI (e.g., "bolt://localhost:7687")
            user: Neo4j username
            password: Neo4j password
            openai_key: Legacy OpenAI API key parameter kept for backward
                compatibility. New callers should prefer provider-aware code
                embedding config via ``config`` or the explicit embedding_* args.
            repo_root: Root path of repository to index (optional, can be set per-method)
            ignore_dirs: Set of directory names to ignore during indexing
            ignore_files: Set of file patterns to ignore during indexing
            ignore_patterns: Set of .graphignore-style path/file patterns to skip
            config: Optional Config object for provider-aware code embedding
                resolution.
            embedding_provider: Explicit provider override for code embeddings.
            embedding_model: Explicit model override for code embeddings.
            embedding_api_key: Explicit API key override for code embeddings.
            embedding_base_url: Optional provider base URL override.
            embedding_dimensions: Optional output dimensionality override.
        """
        # Create ConnectionManager internally — preserves existing caller interface
        conn = ConnectionManager(uri=uri, user=user, password=password)
        super().__init__(conn)

        # Keep existing driver reference for backward compat with internal methods
        self.driver = self._conn.driver
        
        # Circuit breaker for Neo4j connection failures
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        legacy_provider = embedding_provider
        if legacy_provider is None and config is None and openai_key is not None:
            # Backward compatibility: old callers passed only `openai_key=` and
            # expected the code path to use OpenAI without consulting module config.
            legacy_provider = "openai"

        legacy_api_key = embedding_api_key
        if legacy_api_key is None and legacy_provider == "openai":
            legacy_api_key = openai_key
        self.embedding_runtime: EmbeddingRuntimeConfig = resolve_embedding_runtime(
            "code",
            config=config,
            repo_root=repo_root,
            provider=legacy_provider,
            model=embedding_model,
            api_key=legacy_api_key,
            base_url=embedding_base_url,
            output_dimensions=embedding_dimensions,
        )
        self.embedding_service: EmbeddingService | None = None
        if self.embedding_runtime.api_key or (
            self.embedding_runtime.provider == "gemini" and self.embedding_runtime.use_vertexai
        ):
            self.embedding_service = EmbeddingService(
                provider=self.embedding_runtime.provider,
                api_key=self.embedding_runtime.api_key,
                model=self.embedding_runtime.model,
                base_url=self.embedding_runtime.base_url,
                output_dimensions=self.embedding_runtime.dimensions,
                vertexai=self.embedding_runtime.use_vertexai,
                project=self.embedding_runtime.project,
                location=self.embedding_runtime.location,
                api_version=self.embedding_runtime.api_version,
            )
        self.EMBEDDING_MODEL = self.embedding_runtime.model
        self.VECTOR_DIMENSIONS = self.embedding_runtime.dimensions
        # Backward-compatible test hook for legacy OpenAI-specific unit tests.
        self.openai_client = (
            getattr(self.embedding_service, "_client", None)
            if self.embedding_runtime.provider == "openai" and self.embedding_service is not None
            else None
        )
        code_module_cfg: dict[str, Any] = {}
        if config is not None:
            code_module_cfg = config.get_module_config("code")
        self.embedding_document_task_instruction = code_module_cfg.get(
            "embedding_document_task_instruction"
        )
        self.embedding_query_task_instruction = code_module_cfg.get(
            "embedding_query_task_instruction"
        )
        self.parsers = self._init_parsers()
        self.repo_root = repo_root
        self.repo_id = str(repo_root.resolve()) if repo_root else None
        self.token_usage = {
            "embedding_tokens": 0,
            "embedding_calls": 0,
            "total_cost_usd": 0.0,
        }

        # Default ignore patterns. `.claude` contains agent handoffs, cached
        # worktrees, and other local workspace state that should not pollute the
        # repo's searchable code graph.
        default_ignore_dirs = {
            "node_modules",
            "__pycache__",
            ".git",
            ".claude",
            "dist",
            "build",
            ".venv",
            "venv",
            ".pytest_cache",
            ".mypy_cache",
            "target",
            "bin",
            "obj",
        }
        self.ignore_dirs = set(default_ignore_dirs)
        if ignore_dirs:
            self.ignore_dirs.update(ignore_dirs)
        self.ignore_files = ignore_files or set()
        self.ignore_patterns = ignore_patterns or set()

    def _should_ignore_dir(self, dir_name: str) -> bool:
        """Return True when a directory should be excluded from scanning."""
        if any(fnmatch.fnmatch(dir_name, pattern) for pattern in self.ignore_dirs):
            return True
        # Catch common virtualenv naming patterns like .venv-foo / venv-test.
        return dir_name.startswith(".venv") or dir_name.startswith("venv")

    def _should_ignore_path(self, rel_path: str) -> bool:
        """Return True when a relative path matches .graphignore patterns."""
        if not self.ignore_patterns:
            return False

        normalized = rel_path.replace("\\", "/")
        basename = Path(normalized).name
        for pattern in self.ignore_patterns:
            p = pattern.strip().replace("\\", "/")
            if not p:
                continue
            if p.endswith("/"):
                prefix = p.rstrip("/")
                if normalized == prefix or normalized.startswith(prefix + "/"):
                    return True
            if "/" in p:
                if fnmatch.fnmatch(normalized, p):
                    return True
            else:
                if fnmatch.fnmatch(basename, p):
                    return True
        return False

    def _normalize_rel_path(self, rel_path: str) -> str:
        """Store all repo-relative paths in Neo4j using forward slashes."""
        return rel_path.replace("\\", "/").strip()

    def _should_prune_file(
        self, rel_path: str, repo_path: Path, supported_extensions: Set[str]
    ) -> bool:
        """Return True if an existing File node should be removed from the graph."""
        normalized = rel_path.replace("\\", "/")
        rel_obj = Path(normalized)

        if rel_obj.name in self.ignore_files:
            return True
        if rel_obj.suffix not in supported_extensions:
            return True
        if any(self._should_ignore_dir(part) for part in rel_obj.parts[:-1]):
            return True
        if self._should_ignore_path(normalized):
            return True

        return not (repo_path / rel_obj).exists()

    def _delete_file_subgraph(self, session: neo4j.Session, repo_id: str, rel_path: str):
        """Delete one File node and all derived entities/chunks."""
        session.run(
            """
            MATCH (f:File {repo_id: $repo_id, path: $path})-[:DEFINES]->(entity)
            OPTIONAL MATCH (chunk:Chunk)-[:DESCRIBES]->(entity)
            DETACH DELETE chunk, entity
            """,
            repo_id=repo_id,
            path=rel_path,
        )
        session.run(
            "MATCH (f:File {repo_id: $repo_id, path: $path}) DETACH DELETE f",
            repo_id=repo_id,
            path=rel_path,
        )

    def clear_repo_code_graph(self, repo_path: Optional[Path] = None) -> None:
        """Delete one repo's code graph so the next index run rebuilds everything.

        Normal indexing is incremental and skips files whose content hash has not
        changed. That is correct for source edits, but not for embedding-model or
        embedding-format changes where every stored vector must be regenerated.

        This method clears only the repo-scoped code graph so a later ``index``
        run can rebuild the repository from source without touching the repo's
        git graph or writable memory graph.
        """
        _, repo_id = self._require_repo_context(repo_path)

        with self.driver.session() as session:
            session.run(
                """
                MATCH (trace:CodeTraceRun {repo_id: $repo_id})
                DETACH DELETE trace
                """,
                repo_id=repo_id,
            )
            session.run(
                """
                MATCH (issue:CallAnalysisIssue {repo_id: $repo_id})
                DETACH DELETE issue
                """,
                repo_id=repo_id,
            )
            session.run(
                """
                MATCH (f:File {repo_id: $repo_id})
                DETACH DELETE f
                """,
                repo_id=repo_id,
            )
            session.run(
                """
                MATCH (n)
                WHERE n.repo_id = $repo_id
                  AND (n:Chunk OR n:Function OR n:Class)
                DETACH DELETE n
                """,
                repo_id=repo_id,
            )
            session.run(
                """
                MATCH (reason:CallDropReason)
                WHERE NOT EXISTS {
                    MATCH ()-[r:CALL_ANALYSIS_DROP]->(reason)
                }
                DETACH DELETE reason
                """
            )

    def _init_parsers(self) -> Dict[str, Parser]:
        """Initialize the canonical parser and expose its parser cache."""
        code_parser = CodeParser()
        self._code_parser = code_parser
        return code_parser.parsers

    def _get_code_parser(self) -> CodeParser:
        """Return the shared parser instance, creating it lazily if tests stub init."""
        parser = getattr(self, "_code_parser", None)
        if parser is None:
            parser = CodeParser()
            self._code_parser = parser
            self.parsers = parser.parsers
        return parser

    def _get_typescript_call_analyzer(self) -> TypeScriptCallAnalyzer:
        """Return the cached TypeScript call analyzer helper.

        The analyzer is created lazily so unit tests that patch graph-builder
        initialization do not need to also patch Node helper setup. This keeps
        the dependency boundary narrow: the graph layer asks for semantic JS/TS
        call targets only when Pass 4 actually needs them.
        """
        analyzer = getattr(self, "_typescript_call_analyzer", None)
        if analyzer is None:
            analyzer = TypeScriptCallAnalyzer()
            self._typescript_call_analyzer = analyzer
        return analyzer

    def _get_python_call_analyzer(self) -> PythonCallAnalyzer:
        """Return the cached Python semantic call analyzer helper."""
        analyzer = getattr(self, "_python_call_analyzer", None)
        if analyzer is None:
            analyzer = PythonCallAnalyzer()
            self._python_call_analyzer = analyzer
        return analyzer

    def _set_repo_context(self, repo_path: Path) -> tuple[Path, str]:
        """Persist the active repo root and return its stable repo_id."""
        resolved = repo_path.resolve()
        self.repo_root = resolved
        self.repo_id = str(resolved)
        return resolved, self.repo_id

    def _require_repo_context(self, repo_path: Optional[Path] = None) -> tuple[Path, str]:
        """Resolve the active repository context for one graph operation."""
        candidate = repo_path or self.repo_root
        if not candidate:
            raise ValueError("repo_path must be provided either in __init__ or as parameter")
        return self._set_repo_context(Path(candidate))

    def _upsert_file_node(
        self,
        session: neo4j.Session,
        *,
        repo_id: str,
        rel_path: str,
        file_name: str,
        ohash: str,
    ) -> None:
        """Create or update one repo-scoped File node."""
        session.run(
            """
            MERGE (f:File {repo_id: $repo_id, path: $path})
            SET f.name = $name,
                f.ohash = $ohash,
                f.last_updated = datetime()
            """,
            repo_id=repo_id,
            path=rel_path,
            name=file_name,
            ohash=ohash,
        )

    def _clear_file_derivatives(
        self,
        session: neo4j.Session,
        *,
        repo_id: str,
        rel_path: str,
    ) -> None:
        """Delete derived entities, chunks, and outgoing structural edges for one file."""
        session.run(
            """
            MATCH (f:File {repo_id: $repo_id, path: $path})-[:DEFINES]->(entity)
            OPTIONAL MATCH (chunk:Chunk {repo_id: $repo_id})-[:DESCRIBES]->(entity)
            DETACH DELETE chunk, entity
            """,
            repo_id=repo_id,
            path=rel_path,
        )
        session.run(
            """
            MATCH (f:File {repo_id: $repo_id, path: $path})-[r:IMPORTS]->()
            DELETE r
            """,
            repo_id=repo_id,
            path=rel_path,
        )

    def _parse_source_file(self, full_path: Path) -> tuple[str, dict[str, Any]]:
        """Read and parse one source file through the canonical parser."""
        code_content = full_path.read_text(errors="ignore")
        parsed = self._get_code_parser().parse_file(code_content, full_path.suffix)
        return code_content, parsed

    def ingest(self, source: Any) -> dict[str, Any]:
        """Ingest a repository directory. Wraps the existing multi-pass pipeline.

        Implements the BaseIngestionPipeline ABC contract.

        Args:
            source: Path to the repository root (str or Path).

        Returns:
            Dict summarizing the ingestion result.
        """
        repo_path = Path(source) if isinstance(source, str) else source
        self.repo_root = repo_path
        self.run_pipeline(repo_path)
        return {"status": "complete", "domain": self.DOMAIN_LABEL}

    def close(self):
        """Closes database connection."""
        self.driver.close()

    # =========================================================================
    # DATABASE SETUP
    # =========================================================================

    def setup_database(self):
        """
        Pass 0: Pre-flight Configuration.
        Creates constraints and vector indexes to optimize ingestion and retrieval.
        """
        logger.info("🚀 [Pass 0] Configuring Database Constraints & Indexes...")

        queries = [
            # 1. Drop legacy single-repo constraints so the graph can hold
            # multiple repositories without path/signature collisions.
            "DROP CONSTRAINT file_path_unique IF EXISTS",
            "DROP CONSTRAINT function_sig_unique IF EXISTS",
            "DROP CONSTRAINT class_name_unique IF EXISTS",
            # 2. Repo-scoped uniqueness constraints.
            (
                "CREATE CONSTRAINT file_repo_path_unique IF NOT EXISTS "
                "FOR (f:File) REQUIRE (f.repo_id, f.path) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT function_repo_sig_unique IF NOT EXISTS "
                "FOR (f:Function) REQUIRE (f.repo_id, f.signature) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT class_repo_name_unique IF NOT EXISTS "
                "FOR (c:Class) REQUIRE (c.repo_id, c.qualified_name) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT code_trace_run_unique IF NOT EXISTS "
                "FOR (t:CodeTraceRun) REQUIRE (t.repo_id, t.root_signature) IS UNIQUE"
            ),
            # 2. Vector Index for Hybrid Search
            f"""
            CREATE VECTOR INDEX code_embeddings IF NOT EXISTS
            FOR (c:Chunk) ON (c.embedding)
            OPTIONS {{indexConfig: {{
             `vector.dimensions`: {self.VECTOR_DIMENSIONS},
             `vector.similarity_function`: 'cosine'
            }} }}
            """,
            # 3. Fulltext Index for Keyword Search
            """
            CREATE FULLTEXT INDEX entity_text_search IF NOT EXISTS
            FOR (n:Function|Class|File) ON EACH [n.name, n.docstring, n.path]
            """,
        ]

        with self.driver.session() as session:
            for q in queries:
                try:
                    session.run(q)
                except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
                    logger.warning(f"Constraint/Index check: {e}")
        logger.info("✅ Database configured.")

    def setup_memory_schema(self) -> None:
        """Ensure indexes and constraints for agent-authored memory entities exist.

        This concept graph is intentionally separate from research and
        conversation memory. We store agent-authored concepts under a dedicated
        ``:MemoryEntity`` label so CRUD/search operations do not sweep in
        ``:Memory:Research:*`` or ``:Memory:Conversation:*`` nodes.
        """
        logger.info("🧠 Ensuring memory-entity schema exists.")
        queries = [
            (
                "CREATE CONSTRAINT memory_entity_repo_name_unique IF NOT EXISTS "
                f"FOR (m:{self.MEMORY_ENTITY_LABEL}) REQUIRE (m.repo_id, m.name) IS UNIQUE"
            ),
            (
                f"CREATE VECTOR INDEX {self.MEMORY_VECTOR_INDEX} IF NOT EXISTS "
                f"FOR (m:{self.MEMORY_ENTITY_LABEL}) ON (m.embedding) "
                f"OPTIONS {{indexConfig: {{"
                f"`vector.dimensions`: {self.VECTOR_DIMENSIONS}, "
                f"`vector.similarity_function`: 'cosine'"
                f"}} }}"
            ),
            (
                f"CREATE FULLTEXT INDEX {self.MEMORY_FULLTEXT_INDEX} IF NOT EXISTS "
                f"FOR (m:{self.MEMORY_ENTITY_LABEL}) ON EACH "
                "[m.name, m.entity_type, m.observation_text]"
            ),
        ]
        with self.driver.session() as session:
            for query in queries:
                try:
                    session.run(query)
                except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as exc:
                    logger.warning("Memory schema check failed: %s", exc)

    # =========================================================================
    # EMBEDDING GENERATION
    # =========================================================================

    def _calculate_ohash(self, file_path: Path) -> str:
        """Calculates MD5 hash of file content for change detection."""
        try:
            return hashlib.md5(file_path.read_bytes()).hexdigest()
        except (OSError, IOError):
            return ""

    @retry_on_openai_error(max_retries=3, delay=1.0)
    def get_embedding(
        self,
        text: str,
        *,
        task_instruction: str | None = None,
    ) -> List[float]:
        """Generate a code embedding using the configured provider.

        Args:
            text: The text to embed.
            task_instruction: Optional Gemini Embedding 2 task instruction. This
                lets Agentic Memory embed stored code chunks differently from
                user search queries so both sides of retrieval can be tuned.

        Returns:
            List of floats representing the embedding vector
        """
        if self.embedding_service is None:
            logger.warning(
                "No API key configured for code embedding provider '%s'; returning zero-vector embedding.",
                self.embedding_runtime.provider,
            )
            return [0.0] * self.VECTOR_DIMENSIONS

        # Truncate long chunks to keep request size bounded across providers.
        MAX_CHARS = 24000

        if len(text) > MAX_CHARS:
            logger.warning(
                f"⚠️ Truncating text chunk of size {len(text)} to {MAX_CHARS} chars."
            )
            text = text[:MAX_CHARS] + "...[TRUNCATED]"

        text = text.replace("\n", " ")

        # Track calls for every provider. Detailed token/cost accounting remains
        # provider-specific and is only available on some clients.
        self.token_usage["embedding_calls"] += 1

        vector, metadata = self.embedding_service.embed_with_metadata(
            text,
            task_instruction=task_instruction,
        )
        billable_tokens = metadata.prompt_tokens or metadata.total_tokens
        if billable_tokens is not None:
            self.token_usage["embedding_tokens"] += int(billable_tokens)
        if metadata.estimated_cost_usd is not None:
            self.token_usage["total_cost_usd"] += float(metadata.estimated_cost_usd)
        return vector

    def get_document_embedding(self, text: str) -> List[float]:
        """Embed code/document corpus text using the configured document role.

        Stored vectors represent the retrievable code corpus. For Gemini
        Embedding 2 preview, we optionally attach the document-side task
        instruction from config so the model can optimize for that role.
        """
        return self.get_embedding(
            text,
            task_instruction=self.embedding_document_task_instruction,
        )

    def get_query_embedding(self, text: str) -> List[float]:
        """Embed a semantic-search query using the configured query role.

        Query vectors represent operator intent rather than stored code. Keeping
        a separate query-side task instruction lets Gemini Embedding 2 optimize
        retrieval behavior for "find the right code for this query" instead of
        treating queries like ordinary documents.
        """
        return self.get_embedding(
            text,
            task_instruction=self.embedding_query_task_instruction,
        )

    # =========================================================================
    # PASS 1: STRUCTURE SCAN & CHANGE DETECTION
    # =========================================================================

    def pass_1_structure_scan(
        self, repo_path: Optional[Path] = None, supported_extensions: Optional[Set[str]] = None
    ) -> list[str]:
        """
        Scans the directory structure.
        Creates File nodes if they are new or modified. Skips if oHash matches.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
            supported_extensions: Set of file extensions to process

        Returns:
            Repo-relative paths that are new or whose content hash changed.

        Why this matters:
            Phase 11 exposed that `agent-memory index` was still re-running
            Pass 2 for every file even when Pass 1 had already proven the file
            was unchanged. Returning the changed-file set lets later passes
            scope expensive work, especially embeddings, to only the files that
            actually need rebuilding.
        """
        repo_path, repo_id = self._require_repo_context(repo_path)
        supported_extensions = supported_extensions or {".py", ".js", ".ts", ".tsx", ".jsx"}

        logger.info("📂 [Pass 1] Scanning Directory Structure...")

        count = 0
        pruned_count = 0
        changed_paths: list[str] = []
        with self.driver.session() as session:
            for root, dirs, files in os.walk(repo_path):
                # Filter directories
                dirs[:] = [d for d in dirs if not self._should_ignore_dir(d)]

                for file_name in files:
                    if file_name in self.ignore_files:
                        continue
                    file_path = Path(root) / file_name
                    if file_path.suffix not in supported_extensions:
                        continue

                    rel_path = self._normalize_rel_path(str(file_path.relative_to(repo_path)))
                    if self._should_ignore_path(rel_path):
                        continue
                    current_ohash = self._calculate_ohash(file_path)

                    # Check if file exists and hash matches (Change Detection)
                    result = session.run(
                        (
                            "MATCH (f:File {repo_id: $repo_id, path: $path}) "
                            "RETURN f.ohash as hash"
                        ),
                        repo_id=repo_id,
                        path=rel_path,
                    ).single()

                    if result and result["hash"] == current_ohash:
                        # Skip processing, but mark as visited if needed
                        continue

                    # Create/Update File Node
                    self._upsert_file_node(
                        session,
                        repo_id=repo_id,
                        rel_path=rel_path,
                        file_name=file_name,
                        ohash=current_ohash,
                    )
                    count += 1
                    changed_paths.append(rel_path)

            # Prune File nodes that are no longer indexable under current rules.
            existing_paths = [
                record["path"]
                for record in session.run(
                    "MATCH (f:File {repo_id: $repo_id}) RETURN f.path as path",
                    repo_id=repo_id,
                )
            ]
            for rel_path in existing_paths:
                if self._should_prune_file(rel_path, repo_path, supported_extensions):
                    self._delete_file_subgraph(session, repo_id, rel_path)
                    pruned_count += 1

        logger.info(f"✅ [Pass 1] Processed {count} new/modified files.")
        if pruned_count:
            logger.info(f"🧹 [Pass 1] Pruned {pruned_count} excluded/stale files from graph.")
        return changed_paths

    # =========================================================================
    # PASS 2: ENTITY DEFINITION & HYBRID CHUNKING
    # =========================================================================

    def pass_2_entity_definition(
        self,
        repo_path: Optional[Path] = None,
        *,
        target_paths: Optional[Set[str] | list[str]] = None,
    ):
        """
        Parses files using Tree-sitter.
        1. Extracts Classes/Functions.
        2. Creates 'Chunk' nodes with "Contextual Prefixing".

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
            target_paths: Optional repo-relative file paths to rebuild. When
                omitted, Pass 2 rebuilds every indexed file in the repo. When
                provided, only those files are reparsed and re-embedded.
        """
        repo_path, repo_id = self._require_repo_context(repo_path)

        logger.info("🧠 [Pass 2] Extracting Entities & Creating Chunks...")

        with self.driver.session() as session:
            if target_paths is None:
                result = session.run(
                    "MATCH (f:File {repo_id: $repo_id}) RETURN f.path as path",
                    repo_id=repo_id,
                )
                files_to_process = [record["path"] for record in result]
            else:
                files_to_process = sorted(
                    {
                        self._normalize_rel_path(path)
                        for path in target_paths
                        if self._normalize_rel_path(path)
                    }
                )

            if not files_to_process:
                logger.info("⏭️ [Pass 2] No changed files require entity/chunk rebuild.")
                return

            for i, rel_path in enumerate(files_to_process):
                _safe_print(
                    f"[{i+1}/{len(files_to_process)}] 🧠 Processing: {rel_path}...",
                    end="\r",
                )

                full_path = repo_path / rel_path
                if not full_path.exists():
                    continue

                _, parsed = self._parse_source_file(full_path)
                if not parsed["classes"] and not parsed["functions"]:
                    continue

                self._clear_file_derivatives(session, repo_id=repo_id, rel_path=rel_path)
                file_hash = self._calculate_ohash(full_path)
                self._upsert_file_node(
                    session,
                    repo_id=repo_id,
                    rel_path=rel_path,
                    file_name=full_path.name,
                    ohash=file_hash,
                )

                for class_row in parsed["classes"]:
                    class_name = class_row["name"]
                    class_signature = f"{rel_path}:{class_name}"
                    class_code = class_row["code"]
                    session.run(
                        """
                        MATCH (f:File {repo_id: $repo_id, path: $path})
                        MERGE (c:Class {repo_id: $repo_id, qualified_name: $sig})
                        SET c.name = $name,
                            c.code = $code,
                            c.path = $path
                        MERGE (f)-[:DEFINES]->(c)
                        """,
                        repo_id=repo_id,
                        path=rel_path,
                        sig=class_signature,
                        name=class_name,
                        code=class_code,
                    )

                    enriched_text = f"Context: File {rel_path} > Class {class_name}\n\n{class_code}"
                    session.run(
                        """
                        MATCH (c:Class {repo_id: $repo_id, qualified_name: $sig})
                        CREATE (ch:Chunk {id: randomUUID()})
                        SET ch.repo_id = $repo_id,
                            ch.path = $path,
                            ch.text = $text,
                            ch.embedding = $embedding,
                            ch.created_at = datetime()
                        MERGE (ch)-[:DESCRIBES]->(c)
                        """,
                        repo_id=repo_id,
                        path=rel_path,
                        sig=class_signature,
                        text=class_code,
                        embedding=self.get_document_embedding(enriched_text),
                    )

                for function_row in parsed["functions"]:
                    function_name = function_row["name"]
                    parent_class = function_row.get("parent_class", "")
                    qualified_name = function_row.get("qualified_name") or function_name
                    function_signature = f"{rel_path}:{qualified_name}"
                    function_code = function_row["code"]

                    session.run(
                        """
                        MATCH (f:File {repo_id: $repo_id, path: $path})
                        MERGE (fn:Function {repo_id: $repo_id, signature: $sig})
                        SET fn.name = $name,
                            fn.qualified_name = $qualified_name,
                            fn.parent_class = $parent_class,
                            fn.name_line = $name_line,
                            fn.name_column = $name_column,
                            fn.code = $code,
                            fn.path = $path
                        MERGE (f)-[:DEFINES]->(fn)
                        """,
                        repo_id=repo_id,
                        path=rel_path,
                        sig=function_signature,
                        name=function_name,
                        qualified_name=qualified_name,
                        parent_class=parent_class,
                        name_line=function_row.get("name_line"),
                        name_column=function_row.get("name_column"),
                        code=function_code,
                    )

                    if parent_class:
                        class_signature = f"{rel_path}:{parent_class}"
                        session.run(
                            """
                            MATCH (c:Class {repo_id: $repo_id, qualified_name: $csig})
                            MATCH (fn:Function {repo_id: $repo_id, signature: $fsig})
                            MERGE (c)-[:HAS_METHOD]->(fn)
                            """,
                            repo_id=repo_id,
                            csig=class_signature,
                            fsig=function_signature,
                        )

                    context_prefix = f"File: {rel_path}"
                    if parent_class:
                        context_prefix += f" > Class: {parent_class}"
                    enriched_text = (
                        f"Context: {context_prefix} > Method: {function_name}\n\n{function_code}"
                    )
                    session.run(
                        """
                        MATCH (fn:Function {repo_id: $repo_id, signature: $sig})
                        CREATE (ch:Chunk {id: randomUUID()})
                        SET ch.repo_id = $repo_id,
                            ch.path = $path,
                            ch.text = $text,
                            ch.embedding = $embedding,
                            ch.created_at = datetime()
                        MERGE (ch)-[:DESCRIBES]->(fn)
                        """,
                        repo_id=repo_id,
                        path=rel_path,
                        sig=function_signature,
                        text=function_code,
                        embedding=self.get_document_embedding(enriched_text),
                    )

        logger.info("✅ [Pass 2] Entities and Semantic Chunks created.")

    # =========================================================================
    # PASS 3: IMPORT RESOLUTION
    # =========================================================================

    def _extract_python_import_modules(self, code: str) -> Set[str]:
        """Extract Python import module names from source text."""
        parsed = self._get_code_parser().parse_file(code, ".py")
        return set(parsed["imports"])

    def _extract_js_ts_import_modules(self, code: str) -> Set[str]:
        """Extract JS/TS/TSX module specifiers from source text."""
        modules: Set[str] = set()
        for extension in [".js", ".ts", ".tsx", ".jsx"]:
            parsed = self._get_code_parser().parse_file(code, extension)
            modules.update(parsed["imports"])
            if modules:
                break
        return modules

    def _normalize_js_ts_specifier(self, module_name: str) -> str:
        """Normalize JS/TS module specifier for matching against File.path."""
        spec = module_name.strip().strip("'\"")
        spec = spec.split("?", 1)[0].split("#", 1)[0]
        if spec.startswith("@/"):
            return spec[2:]
        if spec.startswith("~/"):
            return spec[2:]
        if spec.startswith("/"):
            return spec[1:]
        return spec

    def _resolve_import_candidates(
        self, source_rel_path: str, module_name: str, source_ext: str
    ) -> Set[str]:
        """
        Return candidate file paths for a module specifier.

        For Python imports, converts dotted names to module paths.
        For JS/TS imports, resolves relative specifiers and common extension/index variants.
        """
        candidates: Set[str] = set()

        if source_ext == ".py":
            raw_module = module_name.strip()
            if not raw_module:
                return candidates

            source_dir = posixpath.dirname(source_rel_path)
            leading_dots = len(raw_module) - len(raw_module.lstrip("."))
            remainder = raw_module.lstrip(".").replace(".", "/")

            if leading_dots:
                base_dir = source_dir
                for _ in range(max(leading_dots - 1, 0)):
                    base_dir = posixpath.dirname(base_dir)
                normalized = (
                    posixpath.normpath(posixpath.join(base_dir, remainder))
                    if remainder
                    else posixpath.normpath(base_dir)
                )
            else:
                normalized = remainder

            if not normalized or normalized.startswith("../"):
                return candidates

            candidates.add(normalized)
            candidates.add(f"{normalized}.py")
            candidates.add(f"{normalized}/__init__.py")
            return candidates

        spec = self._normalize_js_ts_specifier(module_name)
        if not spec:
            return candidates

        source_dir = posixpath.dirname(source_rel_path)
        if spec.startswith("."):
            base = posixpath.normpath(posixpath.join(source_dir, spec))
        else:
            base = posixpath.normpath(spec)

        # Avoid escaping repo root for relative imports.
        if base.startswith("../"):
            return candidates

        js_ts_exts = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]
        _, ext = os.path.splitext(base)

        if ext:
            candidates.add(base)
        else:
            candidates.add(base)
            for candidate_ext in js_ts_exts:
                candidates.add(f"{base}{candidate_ext}")
                candidates.add(f"{base}/index{candidate_ext}")

        return candidates

    def _module_to_fuzzy_part(self, module_name: str, source_ext: str) -> str:
        """Return a fuzzy module path fragment for fallback import linking."""
        if source_ext == ".py":
            return module_name.replace(".", "/").strip()

        spec = self._normalize_js_ts_specifier(module_name)
        if spec.startswith("."):
            # For relative JS/TS imports, fallback matching is less useful than exact candidates.
            return ""
        return spec

    def pass_3_imports(
        self,
        repo_path: Optional[Path] = None,
        *,
        target_paths: Optional[Set[str] | list[str]] = None,
    ):
        """
        Analyzes import statements to link File nodes.
        Supports Python and JS/TS import patterns.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
            target_paths: Optional source files whose outgoing IMPORTS edges
                should be rebuilt. This is enough for incremental indexing
                because IMPORTS are stored from the source file to its targets.
        """
        repo_path, repo_id = self._require_repo_context(repo_path)

        logger.info("🕸️ [Pass 3] Linking Files via Imports...")
        supported_exts = {".py", ".js", ".jsx", ".ts", ".tsx"}

        with self.driver.session() as session:
            result = session.run(
                "MATCH (f:File {repo_id: $repo_id}) RETURN f.path as path",
                repo_id=repo_id,
            )
            all_paths = [r["path"] for r in result]
            path_set = set(all_paths)
            files = [path for path in all_paths if Path(path).suffix in supported_exts]
            if target_paths is not None:
                normalized_targets = {
                    self._normalize_rel_path(path)
                    for path in target_paths
                    if self._normalize_rel_path(path)
                }
                files = [path for path in files if path in normalized_targets]

            if not files:
                logger.info("⏭️ [Pass 3] No changed files require import relinking.")
                return

            for rel_path in files:
                full_path = repo_path / rel_path
                source_ext = full_path.suffix

                if not full_path.exists():
                    logger.warning(
                        "⚠️ File found in graph but missing on disk (stale): %s. Deleting node.",
                        rel_path,
                    )
                    session.run(
                        "MATCH (f:File {repo_id: $repo_id, path: $path}) DETACH DELETE f",
                        repo_id=repo_id,
                        path=rel_path,
                    )
                    continue

                _, parsed = self._parse_source_file(full_path)
                modules = parsed["imports"]

                # Rebuild imports for this source file to avoid stale edges.
                session.run(
                    """
                    MATCH (source:File {repo_id: $repo_id, path: $src})-[r:IMPORTS]->()
                    DELETE r
                    """,
                    repo_id=repo_id,
                    src=rel_path,
                )

                exact_targets: Set[str] = set()
                for module_name in modules:
                    candidates = self._resolve_import_candidates(rel_path, module_name, source_ext)
                    matched = {candidate for candidate in candidates if candidate in path_set}
                    exact_targets.update(matched)

                if exact_targets:
                    session.run(
                        """
                        MATCH (source:File {repo_id: $repo_id, path: $src})
                        UNWIND $targets as target_path
                        MATCH (target:File {repo_id: $repo_id, path: target_path})
                        MERGE (source)-[:IMPORTS]->(target)
                        """,
                        repo_id=repo_id,
                        src=rel_path,
                        targets=sorted(exact_targets),
                    )

            logger.info("✅ [Pass 3] Import graph built.")

    def _build_function_signature_indexes(
        self,
        file_records: list[neo4j.Record],
    ) -> tuple[
        dict[str, dict[str, str]],
        dict[str, dict[str, list[str]]],
        dict[str, dict[tuple[int, int], str]],
    ]:
        """Build lookup tables for repo-scoped function signatures.

        Pass 4 needs to translate analyzer output back into the graph's stable
        function identity scheme. The graph stores function nodes as
        ``repo_id + signature`` where the signature is ``path:qualified_name``.
        TypeScript's call hierarchy gives us target file paths plus symbol
        names/container names, so we build exact and fallback indexes here.

        Some semantic analyzers can also point at the exact definition line and
        column for the target symbol. The positional index gives Pass 4 one more
        repo-generic way to disambiguate collisions inside a single file before
        it falls back to the noisy short-name heuristic.
        """
        qualified_index: dict[str, dict[str, str]] = {}
        name_index: dict[str, dict[str, list[str]]] = {}
        position_index: dict[str, dict[tuple[int, int], str]] = {}

        for record in file_records:
            rel_path = record["path"]
            per_path_qualified: dict[str, str] = {}
            per_path_name: dict[str, list[str]] = {}
            per_path_position: dict[tuple[int, int], str] = {}

            for function_row in record["funcs"]:
                signature = str(function_row["sig"])
                qualified_name = str(
                    function_row.get("qualified_name") or function_row.get("name") or ""
                )
                function_name = str(function_row.get("name") or qualified_name)
                if qualified_name:
                    per_path_qualified[qualified_name] = signature
                if function_name:
                    per_path_name.setdefault(function_name, []).append(signature)
                name_line = function_row.get("name_line")
                name_column = function_row.get("name_column")
                if isinstance(name_line, int) and isinstance(name_column, int):
                    per_path_position[(name_line, name_column)] = signature

            qualified_index[rel_path] = per_path_qualified
            name_index[rel_path] = per_path_name
            position_index[rel_path] = per_path_position

        return qualified_index, name_index, position_index

    def _prepare_typescript_analysis_requests(
        self,
        *,
        repo_path: Path,
        file_records: list[neo4j.Record],
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Parse JS/TS files once and prepare analyzer input rows.

        Returns:
            A tuple of:
            - parsed rows keyed by repo-relative path
            - JS/TS analyzer requests keyed by the parser's function contract
        """
        parsed_by_path: dict[str, dict[str, Any]] = {}
        analyzer_requests: list[dict[str, Any]] = []
        js_like_extensions = {".js", ".jsx", ".ts", ".tsx"}

        for record in file_records:
            rel_path = record["path"]
            full_path = repo_path / rel_path
            if not full_path.exists():
                continue

            _, parsed = self._parse_source_file(full_path)
            parsed_by_path[rel_path] = parsed

            if full_path.suffix not in js_like_extensions or not parsed["functions"]:
                continue

            analyzer_requests.append(
                {
                    "path": rel_path,
                    "functions": [
                        {
                            "name": function_row["name"],
                            "qualified_name": function_row.get("qualified_name")
                            or function_row["name"],
                            "parent_class": function_row.get("parent_class") or "",
                            "name_line": function_row.get("name_line"),
                            "name_column": function_row.get("name_column"),
                        }
                        for function_row in parsed["functions"]
                    ],
                }
            )

        return parsed_by_path, analyzer_requests

    def _prepare_python_analysis_requests(
        self,
        *,
        file_records: list[neo4j.Record],
        parsed_by_path: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Prepare Python semantic-analyzer requests from the shared parser rows."""
        analyzer_requests: list[dict[str, Any]] = []

        for record in file_records:
            rel_path = record["path"]
            if Path(rel_path).suffix.lower() != ".py":
                continue

            parsed = parsed_by_path.get(rel_path)
            if not parsed or not parsed["functions"]:
                continue

            analyzer_requests.append(
                {
                    "path": rel_path,
                    "functions": [
                        {
                            "name": function_row["name"],
                            "qualified_name": function_row.get("qualified_name")
                            or function_row["name"],
                            "parent_class": function_row.get("parent_class") or "",
                            "name_line": function_row.get("name_line"),
                            "name_column": function_row.get("name_column"),
                        }
                        for function_row in parsed["functions"]
                    ],
                }
            )

        return analyzer_requests

    def _resolve_semantic_call_target(
        self,
        call_target: Any,
        *,
        qualified_index: dict[str, dict[str, str]],
        name_index: dict[str, dict[str, list[str]]],
        position_index: dict[str, dict[tuple[int, int], str]],
    ) -> tuple[str | None, str]:
        """Map one semantic analyzer target back to a graph function signature.

        This shared helper keeps Python and JS/TS analyzers on the same graph
        contract. The caller can still label the edge source separately, but the
        matching logic should stay generic so real repos fail for understandable
        reasons rather than language-specific copy-paste divergence.
        """
        target_path = getattr(call_target, "rel_path", None)
        if not target_path:
            return None, "missing_target_path"

        per_path_qualified = qualified_index.get(target_path, {})
        per_path_name = name_index.get(target_path, {})
        per_path_position = position_index.get(target_path, {})
        if not per_path_qualified and not per_path_name and not per_path_position:
            return None, "target_path_not_indexed"

        qualified_name_guess = getattr(call_target, "qualified_name_guess", None)
        if qualified_name_guess:
            exact_signature = per_path_qualified.get(qualified_name_guess)
            if exact_signature:
                return exact_signature, "matched_qualified_name"

        target_line = (
            getattr(call_target, "definition_line", None)
            or getattr(call_target, "target_line", None)
            or getattr(call_target, "name_line", None)
        )
        target_column = (
            getattr(call_target, "definition_column", None)
            or getattr(call_target, "target_column", None)
            or getattr(call_target, "name_column", None)
        )
        if isinstance(target_line, int) and isinstance(target_column, int):
            position_signature = per_path_position.get((target_line, target_column))
            if position_signature:
                return position_signature, "matched_target_position"

        target_name = getattr(call_target, "name", "")
        name_candidates = per_path_name.get(target_name, [])
        if len(name_candidates) == 1:
            return name_candidates[0], "matched_unique_name"
        if len(name_candidates) > 1:
            return None, "ambiguous_short_name"

        return None, "no_matching_symbol"

    def _resolve_typescript_call_target(
        self,
        call_target: TypeScriptOutgoingCall,
        *,
        qualified_index: dict[str, dict[str, str]],
        name_index: dict[str, dict[str, list[str]]],
        position_index: dict[str, dict[tuple[int, int], str]],
    ) -> tuple[str | None, str]:
        """Compatibility wrapper for the shared semantic-target matcher."""
        return self._resolve_semantic_call_target(
            call_target,
            qualified_index=qualified_index,
            name_index=name_index,
            position_index=position_index,
        )

    def _write_call_edges(
        self,
        session: neo4j.Session,
        *,
        repo_id: str,
        caller_signature: str,
        callee_signatures: list[str],
        source: str,
        confidence: float,
    ) -> None:
        """Write repo-scoped CALLS edges with provenance metadata."""
        if not callee_signatures:
            return

        session.run(
            """
            MATCH (caller:Function {repo_id: $repo_id, signature: $caller_sig})
            UNWIND $callee_sigs as callee_sig
            MATCH (callee:Function {repo_id: $repo_id, signature: callee_sig})
            MERGE (caller)-[r:CALLS]->(callee)
            SET r.source = $source,
                r.confidence = $confidence,
                r.last_updated = datetime()
            """,
            repo_id=repo_id,
            caller_sig=caller_signature,
            callee_sigs=callee_signatures,
            source=source,
            confidence=confidence,
        )

    def _clear_call_analysis_artifacts(
        self,
        session: neo4j.Session,
        *,
        repo_id: str,
        rel_path: str,
    ) -> None:
        """Delete one file's outgoing CALLS edges and drop diagnostics.

        Pass 4 is an idempotent rebuild step. Re-indexing a file should replace
        both its outgoing `CALLS` edges and any persisted semantic-analysis drop
        reasons from the previous run. Keeping both cleanup operations together
        avoids stale diagnostics that would otherwise make `call-status` look
        worse than the current code actually is.
        """
        session.run(
            """
            MATCH (:File {repo_id: $repo_id, path: $path})-[:DEFINES]->(fn:Function)-[r:CALLS]->()
            DELETE r
            """,
            repo_id=repo_id,
            path=rel_path,
        )
        session.run(
            """
            MATCH (:File {repo_id: $repo_id, path: $path})-[r:CALL_ANALYSIS_DROP]->(:CallDropReason)
            DELETE r
            """,
            repo_id=repo_id,
            path=rel_path,
        )

    def _write_call_drop_reasons(
        self,
        session: neo4j.Session,
        *,
        repo_id: str,
        rel_path: str,
        source: str,
        drop_reasons: dict[str, int],
    ) -> None:
        """Persist per-file semantic-analysis drop reasons for later diagnostics.

        The important operational question after indexing is not just
        "how many `CALLS` edges do we have?" but also "why did semantic targets
        fail to become edges?". We store those reasons on the file node so
        `call-status` can aggregate them without re-running the analyzers.
        """
        if not drop_reasons:
            return

        rows = [
            {"reason": reason, "count": int(count)}
            for reason, count in sorted(drop_reasons.items())
            if count
        ]
        if not rows:
            return

        session.run(
            """
            MATCH (file:File {repo_id: $repo_id, path: $path})
            UNWIND $rows as row
            MERGE (reason:CallDropReason {name: row.reason})
            MERGE (file)-[r:CALL_ANALYSIS_DROP {source: $source}]->(reason)
            SET r.count = row.count,
                r.last_updated = datetime()
            """,
            repo_id=repo_id,
            path=rel_path,
            source=source,
            rows=rows,
        )

    def _record_call_analyzer_issue(
        self,
        session: neo4j.Session,
        *,
        repo_id: str,
        source: str,
        status: str,
        message: str,
    ) -> None:
        """Persist one repo-level analyzer issue for later inspection."""
        session.run(
            """
            MERGE (issue:CallAnalysisIssue {repo_id: $repo_id, source: $source})
            SET issue.status = $status,
                issue.message = $message,
                issue.updated_at = datetime()
            """,
            repo_id=repo_id,
            source=source,
            status=status,
            message=message,
        )

    def _clear_call_analyzer_issue(
        self,
        session: neo4j.Session,
        *,
        repo_id: str,
        source: str,
    ) -> None:
        """Remove any stale repo-level analyzer issue after a healthy run."""
        session.run(
            """
            MATCH (issue:CallAnalysisIssue {repo_id: $repo_id, source: $source})
            DETACH DELETE issue
            """,
            repo_id=repo_id,
            source=source,
        )

    # =========================================================================
    # PASS 4: CALL GRAPH (OPTIMIZED)
    # =========================================================================

    def pass_4_call_graph(self, repo_path: Optional[Path] = None):
        """
        Link functions based on calls.

        The call graph now has three resolution modes:
        - Python when available: basedpyright-backed semantic analysis.
        - JS/TS when available: TypeScript semantic call analysis across the repo.
        - Fallback for any unsupported/unavailable case: conservative parser-only
          same-file linking.

        This keeps Pass 4 safe by preferring exact analyzer-backed targets when
        the local language-service helper can resolve them, while still
        preserving a deterministic static fallback when semantic analysis is
        unavailable.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
        """
        repo_path, repo_id = self._require_repo_context(repo_path)

        logger.info("📞 [Pass 4] Constructing Call Graph...")

        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (f:File {repo_id: $repo_id})-[:DEFINES]->(fn:Function)
                RETURN f.path as path,
                       collect({
                           name: fn.name,
                           sig: fn.signature,
                           qualified_name: fn.qualified_name,
                           parent_class: fn.parent_class,
                           name_line: fn.name_line,
                           name_column: fn.name_column
                       }) as funcs
                """,
                repo_id=repo_id,
            )
            file_records = list(result)
            total_files = len(file_records)
            qualified_index, name_index, position_index = self._build_function_signature_indexes(
                file_records
            )
            parsed_by_path, analyzer_requests = self._prepare_typescript_analysis_requests(
                repo_path=repo_path,
                file_records=file_records,
            )
            python_requests = self._prepare_python_analysis_requests(
                file_records=file_records,
                parsed_by_path=parsed_by_path,
            )
            typescript_results: dict[str, TypeScriptFileCallAnalysis] = {}
            python_results: dict[str, PythonFileCallAnalysis] = {}

            if analyzer_requests:
                analyzer = self._get_typescript_call_analyzer()
                if analyzer.is_available():
                    try:
                        typescript_results = analyzer.analyze_files(
                            repo_root=repo_path,
                            files=analyzer_requests,
                            timeout_seconds=30,
                            batch_size=10,
                            continue_on_batch_failure=True,
                        )
                        analyzer_issues = list(getattr(analyzer, "last_run_issues", []) or [])
                        if analyzer_issues:
                            failed_batches = len(analyzer_issues)
                            total_batches = max(
                                issue.total_batches for issue in analyzer_issues
                            )
                            latest_issue = analyzer_issues[-1]
                            self._record_call_analyzer_issue(
                                session,
                                repo_id=repo_id,
                                source="typescript_service",
                                status="partial_failure",
                                message=(
                                    f"{failed_batches}/{total_batches} TypeScript analyzer batches failed. "
                                    f"Latest: {latest_issue.message}"
                                ),
                            )
                        else:
                            self._clear_call_analyzer_issue(
                                session,
                                repo_id=repo_id,
                                source="typescript_service",
                            )
                    except TypeScriptCallAnalyzerError as exc:
                        logger.warning(
                            "⚠️ TypeScript call analyzer failed; falling back to parser-only CALLS: %s",
                            exc,
                        )
                        self._record_call_analyzer_issue(
                            session,
                            repo_id=repo_id,
                            source="typescript_service",
                            status="failed",
                            message=str(exc),
                        )
                else:
                    logger.info(
                        "TypeScript call analyzer unavailable; using parser-only CALLS. Reason: %s",
                        analyzer.disabled_reason,
                    )
                    self._record_call_analyzer_issue(
                        session,
                        repo_id=repo_id,
                        source="typescript_service",
                        status="unavailable",
                        message=str(analyzer.disabled_reason or "Analyzer unavailable."),
                    )
            else:
                self._clear_call_analyzer_issue(
                    session,
                    repo_id=repo_id,
                    source="typescript_service",
                )

            if python_requests:
                analyzer = self._get_python_call_analyzer()
                if analyzer.is_available():
                    try:
                        python_results = analyzer.analyze_files(
                            repo_root=repo_path,
                            files=python_requests,
                            timeout_seconds=30,
                            batch_size=25,
                            continue_on_batch_failure=True,
                        )
                        analyzer_issues = list(getattr(analyzer, "last_run_issues", []) or [])
                        if analyzer_issues:
                            failed_batches = len(analyzer_issues)
                            total_batches = max(
                                issue.total_batches for issue in analyzer_issues
                            )
                            latest_issue = analyzer_issues[-1]
                            self._record_call_analyzer_issue(
                                session,
                                repo_id=repo_id,
                                source="python_service",
                                status="partial_failure",
                                message=(
                                    f"{failed_batches}/{total_batches} Python analyzer batches failed. "
                                    f"Latest: {latest_issue.message}"
                                ),
                            )
                        else:
                            self._clear_call_analyzer_issue(
                                session,
                                repo_id=repo_id,
                                source="python_service",
                            )
                    except PythonCallAnalyzerError as exc:
                        logger.warning(
                            "⚠️ Python call analyzer failed; falling back to parser-only CALLS: %s",
                            exc,
                        )
                        self._record_call_analyzer_issue(
                            session,
                            repo_id=repo_id,
                            source="python_service",
                            status="failed",
                            message=str(exc),
                        )
                else:
                    logger.info(
                        "Python call analyzer unavailable; using parser-only CALLS. Reason: %s",
                        analyzer.disabled_reason,
                    )
                    self._record_call_analyzer_issue(
                        session,
                        repo_id=repo_id,
                        source="python_service",
                        status="unavailable",
                        message=str(analyzer.disabled_reason or "Analyzer unavailable."),
                    )
            else:
                self._clear_call_analyzer_issue(
                    session,
                    repo_id=repo_id,
                    source="python_service",
                )

            for i, record in enumerate(file_records):
                rel_path = record["path"]
                full_path = repo_path / rel_path

                # Progress logging
                _safe_print(
                    f"[{i+1}/{total_files}] 📞 Processing calls in: {rel_path}...",
                    end="\r",
                )

                if not full_path.exists():
                    continue

                try:
                    parsed = parsed_by_path.get(rel_path)
                    if parsed is None:
                        _, parsed = self._parse_source_file(full_path)
                    function_rows = parsed["functions"]
                    if not function_rows:
                        continue

                    # Clear outgoing calls and drop diagnostics for this file so
                    # Pass 4 remains idempotent across rebuilds.
                    self._clear_call_analysis_artifacts(
                        session,
                        repo_id=repo_id,
                        rel_path=rel_path,
                    )

                    local_candidates: dict[str, list[str]] = {}
                    for function_row in function_rows:
                        function_signature = f"{rel_path}:{function_row['qualified_name']}"
                        local_candidates.setdefault(function_row["name"], []).append(
                            function_signature
                        )

                    typescript_file_result = typescript_results.get(rel_path)
                    python_file_result = python_results.get(rel_path)
                    typescript_drop_reasons: Counter[str] = Counter()
                    python_drop_reasons: Counter[str] = Counter(
                        (python_file_result.drop_reason_counts or {})
                        if python_file_result is not None
                        else {}
                    )
                    for function_row in function_rows:
                        caller_signature = f"{rel_path}:{function_row['qualified_name']}"
                        resolved_calls: list[str] = []
                        call_source = "static_parser"
                        call_confidence = 0.6

                        python_function_result = None
                        typescript_function_result = None
                        if typescript_file_result is not None:
                            typescript_function_result = typescript_file_result.functions.get(
                                function_row["qualified_name"]
                            )
                        if python_file_result is not None:
                            python_function_result = python_file_result.functions.get(
                                function_row["qualified_name"]
                            )

                        if python_function_result is not None:
                            call_source = "python_service"
                            call_confidence = 0.95
                            for call_target in python_function_result.outgoing_calls:
                                candidate_sig, reason = self._resolve_semantic_call_target(
                                    call_target,
                                    qualified_index=qualified_index,
                                    name_index=name_index,
                                    position_index=position_index,
                                )
                                if candidate_sig and candidate_sig != caller_signature:
                                    resolved_calls.append(candidate_sig)
                                elif candidate_sig == caller_signature:
                                    python_drop_reasons["self_edge"] += 1
                                else:
                                    python_drop_reasons[reason] += 1
                        elif typescript_function_result is not None:
                            call_source = "typescript_service"
                            call_confidence = 0.95
                            for call_target in typescript_function_result.outgoing_calls:
                                candidate_sig, reason = self._resolve_typescript_call_target(
                                    call_target,
                                    qualified_index=qualified_index,
                                    name_index=name_index,
                                    position_index=position_index,
                                )
                                if candidate_sig and candidate_sig != caller_signature:
                                    resolved_calls.append(candidate_sig)
                                elif candidate_sig == caller_signature:
                                    typescript_drop_reasons["self_edge"] += 1
                                else:
                                    typescript_drop_reasons[reason] += 1
                        else:
                            if python_file_result is not None:
                                python_drop_reasons["missing_function_analysis"] += 1
                            elif typescript_file_result is not None:
                                typescript_drop_reasons["missing_function_analysis"] += 1
                            for called_name in function_row.get("calls", []):
                                candidate_sigs = local_candidates.get(called_name, [])
                                if (
                                    len(candidate_sigs) == 1
                                    and candidate_sigs[0] != caller_signature
                                ):
                                    resolved_calls.append(candidate_sigs[0])

                        deduped_calls = sorted(set(resolved_calls))
                        if not deduped_calls:
                            continue

                        self._write_call_edges(
                            session,
                            repo_id=repo_id,
                            caller_signature=caller_signature,
                            callee_signatures=deduped_calls,
                            source=call_source,
                            confidence=call_confidence,
                        )

                    self._write_call_drop_reasons(
                        session,
                        repo_id=repo_id,
                        rel_path=rel_path,
                        source="typescript_service",
                        drop_reasons=dict(typescript_drop_reasons),
                    )
                    self._write_call_drop_reasons(
                        session,
                        repo_id=repo_id,
                        rel_path=rel_path,
                        source="python_service",
                        drop_reasons=dict(python_drop_reasons),
                    )

                except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
                    logger.warning(f"⚠️ Failed to process calls in {rel_path}: {e}")

            _safe_print(
                f"\n✅ [Pass 4] Call Graph approximation complete. Processed {total_files} files."
            )

    def reindex_file(
        self,
        rel_path: str,
        *,
        repo_path: Optional[Path] = None,
    ) -> None:
        """Rebuild all derived graph state for one file.

        This is the watcher-safe single-file path used for create/modify events.
        It keeps file structure, imports, and conservative same-file call edges
        in sync without forcing a full repository rebuild.
        """
        repo_path, repo_id = self._require_repo_context(repo_path)
        normalized_path = self._normalize_rel_path(rel_path)
        full_path = repo_path / normalized_path

        if not full_path.exists():
            raise FileNotFoundError(full_path)

        _, parsed = self._parse_source_file(full_path)
        file_hash = self._calculate_ohash(full_path)

        with self.driver.session() as session:
            self._upsert_file_node(
                session,
                repo_id=repo_id,
                rel_path=normalized_path,
                file_name=full_path.name,
                ohash=file_hash,
            )

        # Reuse the multi-pass logic for one changed file. The JIT tracing pivot
        # keeps structural graph rebuilds cheap by stopping at Pass 3; call-path
        # exploration now happens on demand through the trace service instead of
        # forcing every file change to re-run repo-wide CALLS analysis.
        self.pass_2_entity_definition(repo_path, target_paths={normalized_path})
        self.pass_3_imports(repo_path, target_paths={normalized_path})

    def delete_file(
        self,
        rel_path: str,
        *,
        repo_path: Optional[Path] = None,
    ) -> None:
        """Delete one file and its derived graph state from the active repo."""
        _, repo_id = self._require_repo_context(repo_path)
        normalized_path = self._normalize_rel_path(rel_path)
        with self.driver.session() as session:
            self._delete_file_subgraph(session, repo_id, normalized_path)

    # =========================================================================
    # FULL PIPELINE
    # =========================================================================

    def run_pipeline(
        self,
        repo_path: Optional[Path] = None,
        supported_extensions: Optional[Set[str]] = None,
        full_reindex: bool = False,
    ) -> Dict:
        """
        Execute the default code-ingestion pipeline with cost tracking.

        The default pipeline intentionally stops after Pass 3. Repo-wide CALLS
        reconstruction is now an explicit opt-in operation because it is too
        expensive and too repo-fragile to be part of normal indexing or file
        watch flows.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
            supported_extensions: Set of file extensions to process in Pass 1
            full_reindex: When True, clear this repo's existing code graph
                before Pass 1 so every file is reparsed and re-embedded.

        Returns:
            Dict with pipeline execution metrics
        """
        repo_path, _ = self._require_repo_context(repo_path)

        start_time = time.time()
        _safe_print("=" * 60)
        _safe_print("🚀 Starting Hybrid GraphRAG Ingestion")
        _safe_print("=" * 60)

        stage_started = time.time()
        self.setup_database()
        setup_database_seconds = time.time() - stage_started

        full_reindex_seconds = 0.0
        if full_reindex:
            stage_started = time.time()
            self.clear_repo_code_graph(repo_path)
            full_reindex_seconds = time.time() - stage_started

        stage_started = time.time()
        changed_paths = self.pass_1_structure_scan(
            repo_path,
            supported_extensions=supported_extensions,
        )
        pass_1_seconds = time.time() - stage_started

        stage_started = time.time()
        self.pass_2_entity_definition(repo_path, target_paths=changed_paths)
        pass_2_seconds = time.time() - stage_started

        stage_started = time.time()
        self.pass_3_imports(repo_path, target_paths=changed_paths)
        pass_3_seconds = time.time() - stage_started

        elapsed = time.time() - start_time
        changed_file_count = len(changed_paths)

        # Print cost summary
        _safe_print("\n" + "=" * 60)
        _safe_print("📊 COST SUMMARY")
        _safe_print("=" * 60)
        _safe_print(f"⏱️  Total Time: {elapsed:.2f} seconds")
        _safe_print(f"🗂️  Changed Files: {changed_file_count:,}")
        _safe_print(f"🧱 Setup Database: {setup_database_seconds:.2f} seconds")
        if full_reindex:
            _safe_print(f"🧹 Repo Graph Reset: {full_reindex_seconds:.2f} seconds")
        _safe_print(f"📂 Pass 1 Scan: {pass_1_seconds:.2f} seconds")
        _safe_print(f"🧠 Pass 2 Entities/Chunks: {pass_2_seconds:.2f} seconds")
        _safe_print(f"🔗 Pass 3 Imports: {pass_3_seconds:.2f} seconds")
        _safe_print(f"🔢 Embedding API Calls: {self.token_usage['embedding_calls']:,}")
        _safe_print(f"📝 Total Tokens Used: {self.token_usage['embedding_tokens']:,}")
        _safe_print(f"💰 Estimated Cost: ${self.token_usage['total_cost_usd']:.4f} USD")
        _safe_print(f"📦 Model: {self.EMBEDDING_MODEL}")
        _safe_print("=" * 60)
        _safe_print("✅ Graph is ready for Agent retrieval.")
        _safe_print("=" * 60)

        logger.info(
            "Pipeline timing summary | full_reindex=%s changed_files=%s setup=%.2fs reset=%.2fs pass1=%.2fs pass2=%.2fs pass3=%.2fs total=%.2fs",
            full_reindex,
            changed_file_count,
            setup_database_seconds,
            full_reindex_seconds,
            pass_1_seconds,
            pass_2_seconds,
            pass_3_seconds,
            elapsed,
        )

        return {
            "elapsed_seconds": elapsed,
            "full_reindex": full_reindex,
            "changed_files": changed_file_count,
            "setup_database_seconds": setup_database_seconds,
            "full_reindex_seconds": full_reindex_seconds,
            "pass_1_seconds": pass_1_seconds,
            "pass_2_seconds": pass_2_seconds,
            "pass_3_seconds": pass_3_seconds,
            "embedding_calls": self.token_usage["embedding_calls"],
            "tokens_used": self.token_usage["embedding_tokens"],
            "cost_usd": self.token_usage["total_cost_usd"],
        }

    def build_calls(
        self,
        repo_path: Optional[Path] = None,
    ) -> None:
        """Run the experimental repo-wide CALLS build explicitly.

        Normal indexing deliberately skips Pass 4. This wrapper keeps the older
        CALLS pipeline available for diagnostics and experimentation without
        making it part of the default ingestion tax.
        """
        self.pass_4_call_graph(repo_path)

    def resolve_function_symbol(
        self,
        symbol: str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve one user-facing symbol string to a repo-local function node.

        Resolution order is intentionally deterministic:
        1. exact ``path:qualified_name`` signature
        2. unique repo-local ``qualified_name``
        3. unique repo-local short ``name``

        If a lookup remains ambiguous, the method returns candidate functions
        instead of guessing. The JIT trace service depends on that behavior so
        it can avoid inventing paths when the graph cannot pick one symbol safely.
        """

        def _execute_resolution() -> dict[str, Any]:
            resolved_repo_id = repo_id or self.repo_id
            if resolved_repo_id is None:
                raise ValueError("repo_id is required for function symbol resolution")

            normalized_symbol = str(symbol).strip()
            if not normalized_symbol:
                return {
                    "status": "not_found",
                    "match_type": "empty",
                    "input": normalized_symbol,
                    "candidates": [],
                }

            with self.driver.session() as session:
                exact = session.run(
                    """
                    MATCH (fn:Function {repo_id: $repo_id, signature: $signature})
                    RETURN fn.signature as signature,
                           fn.qualified_name as qualified_name,
                           fn.name as name,
                           fn.parent_class as parent_class,
                           fn.path as path
                    """,
                    repo_id=resolved_repo_id,
                    signature=normalized_symbol.replace("\\", "/"),
                ).single()
                if exact:
                    return {
                        "status": "resolved",
                        "match_type": "signature",
                        "input": normalized_symbol,
                        "candidate": dict(exact),
                    }

                qualified_rows = [
                    dict(row)
                    for row in session.run(
                        """
                        MATCH (fn:Function {repo_id: $repo_id, qualified_name: $qualified_name})
                        RETURN fn.signature as signature,
                               fn.qualified_name as qualified_name,
                               fn.name as name,
                               fn.parent_class as parent_class,
                               fn.path as path
                        ORDER BY fn.path ASC, fn.signature ASC
                        """,
                        repo_id=resolved_repo_id,
                        qualified_name=normalized_symbol,
                    )
                ]
                if len(qualified_rows) == 1:
                    return {
                        "status": "resolved",
                        "match_type": "qualified_name",
                        "input": normalized_symbol,
                        "candidate": qualified_rows[0],
                    }
                if len(qualified_rows) > 1:
                    return {
                        "status": "ambiguous",
                        "match_type": "qualified_name",
                        "input": normalized_symbol,
                        "candidates": qualified_rows,
                    }

                name_rows = [
                    dict(row)
                    for row in session.run(
                        """
                        MATCH (fn:Function {repo_id: $repo_id, name: $name})
                        RETURN fn.signature as signature,
                               fn.qualified_name as qualified_name,
                               fn.name as name,
                               fn.parent_class as parent_class,
                               fn.path as path
                        ORDER BY fn.path ASC, fn.signature ASC
                        """,
                        repo_id=resolved_repo_id,
                        name=normalized_symbol,
                    )
                ]
                if len(name_rows) == 1:
                    return {
                        "status": "resolved",
                        "match_type": "name",
                        "input": normalized_symbol,
                        "candidate": name_rows[0],
                    }
                if len(name_rows) > 1:
                    return {
                        "status": "ambiguous",
                        "match_type": "name",
                        "input": normalized_symbol,
                        "candidates": name_rows,
                    }

            return {
                "status": "not_found",
                "match_type": "none",
                "input": normalized_symbol,
                "candidates": [],
            }

        return self.circuit_breaker.call(_execute_resolution)

    def get_function_trace_context(
        self,
        signature: str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the graph context package used by JIT function tracing.

        The trace service needs enough deterministic structure to ground the LLM
        before it reasons about behavioral edges. This method deliberately
        returns:
        - the root function node and source code
        - file-level imports / reverse imports
        - sibling functions and classes in the same file
        - candidate target functions from the same file and directly imported files
        """

        def _execute_context_lookup() -> dict[str, Any] | None:
            resolved_repo_id = repo_id or self.repo_id
            if resolved_repo_id is None:
                raise ValueError("repo_id is required for trace context lookup")

            with self.driver.session() as session:
                root = session.run(
                    """
                    MATCH (fn:Function {repo_id: $repo_id, signature: $signature})
                    MATCH (file:File {repo_id: $repo_id, path: fn.path})
                    OPTIONAL MATCH (file)-[:IMPORTS]->(imported:File {repo_id: $repo_id})
                    OPTIONAL MATCH (dependent:File {repo_id: $repo_id})-[:IMPORTS]->(file)
                    RETURN fn.signature as signature,
                           fn.qualified_name as qualified_name,
                           fn.name as name,
                           fn.parent_class as parent_class,
                           fn.path as path,
                           fn.code as code,
                           file.ohash as file_ohash,
                           collect(DISTINCT imported.path) as imports,
                           collect(DISTINCT dependent.path) as imported_by
                    """,
                    repo_id=resolved_repo_id,
                    signature=signature,
                ).single()
                if not root:
                    return None

                file_path = str(root["path"])
                siblings = [
                    dict(row)
                    for row in session.run(
                        """
                        MATCH (:File {repo_id: $repo_id, path: $path})-[:DEFINES]->(fn:Function {repo_id: $repo_id})
                        RETURN fn.signature as signature,
                               fn.qualified_name as qualified_name,
                               fn.name as name,
                               fn.parent_class as parent_class
                        ORDER BY fn.signature ASC
                        """,
                        repo_id=resolved_repo_id,
                        path=file_path,
                    )
                ]
                classes = [
                    dict(row)
                    for row in session.run(
                        """
                        MATCH (:File {repo_id: $repo_id, path: $path})-[:DEFINES]->(cls:Class {repo_id: $repo_id})
                        RETURN cls.qualified_name as qualified_name,
                               cls.name as name
                        ORDER BY cls.qualified_name ASC
                        """,
                        repo_id=resolved_repo_id,
                        path=file_path,
                    )
                ]
                candidate_paths = {file_path}
                candidate_paths.update(path for path in (root["imports"] or []) if path)
                candidate_functions = [
                    dict(row)
                    for row in session.run(
                        """
                        MATCH (file:File {repo_id: $repo_id})-[:DEFINES]->(fn:Function {repo_id: $repo_id})
                        WHERE file.path IN $paths
                        RETURN file.path as path,
                               fn.signature as signature,
                               fn.qualified_name as qualified_name,
                               fn.name as name,
                               fn.parent_class as parent_class
                        ORDER BY file.path ASC, fn.signature ASC
                        """,
                        repo_id=resolved_repo_id,
                        paths=sorted(candidate_paths),
                    )
                ]

            return {
                "root": dict(root),
                "siblings": siblings,
                "classes": classes,
                "candidate_functions": candidate_functions,
            }

        return self.circuit_breaker.call(_execute_context_lookup)

    def get_cached_jit_trace(
        self,
        root_signature: str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one reusable cached JIT trace when the root file hash still matches."""

        def _execute_cache_lookup() -> dict[str, Any] | None:
            resolved_repo_id = repo_id or self.repo_id
            if resolved_repo_id is None:
                raise ValueError("repo_id is required for JIT trace cache lookup")

            with self.driver.session() as session:
                trace = session.run(
                    """
                    MATCH (trace:CodeTraceRun {repo_id: $repo_id, root_signature: $root_signature, status: 'completed'})
                    MATCH (root:Function {repo_id: $repo_id, signature: $root_signature})
                    MATCH (file:File {repo_id: $repo_id, path: root.path})
                    WHERE trace.root_file_ohash = file.ohash
                    RETURN trace.trace_id as trace_id,
                           trace.root_signature as root_signature,
                           trace.root_file_ohash as root_file_ohash,
                           trace.model as model,
                           trace.max_depth as max_depth,
                           trace.created_at as created_at,
                           trace.unresolved_json as unresolved_json
                    """,
                    repo_id=resolved_repo_id,
                    root_signature=root_signature,
                ).single()
                if not trace:
                    return None

                edges = [
                    dict(row)
                    for row in session.run(
                        """
                        MATCH (caller:Function {repo_id: $repo_id, signature: $root_signature})-[r]->(callee:Function {repo_id: $repo_id})
                        WHERE type(r) IN ['JIT_CALLS_DIRECT', 'JIT_CALLS_CALLBACK', 'JIT_MESSAGE_FLOW']
                          AND r.trace_id = $trace_id
                        RETURN type(r) as relationship_type,
                               caller.signature as caller_signature,
                               callee.signature as callee_signature,
                               callee.qualified_name as callee_qualified_name,
                               callee.name as callee_name,
                               callee.path as callee_path,
                               coalesce(r.edge_type, '') as edge_type,
                               coalesce(r.confidence, 0.0) as confidence,
                               coalesce(r.rationale, '') as rationale,
                               coalesce(r.evidence, '') as evidence
                        ORDER BY callee.signature ASC
                        """,
                        repo_id=resolved_repo_id,
                        root_signature=root_signature,
                        trace_id=trace["trace_id"],
                    )
                ]

            unresolved_json = trace.get("unresolved_json") or "[]"
            try:
                unresolved = json.loads(unresolved_json)
            except json.JSONDecodeError:
                unresolved = []

            payload = dict(trace)
            payload["edges"] = edges
            payload["unresolved"] = unresolved
            return payload

        return self.circuit_breaker.call(_execute_cache_lookup)

    def store_jit_trace_result(
        self,
        *,
        repo_id: str,
        root_signature: str,
        root_file_ohash: str,
        trace_id: str,
        model: str,
        max_depth: int,
        edges: list[dict[str, Any]],
        unresolved: list[dict[str, Any]],
    ) -> None:
        """Persist one per-root JIT trace cache and its derived relationships."""

        def _execute_store() -> None:
            with self.driver.session() as session:
                session.run(
                    """
                    MATCH (trace:CodeTraceRun {repo_id: $repo_id, root_signature: $root_signature})
                    DETACH DELETE trace
                    """,
                    repo_id=repo_id,
                    root_signature=root_signature,
                )
                session.run(
                    """
                    MATCH (caller:Function {repo_id: $repo_id, signature: $root_signature})-[r]->()
                    WHERE type(r) IN ['JIT_CALLS_DIRECT', 'JIT_CALLS_CALLBACK', 'JIT_MESSAGE_FLOW']
                    DELETE r
                    """,
                    repo_id=repo_id,
                    root_signature=root_signature,
                )
                session.run(
                    """
                    CREATE (trace:CodeTraceRun {
                        repo_id: $repo_id,
                        root_signature: $root_signature,
                        trace_id: $trace_id,
                        model: $model,
                        max_depth: $max_depth,
                        status: 'completed',
                        unresolved_json: $unresolved_json,
                        root_file_ohash: $root_file_ohash,
                        created_at: datetime()
                    })
                    """,
                    repo_id=repo_id,
                    root_signature=root_signature,
                    trace_id=trace_id,
                    model=model,
                    max_depth=max_depth,
                    unresolved_json=json.dumps(unresolved),
                    root_file_ohash=root_file_ohash,
                )
                session.run(
                    """
                    MATCH (trace:CodeTraceRun {repo_id: $repo_id, root_signature: $root_signature})
                    MATCH (root:Function {repo_id: $repo_id, signature: $root_signature})
                    MERGE (trace)-[:TRACES_ROOT]->(root)
                    """,
                    repo_id=repo_id,
                    root_signature=root_signature,
                )
                if edges:
                    session.run(
                        """
                        MATCH (caller:Function {repo_id: $repo_id, signature: $root_signature})
                        UNWIND $edges as edge
                        MATCH (callee:Function {repo_id: $repo_id, signature: edge.callee_signature})
                        CALL {
                            WITH caller, callee, edge
                            WITH caller, callee, edge
                            WHERE edge.relationship_type = 'JIT_CALLS_DIRECT'
                            MERGE (caller)-[r:JIT_CALLS_DIRECT]->(callee)
                            SET r.trace_id = edge.trace_id,
                                r.root_signature = edge.root_signature,
                                r.source = edge.source,
                                r.edge_type = edge.edge_type,
                                r.confidence = edge.confidence,
                                r.rationale = edge.rationale,
                                r.evidence = edge.evidence,
                                r.model = edge.model,
                                r.root_file_ohash = edge.root_file_ohash,
                                r.created_at = datetime()
                            RETURN 1 as _
                            UNION
                            WITH caller, callee, edge
                            WHERE edge.relationship_type = 'JIT_CALLS_CALLBACK'
                            MERGE (caller)-[r:JIT_CALLS_CALLBACK]->(callee)
                            SET r.trace_id = edge.trace_id,
                                r.root_signature = edge.root_signature,
                                r.source = edge.source,
                                r.edge_type = edge.edge_type,
                                r.confidence = edge.confidence,
                                r.rationale = edge.rationale,
                                r.evidence = edge.evidence,
                                r.model = edge.model,
                                r.root_file_ohash = edge.root_file_ohash,
                                r.created_at = datetime()
                            RETURN 1 as _
                            UNION
                            WITH caller, callee, edge
                            WHERE edge.relationship_type = 'JIT_MESSAGE_FLOW'
                            MERGE (caller)-[r:JIT_MESSAGE_FLOW]->(callee)
                            SET r.trace_id = edge.trace_id,
                                r.root_signature = edge.root_signature,
                                r.source = edge.source,
                                r.edge_type = edge.edge_type,
                                r.confidence = edge.confidence,
                                r.rationale = edge.rationale,
                                r.evidence = edge.evidence,
                                r.model = edge.model,
                                r.root_file_ohash = edge.root_file_ohash,
                                r.created_at = datetime()
                            RETURN 1 as _
                        }
                        RETURN count(*) as written
                        """,
                        repo_id=repo_id,
                        root_signature=root_signature,
                        edges=[
                            {
                                "callee_signature": edge["callee_signature"],
                                "relationship_type": edge["relationship_type"],
                                "trace_id": trace_id,
                                "root_signature": root_signature,
                                "source": "jit_trace",
                                "edge_type": edge["edge_type"],
                                "confidence": float(edge["confidence"]),
                                "rationale": edge.get("rationale") or "",
                                "evidence": edge.get("evidence") or "",
                                "model": model,
                                "root_file_ohash": root_file_ohash,
                            }
                            for edge in edges
                        ],
                    )

        self.circuit_breaker.call(_execute_store)

    # =========================================================================
    # SEMANTIC SEARCH (for MCP Server)
    # =========================================================================

    def semantic_search(
        self,
        query: str,
        limit: int = 5,
        *,
        repo_id: str | None = None,
    ) -> List[Dict]:
        """
        Hybrid Search for the Agent using vector similarity.

        Args:
            query: Natural language query
            limit: Maximum number of results to return
            repo_id: Optional explicit repository scope. Defaults to the active
                builder repo when available.

        Returns:
            List of dicts with name, signature, score, and text
        """
        def _env_int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None:
                return default
            try:
                return max(1, int(raw))
            except ValueError:
                logger.warning("Invalid integer for %s=%r; using default %s", name, raw, default)
                return default

        def _is_valid_vector(vec: List[float]) -> bool:
            if not vec:
                return False
            norm_sq = 0.0
            for v in vec:
                if not isinstance(v, (int, float)) or not math.isfinite(v):
                    return False
                norm_sq += float(v) * float(v)
            return math.isfinite(norm_sq) and norm_sq > 0.0

        def _lexical_candidate_search(search_limit: int) -> List[Dict]:
            cypher = """
            CALL db.index.fulltext.queryNodes('entity_text_search', $search_query)
            YIELD node, score
            WHERE node.repo_id = $repo_id
            OPTIONAL MATCH (ch:Chunk)-[:DESCRIBES]->(node)
            RETURN
                coalesce(node.name, node.path, 'Unknown') as name,
                coalesce(node.signature, node.qualified_name, '') as sig,
                score,
                coalesce(ch.text, node.docstring, node.path, '') as text,
                node.path as path,
                node.repo_id as repo_id,
                labels(node) as labels
            ORDER BY score DESC
            LIMIT $limit
            """
            with self.driver.session() as session:
                res = session.run(
                    cypher,
                    search_query=query,
                    limit=search_limit,
                    repo_id=resolved_repo_id,
                )
                rows = []
                for rank, record in enumerate(res, start=1):
                    row = dict(record)
                    row["_lexical_rank"] = rank
                    row["_lexical_score"] = float(row.get("score", 0.0) or 0.0)
                    row["_candidate_sources"] = ["lexical"]
                    rows.append(row)
                return rows

        def _vector_candidate_search(vector: List[float], search_limit: int) -> List[Dict]:
            cypher = """
            CALL db.index.vector.queryNodes('code_embeddings', $candidate_limit, $vec)
            YIELD node, score
            WHERE node.repo_id = $repo_id
            MATCH (node)-[:DESCRIBES]->(target)
            WHERE target.repo_id = $repo_id
            RETURN
                target.name as name,
                coalesce(target.signature, target.qualified_name, target.path) as sig,
                score,
                node.text as text,
                target.path as path,
                target.repo_id as repo_id,
                labels(target) as labels
            ORDER BY score DESC
            LIMIT $limit
            """
            with self.driver.session() as session:
                res = session.run(
                    cypher,
                    limit=search_limit,
                    candidate_limit=search_limit,
                    vec=vector,
                    repo_id=resolved_repo_id,
                )
                rows = []
                for rank, record in enumerate(res, start=1):
                    row = dict(record)
                    row["_dense_rank"] = rank
                    row["_dense_score"] = float(row.get("score", 0.0) or 0.0)
                    row["_candidate_sources"] = ["dense"]
                    rows.append(row)
                return rows

        def _merge_candidate_rows(
            dense_rows: List[Dict],
            lexical_rows: List[Dict],
        ) -> List[Dict]:
            rrf_constant = 60.0
            merged: dict[str, Dict] = {}

            def _row_key(row: Dict) -> str:
                return str(row.get("sig") or row.get("path") or row.get("name") or "").strip()

            def _rrf(rank: int | None) -> float:
                if rank is None:
                    return 0.0
                return 1.0 / (rrf_constant + float(rank))

            for row in dense_rows:
                key = _row_key(row)
                if not key:
                    continue
                merged[key] = dict(row)

            for row in lexical_rows:
                key = _row_key(row)
                if not key:
                    continue
                existing = merged.get(key)
                if existing is None:
                    merged[key] = dict(row)
                    continue
                sources = list(existing.get("_candidate_sources") or [])
                if "lexical" not in sources:
                    sources.append("lexical")
                existing["_candidate_sources"] = sources
                existing["_lexical_rank"] = row.get("_lexical_rank")
                existing["_lexical_score"] = row.get("_lexical_score")
                if len(str(existing.get("text") or "")) < len(str(row.get("text") or "")):
                    existing["text"] = row.get("text")

            ranked_rows: list[Dict] = []
            for row in merged.values():
                dense_rank = row.get("_dense_rank")
                lexical_rank = row.get("_lexical_rank")
                dense_rrf = _rrf(int(dense_rank)) if dense_rank is not None else 0.0
                lexical_rrf = _rrf(int(lexical_rank)) if lexical_rank is not None else 0.0
                row["_dense_rrf"] = dense_rrf
                row["_lexical_rrf"] = lexical_rrf
                row["score"] = dense_rrf + lexical_rrf
                ranked_rows.append(row)

            return sorted(
                ranked_rows,
                key=lambda row: (
                    -float(row.get("score", 0.0) or 0.0),
                    -float(row.get("_dense_score", 0.0) or 0.0),
                    -float(row.get("_lexical_score", 0.0) or 0.0),
                    str(row.get("sig") or row.get("path") or ""),
                ),
            )

        def _execute_search():
            if resolved_repo_id is None:
                raise ValueError("repo_id is required for code semantic_search")

            dense_limit = _env_int("AM_CODE_DENSE_TOP_K", max(limit * 8, limit))
            lexical_limit = _env_int("AM_CODE_LEXICAL_TOP_K", max(limit * 4, limit))
            vector = self.get_query_embedding(query)

            dense_rows: List[Dict] = []
            if _is_valid_vector(vector):
                dense_rows = _vector_candidate_search(vector, dense_limit)
            else:
                logger.warning(
                    "Semantic query vector invalid (likely missing code embedding API key or zero-vector); "
                    "dense retrieval skipped, lexical retrieval only."
                )

            lexical_rows = _lexical_candidate_search(lexical_limit)
            merged_rows = _merge_candidate_rows(dense_rows, lexical_rows)
            if not merged_rows and lexical_rows:
                return lexical_rows[:limit]
            return merged_rows[:limit]

        resolved_repo_id = repo_id or self.repo_id
        return self.circuit_breaker.call(_execute_search)

    # =========================================================================
    # DEPENDENCY ANALYSIS (for MCP Server)
    # =========================================================================

    def get_file_dependencies(
        self,
        file_path: str,
        *,
        repo_id: str | None = None,
    ) -> Dict[str, List[str]]:
        """
        Get files that this file imports, and files that import this file.

        Args:
            file_path: Relative path to the file

        Returns:
            Dict with 'imports' and 'imported_by' lists
        """
        cypher = """
        MATCH (f:File {repo_id: $repo_id, path: $path})
        OPTIONAL MATCH (f)-[:IMPORTS]->(imported)
        OPTIONAL MATCH (dependent)-[:IMPORTS]->(f)
        RETURN
            collect(DISTINCT imported.path) as imports,
            collect(DISTINCT dependent.path) as imported_by
        """
        normalized_path = self._normalize_rel_path(file_path)
        resolved_repo_id = repo_id or self.repo_id
        if resolved_repo_id is None:
            raise ValueError("repo_id is required for code dependency lookup")
        with self.driver.session() as session:
            result = session.run(
                cypher,
                repo_id=resolved_repo_id,
                path=normalized_path,
            ).single()
            if result:
                return {
                    "imports": result["imports"] or [],
                    "imported_by": result["imported_by"] or [],
                }
            return {"imports": [], "imported_by": []}

    def identify_impact(
        self,
        file_path: str,
        max_depth: int = 3,
        *,
        repo_id: str | None = None,
    ) -> Dict[str, List[Dict]]:
        """
        Identify the blast radius of changes to a file.
        Returns all files that transitively depend on this file.

        Args:
            file_path: Relative path to the file
            max_depth: Maximum depth to traverse for transitive dependencies

        Returns:
            Dict with 'affected_files' list containing path, depth, and impact_type
        """
        def _execute_impact_analysis():
            depth = max(1, int(max_depth))
            resolved_repo_id = repo_id or self.repo_id
            if resolved_repo_id is None:
                raise ValueError("repo_id is required for impact analysis")
            cypher = f"""
            MATCH path = (f:File {{repo_id: $repo_id, path: $path}})<-[:IMPORTS*1..{depth}]-(dependent:File {{repo_id: $repo_id}})
            RETURN DISTINCT
                dependent.path as path,
                length(path) as depth,
                'dependents' as impact_type
            ORDER BY depth, path
            """
            with self.driver.session() as session:
                result = session.run(
                    cypher,
                    repo_id=resolved_repo_id,
                    path=self._normalize_rel_path(file_path),
                )
                affected_files = [
                    {"path": r["path"], "depth": r["depth"], "impact_type": r["impact_type"]}
                    for r in result
                ]
                return {"affected_files": affected_files, "total_count": len(affected_files)}
        
        return self.circuit_breaker.call(_execute_impact_analysis)

    def get_call_diagnostics(
        self,
        *,
        repo_id: str | None = None,
        high_confidence_threshold: float = 0.9,
    ) -> Dict[str, Any]:
        """Summarize CALLS-edge quality for one repository.

        This is the operational report we use before expanding the traversal graph.
        The point is not just "how many CALLS edges exist", but how many of them
        came from a semantic analyzer versus a fallback parser path, and how much
        of the repo's function surface has any outgoing-call coverage at all.

        Args:
            repo_id: Repository identity to inspect. Defaults to the builder repo.
            high_confidence_threshold: Confidence cutoff used to count traversal-grade
                edges in the summary.

        Returns:
            A diagnostics dictionary with function coverage, file coverage, edge
            source breakdowns, and derived ratios that make quality regressions easy
            to detect in tests or CLI output.
        """

        def _execute_call_diagnostics() -> Dict[str, Any]:
            resolved_repo_id = repo_id or self.repo_id
            if resolved_repo_id is None:
                raise ValueError("repo_id is required for call diagnostics")

            with self.driver.session() as session:
                summary = session.run(
                    """
                    MATCH (:File {repo_id: $repo_id})-[:DEFINES]->(fn:Function)
                    OPTIONAL MATCH (fn)-[r:CALLS]->()
                    RETURN count(DISTINCT fn) as total_functions,
                           count(DISTINCT CASE WHEN r IS NOT NULL THEN fn END) as functions_with_calls,
                           count(r) as total_call_edges,
                           sum(
                               CASE
                                   WHEN coalesce(r.confidence, 0.0) >= $high_confidence_threshold
                                   THEN 1
                                   ELSE 0
                               END
                           ) as high_confidence_edges
                    """,
                    repo_id=resolved_repo_id,
                    high_confidence_threshold=high_confidence_threshold,
                ).single()

                analyzer_sources = ["python_service", "typescript_service"]
                file_coverage = session.run(
                    """
                    MATCH (file:File {repo_id: $repo_id})-[:DEFINES]->(fn:Function)
                    RETURN count(DISTINCT file) as files_with_functions,
                           count(
                               DISTINCT CASE
                                   WHEN EXISTS {
                                       MATCH (file)-[:DEFINES]->(:Function)-[:CALLS]->()
                                   }
                                   THEN file
                               END
                           ) as files_with_call_edges,
                           count(
                               DISTINCT CASE
                                   WHEN EXISTS {
                                       MATCH (file)-[:DEFINES]->(:Function)-[r:CALLS]->()
                                       WHERE coalesce(r.source, "unknown") IN $analyzer_sources
                                   }
                                   THEN file
                               END
                           ) as files_with_analyzer_edges,
                           count(
                               DISTINCT CASE
                                   WHEN EXISTS {
                                       MATCH (file)-[:DEFINES]->(:Function)-[r:CALLS]->()
                                       WHERE coalesce(r.source, "unknown") IN $analyzer_sources
                                   }
                                   OR EXISTS {
                                       MATCH (file)-[:CALL_ANALYSIS_DROP]->(:CallDropReason)
                                   }
                                   THEN file
                               END
                           ) as files_with_analyzer_attempts,
                           count(
                               DISTINCT CASE
                                   WHEN EXISTS {
                                       MATCH (file)-[:CALL_ANALYSIS_DROP]->(:CallDropReason)
                                   }
                                   THEN file
                               END
                           ) as files_with_drop_reasons
                    """,
                    repo_id=resolved_repo_id,
                    analyzer_sources=analyzer_sources,
                ).single()

                source_rows = session.run(
                    """
                    MATCH (:File {repo_id: $repo_id})-[:DEFINES]->(:Function)-[r:CALLS]->()
                    RETURN coalesce(r.source, "unknown") as source,
                           count(r) as edge_count,
                           avg(coalesce(r.confidence, 0.0)) as avg_confidence
                    ORDER BY edge_count DESC, source ASC
                    """,
                    repo_id=resolved_repo_id,
                )

                sources = [
                    {
                        "source": record["source"],
                        "edge_count": int(record["edge_count"] or 0),
                        "avg_confidence": float(record["avg_confidence"] or 0.0),
                    }
                    for record in source_rows
                ]

                drop_reason_rows = session.run(
                    """
                    MATCH (:File {repo_id: $repo_id})-[r:CALL_ANALYSIS_DROP]->(reason:CallDropReason)
                    RETURN reason.name as reason,
                           coalesce(r.source, "unknown") as source,
                           sum(coalesce(r.count, 0)) as drop_count
                    ORDER BY drop_count DESC, source ASC, reason ASC
                    """,
                    repo_id=resolved_repo_id,
                )

                drop_reasons = [
                    {
                        "reason": record["reason"],
                        "source": record["source"],
                        "drop_count": int(record["drop_count"] or 0),
                    }
                    for record in drop_reason_rows
                ]

                analyzer_issue_rows = session.run(
                    """
                    MATCH (issue:CallAnalysisIssue {repo_id: $repo_id})
                    RETURN issue.source as source,
                           issue.status as status,
                           issue.message as message,
                           toString(issue.updated_at) as updated_at
                    ORDER BY issue.source ASC
                    """,
                    repo_id=resolved_repo_id,
                )

                analyzer_issues = [
                    {
                        "source": record["source"],
                        "status": record["status"],
                        "message": record["message"],
                        "updated_at": record["updated_at"],
                    }
                    for record in analyzer_issue_rows
                ]

            total_functions = int(summary["total_functions"] or 0)
            functions_with_calls = int(summary["functions_with_calls"] or 0)
            total_call_edges = int(summary["total_call_edges"] or 0)
            high_confidence_edges = int(summary["high_confidence_edges"] or 0)
            files_with_functions = int(file_coverage["files_with_functions"] or 0)
            files_with_call_edges = int(file_coverage["files_with_call_edges"] or 0)
            files_with_analyzer_edges = int(file_coverage["files_with_analyzer_edges"] or 0)
            files_with_analyzer_attempts = int(file_coverage["files_with_analyzer_attempts"] or 0)
            files_with_drop_reasons = int(file_coverage["files_with_drop_reasons"] or 0)

            functions_without_calls = max(total_functions - functions_with_calls, 0)
            function_coverage_ratio = (
                functions_with_calls / total_functions if total_functions else 0.0
            )
            high_confidence_ratio = (
                high_confidence_edges / total_call_edges if total_call_edges else 0.0
            )
            file_coverage_ratio = (
                files_with_call_edges / files_with_functions if files_with_functions else 0.0
            )

            return {
                "repo_id": resolved_repo_id,
                "high_confidence_threshold": float(high_confidence_threshold),
                "total_functions": total_functions,
                "functions_with_calls": functions_with_calls,
                "functions_without_calls": functions_without_calls,
                "function_coverage_ratio": function_coverage_ratio,
                "total_call_edges": total_call_edges,
                "high_confidence_edges": high_confidence_edges,
                "high_confidence_ratio": high_confidence_ratio,
                "files_with_functions": files_with_functions,
                "files_with_call_edges": files_with_call_edges,
                "files_with_analyzer_edges": files_with_analyzer_edges,
                "files_with_analyzer_attempts": files_with_analyzer_attempts,
                "files_with_drop_reasons": files_with_drop_reasons,
                "file_coverage_ratio": file_coverage_ratio,
                "sources": sources,
                "drop_reasons": drop_reasons,
                "analyzer_issues": analyzer_issues,
            }

        return self.circuit_breaker.call(_execute_call_diagnostics)

    # =========================================================================
    # AGENT-AUTHORED MEMORY GRAPH QUERIES (for MCP Server)
    # =========================================================================

    def _with_repo(self, **kwargs: Any) -> Dict[str, Any]:
        """Return Cypher parameters with the active repo_id attached when set."""
        params = dict(kwargs)
        if self.repo_id is not None:
            params.setdefault("repo_id", self.repo_id)
        return params

    @staticmethod
    def _serialize_memory_observations(observations: List[str]) -> str:
        """Join observations for search-friendly storage."""
        return "\n".join(
            obs.strip() for obs in observations if isinstance(obs, str) and obs.strip()
        )

    @staticmethod
    def _normalize_memory_label(value: str) -> str:
        """Normalize a user-provided memory type into a safe Neo4j label."""
        cleaned = re.sub(r"[^0-9A-Za-z_]", "_", str(value or "").strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if not cleaned:
            return "concept"
        if cleaned[0].isdigit():
            cleaned = f"Type_{cleaned}"
        return cleaned

    @staticmethod
    def _normalize_memory_relation_type(value: str) -> str:
        """Normalize a relation type into a safe Neo4j relationship type."""
        cleaned = re.sub(r"[^0-9A-Za-z_]", "_", str(value or "").strip().upper())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if not cleaned:
            raise ValueError("Relation type cannot be empty.")
        if cleaned[0].isdigit():
            cleaned = f"REL_{cleaned}"
        return cleaned

    @staticmethod
    def _build_memory_embedding_text(
        name: str, entity_type: str, observations: List[str]
    ) -> str:
        """Build the canonical text used for memory embeddings."""
        lines = [f"Name: {name}", f"Type: {entity_type}"]
        if observations:
            lines.append("Observations:")
            lines.extend(f"- {observation}" for observation in observations)
        return "\n".join(lines)

    def _get_memory_embedding_or_none(self, text: str) -> Optional[List[float]]:
        """Return an embedding for memory-entity text when a provider is configured."""
        if self.embedding_service is None:
            return None
        return self.get_embedding(text)

    @staticmethod
    def _normalize_memory_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize one memory-entity payload."""
        if not isinstance(entity, dict):
            raise ValueError("Each entity must be an object.")

        name = str(entity.get("name", "")).strip()
        if not name:
            raise ValueError("Each entity requires a non-empty 'name'.")

        entity_type = str(
            entity.get("entityType") or entity.get("entity_type") or "concept"
        ).strip()
        observations = entity.get("observations") or []
        if not isinstance(observations, list):
            raise ValueError(f"Entity '{name}' observations must be a list of strings.")

        normalized_observations: List[str] = []
        for observation in observations:
            text = str(observation).strip()
            if text:
                normalized_observations.append(text)

        metadata = entity.get("metadata") or {}
        if metadata and not isinstance(metadata, dict):
            raise ValueError(f"Entity '{name}' metadata must be an object.")

        return {
            "name": name,
            "entity_type": entity_type or "concept",
            "entity_label": KnowledgeGraphBuilder._normalize_memory_label(entity_type or "concept"),
            "observations": normalized_observations,
            "observation_text": KnowledgeGraphBuilder._serialize_memory_observations(
                normalized_observations
            ),
            "embedding_text": KnowledgeGraphBuilder._build_memory_embedding_text(
                name, entity_type or "concept", normalized_observations
            ),
            "metadata_json": json.dumps(metadata, sort_keys=True) if metadata else "{}",
        }

    @staticmethod
    def _normalize_memory_relation(relation: Dict[str, Any]) -> Dict[str, str]:
        """Validate and normalize one memory-relation payload."""
        if not isinstance(relation, dict):
            raise ValueError("Each relation must be an object.")

        source = str(
            relation.get("from")
            or relation.get("from_entity")
            or relation.get("source")
            or ""
        ).strip()
        target = str(
            relation.get("to")
            or relation.get("to_entity")
            or relation.get("target")
            or ""
        ).strip()
        relation_type = str(
            relation.get("relationType")
            or relation.get("relation_type")
            or relation.get("type")
            or ""
        ).strip()

        if not source or not target or not relation_type:
            raise ValueError("Each relation requires 'from', 'to', and 'relationType'.")

        return {
            "from": source,
            "to": target,
            "relation_type": KnowledgeGraphBuilder._normalize_memory_relation_type(
                relation_type
            ),
        }

    @staticmethod
    def _normalize_memory_observation_update(item: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize one observation update payload."""
        if not isinstance(item, dict):
            raise ValueError("Each observation update must be an object.")

        entity_name = str(
            item.get("entityName") or item.get("entity_name") or item.get("name") or ""
        ).strip()
        if not entity_name:
            raise ValueError("Each observation update requires 'entityName'.")

        contents = item.get("contents") or item.get("observations") or item.get("content") or []
        if isinstance(contents, str):
            contents = [contents]
        if not isinstance(contents, list):
            raise ValueError(
                f"Observation update for '{entity_name}' must provide a list of strings."
            )

        normalized_contents = [str(content).strip() for content in contents if str(content).strip()]
        if not normalized_contents:
            raise ValueError(
                f"Observation update for '{entity_name}' must include at least one string."
            )

        return {"entity_name": entity_name, "contents": normalized_contents}

    def create_memory_entities(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create or update agent-authored memory entities for the active repo."""
        normalized_entities = [self._normalize_memory_entity(entity) for entity in entities]
        if not normalized_entities:
            raise ValueError("At least one entity is required.")
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory entity creation.")

        self.setup_memory_schema()

        def _execute_create() -> Dict[str, Any]:
            entity_names: List[str] = []
            with self.driver.session() as session:
                for entity in normalized_entities:
                    embedding = self._get_memory_embedding_or_none(entity["embedding_text"])
                    params = self._with_repo(**entity)
                    session.run(
                        f"""
                        MERGE (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $name}})
                        ON CREATE SET
                            m.type = $entity_type,
                            m.entity_type = $entity_type,
                            m.observations = $observations,
                            m.observation_text = $observation_text,
                            m.metadata_json = $metadata_json,
                            m.created_at = datetime(),
                            m.updated_at = datetime()
                        ON MATCH SET
                            m.type = $entity_type,
                            m.entity_type = $entity_type,
                            m.observations = CASE
                                WHEN size($observations) = 0 THEN coalesce(m.observations, [])
                                ELSE $observations
                            END,
                            m.observation_text = CASE
                                WHEN size($observations) = 0 THEN coalesce(m.observation_text, '')
                                ELSE $observation_text
                            END,
                            m.metadata_json = $metadata_json,
                            m.updated_at = datetime()
                        """,
                        **params,
                    )
                    if embedding is not None:
                        session.run(
                            f"""
                            MATCH (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $name}})
                            SET m.embedding = $embedding
                            """,
                            **self._with_repo(name=entity["name"], embedding=embedding),
                        )
                    session.run(
                        f"""
                        MATCH (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $name}})
                        SET m:`{entity['entity_label']}`
                        """,
                        **self._with_repo(name=entity["name"]),
                    )
                    entity_names.append(entity["name"])

            return {"count": len(entity_names), "entity_names": entity_names}

        return self.circuit_breaker.call(_execute_create)

    def delete_memory_entities(self, names: List[str]) -> Dict[str, Any]:
        """Delete memory entities by name for the active repo."""
        normalized_names = [str(name).strip() for name in names if str(name).strip()]
        if not normalized_names:
            raise ValueError("At least one entity name is required.")
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory entity deletion.")

        def _execute_delete() -> Dict[str, Any]:
            with self.driver.session() as session:
                result = session.run(
                    f"""
                    MATCH (m:{self.MEMORY_ENTITY_LABEL})
                    WHERE m.repo_id = $repo_id AND m.name IN $names
                    WITH collect(m.name) as matched_names, collect(m) as matched_nodes
                    FOREACH (node IN matched_nodes | DETACH DELETE node)
                    RETURN matched_names as matched_names
                    """,
                    **self._with_repo(names=normalized_names),
                ).single()

            deleted_names = result["matched_names"] if result and result["matched_names"] else []
            missing_names = [name for name in normalized_names if name not in deleted_names]
            return {
                "count": len(deleted_names),
                "deleted_names": deleted_names,
                "missing_names": missing_names,
            }

        return self.circuit_breaker.call(_execute_delete)

    def create_memory_relations(self, relations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create typed relations between memory entities in the active repo."""
        normalized_relations = [self._normalize_memory_relation(relation) for relation in relations]
        if not normalized_relations:
            raise ValueError("At least one relation is required.")
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory relation creation.")

        self.setup_memory_schema()

        def _execute_create_relations() -> Dict[str, Any]:
            created: List[Dict[str, Any]] = []
            missing: List[Dict[str, str]] = []
            with self.driver.session() as session:
                for relation in normalized_relations:
                    result = session.run(
                        f"""
                        MATCH (source:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $source}})
                        MATCH (target:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $target}})
                        MERGE (source)-[r:`{relation['relation_type']}`]->(target)
                        ON CREATE SET r.created_at = datetime()
                        ON MATCH SET r.updated_at = datetime()
                        RETURN source.name as source, target.name as target, type(r) as relation_type
                        """,
                        **self._with_repo(source=relation["from"], target=relation["to"]),
                    ).single()

                    if result:
                        created.append(dict(result))
                    else:
                        missing.append(relation)

            return {"count": len(created), "relations": created, "missing": missing}

        return self.circuit_breaker.call(_execute_create_relations)

    def delete_memory_relations(self, relations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Delete typed relations between memory entities in the active repo."""
        normalized_relations = [self._normalize_memory_relation(relation) for relation in relations]
        if not normalized_relations:
            raise ValueError("At least one relation is required.")
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory relation deletion.")

        def _execute_delete_relations() -> Dict[str, Any]:
            deleted: List[Dict[str, str]] = []
            missing: List[Dict[str, str]] = []
            with self.driver.session() as session:
                for relation in normalized_relations:
                    result = session.run(
                        f"""
                        MATCH (source:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $source}})
                        MATCH (target:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $target}})
                        OPTIONAL MATCH (source)-[r:`{relation['relation_type']}`]->(target)
                        WITH source, target, r
                        FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END | DELETE r)
                        RETURN source.name as source, target.name as target, '{relation['relation_type']}' as relation_type, r IS NOT NULL as deleted
                        """,
                        **self._with_repo(source=relation["from"], target=relation["to"]),
                    ).single()

                    if result and result["deleted"]:
                        deleted.append(
                            {
                                "from": result["source"],
                                "to": result["target"],
                                "relation_type": result["relation_type"],
                            }
                        )
                    else:
                        missing.append(relation)

            return {"count": len(deleted), "relations": deleted, "missing": missing}

        return self.circuit_breaker.call(_execute_delete_relations)

    def add_memory_observations(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Append observations to existing memory entities in the active repo."""
        normalized_items = [self._normalize_memory_observation_update(item) for item in items]
        if not normalized_items:
            raise ValueError("At least one observation update is required.")
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory observation updates.")

        self.setup_memory_schema()

        def _execute_add_observations() -> Dict[str, Any]:
            updated: List[Dict[str, Any]] = []
            missing: List[str] = []
            with self.driver.session() as session:
                for item in normalized_items:
                    result = session.run(
                        f"""
                        MATCH (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $name}})
                        WITH m, [obs IN $contents WHERE NOT obs IN coalesce(m.observations, [])] as new_obs
                        SET m.observations = coalesce(m.observations, []) + new_obs,
                            m.observation_text = reduce(acc = '', obs IN (coalesce(m.observations, []) + new_obs) |
                                CASE WHEN acc = '' THEN obs ELSE acc + '\n' + obs END),
                            m.updated_at = datetime()
                        RETURN m.name as name, coalesce(m.type, m.entity_type, 'concept') as entity_type, size(new_obs) as added_count, m.observations as observations
                        """,
                        **self._with_repo(name=item["entity_name"], contents=item["contents"]),
                    ).single()

                    if result:
                        row = dict(result)
                        embedding = self._get_memory_embedding_or_none(
                            self._build_memory_embedding_text(
                                row["name"], row["entity_type"], row["observations"] or []
                            )
                        )
                        if embedding is not None:
                            session.run(
                                f"""
                                MATCH (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $name}})
                                SET m.embedding = $embedding
                                """,
                                **self._with_repo(name=row["name"], embedding=embedding),
                            )
                        updated.append(row)
                    else:
                        missing.append(item["entity_name"])

            return {"count": len(updated), "entities": updated, "missing_names": missing}

        return self.circuit_breaker.call(_execute_add_observations)

    def delete_memory_observations(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Delete observations from memory entities in the active repo."""
        normalized_items = [self._normalize_memory_observation_update(item) for item in items]
        if not normalized_items:
            raise ValueError("At least one observation delete request is required.")
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory observation deletion.")

        def _execute_delete_observations() -> Dict[str, Any]:
            updated: List[Dict[str, Any]] = []
            missing: List[str] = []
            with self.driver.session() as session:
                for item in normalized_items:
                    result = session.run(
                        f"""
                        MATCH (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $name}})
                        WITH m, [obs IN coalesce(m.observations, []) WHERE NOT obs IN $contents] as kept
                        SET m.observations = kept,
                            m.observation_text = reduce(acc = '', obs IN kept |
                                CASE WHEN acc = '' THEN obs ELSE acc + '\n' + obs END),
                            m.updated_at = datetime()
                        RETURN m.name as name, coalesce(m.type, m.entity_type, 'concept') as entity_type, size(kept) as remaining_count, m.observations as observations
                        """,
                        **self._with_repo(name=item["entity_name"], contents=item["contents"]),
                    ).single()

                    if result:
                        row = dict(result)
                        embedding = self._get_memory_embedding_or_none(
                            self._build_memory_embedding_text(
                                row["name"], row["entity_type"], row["observations"] or []
                            )
                        )
                        if embedding is not None:
                            session.run(
                                f"""
                                MATCH (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $name}})
                                SET m.embedding = $embedding
                                """,
                                **self._with_repo(name=row["name"], embedding=embedding),
                            )
                        updated.append(row)
                    else:
                        missing.append(item["entity_name"])

            return {"count": len(updated), "entities": updated, "missing_names": missing}

        return self.circuit_breaker.call(_execute_delete_observations)

    def backfill_memory_embeddings(
        self, limit: int = 100, only_missing: bool = True
    ) -> Dict[str, Any]:
        """Backfill embeddings for existing memory entities in the active repo."""
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory embedding backfill.")
        self.setup_memory_schema()
        safe_limit = max(1, int(limit))
        if self.embedding_service is None:
            raise ValueError(
                "An embedding provider is required to backfill memory embeddings."
            )

        def _execute_backfill() -> Dict[str, Any]:
            with self.driver.session() as session:
                filter_parts = ["m.repo_id = $repo_id"]
                if only_missing:
                    filter_parts.append("m.embedding IS NULL")
                filter_clause = f"WHERE {' AND '.join(filter_parts)}"
                rows = list(
                    session.run(
                        f"""
                        MATCH (m:{self.MEMORY_ENTITY_LABEL})
                        {filter_clause}
                        RETURN m.name as name,
                               coalesce(m.type, m.entity_type, 'concept') as entity_type,
                               coalesce(m.observations, []) as observations
                        ORDER BY m.name
                        LIMIT $limit
                        """,
                        **self._with_repo(limit=safe_limit),
                    )
                )

                updated_names: List[str] = []
                for row in rows:
                    payload = dict(row)
                    embedding = self.get_embedding(
                        self._build_memory_embedding_text(
                            payload["name"],
                            payload["entity_type"],
                            payload["observations"] or [],
                        )
                    )
                    session.run(
                        f"""
                        MATCH (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id, name: $name}})
                        SET m.embedding = $embedding,
                            m.updated_at = datetime()
                        """,
                        **self._with_repo(name=payload["name"], embedding=embedding),
                    )
                    updated_names.append(payload["name"])

                remaining_result = session.run(
                    f"""
                    MATCH (m:{self.MEMORY_ENTITY_LABEL})
                    WHERE m.repo_id = $repo_id AND m.embedding IS NULL
                    RETURN count(m) as remaining
                    """,
                    **self._with_repo(),
                ).single()

            return {
                "count": len(updated_names),
                "entity_names": updated_names,
                "remaining_without_embeddings": (
                    remaining_result["remaining"] if remaining_result else 0
                ),
            }

        return self.circuit_breaker.call(_execute_backfill)

    def search_memory_nodes(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search agent-authored memory entities for the active repo."""
        normalized_query = str(query).strip()
        safe_limit = max(1, int(limit))
        if not normalized_query:
            return []
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory search.")

        self.setup_memory_schema()

        def _execute_search() -> List[Dict[str, Any]]:
            with self.driver.session() as session:
                if self.embedding_service is None:
                    result = session.run(
                        f"""
                        CALL db.index.fulltext.queryNodes('{self.MEMORY_FULLTEXT_INDEX}', $query_text)
                        YIELD node, score
                        WHERE node.repo_id = $repo_id
                        OPTIONAL MATCH (node:{self.MEMORY_ENTITY_LABEL})-[r_out]->(target:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id}})
                        OPTIONAL MATCH (source:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id}})-[r_in]->(node:{self.MEMORY_ENTITY_LABEL})
                        RETURN
                            node.name as name,
                            coalesce(node.type, node.entity_type, 'concept') as entity_type,
                            coalesce(node.observations, []) as observations,
                            coalesce(node.metadata_json, '{{}}') as metadata_json,
                            score,
                            ['fulltext'] as sources,
                            collect(DISTINCT CASE
                                WHEN target IS NULL THEN NULL
                                ELSE {{target: target.name, relation_type: type(r_out)}}
                            END) as outgoing_relations,
                            collect(DISTINCT CASE
                                WHEN source IS NULL THEN NULL
                                ELSE {{source: source.name, relation_type: type(r_in)}}
                            END) as incoming_relations
                        ORDER BY score DESC
                        LIMIT $limit
                        """,
                        **self._with_repo(query_text=normalized_query, limit=safe_limit),
                    )
                else:
                    vector = self.get_embedding(normalized_query)
                    result = session.run(
                        f"""
                        CALL {{
                            CALL db.index.vector.queryNodes('{self.MEMORY_VECTOR_INDEX}', $limit, $vector)
                            YIELD node, score
                            RETURN node, score, 'vector' as source
                            UNION
                            CALL db.index.fulltext.queryNodes('{self.MEMORY_FULLTEXT_INDEX}', $query_text)
                            YIELD node, score
                            RETURN node, score, 'fulltext' as source
                        }}
                        WITH node, max(score) as score, collect(DISTINCT source) as sources
                        WHERE node.repo_id = $repo_id
                        OPTIONAL MATCH (node:{self.MEMORY_ENTITY_LABEL})-[r_out]->(target:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id}})
                        OPTIONAL MATCH (source:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id}})-[r_in]->(node:{self.MEMORY_ENTITY_LABEL})
                        RETURN
                            node.name as name,
                            coalesce(node.type, node.entity_type, 'concept') as entity_type,
                            coalesce(node.observations, []) as observations,
                            coalesce(node.metadata_json, '{{}}') as metadata_json,
                            score,
                            sources,
                            collect(DISTINCT CASE
                                WHEN target IS NULL THEN NULL
                                ELSE {{target: target.name, relation_type: type(r_out)}}
                            END) as outgoing_relations,
                            collect(DISTINCT CASE
                                WHEN source IS NULL THEN NULL
                                ELSE {{source: source.name, relation_type: type(r_in)}}
                            END) as incoming_relations
                        ORDER BY score DESC
                        LIMIT $limit
                        """,
                        **self._with_repo(
                            query_text=normalized_query,
                            vector=vector,
                            limit=safe_limit,
                        ),
                    )

                rows: List[Dict[str, Any]] = []
                for record in result:
                    row = dict(record)
                    row["outgoing_relations"] = [
                        rel for rel in row.get("outgoing_relations", []) if rel
                    ]
                    row["incoming_relations"] = [
                        rel for rel in row.get("incoming_relations", []) if rel
                    ]
                    rows.append(row)
                return rows

        return self.circuit_breaker.call(_execute_search)

    def read_memory_graph(self) -> Dict[str, Any]:
        """Return a summarized view of the current repo-scoped memory graph."""
        if self.repo_id is None:
            raise ValueError("repo_id is required for memory graph reads.")
        self.setup_memory_schema()

        def _execute_read() -> Dict[str, Any]:
            with self.driver.session() as session:
                nodes_result = session.run(
                    f"""
                    MATCH (m:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id}})
                    OPTIONAL MATCH (m)-[r]->(target:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id}})
                    RETURN
                        m.name as name,
                        coalesce(m.type, m.entity_type, 'concept') as entity_type,
                        coalesce(m.observations, []) as observations,
                        collect(DISTINCT CASE
                            WHEN target IS NULL THEN NULL
                            ELSE {{
                                target: target.name,
                                relation_type: type(r)
                            }}
                        END) as outgoing_relations
                    ORDER BY m.name
                    """,
                    **self._with_repo(),
                )
                entities: List[Dict[str, Any]] = []
                for record in nodes_result:
                    row = dict(record)
                    row["outgoing_relations"] = [
                        rel for rel in row.get("outgoing_relations", []) if rel
                    ]
                    entities.append(row)

                relation_count_result = session.run(
                    f"""
                    MATCH (source:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id}})-[r]->(target:{self.MEMORY_ENTITY_LABEL} {{repo_id: $repo_id}})
                    RETURN count(r) as count
                    """,
                    **self._with_repo(),
                ).single()
                relation_count = relation_count_result["count"] if relation_count_result else 0

            return {
                "entity_count": len(entities),
                "relation_count": relation_count,
                "entities": entities,
            }

        return self.circuit_breaker.call(_execute_read)

    # =========================================================================
    # GIT GRAPH QUERIES (for MCP Server)
    # =========================================================================

    def has_git_graph_data(self) -> bool:
        """Return True if at least one GitCommit node exists."""
        def _execute_check() -> bool:
            cypher = "MATCH (c:GitCommit) RETURN count(c) > 0 as has_data"
            with self.driver.session() as session:
                result = session.run(cypher).single()
                return bool(result["has_data"]) if result else False

        return self.circuit_breaker.call(_execute_check)

    def get_git_file_history(
        self,
        file_path: str,
        limit: int = 20,
        *,
        repo_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Return commit history touching a specific file.

        Args:
            file_path: Relative repository file path
            limit: Maximum number of commits to return

        Returns:
            List of commit metadata records sorted by commit time descending
        """
        def _execute_history_query() -> List[Dict[str, Any]]:
            safe_limit = max(1, int(limit))
            resolved_repo_id = repo_id or self.repo_id
            if resolved_repo_id is None:
                raise ValueError("repo_id is required for git file history lookup")
            cypher = """
            MATCH (c:GitCommit {repo_id: $repo_id})-[:TOUCHES]->(fv:GitFileVersion {repo_id: $repo_id, path: $path})
            OPTIONAL MATCH (c)-[:AUTHORED_BY]->(a:GitAuthor)
            RETURN
                c.sha as sha,
                c.committed_at as committed_at,
                c.message_subject as message_subject,
                c.message_body as message_body,
                a.name_latest as author_name,
                a.email_norm as author_email,
                fv.change_type as change_type,
                coalesce(fv.additions, 0) as additions,
                coalesce(fv.deletions, 0) as deletions
            ORDER BY c.committed_at DESC
            LIMIT $limit
            """
            with self.driver.session() as session:
                result = session.run(
                    cypher,
                    repo_id=resolved_repo_id,
                    path=self._normalize_rel_path(file_path),
                    limit=safe_limit,
                )
                return [dict(record) for record in result]

        return self.circuit_breaker.call(_execute_history_query)

    def get_commit_context(
        self, sha: str, include_diff_stats: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Return detailed metadata for a commit.

        Args:
            sha: Commit SHA
            include_diff_stats: Whether to include changed file and line-change data

        Returns:
            Dict with commit metadata and optional diff stats, or None if missing
        """
        def _execute_commit_context_query() -> Optional[Dict[str, Any]]:
            commit_cypher = """
            MATCH (c:GitCommit {sha: $sha})
            OPTIONAL MATCH (c)-[:AUTHORED_BY]->(a:GitAuthor)
            OPTIONAL MATCH (c)-[:PARENT]->(p:GitCommit)
            OPTIONAL MATCH (c)-[:PART_OF_PR]->(pr:GitPullRequest)
            OPTIONAL MATCH (c)-[:REFERENCES_ISSUE]->(issue:GitIssue)
            RETURN
                c.sha as sha,
                c.repo_id as repo_id,
                c.authored_at as authored_at,
                c.committed_at as committed_at,
                c.message_subject as message_subject,
                c.message_body as message_body,
                coalesce(c.parent_count, 0) as parent_count,
                coalesce(c.is_merge, false) as is_merge,
                a.name_latest as author_name,
                a.email_norm as author_email,
                collect(DISTINCT p.sha) as parent_shas,
                collect(DISTINCT CASE
                    WHEN pr IS NULL THEN NULL
                    ELSE {
                        number: pr.number,
                        title: pr.title,
                        state: pr.state,
                        url: pr.url
                    }
                END) as pull_requests,
                collect(DISTINCT CASE
                    WHEN issue IS NULL THEN NULL
                    ELSE {
                        number: issue.number,
                        title: issue.title,
                        state: issue.state,
                        url: issue.url
                    }
                END) as issues
            """

            with self.driver.session() as session:
                commit_result = session.run(commit_cypher, sha=sha).single()
                if not commit_result:
                    return None

                context: Dict[str, Any] = dict(commit_result)
                context["parent_shas"] = [
                    parent_sha for parent_sha in (context.get("parent_shas") or []) if parent_sha
                ]
                context["pull_requests"] = [
                    pr for pr in (context.get("pull_requests") or []) if pr is not None
                ]
                context["issues"] = [
                    issue for issue in (context.get("issues") or []) if issue is not None
                ]

                if not include_diff_stats:
                    context["files"] = []
                    context["stats"] = {"files_changed": 0, "additions": 0, "deletions": 0}
                    return context

                files_cypher = """
                MATCH (c:GitCommit {sha: $sha})-[:TOUCHES]->(fv:GitFileVersion)
                RETURN
                    fv.path as path,
                    fv.change_type as change_type,
                    coalesce(fv.additions, 0) as additions,
                    coalesce(fv.deletions, 0) as deletions
                ORDER BY fv.path
                """
                files_result = session.run(files_cypher, sha=sha)
                files = [dict(record) for record in files_result]
                additions = sum(int(file_info.get("additions", 0) or 0) for file_info in files)
                deletions = sum(int(file_info.get("deletions", 0) or 0) for file_info in files)

                context["files"] = files
                context["stats"] = {
                    "files_changed": len(files),
                    "additions": additions,
                    "deletions": deletions,
                }
                return context

        return self.circuit_breaker.call(_execute_commit_context_query)
