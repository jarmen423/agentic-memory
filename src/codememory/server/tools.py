from typing import List, Dict, Optional
import logging
from codememory.ingestion.graph import KnowledgeGraphBuilder

logger = logging.getLogger(__name__)

class Toolkit:
    """
    The 'Brain' logic.
    Separated from the Server so it can be tested or used in CLI/Scripts directly.
    """
    def __init__(self, graph: KnowledgeGraphBuilder):
        self.graph = graph

    def semantic_search(self, query: str, limit: int = 5) -> str:
        """
        Performs hybrid search and formats the result as a readable string for the Agent.
        """
        try:
            results = self.graph.semantic_search(query, limit=limit)
            if not results:
                return "No relevant code found in the graph."

            # Format for LLM consumption (Markdown)
            report = f"### Found {len(results)} relevant code snippets for '{query}':\n\n"
            for r in results:
                report += f"#### 📄 {r['name']} (Score: {r['score']:.2f})\n"
                report += f"**Signature:** `{r['sig']}`\n"
            return report
        except Exception as e:
            logger.error(f"search failed:{e}")
            return f"Error executing search: {str(e)}"
    
    def get_file_dependencies(self, file_path: str) -> str:
        """
        Returns what this file imports and what calls it.
        """
        # We need a direct Cypher query here that isn't in the generic graph builder yet.
        # Ideally, we add a method to KnowledgeGraphBuilder, but we can access driver here too.
        query_imports = """
        MATCH (f:File {path: $path})-[:IMPORTS]->(dep)
        RETURN dep.path as dependency
        """
        
        query_callers = """
        MATCH (f:File {path: $path})<-[:IMPORTS]-(caller)
        RETURN caller.path as caller
        """

        try:
            with self.graph.driver.session() as session:
                deps = session.run(query_imports, path=file_path)
                callers = session.run(query_callers, path=file_path)
                
                dep_list = [r["dependency"] for r in deps]
                caller_list = [r["caller"] for r in callers]
                
                return (
                    f"### Dependency Report for `{file_path}`\n"
                    f"**Imports (outgoing):** {dep_list if dep_list else 'None'}\n"
                    f"**Used By (incoming):** {caller_list if caller_list else 'None'}"
                )
        except Exception as e:
            return f"Error analyzing dependencies: {str(e)}"