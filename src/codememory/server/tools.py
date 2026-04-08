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
        Graph-enriched hybrid search formatted for the Agent.

        Each result includes the vector-matched code plus graph context:
        file location, call relationships, sibling functions, and file imports.
        """
        try:
            results = self.graph.semantic_search(query, limit)
            if not results:
                return "No relevant code found in the graph."

            report = f"### Found {len(results)} relevant code results for '{query}':\n\n"
            for r in results:
                score_display = r.get('final_score', r.get('score', 0.0))
                report += f"#### {r['name']} (Score: {score_display:.2f})\n"
                if r.get('sig'):
                    report += f"**Signature:** `{r['sig']}`\n"
                if r.get('file_path'):
                    report += f"**File:** `{r['file_path']}`\n"
                if r.get('calls_out'):
                    report += f"**Calls:** {', '.join(r['calls_out'])}\n"
                if r.get('called_by'):
                    report += f"**Called by:** {', '.join(r['called_by'])}\n"
                if r.get('methods'):
                    report += f"**Methods:** {', '.join(r['methods'])}\n"
                if r.get('siblings'):
                    report += f"**Siblings in file:** {', '.join(r['siblings'])}\n"
                if r.get('file_imports'):
                    report += f"**File imports:** {', '.join(r['file_imports'])}\n"
                if r.get('text'):
                    report += f"```\n{r['text']}\n```\n"
                report += "\n"
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

    def create_memory_entities(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create or update memory entities."""
        return self.graph.create_memory_entities(entities)

    def create_memory_relations(self, relations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create typed memory relations."""
        return self.graph.create_memory_relations(relations)

    def add_memory_observations(self, observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Append observations to memory entities."""
        return self.graph.add_memory_observations(observations)

    def delete_memory_entities(self, names: List[str]) -> Dict[str, Any]:
        """Delete memory entities."""
        return self.graph.delete_memory_entities(names)

    def delete_memory_relations(self, relations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Delete typed memory relations."""
        return self.graph.delete_memory_relations(relations)

    def delete_memory_observations(self, observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Delete observations from memory entities."""
        return self.graph.delete_memory_observations(observations)

    def search_memory_nodes(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search memory entities."""
        return self.graph.search_memory_nodes(query, limit=limit)

    def read_memory_graph(self) -> Dict[str, Any]:
        """Read the current memory graph snapshot."""
        return self.graph.read_memory_graph()

    def backfill_memory_embeddings(
        self, limit: int = 100, only_missing: bool = True
    ) -> Dict[str, Any]:
        """Backfill embeddings for existing memory entities."""
        return self.graph.backfill_memory_embeddings(limit=limit, only_missing=only_missing)
