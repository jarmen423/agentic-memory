import os
import logging
import hashlib
from pathlib import Path
from typing import List, Dict

import neo4j
from openai import OpenAI
from tree_sitter import Language, Parser

# Import language bindings
import tree_sitter_python
import tree_sitter_javascript

logger = logging.getLogger(__name__)

class KnowledgeGraphBuilder:
    """
    Refactored builder from graphRAG/4_pass_ingestion...
    Now accepts dynamic configuration.
    """
    EMBEDDING_MODEL = "text-embedding-3-small" # Changed to small for cost/speed in MVP

    def __init__(self, uri: str, user: str, password: str, openai_key: str):
        self.driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
        self.openai_client = OpenAI(api_key=openai_key)
        self.parsers = self._init_parsers()

    def _init_parsers(self) -> Dict[str, Parser]:
        parsers = {}
        # Python
        py_lang = Language(tree_sitter_python.language())
        parsers['.py'] = Parser(py_lang)
        # JS/TS
        js_lang = Language(tree_sitter_javascript.language())
        for ext in ['.js', '.jsx', '.ts', '.tsx']:
            parsers[ext] = Parser(js_lang)
        return parsers

    def close(self):
        self.driver.close()

    def get_embedding(self, text: str) -> List[float]:
        text = text.replace("\n", " ")[:8000] # Simple truncation
        try:
            res = self.openai_client.embeddings.create(input=[text], model=self.EMBEDDING_MODEL)
            return res.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return [0.0] * 1536 # Fallback

    def setup_indexes(self):
        """Creates constraints and vector indexes."""
        queries = [
            "CREATE CONSTRAINT file_path_unique IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
            "CREATE CONSTRAINT func_sig_unique IF NOT EXISTS FOR (f:Function) REQUIRE f.signature IS UNIQUE",
            """
            CREATE VECTOR INDEX code_embeddings IF NOT EXISTS
            FOR (c:Chunk) ON (c.embedding)
            OPTIONS {indexConfig: {
             `vector.dimensions`: 1536,
             `vector.similarity_function`: 'cosine'
            }}
            """
        ]
        with self.driver.session() as session:
            for q in queries:
                session.run(q)

    def process_file(self, file_path: Path, repo_root: Path):
        """
        Ingests a single file. (Simplified version of Pass 2)
        """
        rel_path = str(file_path.relative_to(repo_root))
        code = file_path.read_text(errors='ignore')
        
        with self.driver.session() as session:
            # 1. Create File Node
            session.run("""
                MERGE (f:File {path: $path})
                SET f.last_updated = datetime()
            """, path=rel_path)

            # 2. Parse Functions (Simplified)
            parser = self.parsers.get(file_path.suffix)
            if not parser: return

            tree = parser.parse(bytes(code, "utf8"))
            # ... (TreeSitter Query Logic would go here, identical to your script) ...
            # For MVP brevity, I am stubbing the complex extraction, but in the full version
            # you would paste your `pass_2_entity_definition` logic here.
            
            # Example stub:
            logger.info(f"Processed structure for {rel_path}")

    def semantic_search(self, query: str, limit: int = 5) -> List[Dict]:
        """Hybrid Search for the Agent."""
        vector = self.get_embedding(query)
        cypher = """
        CALL db.index.vector.queryNodes('code_embeddings', $limit, $vec)
        YIELD node, score
        MATCH (node)-[:DESCRIBES]->(target)
        RETURN target.name as name, target.signature as sig, score, node.text as text
        """
        with self.driver.session() as session:
            res = session.run(cypher, limit=limit, vec=vector)
            return [dict(r) for r in res]