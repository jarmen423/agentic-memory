#!/usr/bin/env python3
"""
Manual Upload Script for Embedding Checkpoint.

Use this when Neo4j is confirmed online and you want to upload saved embeddings
without re-running the full pipeline.

Usage:
    source .venv-3.11-llama/bin/activate
    python graphRAG/upload_checkpoint.py
"""
import os
import pickle
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
CHECKPOINT_PATH = Path(__file__).parent / ".embedding_checkpoint.pkl"

def main():
    if not CHECKPOINT_PATH.exists():
        print("❌ No checkpoint file found at:", CHECKPOINT_PATH)
        print("   Run the main ingestion script first to generate embeddings.")
        return
    
    print(f"📂 Loading checkpoint: {CHECKPOINT_PATH}")
    with open(CHECKPOINT_PATH, "rb") as f:
        data = pickle.load(f)
    
    nodes = data.get("nodes", [])
    print(f"✅ Loaded {len(nodes)} nodes with embeddings")
    
    # Connect to Neo4j
    from llama_index.vector_stores.neo4jvector import Neo4jVectorStore
    
    print("🔌 Connecting to Neo4j...")
    vector_store = Neo4jVectorStore(
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        url=NEO4J_URI,
        index_name="code_embeddings",
        node_label="Chunk",
        embedding_dimension=3072
    )
    
    print(f"📤 Uploading {len(nodes)} embeddings to Neo4j in batches of 100...")
    BATCH_SIZE = 100
    for i in range(0, len(nodes), BATCH_SIZE):
        batch = nodes[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(nodes) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  📦 Batch {batch_num}/{total_batches} ({len(batch)} nodes)...")
        vector_store.add(batch)
    print("✅ Upload complete!")
    
    # Delete checkpoint
    CHECKPOINT_PATH.unlink()
    print("🗑️ Checkpoint deleted.")

if __name__ == "__main__":
    main()
