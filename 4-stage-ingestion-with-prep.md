# This document is a discussion of scripts/4_pass_ingestion_with_prep_hybridgraphRAG.py
Why this is "Optimal" for your needs:
Hybrid Chunking (Pass 2): It doesn't just chunk blindly. It specifically looks for class_definition and function_definition nodes via Tree-sitter. Crucially, it creates an "Enriched" text for the embedding that looks like Context: File > Class > Method, effectively solving the "contextual blindness" of standard vector search.

Schema Agnostic Retrieval: By separating Function nodes (structure) from Chunk nodes (text/vector), your agent can query the structure (MATCH (f:Function)-[:CALLS]->()) separately from the content (vector.search(...)), which is the definition of Hybrid RAG.

Change Detection (Pass 1): The _calculate_ohash and MATCH (f:File)... logic ensures that subsequent runs (e.g., in CI/CD) are instant for unchanged files, saving massive amounts of API costs and time.

Agent Ready: The resulting graph structure directly supports the text2cypher tools because the schema (File, Class, Function, CALLS, IMPORTS) is intuitive and standard.

How to use this with your Agent (MCP)
When you configure your mcp-neo4j-cypher server in cursor or windsurf, your agent can now perform advanced queries like:

User: "Where is the auth logic handled?"

Agent (Vector): Finds Chunk nodes describing "auth" with high similarity.

Agent (Graph): Traverses (:Chunk)-->(:Function)<-[:CALLS]-(:Function) to find who uses that auth logic, effectively answering "What depends on the auth service?" without you asking.