"""
Knowledge Graph Builder for Agentic Memory.

Ported from legacy 4_pass_ingestion_with_prep_hybridgraphRAG.py
This module orchestrates the creation of a hybrid GraphRAG system in Neo4j.
"""

import os
import hashlib
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from functools import wraps

import openai
import neo4j
from openai import OpenAI
from tree_sitter import Language, Parser, Query, QueryCursor

# Import language bindings
import tree_sitter_python
import tree_sitter_javascript

logger = logging.getLogger(__name__)


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
    """
    Decorator to retry OpenAI API calls on transient errors.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Delay between retries in seconds (with exponential backoff)
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


class KnowledgeGraphBuilder:
    """
    Orchestrates the creation of the Hybrid GraphRAG system.

    Attributes:
        driver (neo4j.Driver): Database connection.
        openai_client (OpenAI): Embedding client.
        parsers (Dict): Tree-sitter parsers for supported languages.
        repo_root (Path): Root path of the repository being indexed.
        token_usage (Dict): Tracks OpenAI API token usage and costs.
    """

    # OpenAI Pricing (as of Dec 2024)
    EMBEDDING_MODEL = "text-embedding-3-large"
    COST_PER_1M_TOKENS = 0.13  # USD
    VECTOR_DIMENSIONS = 3072

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        openai_key: str,
        repo_root: Optional[Path] = None,
        ignore_dirs: Optional[Set[str]] = None,
        ignore_files: Optional[Set[str]] = None,
    ):
        """
        Initialize the KnowledgeGraphBuilder.

        Args:
            uri: Neo4j connection URI (e.g., "bolt://localhost:7687")
            user: Neo4j username
            password: Neo4j password
            openai_key: OpenAI API key for embeddings
            repo_root: Root path of repository to index (optional, can be set per-method)
            ignore_dirs: Set of directory names to ignore during indexing
            ignore_files: Set of file patterns to ignore during indexing
        """
        # Configure connection pool for better performance
        self.driver = neo4j.GraphDatabase.driver(
            uri, 
            auth=(user, password),
            max_connection_pool_size=50,
            connection_acquisition_timeout=60,
            connection_timeout=30,
            max_transaction_retry_time=30.0,
        )
        
        # Circuit breaker for Neo4j connection failures
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        self.openai_client = OpenAI(api_key=openai_key)
        self.parsers = self._init_parsers()
        self.repo_root = repo_root
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

    def _init_parsers(self) -> Dict[str, Parser]:
        """Initializes Tree-sitter parsers for Python and JS/TS."""
        parsers = {}

        # Python
        py_lang = Language(tree_sitter_python.language())
        parsers[".py"] = Parser(py_lang)

        # JavaScript/TypeScript
        js_lang = Language(tree_sitter_javascript.language())
        js_parser = Parser(js_lang)
        for ext in [".js", ".jsx", ".ts", ".tsx"]:
            parsers[ext] = js_parser

        return parsers

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
            # 1. Uniqueness Constraints (Critical for Merge performance)
            "CREATE CONSTRAINT file_path_unique IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
            "CREATE CONSTRAINT function_sig_unique IF NOT EXISTS FOR (f:Function) REQUIRE f.signature IS UNIQUE",
            "CREATE CONSTRAINT class_name_unique IF NOT EXISTS FOR (c:Class) REQUIRE c.qualified_name IS UNIQUE",
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
    def get_embedding(self, text: str) -> List[float]:
        """
        Generates embedding using OpenAI text-embedding-3-large with token tracking and truncation.

        Args:
            text: The text to embed

        Returns:
            List of floats representing the embedding vector
        """
        # Truncate text to avoid OpenAI 400 Bad Request (Limit is 8192 tokens)
        # Using 24000 chars as safety margin for most code files.
        MAX_CHARS = 24000

        if len(text) > MAX_CHARS:
            logger.warning(
                f"⚠️ Truncating text chunk of size {len(text)} to {MAX_CHARS} chars."
            )
            text = text[:MAX_CHARS] + "...[TRUNCATED]"

        text = text.replace("\n", " ")

        try:
            response = self.openai_client.embeddings.create(
                input=[text], model=self.EMBEDDING_MODEL
            )

            # Track token usage
            tokens_used = response.usage.total_tokens
            self.token_usage["embedding_tokens"] += tokens_used
            self.token_usage["embedding_calls"] += 1
            self.token_usage["total_cost_usd"] = (
                self.token_usage["embedding_tokens"] / 1_000_000
            ) * self.COST_PER_1M_TOKENS

            return response.data[0].embedding
        except (openai.APIError, openai.RateLimitError, openai.APIConnectionError) as e:
            logger.error(f"❌ OpenAI Embedding Error: {e}")
            # Return zero-vector on failure to allow pipeline to continue
            return [0.0] * self.VECTOR_DIMENSIONS

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
        repo_path = repo_path or self.repo_root
        if not repo_path:
            raise ValueError("repo_path must be provided either in __init__ or as parameter")

        supported_extensions = supported_extensions or {".py", ".js", ".ts", ".tsx", ".jsx"}

        logger.info("📂 [Pass 1] Scanning Directory Structure...")

        count = 0
        with self.driver.session() as session:
            for root, dirs, files in os.walk(repo_path):
                # Filter directories
                dirs[:] = [d for d in dirs if d not in self.ignore_dirs]

                for file_name in files:
                    if file_name in self.ignore_files:
                        continue
                    file_path = Path(root) / file_name
                    if file_path.suffix not in supported_extensions:
                        continue

                    rel_path = str(file_path.relative_to(repo_path))
                    current_ohash = self._calculate_ohash(file_path)

                    # Check if file exists and hash matches (Change Detection)
                    result = session.run(
                        "MATCH (f:File {path: $path}) RETURN f.ohash as hash", path=rel_path
                    ).single()

                    if result and result["hash"] == current_ohash:
                        # Skip processing, but mark as visited if needed
                        continue

                    # Create/Update File Node
                    session.run(
                        """
                        MERGE (f:File {path: $path})
                        SET f.name = $name,
                            f.ohash = $ohash,
                            f.last_updated = datetime()
                    """,
                        path=rel_path,
                        name=file_name,
                        ohash=current_ohash,
                    )
                    count += 1

        logger.info(f"✅ [Pass 1] Processed {count} new/modified files.")

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
        repo_path = repo_path or self.repo_root
        if not repo_path:
            raise ValueError("repo_path must be provided either in __init__ or as parameter")

        logger.info("🧠 [Pass 2] Extracting Entities & Creating Chunks...")

        with self.driver.session() as session:
            # Fetch all files that need indexing
            result = session.run("MATCH (f:File) RETURN f.path as path")
            files_to_process = [record["path"] for record in result]

            for i, rel_path in enumerate(files_to_process):
                print(f"[{i+1}/{len(files_to_process)}] 🧠 Processing: {rel_path}...", end="\r")

                full_path = repo_path / rel_path
                if not full_path.exists():
                    continue

                code_content = full_path.read_text(errors="ignore")
                extension = full_path.suffix
                parser = self.parsers.get(extension)
                if not parser:
                    continue

                tree = parser.parse(bytes(code_content, "utf8"))

                # Language-specific query to find definitions
                if extension == ".py":
                    query_scm = """
                    (class_definition
                        name: (identifier) @name
                        body: (block) @body) @class
                    (function_definition
                        name: (identifier) @name
                        body: (block) @body) @function
                    """
                else:  # Simple JS/TS fallback
                    query_scm = """
                    (class_declaration name: (identifier) @name) @class
                    (function_declaration name: (identifier) @name) @function
                    """

                # Use updated querycursor for executing queries
                lang = (
                    Language(tree_sitter_python.language())
                    if extension == ".py"
                    else Language(tree_sitter_javascript.language())
                )

                query = Query(lang, query_scm)
                cursor = QueryCursor(query)
                captures = cursor.captures(tree.root_node)

                # Process captures
                for tag, nodes in captures.items():
                    for node in nodes:
                        node_text = code_content[node.start_byte:node.end_byte]
                        name = ""

                        # Try to extract name from identifier child
                        for child in node.children:
                            if child.type == "identifier":
                                name = code_content[child.start_byte:child.end_byte]
                                break

                        if not name:
                            continue

                        signature = f"{rel_path}:{name}"

                        if tag == "class":
                            # 1. Create Class Node
                            session.run(
                                """
                                MATCH (f:File {path: $path})
                                MERGE (c:Class {qualified_name: $sig})
                                SET c.name = $name, c.code = $code
                                MERGE (f)-[:DEFINES]->(c)
                            """,
                                path=rel_path,
                                sig=signature,
                                name=name,
                                code=node_text,
                            )

                            # 2. Hybrid Chunking: Class Context
                            # Skip if chunk already exists (avoid re-embedding)
                            existing = session.run(
                                """
                                MATCH (c:Class {qualified_name: $sig})
                                OPTIONAL MATCH (ch:Chunk)-[:DESCRIBES]->(c)
                                RETURN ch.id as chunk_id LIMIT 1
                            """,
                                sig=signature,
                            ).single()

                            if not existing or not existing["chunk_id"]:
                                # Prepend context to the vector
                                enriched_text = f"Context: File {rel_path} > Class {name}\n\n{node_text}"
                                embedding = self.get_embedding(enriched_text)

                                session.run(
                                    """
                                    MATCH (c:Class {qualified_name: $sig})
                                    CREATE (ch:Chunk {id: randomUUID()})
                                    SET ch.text = $text,
                                        ch.embedding = $embedding,
                                        ch.created_at = datetime()
                                    MERGE (ch)-[:DESCRIBES]->(c)
                                """,
                                    sig=signature,
                                    text=node_text,
                                    embedding=embedding,
                                )

                        elif tag == "function":
                            # Check parent for Class context
                            parent_class = ""
                            current = node.parent
                            while current:
                                if current.type == "class_definition":
                                    for child in current.children:
                                        if child.type == "identifier":
                                            parent_class = code_content[
                                                child.start_byte:child.end_byte
                                            ]
                                            break
                                current = current.parent

                            qual_name = f"{parent_class}.{name}" if parent_class else name
                            full_sig = f"{rel_path}:{qual_name}"

                            # 1. Create Function Node
                            session.run(
                                """
                                MATCH (f:File {path: $path})
                                MERGE (fn:Function {signature: $sig})
                                SET fn.name = $name, fn.code = $code
                                MERGE (f)-[:DEFINES]->(fn)
                            """,
                                path=rel_path,
                                sig=full_sig,
                                name=name,
                                code=node_text,
                            )

                            # Link to parent class if exists
                            if parent_class:
                                class_sig = f"{rel_path}:{parent_class}"
                                session.run(
                                    """
                                    MATCH (c:Class {qualified_name: $csig})
                                    MATCH (fn:Function {signature: $fsig})
                                    MERGE (c)-[:HAS_METHOD]->(fn)
                                """,
                                    csig=class_sig,
                                    fsig=full_sig,
                                )

                            # 2. Hybrid Chunking: Function Context
                            # Skip if chunk already exists (avoid re-embedding)
                            existing = session.run(
                                """
                                MATCH (fn:Function {signature: $sig})
                                OPTIONAL MATCH (ch:Chunk)-[:DESCRIBES]->(fn)
                                RETURN ch.id as chunk_id LIMIT 1
                            """,
                                sig=full_sig,
                            ).single()

                            if not existing or not existing["chunk_id"]:
                                # The secret sauce: "Contextual Prefixing"
                                context_prefix = f"File: {rel_path}"
                                if parent_class:
                                    context_prefix += f" > Class: {parent_class}"

                                enriched_text = (
                                    f"Context: {context_prefix} > Method: {name}\n\n{node_text}"
                                )
                                embedding = self.get_embedding(enriched_text)

                                session.run(
                                    """
                                    MATCH (fn:Function {signature: $sig})
                                    CREATE (ch:Chunk {id: randomUUID()})
                                    SET ch.text = $text,
                                        ch.embedding = $embedding,
                                        ch.created_at = datetime()
                                    MERGE (ch)-[:DESCRIBES]->(fn)
                                """,
                                    sig=full_sig,
                                    text=node_text,
                                    embedding=embedding,
                                )

        logger.info("✅ [Pass 2] Entities and Semantic Chunks created.")

    # =========================================================================
    # PASS 3: IMPORT RESOLUTION
    # =========================================================================

    def pass_3_imports(self, repo_path: Optional[Path] = None):
        """
        Analyzes import statements to link File nodes.
        Simplified for Python: Looks for 'import x' or 'from x import y'.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
        """
        repo_path = repo_path or self.repo_root
        if not repo_path:
            raise ValueError("repo_path must be provided either in __init__ or as parameter")

        logger.info("🕸️ [Pass 3] Linking Files via Imports...")

        query_scm = """
        (import_statement name: (dotted_name) @module)
        (import_from_statement module_name: (dotted_name) @module)
        """

        with self.driver.session() as session:
            result = session.run("MATCH (f:File) RETURN f.path as path")
            files = [r["path"] for r in result if r["path"].endswith(".py")]

            for rel_path in files:
                full_path = repo_path / rel_path

                if not full_path.exists():
                    logger.warning(
                        f"⚠️ File found in graph but missing on disk (Stale): {rel_path}. Deleting node."
                    )
                    session.run("MATCH (f:File {path: $path}) DETACH DELETE f", path=rel_path)
                    continue

                code = full_path.read_text(errors="ignore")
                tree = self.parsers[".py"].parse(bytes(code, "utf8"))

                # Initialize QueryCursor with the query object
                lang = Language(tree_sitter_python.language())
                query = Query(lang, query_scm)
                cursor = QueryCursor(query)
                captures = cursor.captures(tree.root_node)

                for tag, nodes in captures.items():
                    for node in nodes:
                        module_name = code[node.start_byte:node.end_byte]
                        # Simple heuristic: convert 'command_service.app' -> 'command_service/app.py'
                        potential_path_part = module_name.replace(".", "/")

                        # Create fuzzy link
                        session.run(
                            """
                            MATCH (source:File {path: $src})
                            MATCH (target:File)
                            WHERE target.path CONTAINS $mod_part
                            MERGE (source)-[:IMPORTS]->(target)
                        """,
                            src=rel_path,
                            mod_part=potential_path_part,
                        )

            logger.info("✅ [Pass 3] Import graph built.")

    # =========================================================================
    # PASS 4: CALL GRAPH (OPTIMIZED)
    # =========================================================================

    def pass_4_call_graph(self, repo_path: Optional[Path] = None):
        """
        Links functions based on calls.
        Optimized to parse each file once, then process all functions within it.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)
        """
        repo_path = repo_path or self.repo_root
        if not repo_path:
            raise ValueError("repo_path must be provided either in __init__ or as parameter")

        logger.info("📞 [Pass 4] Constructing Call Graph...")

        query_scm = """(call function: (identifier) @name)"""

        with self.driver.session() as session:
            # Get all function definitions ordered by file
            result = session.run(
                """
                MATCH (f:File)-[:DEFINES]->(fn:Function)
                RETURN f.path as path, collect({name: fn.name, sig: fn.signature}) as funcs
            """
            )
            file_records = list(result)
            total_files = len(file_records)

            for i, record in enumerate(file_records):
                rel_path = record["path"]
                funcs_in_file = record["funcs"]
                full_path = repo_path / rel_path

                # Progress logging
                print(f"[{i+1}/{total_files}] 📞 Processing calls in: {rel_path}...", end="\r")

                if not full_path.exists():
                    continue

                try:
                    code = full_path.read_text(errors="ignore")
                    tree = self.parsers[".py"].parse(bytes(code, "utf8"))

                    lang = Language(tree_sitter_python.language())
                    query = Query(lang, query_scm)
                    cursor = QueryCursor(query)
                    captures = cursor.captures(tree.root_node)

                    # Extract all calls in the file once
                    calls_in_file = []
                    for tag, nodes in captures.items():
                        for node in nodes:
                            called_name = code[node.start_byte:node.end_byte]
                            calls_in_file.append(called_name)

                    if not calls_in_file:
                        continue

                    # Batch the creation of relationships for performance
                    for func in funcs_in_file:
                        caller_sig = func["sig"]

                        # Create relationships for found calls
                        session.run(
                            """
                            UNWIND $calls as called_name
                            MATCH (caller:Function {signature: $caller_sig})
                            MATCH (callee:Function {name: called_name})
                            WHERE caller <> callee
                            MERGE (caller)-[:CALLS]->(callee)
                        """,
                            caller_sig=caller_sig,
                            calls=calls_in_file,
                        )

                except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
                    logger.warning(f"⚠️ Failed to process calls in {rel_path}: {e}")

            print(f"\n✅ [Pass 4] Call Graph approximation complete. Processed {total_files} files.")

    # =========================================================================
    # FULL PIPELINE
    # =========================================================================

    def run_pipeline(self, repo_path: Optional[Path] = None) -> Dict:
        """
        Executes the full 4-pass pipeline with cost tracking.

        Args:
            repo_path: Path to repository root (defaults to self.repo_root)

        Returns:
            Dict with pipeline execution metrics
        """
        repo_path = repo_path or self.repo_root
        if not repo_path:
            raise ValueError("repo_path must be provided either in __init__ or as parameter")

        start_time = time.time()
        print("=" * 60)
        print("🚀 Starting Hybrid GraphRAG Ingestion")
        print("=" * 60)

        self.setup_database()
        self.pass_1_structure_scan(repo_path)
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

    def semantic_search(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Hybrid Search for the Agent using vector similarity.

        Args:
            query: Natural language query
            limit: Maximum number of results to return

        Returns:
            List of dicts with name, signature, score, and text
        """
        def _execute_search():
            vector = self.get_embedding(query)
            cypher = """
            CALL db.index.vector.queryNodes('code_embeddings', $limit, $vec)
            YIELD node, score
            MATCH (node)-[:DESCRIBES]->(target)
            RETURN target.name as name, target.signature as sig, score, node.text as text
            ORDER BY score DESC
            """
            with self.driver.session() as session:
                res = session.run(cypher, limit=limit, vec=vector)
                return [dict(r) for r in res]
        
        return self.circuit_breaker.call(_execute_search)

    # =========================================================================
    # DEPENDENCY ANALYSIS (for MCP Server)
    # =========================================================================

    def get_file_dependencies(self, file_path: str) -> Dict[str, List[str]]:
        """
        Get files that this file imports, and files that import this file.

        Args:
            file_path: Relative path to the file

        Returns:
            Dict with 'imports' and 'imported_by' lists
        """
        cypher = """
        MATCH (f:File {path: $path})
        OPTIONAL MATCH (f)-[:IMPORTS]->(imported)
        OPTIONAL MATCH (dependent)-[:IMPORTS]->(f)
        RETURN
            collect(DISTINCT imported.path) as imports,
            collect(DISTINCT dependent.path) as imported_by
        """
        with self.driver.session() as session:
            result = session.run(cypher, path=file_path).single()
            if result:
                return {
                    "imports": result["imports"] or [],
                    "imported_by": result["imported_by"] or [],
                }
            return {"imports": [], "imported_by": []}

    def identify_impact(
        self, file_path: str, max_depth: int = 3
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
            cypher = f"""
            MATCH path = (f:File {{path: $path}})<-[:IMPORTS*1..{depth}]-(dependent)
            RETURN DISTINCT
                dependent.path as path,
                length(path) as depth,
                'dependents' as impact_type
            ORDER BY depth, path
            """
            with self.driver.session() as session:
                result = session.run(cypher, path=file_path)
                affected_files = [
                    {"path": r["path"], "depth": r["depth"], "impact_type": r["impact_type"]}
                    for r in result
                ]
                return {"affected_files": affected_files, "total_count": len(affected_files)}
        
        return self.circuit_breaker.call(_execute_impact_analysis)
