# GraphRAG Pipeline

This directory contains the "GraphRAG" (Graph-Retrieval Augmented Generation) pipeline scripts, which build a "Digital Twin" of the codebase in Neo4j to power AI coding agents.

**⚠️ IMPORTANT: Python 3.11 Required**
These scripts rely on `llama-index` and `tree-sitter` bindings that may have compatibility issues with Python 3.13 (the project's main version). You **MUST** use a dedicated Python 3.11 virtual environment.

## 📂 Files

*   **`4_pass_ingestion_with_prep_hybridgraphRAG.py`**: The "Day 0" full ingestion script. It wipes relevant graph parts and rebuilds the structure (Files, Classes, Functions), Imports, Call Graph, and Embeddings.
*   **`5_continuous_ingestion.py`**: The "Day N" continuous ingestion daemon. It watches for file changes, processes only diffs, and updates the graph incrementally using a Postgres-backed state store.

## 🛠️ Setup

1.  **install python 3.11 using pyenv** (Address this however you prefer on your OS)
```shell
    # 1. Install Python 3.11 using pyenv
    # This compiles a fresh 3.11 binary and stores it in ~/.pyenv/versions/
    pyenv install 3.11.9

    # 2. Create the Virtual Environment
    # We point directly to the pyenv version to create the venv.
    # This replaces the 'python3.11 -m venv' command from your README.
    ~/.pyenv/versions/3.11.9/bin/python -m venv .venv-graphrag

    # 3. Activate the new environment
    # Notice your prompt will likely change to (.venv-graphrag)
    source .venv-graphrag/bin/activate

    # 4. Verify you are using the correct version
    # This should output 3.11.9, even if your global python is 3.13 or 3.12
    python --version

    # 5. Install the GraphRAG dependencies
    # As specified in your README
    pip install -r graphRAG/graphrag_requirements.txt
```
    

2.  **Create a dedicated virtual environment**:
    ```bash
    python3.11 -m venv .venv-graphrag
    source .venv-graphrag/bin/activate
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r graphRAG/graphrag_requirements.txt
    ```

## ⚙️ Configuration (.env)

Ensure your `.env` file in the project root contains the following:

```ini
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
OPENAI_API_KEY=sk-...
POSTGRES_URI=postgresql+psycopg2://user:pass@localhost:5432/m26sales  # For Script 5
REPO_PATH=/absolute/path/to/m26pipeline
```

## 🚀 Usage

### 1. Initial Ingestion (Day 0)
Run this significantly when setting up a new repo or after massive changes.
```bash
source .venv-graphrag/bin/activate
python graphRAG/4_pass_ingestion_with_prep_hybridgraphRAG.py
```

### 2. Continuous Ingestion (Daemon)
Run this in the background to keep the graph in sync with your edits.
```bash
source .venv-graphrag/bin/activate
python graphRAG/5_continuous_ingestion.py
```
