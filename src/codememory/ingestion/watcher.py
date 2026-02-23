"""
File Watcher for Agentic Memory.

Monitors a codebase for file changes and incrementally updates the knowledge graph.
"""

import os
import time
import logging
from pathlib import Path
from typing import Optional, Set

import neo4j
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from codememory.ingestion.graph import KnowledgeGraphBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Observer")


class CodeChangeHandler(FileSystemEventHandler):
    """
    Handles file system change events and updates the knowledge graph.

    On file modification, performs incremental updates:
    1. Updates file node with new hash
    2. Re-parses entities (functions/classes)
    3. Re-creates embeddings
    4. Updates import relationships
    """

    def __init__(self, builder: KnowledgeGraphBuilder, repo_root: Path):
        self.builder = builder
        self.repo_root = repo_root
        self._debounce_cache: dict[str, float] = {}

    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Check file extension
        if path.suffix not in {".py", ".js", ".ts", ".tsx", ".jsx"}:
            return

        # Simple debounce (ignore events within 1 second of last event for this file)
        now = time.time()
        last_time = self._debounce_cache.get(str(path), 0)
        if now - last_time < 1.0:
            return
        self._debounce_cache[str(path)] = now

        try:
            rel_path = str(path.relative_to(self.repo_root))
            logger.info(f"♻️  Change detected: {rel_path}")

            # Delete old entities for this file
            self._delete_file_entities(rel_path)

            # Process the updated file
            self._process_single_file(path, rel_path)

            logger.info(f"✅ Updated graph for: {rel_path}")

        except (OSError, IOError, neo4j.exceptions.DatabaseError) as e:
            logger.error(f"❌ Failed to ingest {path.name}: {e}")

    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix not in {".py", ".js", ".ts", ".tsx", ".jsx"}:
            return

        try:
            rel_path = str(path.relative_to(self.repo_root))
            logger.info(f"➕ New file detected: {rel_path}")

            self._process_single_file(path, rel_path)
            logger.info(f"✅ Indexed new file: {rel_path}")

        except (OSError, IOError, neo4j.exceptions.DatabaseError) as e:
            logger.error(f"❌ Failed to ingest new file {path.name}: {e}")

    def on_deleted(self, event):
        """Handle file deletion events."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix not in {".py", ".js", ".ts", ".tsx", ".jsx"}:
            return

        try:
            rel_path = str(path.relative_to(self.repo_root))
            logger.info(f"🗑️  File deleted: {rel_path}")

            self._delete_file_entities(rel_path)

            # Also delete the file node
            with self.builder.driver.session() as session:
                session.run("MATCH (f:File {path: $path}) DETACH DELETE f", path=rel_path)

            logger.info(f"✅ Removed from graph: {rel_path}")

        except (OSError, neo4j.exceptions.DatabaseError) as e:
            logger.error(f"❌ Failed to delete {path.name} from graph: {e}")

    def _delete_file_entities(self, rel_path: str):
        """
        Delete all entities associated with a file.

        This removes:
        - Function nodes
        - Class nodes
        - Chunk nodes
        - Import relationships (from this file)

        The file node itself is preserved and re-used.
        """
        with self.builder.driver.session() as session:
            # Delete chunks (they have DESCRIBES relationships)
            session.run("""
                MATCH (f:File {path: $path})-[:DEFINES]->(entity)
                OPTIONAL MATCH (chunk)-[:DESCRIBES]->(entity)
                DETACH DELETE chunk
            """, path=rel_path)

            # Delete functions and classes defined in this file
            session.run("""
                MATCH (f:File {path: $path})-[:DEFINES]->(entity)
                DETACH DELETE entity
            """, path=rel_path)

            # Remove import relationships from this file
            session.run("""
                MATCH (f:File {path: $path})-[r:IMPORTS]->()
                DELETE r
            """, path=rel_path)

    def _process_single_file(self, full_path: Path, rel_path: str):
        """
        Process a single file: parse and store in graph.

        This is a simplified version of Pass 2 for single files.
        It does NOT update the call graph (requires full repo scan).
        """
        code_content = full_path.read_text(errors="ignore")
        extension = full_path.suffix
        parser = self.builder.parsers.get(extension)

        if not parser:
            return

        # Calculate new hash
        new_ohash = self.builder._calculate_ohash(full_path)

        with self.builder.driver.session() as session:
            # Update File node
            session.run("""
                MERGE (f:File {path: $path})
                SET f.name = $name,
                    f.ohash = $ohash,
                    f.last_updated = datetime()
            """, path=rel_path, name=full_path.name, ohash=new_ohash)

            # Parse entities
            tree = parser.parse(bytes(code_content, "utf8"))

            # Language-specific query
            if extension == ".py":
                query_scm = """
                (class_definition
                    name: (identifier) @name
                    body: (block) @body) @class
                (function_definition
                    name: (identifier) @name
                    body: (block) @body) @function
                """
            else:
                query_scm = """
                (class_declaration name: (identifier) @name) @class
                (function_declaration name: (identifier) @name) @function
                """

            from tree_sitter import Language, Query, QueryCursor
            import tree_sitter_python
            import tree_sitter_javascript

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

                    for child in node.children:
                        if child.type == "identifier":
                            name = code_content[child.start_byte:child.end_byte]
                            break

                    if not name:
                        continue

                    signature = f"{rel_path}:{name}"

                    if tag == "class":
                        # Create Class Node
                        session.run("""
                            MATCH (f:File {path: $path})
                            MERGE (c:Class {qualified_name: $sig})
                            SET c.name = $name, c.code = $code
                            MERGE (f)-[:DEFINES]->(c)
                        """, path=rel_path, sig=signature, name=name, code=node_text)

                        # Create Chunk with embedding
                        enriched_text = f"Context: File {rel_path} > Class {name}\n\n{node_text}"
                        embedding = self.builder.get_embedding(enriched_text)

                        session.run("""
                            MATCH (c:Class {qualified_name: $sig})
                            CREATE (ch:Chunk {id: randomUUID()})
                            SET ch.text = $text,
                                ch.embedding = $embedding,
                                ch.created_at = datetime()
                            MERGE (ch)-[:DESCRIBES]->(c)
                        """, sig=signature, text=node_text, embedding=embedding)

                    elif tag == "function":
                        # Check for parent class
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

                        # Create Function Node
                        session.run("""
                            MATCH (f:File {path: $path})
                            MERGE (fn:Function {signature: $sig})
                            SET fn.name = $name, fn.code = $code
                            MERGE (f)-[:DEFINES]->(fn)
                        """, path=rel_path, sig=full_sig, name=name, code=node_text)

                        # Link to parent class
                        if parent_class:
                            class_sig = f"{rel_path}:{parent_class}"
                            session.run("""
                                MATCH (c:Class {qualified_name: $csig})
                                MATCH (fn:Function {signature: $fsig})
                                MERGE (c)-[:HAS_METHOD]->(fn)
                            """, csig=class_sig, fsig=full_sig)

                        # Create Chunk with embedding
                        context_prefix = f"File: {rel_path}"
                        if parent_class:
                            context_prefix += f" > Class: {parent_class}"

                        enriched_text = (
                            f"Context: {context_prefix} > Method: {name}\n\n{node_text}"
                        )
                        embedding = self.builder.get_embedding(enriched_text)

                        session.run("""
                            MATCH (fn:Function {signature: $sig})
                            CREATE (ch:Chunk {id: randomUUID()})
                            SET ch.text = $text,
                                ch.embedding = $embedding,
                                ch.created_at = datetime()
                            MERGE (ch)-[:DESCRIBES]->(fn)
                        """, sig=full_sig, text=node_text, embedding=embedding)


def start_continuous_watch(
    repo_path: Path,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    initial_scan: bool = True,
):
    """
    Start continuous file watching for a repository.

    Args:
        repo_path: Path to the repository to watch
        neo4j_uri: Neo4j connection URI
        neo4j_user: Neo4j username
        neo4j_password: Neo4j password
        initial_scan: Whether to run full pipeline before watching (default: True)
    """
    # Init Builder
    builder = KnowledgeGraphBuilder(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        openai_key=os.getenv("OPENAI_API_KEY"),
        repo_root=repo_path,
    )

    # Run initial setup
    logger.info("🛠️  Setting up Database Indexes...")
    builder.setup_database()

    if initial_scan:
        logger.info("🚀 Running initial full pipeline...")
        builder.run_pipeline(repo_path)
        logger.info("✅ Initial scan complete. Watching for changes...")

    # Start Watcher
    event_handler = CodeChangeHandler(builder, repo_path)
    observer = Observer()
    observer.schedule(event_handler, str(repo_path), recursive=True)
    observer.start()

    logger.info(f"👀 Watching {repo_path} for changes. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        builder.close()
        logger.info("👋 Shutting down...")
    observer.join()
