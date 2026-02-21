import os
import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Any

import neo4j
from openai import OpenAI

from codememory.ingestion.parser import CodeParser

logger = logging.getLogger(__name__)

class KnowledgeGraphBuilder:
    """
    Refactored builder from graphRAG/4_pass_ingestion...
    Now accepts dynamic configuration.
    """
    EMBEDDING_MODEL = "text-embedding-3-small"

    def __init__(self, uri: str, user: str, password: str, openai_key: str):
        self.driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
        self.openai_client = OpenAI(api_key=openai_key)
        self.parser = CodeParser()

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
            "CREATE CONSTRAINT class_name_unique IF NOT EXISTS FOR (c:Class) REQUIRE c.qualified_name IS UNIQUE",
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
                try:
                    session.run(q)
                except Exception as e:
                    logger.warning(f"Constraint/Index check: {e}")

    def process_file(self, file_path: Path, repo_root: Path):
        """
        Ingests a single file. (Simplified version of Pass 2)
        """
        rel_path = str(file_path.relative_to(repo_root))
        try:
            code = file_path.read_text(errors='ignore')
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return

        extension = file_path.suffix
        parse_result = self.parser.parse_file(code, extension)
        
        if not parse_result:
            return

        # We need a shared session for efficiency, but maybe separate transactions?
        # neo4j python driver handles transactions automatically usually.
        with self.driver.session() as session:
            # 1. Create File Node
            session.run("""
                MERGE (f:File {path: $path})
                SET f.last_updated = datetime()
            """, path=rel_path)

            # 2. Process Classes
            for cls in parse_result.get("classes", []):
                self._ingest_class(session, rel_path, cls)

            # 3. Process Functions
            for func in parse_result.get("functions", []):
                self._ingest_function(session, rel_path, func)

            # 4. Process Imports
            for module in parse_result.get("imports", []):
                self._ingest_import(session, rel_path, module)

            # 5. Process Calls (Heuristic: link all functions in file to all calls in file)
            calls = parse_result.get("calls", [])
            functions = parse_result.get("functions", [])
            if calls and functions:
                 for func in functions:
                     self._ingest_calls_for_function(session, rel_path, func, calls)
            
            # 6. Process Env Vars
            for env in parse_result.get("env_vars", []):
                self._ingest_env_var(session, rel_path, env)

        logger.info(f"Processed structure for {rel_path}")

    def _ingest_class(self, session, rel_path: str, cls_data: Dict[str, Any]):
        name = cls_data["name"]
        code = cls_data["code"]
        signature = f"{rel_path}:{name}" # Simple signature

        # 1. Create Class Node
        session.run("""
            MATCH (f:File {path: $path})
            MERGE (c:Class {qualified_name: $sig})
            SET c.name = $name, c.code = $code
            MERGE (f)-[:DEFINES]->(c)
        """, path=rel_path, sig=signature, name=name, code=code)

        # 2. Hybrid Chunking: Class Context
        # Skip if chunk already exists (avoid re-embedding)
        existing = session.run("""
            MATCH (c:Class {qualified_name: $sig})
            OPTIONAL MATCH (ch:Chunk)-[:DESCRIBES]->(c)
            RETURN ch.id as chunk_id LIMIT 1
        """, sig=signature).single()

        if not existing or not existing["chunk_id"]:
            # Prepend context to the vector
            enriched_text = f"Context: File {rel_path} > Class {name}\n\n{code}"
            embedding = self.get_embedding(enriched_text)

            session.run("""
                MATCH (c:Class {qualified_name: $sig})
                CREATE (ch:Chunk {id: randomUUID()})
                SET ch.text = $text,
                    ch.embedding = $embedding,
                    ch.created_at = datetime()
                MERGE (ch)-[:DESCRIBES]->(c)
            """, sig=signature, text=code, embedding=embedding)

    def _ingest_function(self, session, rel_path: str, func_data: Dict[str, Any]):
        name = func_data["name"]
        code = func_data["code"]
        parent_class = func_data.get("parent_class")

        qual_name = f"{parent_class}.{name}" if parent_class else name
        full_sig = f"{rel_path}:{qual_name}"

        # 1. Create Function Node
        session.run("""
            MATCH (f:File {path: $path})
            MERGE (fn:Function {signature: $sig})
            SET fn.name = $name, fn.code = $code
            MERGE (f)-[:DEFINES]->(fn)
        """, path=rel_path, sig=full_sig, name=name, code=code)

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
            # Contextual Prefixing
            context_prefix = f"File: {rel_path}"
            if parent_class:
                context_prefix += f" > Class: {parent_class}"

            enriched_text = f"Context: {context_prefix} > Method: {name}\n\n{code}"
            embedding = self.get_embedding(enriched_text)

            session.run("""
                MATCH (fn:Function {signature: $sig})
                CREATE (ch:Chunk {id: randomUUID()})
                SET ch.text = $text,
                    ch.embedding = $embedding,
                    ch.created_at = datetime()
                MERGE (ch)-[:DESCRIBES]->(fn)
            """, sig=full_sig, text=code, embedding=embedding)

    def _ingest_import(self, session, rel_path: str, module_name: str):
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

    def _ingest_calls_for_function(self, session, rel_path: str, func_data: Dict[str, Any], calls: List[str]):
        name = func_data["name"]
        parent_class = func_data.get("parent_class")
        qual_name = f"{parent_class}.{name}" if parent_class else name
        caller_sig = f"{rel_path}:{qual_name}"

        # Create relationships for found calls
        session.run("""
            UNWIND $calls as called_name
            MATCH (caller:Function {signature: $caller_sig})
            MATCH (callee:Function {name: called_name})
            WHERE caller <> callee
            MERGE (caller)-[:CALLS]->(callee)
        """, caller_sig=caller_sig, calls=calls)

    def _ingest_env_var(self, session, rel_path: str, env_data: Dict[str, Any]):
        line = env_data["line"]
        type_ = env_data.get("type")

        if type_ == "read":
            var_name = env_data["name"]
            session.run("""
                MATCH (f:File {path: $path})
                MERGE (v:EnvVar {name: $name})
                MERGE (f)-[:READS_ENV_VAR {line: $line}]->(v)
            """, path=rel_path, name=var_name, line=line)

        elif type_ == "load":
            session.run("""
                MATCH (f:File {path: $path})
                MERGE (f)-[:CALLS_LOAD_DOTENV {line: $line}]->(f)
            """, path=rel_path, line=line)

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
