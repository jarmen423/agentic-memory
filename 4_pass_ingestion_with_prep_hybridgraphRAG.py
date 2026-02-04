# scripts/4_pass_ingestion_with_prep_hybridgraphRAG.py
"""
m26pipeline Hybrid GraphRAG Builder.

Purpose:
    Constructs a "Digital Twin" of the codebase in Neo4j to power AI coding agents.
    It moves beyond simple vector search by establishing a property graph that models
    syntax, dependencies (Imports/Calls), and semantic meaning (Embeddings).

Architecture:
    - Database: Neo4j (Graph Structure + Vector Index).
    - Parsing: Tree-sitter (Static Analysis for structure).
    - Embeddings: OpenAI (Semantic search).
    - Strategy: 4-Pass Ingestion (Structure -> Definitions -> Imports -> Calls).

Usage:
    1. Configure .env with NEO4J_URI, NEO4J_PASSWORD, OPENAI_API_KEY.
    2. Run: python scripts/4_pass_ingestion_with_prep_hybridgraphRAG.py

Role in Codebase:
    This is the "Day 0" indexer. It should be run as a CI/CD step or manually
    whenever significant architectural changes occur in the repo.
"""

import os
import hashlib
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set, Any

import neo4j
from openai import OpenAI
from dotenv import load_dotenv

# Tree-sitter imports
from tree_sitter import Language, Parser, Query, QueryCursor
import tree_sitter_python
import tree_sitter_javascript

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load Environment Variables
load_dotenv()

# Configuration Constants
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://your-instance.databases.neo4j.io") # <--- REPLACE WITH YOUR ENV VAR FROM .ENV
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j") # <--- REPLACE WITH YOUR ENV VAR FROM .ENV
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD") # <--- REPLACE WITH YOUR ENV VAR FROM .ENV
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # <--- REPLACE WITH YOUR ENV VAR FROM .ENV
REPO_PATH = Path(os.getenv("REPO_PATH", "/home/josh/code/m26pipeline")) # <--- ADJUST TO YOUR LOCAL PATH

# Ignore Patterns - loaded from .graphignore (GraphRAG-specific, not .gitignore)
def load_graphignore_patterns(repo_path: Path) -> tuple:
    """
    Parses .graphignore for GraphRAG-specific exclusions.
    Returns (ignore_dirs, ignore_files) sets for os.walk filtering.
    
    Unlike .gitignore, .graphignore uses simple glob patterns that we convert
    to directory/file names for os.walk compatibility.
    """
    graphignore_path = repo_path / ".graphignore"
    ignore_dirs = set()
    ignore_files = set()
    
    # Always ignore these regardless of graphignore
    ignore_dirs.update({"node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv"})
    
    if not graphignore_path.exists():
        logger.warning("⚠️ No .graphignore file found. Using default exclusions.")
        return ignore_dirs, ignore_files
    
    with open(graphignore_path, "r") as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            
            # Extract directory names from glob patterns like **/dist/** or **/venv/**
            if "**/" in line and "/**" in line:
                # Pattern like **/node_modules/** -> extract "node_modules"
                dir_name = line.replace("**/", "").replace("/**", "").strip("/")
                if dir_name and "/" not in dir_name:
                    ignore_dirs.add(dir_name)
            # File patterns like *.archived.md or *_original.py
            elif line.startswith("*") and "." in line:
                # Can't easily filter by extension in os.walk, but we track the suffix
                ignore_files.add(line.lstrip("*"))
            # Specific file patterns
            elif "." in line and "/" not in line:
                ignore_files.add(line)
    
    logger.info(f"📋 Loaded exclusions from .graphignore: {len(ignore_dirs)} dirs, {len(ignore_files)} file patterns")
    return ignore_dirs, ignore_files

# Load patterns from .graphignore
IGNORE_DIRS, IGNORE_FILES = load_graphignore_patterns(REPO_PATH)
SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".yml", ".yaml"} # Focus on code logic

class KnowledgeGraphBuilder:
    """
    Orchestrates the creation of the Hybrid GraphRAG system.
    
    Attributes:
        driver (neo4j.Driver): Database connection.
        openai_client (OpenAI): Embedding client.
        parsers (Dict): Tree-sitter parsers for supported languages.
        token_usage (Dict): Tracks OpenAI API token usage and costs.
    """
    
    # OpenAI Pricing (as of Dec 2024)
    EMBEDDING_MODEL = "text-embedding-3-large"
    COST_PER_1M_TOKENS = 0.13  # USD

    def __init__(self):
        self.driver = neo4j.GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
        self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
        self.parsers = self._init_parsers()
        self.token_usage = {
            "embedding_tokens": 0,
            "embedding_calls": 0,
            "total_cost_usd": 0.0
        }
        
    def _init_parsers(self) -> Dict[str, Parser]:
        """Initializes Tree-sitter parsers for Python and JS/TS."""
        parsers = {}
        
        # Python
        py_lang = Language(tree_sitter_python.language())
        # in tree-sitter >=0.22.0 , language must be passed to the constructor. 
        # the .set_language() method has been removed from the parser class. 
        py_parser = Parser(py_lang)
        parsers['.py'] = py_parser
        
        # JavaScript/TypeScript (Using JS grammar for simplicity in this example)
        # For full TS support, you would add tree_sitter_typescript
        js_lang = Language(tree_sitter_javascript.language())
        js_parser = Parser(js_lang)
        for ext in ['.js', '.jsx', '.ts', '.tsx']:
            parsers[ext] = js_parser
            
        return parsers

    def close(self):
        """Closes database connection."""
        self.driver.close()

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
            # Indexing the 'embedding' property on 'Chunk' nodes using Cosine Similarity
            """
            CREATE VECTOR INDEX code_embeddings IF NOT EXISTS
            FOR (c:Chunk) ON (c.embedding)
            OPTIONS {indexConfig: {
             `vector.dimensions`: 3072,
             `vector.similarity_function`: 'cosine'
            }}
            """,
            
            # 3. Fulltext Index for Keyword Search (Tools/Agents use this)
            """
            CREATE FULLTEXT INDEX entity_text_search IF NOT EXISTS
            FOR (n:Function|Class|File) ON EACH [n.name, n.docstring, n.path]
            """
        ]
        
        with self.driver.session() as session:
            for q in queries:
                try:
                    session.run(q)
                except Exception as e:
                    logger.warning(f"Constraint/Index check: {e}")
        logger.info("✅ Database configured.")

    def _calculate_ohash(self, file_path: Path) -> str:
        """Calculates MD5 hash of file content for change detection."""
        try:
            return hashlib.md5(file_path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def _get_embedding(self, text: str) -> List[float]:
        """Generates embedding using OpenAI text-embedding-3-large with token tracking and truncation."""
        # 1. Truncate text to avoid OpenAI 400 Bad Request (Limit is 8192 tokens)
        # Using 24000 chars as safety margin for most code files.
        MAX_CHARS = 24000
        
        if len(text) > MAX_CHARS:
            logger.warning(f"⚠️ Truncating text chunk of size {len(text)} to {MAX_CHARS} chars.")
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
        except Exception as e:
            logger.error(f"❌ OpenAI Embedding Error: {e}")
            # Return zero-vector on failure to allow pipeline to continue
            return [0.0] * 3072

    # =========================================================================
    # PASS 1: STRUCTURE SCAN & CHANGE DETECTION
    # =========================================================================
    def pass_1_structure_scan(self):
        """
        Scans the directory structure.
        Creates File nodes if they are new or modified. Skips if oHash matches.
        Also discovers .env files for configuration tracking.
        """
        logger.info("📂 [Pass 1] Scanning Directory Structure...")
        
        count = 0
        env_file_count = 0
        with self.driver.session() as session:
            for root, dirs, files in os.walk(REPO_PATH):
                # Filter directories
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                
                # Process .env files first (for configuration tracking)
                for file_name in files:
                    if file_name.startswith(".env"):
                        env_file_count += self._process_env_file(session, root, file_name)
                
                for file_name in files:
                    if file_name in IGNORE_FILES: continue
                    file_path = Path(root) / file_name
                    if file_path.suffix not in SUPPORTED_EXTENSIONS: continue
                    
                    rel_path = str(file_path.relative_to(REPO_PATH))
                    current_ohash = self._calculate_ohash(file_path)
                    
                    # Check if file exists and hash matches (Change Detection)
                    result = session.run(
                        "MATCH (f:File {path: $path}) RETURN f.ohash as hash",
                        path=rel_path
                    ).single()
                    
                    if result and result["hash"] == current_ohash:
                        # Skip processing, but mark as visited if needed
                        continue
                    
                    # Create/Update File Node
                    session.run("""
                        MERGE (f:File {path: $path})
                        SET f.name = $name,
                            f.ohash = $ohash,
                            f.last_updated = datetime()
                    """, path=rel_path, name=file_name, ohash=current_ohash)
                    count += 1
                    
        logger.info(f"✅ [Pass 1] Processed {count} new/modified files, {env_file_count} env files.")

    def _process_env_file(self, session, root: str, filename: str) -> int:
        """
        Parses .env files to track RELATIONSHIPS only (no secret values).
        Creates EnvFile nodes and links to EnvVar nodes.
        
        Args:
            session: Neo4j session
            root: Directory path
            filename: .env filename
            
        Returns:
            Number of env vars discovered
        """
        full_path = Path(root) / filename
        rel_path = str(full_path.relative_to(REPO_PATH))
        
        try:
            logger.info(f"⚙️  Indexing Env File: {rel_path}")
            # Create EnvFile node
            session.run("MERGE (e:EnvFile {path: $path})", path=rel_path)
            
            var_count = 0
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    
                    key = line.split("=", 1)[0].strip()
                    
                    # Create RELATIONSHIP only - no value storage
                    session.run("""
                        MATCH (f:EnvFile {path: $path})
                        MERGE (v:EnvVar {name: $key})
                        MERGE (f)-[:DEFINES_VAR {line: $line}]->(v)
                    """, path=rel_path, key=key, line=line_num)
                    var_count += 1
            
            return var_count
        except Exception as e:
            logger.warning(f"⚠️ Failed to parse .env file {rel_path}: {e}")
            return 0

    # =========================================================================
    # PASS 2: ENTITY DEFINITION & HYBRID CHUNKING
    # =========================================================================
    def pass_2_entity_definition(self):
        """
        Parses files using Tree-sitter.
        1. Extracts Classes/Functions.
        2. Creates 'Chunk' nodes with "Contextual Prefixing".
        """
        logger.info("🧠 [Pass 2] Extracting Entities & Creating Chunks...")
        
        with self.driver.session() as session:
            # Fetch all files that need indexing (based on timestamp or just scan all for simplicity in this script)
            # In production, you'd filter by "last_updated > last_run"
            result = session.run("MATCH (f:File) RETURN f.path as path")
            files_to_process = [record["path"] for record in result]
            
            for i, rel_path in enumerate(files_to_process):
                # Progress logging every file
                print(f"[{i+1}/{len(files_to_process)}] 🧠 Processing: {rel_path}...", end='\r')
                
                full_path = REPO_PATH / rel_path
                if not full_path.exists(): continue
                
                code_content = full_path.read_text(errors='ignore')
                extension = full_path.suffix
                parser = self.parsers.get(extension)
                if not parser: continue
                
                tree = parser.parse(bytes(code_content, "utf8"))
                
                # Language-specific query to find definitions
                if extension == '.py':
                    query_scm = """
                    (class_definition 
                        name: (identifier) @name
                        body: (block) @body) @class
                    (function_definition 
                        name: (identifier) @name
                        body: (block) @body) @function
                    """
                else: # Simple JS/TS fallback
                    query_scm = """
                    (class_declaration name: (identifier) @name) @class
                    (function_declaration name: (identifier) @name) @function
                    """
                
                # use updated querycursor for executing queries
                lang = Language(tree_sitter_python.language()) if extension == '.py' else \
                    Language(tree_sitter_javascript.language())
                
                query = Query(lang, query_scm)
                cursor = QueryCursor(query)
                captures = cursor.captures(tree.root_node)
                
                # Process captures
                context_stack = [] # Track class context
                
                for tag, nodes in captures.items():
                    for node in nodes:
                        node_text = code_content[node.start_byte:node.end_byte]
                        name = ""
                    
                    # Try to extract name from identifier child
                    for child in node.children:
                        if child.type == 'identifier':
                            name = code_content[child.start_byte:child.end_byte]
                            break
                            
                    if not name: continue
                    
                    signature = f"{rel_path}:{name}"
                    
                    if tag == 'class':
                        # 1. Create Class Node
                        session.run("""
                            MATCH (f:File {path: $path})
                            MERGE (c:Class {qualified_name: $sig})
                            SET c.name = $name, c.code = $code
                            MERGE (f)-[:DEFINES]->(c)
                        """, path=rel_path, sig=signature, name=name, code=node_text)
                        
                        # 2. Hybrid Chunking: Class Context
                        # Skip if chunk already exists (avoid re-embedding)
                        existing = session.run("""
                            MATCH (c:Class {qualified_name: $sig})
                            OPTIONAL MATCH (ch:Chunk)-[:DESCRIBES]->(c)
                            RETURN ch.id as chunk_id LIMIT 1
                        """, sig=signature).single()
                        
                        if not existing or not existing["chunk_id"]:
                            # Prepend context to the vector
                            enriched_text = f"Context: File {rel_path} > Class {name}\n\n{node_text}"
                            embedding = self._get_embedding(enriched_text)
                            
                            session.run("""
                                MATCH (c:Class {qualified_name: $sig})
                                CREATE (ch:Chunk {id: randomUUID()})
                                SET ch.text = $text, 
                                    ch.embedding = $embedding,
                                    ch.created_at = datetime()
                                MERGE (ch)-[:DESCRIBES]->(c)
                            """, sig=signature, text=node_text, embedding=embedding)

                    elif tag == 'function':
                        # Check parent for Class context
                        parent_class = ""
                        current = node.parent
                        while current:
                            if current.type == 'class_definition':
                                for child in current.children:
                                    if child.type == 'identifier':
                                        parent_class = code_content[child.start_byte:child.end_byte]
                                        break
                            current = current.parent
                        
                        qual_name = f"{parent_class}.{name}" if parent_class else name
                        full_sig = f"{rel_path}:{qual_name}"
                        
                        # 1. Create Function Node
                        session.run("""
                            MATCH (f:File {path: $path})
                            MERGE (fn:Function {signature: $sig})
                            SET fn.name = $name, fn.code = $code
                            MERGE (f)-[:DEFINES]->(fn)
                        """, path=rel_path, sig=full_sig, name=name, code=node_text)
                        
                        # Link to parent class if exists
                        if parent_class:
                            class_sig = f"{rel_path}:{parent_class}"
                            session.run("""
                                MATCH (c:Class {qualified_name: $csig})
                                MATCH (fn:Function {signature: $fsig})
                                MERGE (c)-[:HAS_METHOD]->(fn)
                            """, csig=class_sig, fsig=full_sig)

                        # 2. Hybrid Chunking: Function Context
                        # Skip if chunk already exists (avoid re-embedding)
                        existing = session.run("""
                            MATCH (fn:Function {signature: $sig})
                            OPTIONAL MATCH (ch:Chunk)-[:DESCRIBES]->(fn)
                            RETURN ch.id as chunk_id LIMIT 1
                        """, sig=full_sig).single()
                        
                        if not existing or not existing["chunk_id"]:
                            # The secret sauce: "Contextual Prefixing"
                            context_prefix = f"File: {rel_path}"
                            if parent_class:
                                context_prefix += f" > Class: {parent_class}"
                            
                            enriched_text = f"Context: {context_prefix} > Method: {name}\n\n{node_text}"
                            embedding = self._get_embedding(enriched_text)
                            
                            session.run("""
                                MATCH (fn:Function {signature: $sig})
                                CREATE (ch:Chunk {id: randomUUID()})
                                SET ch.text = $text, 
                                    ch.embedding = $embedding,
                                    ch.created_at = datetime()
                                MERGE (ch)-[:DESCRIBES]->(fn)
                            """, sig=full_sig, text=node_text, embedding=embedding)

        # Track Environment Variable Usage
        self._track_env_var_usage()
        
        logger.info("✅ [Pass 2] Entities and Semantic Chunks created.")

    def _track_env_var_usage(self):
        """
        Tracks os.getenv() and load_dotenv() calls in Python files.
        Creates relationships: File -> READS_ENV_VAR -> EnvVar
                             File -> LOADS_ENV_FILE -> EnvFile
        """
        logger.info("🔍 [Pass 2.5] Tracking Env Var Usage...")
        
        with self.driver.session() as session:
            result = session.run("MATCH (f:File) WHERE f.path ENDS WITH '.py' RETURN f.path as path")
            files = [record["path"] for record in result]
            
            load_order_tracker = {}  # Track load_dotenv call order per file
            
            for rel_path in files:
                full_path = REPO_PATH / rel_path
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        code = f.read()
                except Exception:
                    continue

                tree = self.parsers['.py'].parse(bytes(code, "utf8"))
                
                # Query 1: Track os.getenv() and os.environ.get() calls
                env_read_query = """
                (call
                    function: (attribute
                        attribute: (identifier) @method)
                    arguments: (argument_list
                        (string) @var_name))
                """
                
                lang = Language(tree_sitter_python.language())
                query = Query(lang, env_read_query)
                cursor = QueryCursor(query)
                captures = cursor.captures(tree.root_node)
                
                # Process env var reads
                for tag, nodes in captures.items():
                    if tag == "method":
                        for i, node in enumerate(nodes):
                            method_name = code[node.start_byte:node.end_byte]
                            if method_name in ["getenv", "get"]:
                                # Get corresponding var_name capture
                                if tag in captures and i < len(captures.get("var_name", [])):
                                    var_node = captures["var_name"][i]
                                    var_name = code[var_node.start_byte:var_node.end_byte].strip("'\"")
                                    line_num = node.start_point[0] + 1
                                    
                                    session.run("""
                                        MATCH (f:File {path: $path})
                                        MERGE (v:EnvVar {name: $name})
                                        MERGE (f)-[:READS_ENV_VAR {line: $line}]->(v)
                                    """, path=rel_path, name=var_name, line=line_num)
                
                # Query 2: Track load_dotenv() calls
                dotenv_query = """
                (call
                    function: (identifier) @func
                    arguments: (argument_list) @args)
                """
                
                query2 = Query(lang, dotenv_query)
                cursor2 = QueryCursor(query2)
                captures2 = cursor2.captures(tree.root_node)
                
                if rel_path not in load_order_tracker:
                    load_order_tracker[rel_path] = 0
                
                for tag, nodes in captures2.items():
                    if tag == "func":
                        for node in nodes:
                            func_name = code[node.start_byte:node.end_byte]
                            if func_name == "load_dotenv":
                                # Try to extract the path argument
                                # For simplicity, we'll just track that load_dotenv was called
                                line_num = node.start_point[0] + 1
                                load_order_tracker[rel_path] += 1
                                order = load_order_tracker[rel_path]
                                
                                # Check for override parameter in the call
                                parent = node.parent
                                call_text = code[parent.start_byte:parent.end_byte] if parent else ""
                                has_override = "override=True" in call_text or "override = True" in call_text
                                
                                # Create relationship with metadata
                                session.run("""
                                    MATCH (f:File {path: $path})
                                    MERGE (f)-[:CALLS_LOAD_DOTENV {line: $line, order: $order, override: $override}]->(f)
                                """, path=rel_path, line=line_num, order=order, override=has_override)
        
        logger.info("✅ [Pass 2.5] Env var usage tracked.")

    # =========================================================================
    # PASS 3: IMPORT RESOLUTION
    # =========================================================================
    def pass_3_imports(self):
        """
        Analyzes import statements to link File nodes.
        Simplified for Python: Looks for 'import x' or 'from x import y'.
        """
        logger.info("🕸️ [Pass 3] Linking Files via Imports...")
        
        query_scm = """
        (import_statement name: (dotted_name) @module)
        (import_from_statement module_name: (dotted_name) @module)
        """
        
        with self.driver.session() as session:
            result = session.run("MATCH (f:File) RETURN f.path as path")
            files = [r["path"] for r in result if r["path"].endswith(".py")]
            
            for rel_path in files:
                full_path = REPO_PATH / rel_path
                
                if not full_path.exists():
                    logger.warning(f"⚠️ File found in graph but missing on disk (Stale): {rel_path}. Deleting node.")
                    session.run("MATCH (f:File {path: $path}) DETACH DELETE f", path=rel_path)
                    continue

                code = full_path.read_text(errors='ignore')
                tree = self.parsers['.py'].parse(bytes(code, "utf8"))
                
                # Initialize QueryCursor with the query object
                lang = Language(tree_sitter_python.language())
                query = Query(lang, query_scm)
                cursor = QueryCursor(query)
                captures = cursor.captures(tree.root_node)
                
                for tag, nodes in captures.items():
                    for node in nodes:
                        module_name = code[node.start_byte:node.end_byte]
                        # Simple heuristic: convert 'command_service.app' -> 'command_service/app.py'
                        # In a real system, you'd need a robust resolver using sys.path
                        potential_path_part = module_name.replace(".", "/")
                        
                        # Create fuzzy link
                        session.run("""
                            MATCH (source:File {path: $src})
                            MATCH (target:File)
                            WHERE target.path CONTAINS $mod_part
                            MERGE (source)-[:IMPORTS]->(target)
                        """, src=rel_path, mod_part=potential_path_part)
                    
            logger.info("✅ [Pass 3] Import graph built.")

    # =========================================================================
    # PASS 4: CALL GRAPH (OPTIMIZED)
    # =========================================================================
    def pass_4_call_graph(self):
        """
        Links functions based on calls.
        Optimized to parse each file once, then process all functions within it.
        """
        logger.info("📞 [Pass 4] Constructing Call Graph...")
        
        query_scm = """(call function: (identifier) @name)"""
        
        with self.driver.session() as session:
            # Get all function definitions ordered by file
            result = session.run("""
                MATCH (f:File)-[:DEFINES]->(fn:Function) 
                RETURN f.path as path, collect({name: fn.name, sig: fn.signature}) as funcs
            """)
            file_records = list(result)
            total_files = len(file_records)
            
            for i, record in enumerate(file_records):
                rel_path = record["path"]
                funcs_in_file = record["funcs"]
                full_path = REPO_PATH / rel_path
                
                # Progress logging
                print(f"[{i+1}/{total_files}] 📞 Processing calls in: {rel_path}...", end='\r')
                
                if not full_path.exists(): continue
                
                try:
                    code = full_path.read_text(errors='ignore')
                    tree = self.parsers['.py'].parse(bytes(code, "utf8"))
                    
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

                    # Heuristic: Link *every* function in this file to these calls
                    # (This is a simplification; ideally we'd check which function body the call is in)
                    # For RAG, strictly linking A->B isn't as critical as just having the edge exists.
                    # A better approximation: Link the file's functions to the calls found in the file.
                    
                    # Batch the creation of relationships for performance
                    for func in funcs_in_file:
                        caller_sig = func["sig"]
                        
                        # Create relationships for found calls
                        # We use UNWIND to batch the writes per function
                        session.run("""
                            UNWIND $calls as called_name
                            MATCH (caller:Function {signature: $caller_sig})
                            MATCH (callee:Function {name: called_name})
                            WHERE caller <> callee
                            MERGE (caller)-[:CALLS]->(callee)
                        """, caller_sig=caller_sig, calls=calls_in_file)

                except Exception as e:
                    logger.warning(f"⚠️ Failed to process calls in {rel_path}: {e}")

            print(f"\n✅ [Pass 4] Call Graph approximation complete. Processed {total_files} files.")

    def run_pipeline(self):
        """Executes the full 4-pass pipeline with cost tracking."""
        start_time = time.time()
        print("="*60)
        print("🚀 Starting Hybrid GraphRAG Ingestion")
        print("="*60)
        
        self.setup_database()
        self.pass_1_structure_scan()
        self.pass_2_entity_definition()
        self.pass_3_imports()
        self.pass_4_call_graph()
        
        elapsed = time.time() - start_time
        
        # Print cost summary
        print("\n" + "="*60)
        print("📊 COST SUMMARY")
        print("="*60)
        print(f"⏱️  Total Time: {elapsed:.2f} seconds")
        print(f"🔢 Embedding API Calls: {self.token_usage['embedding_calls']:,}")
        print(f"📝 Total Tokens Used: {self.token_usage['embedding_tokens']:,}")
        print(f"💰 Estimated Cost: ${self.token_usage['total_cost_usd']:.4f} USD")
        print(f"📦 Model: {self.EMBEDDING_MODEL}")
        print("="*60)
        print("✅ Graph is ready for Agent retrieval.")
        print("="*60)

if __name__ == "__main__":
    if not OPENAI_API_KEY:
        print("❌ Error: OPENAI_API_KEY not found in environment.")
        exit(1)
        
    builder = KnowledgeGraphBuilder()
    try:
        builder.run_pipeline()
    finally:
        builder.close()