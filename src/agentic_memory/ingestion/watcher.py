"""
File Watcher for Agentic Memory.

Monitors a codebase for file changes and incrementally updates the knowledge graph.
"""

import time
import logging
from pathlib import Path
from typing import Optional, Set

import neo4j
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from agentic_memory.config import Config
from agentic_memory.ingestion.graph import KnowledgeGraphBuilder

logging.basicConfig(level=logging.INFO)
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)
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

    def __init__(
        self,
        builder: KnowledgeGraphBuilder,
        repo_root: Path,
        supported_extensions: Optional[Set[str]] = None,
    ):
        self.builder = builder
        self.repo_root = repo_root
        self._debounce_cache: dict[str, float] = {}
        self.supported_extensions = supported_extensions or {".py", ".js", ".ts", ".tsx", ".jsx"}

    def _is_ignored_path(self, path: Path) -> bool:
        """Check if any parent directory in this path should be ignored."""
        try:
            rel_path = path.relative_to(self.repo_root)
            dir_parts = rel_path.parts[:-1]
        except ValueError:
            dir_parts = path.parts[:-1]
            rel_path = path
        rel_path_str = str(rel_path).replace("\\", "/")
        if self.builder._should_ignore_path(rel_path_str):
            return True
        return any(self.builder._should_ignore_dir(part) for part in dir_parts)

    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Check file extension
        if path.suffix not in self.supported_extensions:
            return
        if self._is_ignored_path(path):
            return

        # Simple debounce (ignore events within 1 second of last event for this file)
        now = time.time()
        last_time = self._debounce_cache.get(str(path), 0)
        if now - last_time < 1.0:
            return
        self._debounce_cache[str(path)] = now

        try:
            rel_path = str(path.relative_to(self.repo_root))
            rel_path = rel_path.replace("\\", "/")
            logger.info(f"♻️  Change detected: {rel_path}")

            self.builder.reindex_file(rel_path, repo_path=self.repo_root)

            logger.info(f"✅ Updated graph for: {rel_path}")

        except (OSError, IOError, neo4j.exceptions.DatabaseError) as e:
            logger.error(f"❌ Failed to ingest {path.name}: {e}")

    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix not in self.supported_extensions:
            return
        if self._is_ignored_path(path):
            return

        try:
            rel_path = str(path.relative_to(self.repo_root))
            rel_path = rel_path.replace("\\", "/")
            logger.info(f"➕ New file detected: {rel_path}")

            self.builder.reindex_file(rel_path, repo_path=self.repo_root)
            logger.info(f"✅ Indexed new file: {rel_path}")

        except (OSError, IOError, neo4j.exceptions.DatabaseError) as e:
            logger.error(f"❌ Failed to ingest new file {path.name}: {e}")

    def on_deleted(self, event):
        """Handle file deletion events."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix not in self.supported_extensions:
            return
        if self._is_ignored_path(path):
            return

        try:
            rel_path = str(path.relative_to(self.repo_root))
            rel_path = rel_path.replace("\\", "/")
            logger.info(f"🗑️  File deleted: {rel_path}")

            self.builder.delete_file(rel_path, repo_path=self.repo_root)

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
        self.builder.delete_file(rel_path, repo_path=self.repo_root)

    def _process_single_file(self, full_path: Path, rel_path: str):
        """
        Process a single file: parse and store in graph.

        This is a simplified version of Pass 2 for single files.
        It does NOT update the call graph (requires full repo scan).
        """
        self.builder.reindex_file(rel_path, repo_path=self.repo_root)


def start_continuous_watch(
    repo_path: Path,
    config: Config,
    ignore_dirs: Optional[Set[str]] = None,
    ignore_files: Optional[Set[str]] = None,
    ignore_patterns: Optional[Set[str]] = None,
    supported_extensions: Optional[Set[str]] = None,
    initial_scan: bool = True,
):
    """
    Start continuous file watching for a repository.

    Args:
        repo_path: Path to the repository to watch
        config: Repo config used for Neo4j connection and code embedding resolution
        ignore_dirs: Directory names/patterns to ignore
        ignore_files: File names/patterns to ignore
        ignore_patterns: .graphignore-style patterns to ignore
        supported_extensions: File extensions to process
        initial_scan: Whether to run full pipeline before watching (default: True)
    """
    neo4j_cfg = config.get_neo4j_config()

    # Init Builder
    builder = KnowledgeGraphBuilder(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        openai_key=None,
        config=config,
        repo_root=repo_path,
        ignore_dirs=ignore_dirs,
        ignore_files=ignore_files,
        ignore_patterns=ignore_patterns,
    )

    # Run initial setup
    logger.info("🛠️  Setting up Database Indexes...")
    builder.setup_database()

    if initial_scan:
        logger.info("🚀 Running initial full pipeline...")
        builder.run_pipeline(repo_path, supported_extensions=supported_extensions)
        logger.info("✅ Initial scan complete. Watching for changes...")

    # Start Watcher
    event_handler = CodeChangeHandler(
        builder,
        repo_root=repo_path,
        supported_extensions=supported_extensions,
    )
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
