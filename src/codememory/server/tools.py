from typing import Any, Dict, List, Optional
import logging
import neo4j
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
            results = self.graph.semantic_search(query, limit)
            if not results:
                return "No relevant code found in the graph."

            # Format for LLM consumption (Markdown)
            report = f"### Found {len(results)} relevant code snippets for '{query}':\n\n"
            for r in results:
                report += f"#### 📄 {r['name']} (Score: {r['score']:.2f})\n"
                report += f"**Signature:** `{r['sig']}`\n"
            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            logger.error(f"search failed:{e}")
            return f"Error executing search: {str(e)}"
    
    def get_file_dependencies(self, file_path: str) -> str:
        """
        Returns what this file imports and what calls it.
        """
        try:
            deps = self.graph.get_file_dependencies(file_path)
            dep_list = deps.get("imports", [])
            caller_list = deps.get("imported_by", [])

            return (
                f"### Dependency Report for `{file_path}`\n"
                f"**Imports (outgoing):** {dep_list if dep_list else 'None'}\n"
                f"**Used By (incoming):** {caller_list if caller_list else 'None'}"
            )
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error analyzing dependencies: {str(e)}"

    def get_git_file_history(self, file_path: str, limit: int = 20) -> str:
        """
        Return git commit history for a specific file.
        """
        try:
            if not self.graph.has_git_graph_data():
                return "No git graph data found. Run git ingestion first."

            history = self.graph.get_git_file_history(file_path, limit=limit)
            if not history:
                return f"No git history found for `{file_path}`."

            report = f"### Git History for `{file_path}`\n"
            report += f"Found {len(history)} commit(s):\n"
            for row in history:
                sha = row.get("sha", "unknown")
                short_sha = sha[:12] if isinstance(sha, str) else "unknown"
                subject = row.get("message_subject", "(no subject)")
                report += f"- `{short_sha}` {subject}\n"
            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error getting git file history: {str(e)}"

    def get_commit_context(self, sha: str, include_diff_stats: bool = True) -> str:
        """
        Return metadata and optional diff stats for a commit.
        """
        try:
            if not self.graph.has_git_graph_data():
                return "No git graph data found. Run git ingestion first."

            context: Optional[Dict[str, Any]] = self.graph.get_commit_context(
                sha, include_diff_stats=include_diff_stats
            )
            if not context:
                return f"No commit found for `{sha}`."

            report = f"### Commit `{context.get('sha', sha)}`\n"
            report += f"Subject: {context.get('message_subject', '(no subject)')}\n"
            report += f"Author: {context.get('author_name', 'unknown')}\n"
            report += f"Committed: {context.get('committed_at', 'unknown')}\n"

            if include_diff_stats:
                stats = context.get("stats", {})
                report += (
                    f"Files Changed: {stats.get('files_changed', 0)}, "
                    f"Additions: {stats.get('additions', 0)}, "
                    f"Deletions: {stats.get('deletions', 0)}\n"
                )

            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error getting commit context: {str(e)}"
