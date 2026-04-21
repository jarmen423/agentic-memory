"""Filesystem observer that keeps the code graph aligned with the working tree.

Uses ``watchdog`` to receive create/modify/delete events under a repository
root, filters by extension and ignore rules shared with
:class:`~agentic_memory.ingestion.graph.KnowledgeGraphBuilder`, and forwards
each accepted event to incremental graph updates.

The long-running entrypoint is :func:`start_continuous_watch`, which optionally
runs a full ingestion pipeline once, then blocks in a sleep loop while the
observer thread processes events until interrupted.
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
    """Translate ``watchdog`` events into incremental Neo4j updates.

    For each supported, non-ignored path, dispatches to
    :meth:`KnowledgeGraphBuilder.reindex_file` on create/modify and
    :meth:`KnowledgeGraphBuilder.delete_file` on delete. Rapid duplicate
    ``modified`` events for the same path are suppressed briefly so save bursts
    from editors do not enqueue redundant full reindexes.

    Attributes:
        builder: Graph builder that owns Neo4j sessions and ignore rules.
        repo_root: Absolute repository root; relative paths stored in the graph
            are computed from this anchor.
        supported_extensions: File suffixes eligible for indexing; defaults to
            common Python and JS/TS extensions.
    """

    def __init__(
        self,
        builder: KnowledgeGraphBuilder,
        repo_root: Path,
        supported_extensions: Optional[Set[str]] = None,
    ):
        """Create a handler bound to one builder and repository root.

        Args:
            builder: Configured :class:`KnowledgeGraphBuilder` instance.
            repo_root: Root directory passed to ``watchdog`` and used to build
                repo-relative paths for graph operations.
            supported_extensions: If omitted, uses ``.py``, ``.js``, ``.ts``,
                ``.tsx``, and ``.jsx``.
        """
        self.builder = builder
        self.repo_root = repo_root
        self._debounce_cache: dict[str, float] = {}
        self.supported_extensions = supported_extensions or {".py", ".js", ".ts", ".tsx", ".jsx"}

    def _is_ignored_path(self, path: Path) -> bool:
        """Return True when the path or any ancestor segment is ignored.

        Args:
            path: Absolute or repo-relative path from the event.

        Returns:
            True if the builder's path or directory ignore rules exclude this
            file.
        """
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
        """Reindex a changed file when it passes extension and ignore filters."""
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Check file extension
        if path.suffix not in self.supported_extensions:
            return
        if self._is_ignored_path(path):
            return

        # Editors often emit several modified events in quick succession; skip
        # duplicates within one second per path to avoid redundant graph work.
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
        """Index a newly created file when it passes extension and ignore filters."""
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
        """Remove a deleted file and its derived nodes from the graph."""
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
    """Configure Neo4j, optionally ingest the whole repo, then watch until Ctrl+C.

    Creates a :class:`KnowledgeGraphBuilder`, ensures constraints/indexes exist,
    and when ``initial_scan`` is True runs :meth:`KnowledgeGraphBuilder.run_pipeline`
    so the graph matches disk before events arrive. Schedules a recursive
    :class:`watchdog.observers.Observer` on ``repo_path`` and blocks in a sleep
    loop; the observer processes filesystem events on a background thread.

    Args:
        repo_path: Repository root to watch and to use as the graph ``repo_id``.
        config: Application configuration (Neo4j URI/credentials and code
            embedding module settings).
        ignore_dirs: Directory name globs skipped during scans (merged with
            builder defaults when provided).
        ignore_files: Basenames to skip.
        ignore_patterns: Path/basename patterns in ``.graphignore`` style.
        supported_extensions: Suffixes for Pass 1 and for handler filtering;
            defaults inside the builder/handler if omitted.
        initial_scan: If True, run the full default pipeline (through import pass)
            before subscribing to events.

    Returns:
        None. This function is intended to run until ``KeyboardInterrupt``,
        then stop the observer and close the Neo4j driver.
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
        # Main thread idles; filesystem work runs on the observer thread.
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        builder.close()
        logger.info("👋 Shutting down...")
    observer.join()
