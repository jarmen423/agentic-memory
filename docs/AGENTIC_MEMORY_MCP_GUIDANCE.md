# Agentic Memory MCP Guidance

When exploring this codebase, prefer using the `agentic-memory` MCP tools over native tools when they can answer the question faster or with better repo context.

## Agentic Memory MCP Tools

### Tool List

- `search_codebase`
- `get_file_dependencies`
- `get_git_file_history`
- `get_commit_context`
- `identify_impact`
- `get_file_info`
- `trace_execution_path`
- `search_all_memory`
- `search_conversations`
- `get_conversation_context`
- `search_web_memory`
- `memory_ingest_research`
- `create_memory_entities`
- `create_memory_relations`
- `add_memory_observations`
- `delete_memory_entities`
- `delete_memory_relations`
- `delete_memory_observations`
- `search_memory_nodes`
- `read_memory_graph`
- `backfill_memory_embeddings`

### Tool Descriptions

| Tool | Description |
|------|-------------|
| `search_codebase(query, limit, domain)` | Semantically search the codebase for functionality using vector similarity. Supports `code`, `git`, and `hybrid` domains. |
| `get_file_dependencies(file_path)` | Returns files this file imports and files that import this file. Useful for understanding upstream and downstream dependencies. |
| `get_git_file_history(file_path, limit)` | Returns commit history for a file from the git graph domain. |
| `get_commit_context(sha, include_diff_stats)` | Returns detailed metadata and optional diff stats for a commit SHA. |
| `identify_impact(file_path, max_depth)` | Identifies the blast radius of changes to a file by returning transitive dependents organized by depth. |
| `get_file_info(file_path)` | Returns detailed file info including defined functions, classes, and direct import relationships. |
| `trace_execution_path(start_symbol, max_depth)` | Traces one function's likely execution path on demand instead of relying on a repo-wide call graph. |
| `search_all_memory(query, limit, modules)` | Searches across code, git, web research, and conversation memory in one combined result set. |
| `search_conversations(query, limit)` | Searches stored conversation history for relevant prior exchanges. |
| `get_conversation_context(query, limit)` | Retrieves the most relevant prior conversation context bundle for the current task. |
| `search_web_memory(query, limit)` | Searches previously ingested research and web findings. |
| `memory_ingest_research(content, title, type, findings, citations, ...)` | Saves research findings and reports into persistent memory for later retrieval. |
| `create_memory_entities(entities)` | Creates or updates repo-scoped concept or decision nodes for agent-authored durable memory. |
| `create_memory_relations(relations)` | Creates typed relations between memory entities such as `DEPENDS_ON`, `DECIDES`, or `RELATES_TO`. |
| `add_memory_observations(observations)` | Appends additional observations to an existing memory entity without replacing prior observations. |
| `delete_memory_entities(entity_names)` | Deletes memory entities by name from the repo-scoped memory graph. |
| `delete_memory_relations(relations)` | Deletes typed relations between existing memory entities. |
| `delete_memory_observations(observations)` | Removes specific observations from existing memory entities. |
| `search_memory_nodes(query, limit)` | Searches the writable memory graph for abstract concepts, design decisions, and stored observations. |
| `read_memory_graph()` | Returns a summary snapshot of the current repo-scoped memory graph. |
| `backfill_memory_embeddings(limit, only_missing)` | Regenerates embeddings for memory entities, mainly for repair or migration workflows. |

## Memory Graph

1. **Agentic Memory (`agentic-memory` MCP):** Tracks code structure, git history, research memory, conversation memory, and a writable repo-scoped concept graph through a shared Neo4j-backed retrieval surface.
