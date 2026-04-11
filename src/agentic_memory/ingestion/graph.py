"""Knowledge Graph Builder for Agentic Memory code memory.

This module is the code-domain ingestion and retrieval engine. It is still the
same multi-pass GraphRAG builder conceptually, but it now resolves its
embedding provider through the shared runtime embedding configuration so code
memory can participate in the same provider strategy as the rest of Agentic
Memory.

That means the builder no longer assumes OpenAI for code embeddings. Instead it
accepts the configured code-module provider (Gemini by default, or OpenAI /
another supported provider when explicitly requested).
"""

import os
import hashlib
import logging
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
    """
    Orchestrates the creation of the Hybrid GraphRAG system.

    Attributes:
        driver (neo4j.Driver): Database connection.
        embedding_runtime (EmbeddingRuntimeConfig): Resolved provider/model settings
            for code embeddings.
        embedding_service (EmbeddingService | None): Provider-dispatching embedder.
            When no API key is available, this remains None and semantic search
            gracefully degrades to full-text fallback.
        embedding_document_task_instruction (str | None): Optional Gemini
            Embedding 2 task instruction for stored code/document vectors.
        embedding_query_task_instruction (str | None): Optional Gemini
            Embedding 2 task instruction for semantic search query vectors.
        parsers (Dict): Tree-sitter parsers for supported languages.
        repo_root (Path): Root path of the repository being indexed.
        token_usage (Dict): Tracks embedding calls and any provider-specific usage
            metadata we can observe at runtime.
    """

    # Class-level defaults remain for callers/tests that introspect these
    # attributes before initialization, but __init__ resolves per-instance
    # values from the repo config / environment.
    EMBEDDING_MODEL = "gemini-embedding-2-preview"
    VECTOR_DIMENSIONS = 3072
    DOMAIN_LABEL = "Code"

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

        # Default ignore patterns
        self.ignore_dirs = ignore_dirs or {
            "node_modules",
            "__pycache__",
            ".git",
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
    ):
        """
        Scans the directory structure.
        Creates File nodes if they are new or modified. Skips if oHash matches.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
            supported_extensions: Set of file extensions to process
        """
        repo_path, repo_id = self._require_repo_context(repo_path)
        supported_extensions = supported_extensions or {".py", ".js", ".ts", ".tsx", ".jsx"}

        logger.info("📂 [Pass 1] Scanning Directory Structure...")

        count = 0
        pruned_count = 0
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

    # =========================================================================
    # PASS 2: ENTITY DEFINITION & HYBRID CHUNKING
    # =========================================================================

    def pass_2_entity_definition(self, repo_path: Optional[Path] = None):
        """
        Parses files using Tree-sitter.
        1. Extracts Classes/Functions.
        2. Creates 'Chunk' nodes with "Contextual Prefixing".

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
        """
        repo_path, repo_id = self._require_repo_context(repo_path)

        logger.info("🧠 [Pass 2] Extracting Entities & Creating Chunks...")

        with self.driver.session() as session:
            # Fetch all files that need indexing
            result = session.run(
                "MATCH (f:File {repo_id: $repo_id}) RETURN f.path as path",
                repo_id=repo_id,
            )
            files_to_process = [record["path"] for record in result]

            for i, rel_path in enumerate(files_to_process):
                print(f"[{i+1}/{len(files_to_process)}] 🧠 Processing: {rel_path}...", end="\r")

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

    def pass_3_imports(self, repo_path: Optional[Path] = None):
        """
        Analyzes import statements to link File nodes.
        Supports Python and JS/TS import patterns.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
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
                        )
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
                        )
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
                print(f"[{i+1}/{total_files}] 📞 Processing calls in: {rel_path}...", end="\r")

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

            print(f"\n✅ [Pass 4] Call Graph approximation complete. Processed {total_files} files.")

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

        # Reuse the multi-pass logic for one file by re-running the passes on the
        # repo. This keeps the watcher behavior aligned with the main pipeline
        # until a dedicated incremental graph-updater is carved out.
        self.pass_2_entity_definition(repo_path)
        self.pass_3_imports(repo_path)
        self.pass_4_call_graph(repo_path)

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
    ) -> Dict:
        """
        Executes the full 4-pass pipeline with cost tracking.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
            supported_extensions: Set of file extensions to process in Pass 1

        Returns:
            Dict with pipeline execution metrics
        """
        repo_path, _ = self._require_repo_context(repo_path)

        start_time = time.time()
        print("=" * 60)
        print("🚀 Starting Hybrid GraphRAG Ingestion")
        print("=" * 60)

        self.setup_database()
        self.pass_1_structure_scan(repo_path, supported_extensions=supported_extensions)
        self.pass_2_entity_definition(repo_path)
        self.pass_3_imports(repo_path)
        self.pass_4_call_graph(repo_path)

        elapsed = time.time() - start_time

        # Print cost summary
        print("\n" + "=" * 60)
        print("📊 COST SUMMARY")
        print("=" * 60)
        print(f"⏱️  Total Time: {elapsed:.2f} seconds")
        print(f"🔢 Embedding API Calls: {self.token_usage['embedding_calls']:,}")
        print(f"📝 Total Tokens Used: {self.token_usage['embedding_tokens']:,}")
        print(f"💰 Estimated Cost: ${self.token_usage['total_cost_usd']:.4f} USD")
        print(f"📦 Model: {self.EMBEDDING_MODEL}")
        print("=" * 60)
        print("✅ Graph is ready for Agent retrieval.")
        print("=" * 60)

        return {
            "elapsed_seconds": elapsed,
            "embedding_calls": self.token_usage["embedding_calls"],
            "tokens_used": self.token_usage["embedding_tokens"],
            "cost_usd": self.token_usage["total_cost_usd"],
        }

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
        def _is_valid_vector(vec: List[float]) -> bool:
            if not vec:
                return False
            norm_sq = 0.0
            for v in vec:
                if not isinstance(v, (int, float)) or not math.isfinite(v):
                    return False
                norm_sq += float(v) * float(v)
            return math.isfinite(norm_sq) and norm_sq > 0.0

        def _fallback_fulltext_search() -> List[Dict]:
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
                    limit=limit,
                    repo_id=resolved_repo_id,
                )
                return [dict(r) for r in res]

        def _execute_search():
            if resolved_repo_id is None:
                raise ValueError("repo_id is required for code semantic_search")

            vector = self.get_query_embedding(query)
            if not _is_valid_vector(vector):
                logger.warning(
                    "Semantic query vector invalid (likely missing code embedding API key or zero-vector); "
                    "falling back to full-text search."
                )
                return _fallback_fulltext_search()

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
                    limit=limit,
                    candidate_limit=max(limit * 8, limit),
                    vec=vector,
                    repo_id=resolved_repo_id,
                )
                return [dict(r) for r in res]

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
