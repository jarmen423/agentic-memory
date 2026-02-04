# CodeMemory: Structural Memory Layer for AI Agents

**Version:** 1.0.0-alpha
**Status:** Architecture Frozen

## 1. Product Vision

CodeMemory is not just "RAG" for code. It is an **active, structural memory system** for Autonomous Agents. Unlike standard vector databases that only know "similarity," CodeMemory understands **structure** (dependencies, imports, inheritance).

**Core Value Prop:** "Don't let your Agent code blind. Give it a map."

## 2. System Architecture

The system is decoupled into three independent components:

```mermaid
graph LR
    UserRepo[(User Repository)] -->|Watches| CLI[Ingestion Service (Observer)]
    CLI -->|Writes Nodes/Vectors| DB[(Neo4j Cortex)]
    
    Agent[AI Agent / Claude] <-->|MCP Protocol| MCPServer[MCP Skill (The Interface)]
    MCPServer -->|Reads/Traverses| DB

```

### Component A: The Observer (Ingestion Service)

* **Role:** The "Writer." It watches the file system and keeps the graph in sync.
* **Refactor Goal:** Move from hardcoded paths to `argparse`.
* **Key Command:** `codemem watch ./my-repo`

### Component B: The Interface (MCP Server)

* **Role:** The "Reader" and "Translator."
* **Why MCP?** It allows us to expose high-level *skills* to the agent, rather than raw SQL access.
* **Key Tools:**
1. `search_code(query: str)`: Hybrid search (Vector + Keyword).
2. `get_file_context(path: str)`: Returns the file's content *plus* its imports and dependencies.
3. `impact_analysis(path: str)`: Returns a graph of what *calls* this file (the blast radius).



## 3. Implementation Plan

### Phase 1: Repository Restructuring

We will move from a flat script directory to a proper Python package structure.

```text
code-memory/
├── src/
│   └── codememory/
│       ├── __init__.py
│       ├── cli.py              # Entry point (argparse)
│       ├── ingestion/          # Refactored 5_continuous_ingestion.py
│       │   ├── watcher.py
│       │   ├── parser.py       # TreeSitter logic
│       │   └── graph.py        # Neo4j Writer
│       └── server/             # The New MCP Server
│           ├── app.py
│           └── tools.py        # The "Brain" logic
├── docker/
│   └── docker-compose.yml
├── pyproject.toml              # Dependency management
└── README.md

```

### Phase 2: Refactoring Ingestion

**Goal:** Remove hardcoded `REPO_PATH` and `.env` dependencies in favor of CLI arguments.

**Old Code (`5_continuous_ingestion.py`):**

```python
REPO_PATH = Path("/home/josh/code/m26pipeline") # Hardcoded

```

**New Code (`src/codememory/cli.py`):**

```python
import argparse
from codememory.ingestion import start_watcher

def main():
    parser = argparse.ArgumentParser(description="CodeMemory Ingestion")
    parser.add_argument("path", help="Path to the repository to watch")
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--watch", action="store_true", help="Run in continuous mode")
    
    args = parser.parse_args()
    
    # Pass args down to the logic
    start_watcher(repo_path=args.path, uri=args.neo4j_uri, ...)

```

### Phase 3: The MCP Server (The "Brain")

We will implement a FastMCP server that wraps your hybrid logic.

**Tool Definition:**

```python
@mcp.tool()
def identify_impact(file_path: str) -> str:
    """
    Returns a list of files that depend on the given file_path.
    Use this before editing a file to ensure you don't break dependencies.
    """
    # 1. Run Cypher to find incoming calls
    result = graph.run("MATCH (f:File {path: $p})<-[:IMPORTS]-(dependent) RETURN dependent.path", p=file_path)
    return format_as_list(result)

```

## 4. Deployment Strategy

* **Local Dev:** `pip install -e .` then `codemem watch .`
* **Docker:** Users run `docker-compose up`. The container mounts their code volume and starts the watcher + Neo4j.