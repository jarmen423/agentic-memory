import os
import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from codememory.ingestion.graph import KnowledgeGraphBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Observer")

class CodeChangeHandler(FileSystemEventHandler):
    def __init__(self, builder: KnowledgeGraphBuilder, repo_root: Path):
        self.builder = builder
        self.repo_root = repo_root

    def on_modified(self, event):
        if event.is_directory: return
        path = Path(event.src_path)
        if path.suffix in ['.py', '.js', '.ts']:
            logger.info(f"♻️  Change detected: {path.name}")
            try:
                self.builder.process_file(path, self.repo_root)
            except Exception as e:
                logger.error(f"Failed to ingest {path.name}: {e}")

def start_continuous_watch(repo_path: Path, neo4j_uri, neo4j_user, neo4j_password):
    # 1. Init Builder
    # Note: In production, pass OPENAI_KEY securely
    builder = KnowledgeGraphBuilder(
        uri=neo4j_uri, 
        user=neo4j_user, 
        password=neo4j_password,
        openai_key=os.getenv("OPENAI_API_KEY")
    )
    
    # 2. Run Initial Setup
    logger.info("🛠️  Setting up Database Indexes...")
    builder.setup_indexes()
    
    # 3. Start Watcher
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
    observer.join()