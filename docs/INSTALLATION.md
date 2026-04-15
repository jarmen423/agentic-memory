# Installation Guide

This guide covers installing and configuring Agentic Memory for local development or production use.

## Table of Contents

- [OpenClaw Private Beta](#openclaw-private-beta)
- [Prerequisites](#prerequisites)
- [Installation Methods](#installation-methods)
- [Neo4j Setup](#neo4j-setup)
- [Environment Configuration](#environment-configuration)
- [Initial Setup](#initial-setup)
- [Troubleshooting](#troubleshooting)

---

## OpenClaw Private Beta

If you are installing Agentic Memory specifically for the OpenClaw beta, use
the OpenClaw plugin flow instead of the Python CLI install paths below. This is
separate from the public publication path used for OpenAI, Codex, and Claude.

There are now two supported OpenClaw paths:

- managed hosted beta
  - preferred for normal users
  - connect the plugin to the hosted backend URL and use a workspace-bound API key
- self-hosted full stack
  - operator path
  - stand up the backend yourself, then point the plugin at that backend URL

Managed hosted beta path:

```bash
openclaw plugin install agentic-memory-openclaw
openclaw agentic-memory doctor --hosted --backend-url https://backend.agentmemorylabs.com
openclaw agentic-memory setup --hosted --backend-url https://backend.agentmemorylabs.com
openclaw agentic-memory project status
```

Self-hosted path:

```bash
openclaw plugin install agentic-memory-openclaw
openclaw agentic-memory doctor --self-hosted --backend-url http://127.0.0.1:8765
openclaw agentic-memory setup --self-hosted --backend-url http://127.0.0.1:8765
openclaw agentic-memory project status
```

Important distinctions:

- `agentic-memory-openclaw`
  - npm package name used by `openclaw plugin install`
- `agentic-memory`
  - runtime plugin id used by OpenClaw after install
- Agentic Memory backend
  - separate service that must already be reachable by the plugin

Important setup behavior:

- `doctor` checks `/health/onboarding` first
- `setup` now uses that same contract before it writes config
- `setup` and `doctor` both support `--hosted` and `--self-hosted`
- the plugin can refuse to save config if the backend is reachable but the
  required OpenClaw memory path is not honestly ready yet
- if you omit `--backend-url`, the plugin falls back to saved config first and only then to the local self-hosted default `http://127.0.0.1:8765`

Use these docs for the beta flow:

- `D:\code\agentic-memory\docs\openclaw\guides\PRIVATE_BETA_QUICKSTART.md`
- `D:\code\agentic-memory\docs\openclaw\DEPLOYMENT_RUNBOOK.md`
- `D:\code\agentic-memory\docs\openclaw\BETA_ROLLOUT.md`

The rest of this guide covers the Python/CLI install surface for the broader
Agentic Memory product.

## Running Agentic Memory On This Repo

If you are working inside this repository itself, it is already initialized for
code memory through:

- `D:\code\agentic-memory\.codememory\config.json`

That means the normal local sequence here is:

```powershell
cd D:\code\agentic-memory
docker compose up -d neo4j
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli status --json
.\.venv-agentic-memory\Scripts\python.exe -m agentic_memory.cli index --json
```

Use the explicit virtualenv Python path because `agent-memory` may not be on
`PATH` on every developer machine.

Current repo-local expectations:

- Neo4j at `bolt://localhost:7687`
- Neo4j auth `neo4j/password`
- code embeddings configured for Gemini by default in the local config

If `status` fails before indexing begins, fix the local Neo4j connection first.
That is the most common local blocker on this checkout.

## Public Plugin Publication

If you are preparing the hosted/public plugin surfaces, use the publication
packets instead of the local install flow:

- OpenAI / ChatGPT: app review and publish
- Codex: distribution derived from the approved OpenAI app, with `.codex-plugin/plugin.json` as the local preflight package
- Claude: Anthropic directory submission

Canonical publication/legal URLs:

- `https://mcp.agentmemorylabs.com/publication/agentic-memory`
- `https://mcp.agentmemorylabs.com/publication/privacy`
- `https://mcp.agentmemorylabs.com/publication/terms`
- `https://mcp.agentmemorylabs.com/publication/support`
- `https://mcp.agentmemorylabs.com/publication/dpa`

Reference packets:

- `docs/publication/openai`
- `docs/publication/anthropic`
- `docs/publication/shared`

For the public surface contract and auth model, see
[docs/PUBLIC_PLUGIN_SURFACES.md](docs/PUBLIC_PLUGIN_SURFACES.md).

---

## Prerequisites

### Required Software

| Software | Minimum Version | Recommended | Purpose |
|----------|----------------|-------------|---------|
| **Python** | 3.10 | 3.11+ | Runtime environment |
| **Neo4j** | 5.18 | 5.25+ | Graph database with vector search |
| **Gemini API Key** | - | - | Default code embedding provider |
| **Git** | 2.0+ | Latest | For version control (optional) |

### System Requirements

- **RAM:** 4GB minimum (8GB recommended for larger codebases)
- **Disk Space:** 500MB for Neo4j + additional space for graph data
- **OS:** Linux, macOS, or Windows 10+

### API Keys Required

- **Gemini API Key** - Default for code semantic search in new repos
  - Set `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- **OpenAI API Key** - Optional if you intentionally want code memory on a separate text embedding provider
  - Set `CODE_EMBEDDING_PROVIDER=openai`
  - Then provide `OPENAI_API_KEY`

---

## Installation Methods

### Method 1: pipx (Recommended for Global Installation)

**pipx** installs packages in isolated environments, ideal for CLI tools:

```bash
# Install pipx (if not already installed)
python -m pip install --user pipx

# Add pipx to PATH (Linux/macOS)
# Add this to your ~/.bashrc or ~/.zshrc:
export PATH="$PATH:$HOME/.local/bin"

# Install Agentic Memory
pipx install agent-memory-labs

# Verify installation
agent-memory --version
```

**Advantages:**
- Isolated from system Python
- No dependency conflicts
- Easy to uninstall: `pipx uninstall agent-memory-labs`

**How this works across multiple repos:**
- `pipx install agent-memory-labs` installs the CLI once for the whole machine
- `agent-memory` becomes available globally
- each repo still needs its own one-time `agent-memory init`
- after init, commands like `agent-memory index` and `agent-memory serve` use the repo you are currently inside

**Recommended multi-repo flow:**
```bash
cd /path/to/repo-a
agent-memory init

cd /path/to/repo-b
agent-memory init

cd /path/to/repo-a
agent-memory index

cd /path/to/repo-b
agent-memory serve
```

**Important env note:**
- no-flags operation expects Agentic Memory env values in `/path/to/repo/.agentic-memory/.env`
- the CLI intentionally does not auto-load `/path/to/repo/.env`
- use `--env-file` only when you intentionally want a non-default env source

### Method 2: uv / uvx (Global Tooling)

```bash
# Install globally as a Python tool
uv tool install agent-memory-labs

# Run without installing globally
uvx --from agent-memory-labs agent-memory --help
```

**Advantages:**
- Fast dependency resolution and installs
- Great for ephemeral tool usage via `uvx`

### Method 3: pip (System-wide Installation)

```bash
# Install directly
pip install agent-memory-labs

# Or with user-only installation
pip install --user agent-memory-labs
```

**Note:** This may conflict with other packages requiring different versions of dependencies.

### Method 4: From Source (For Developers)

```bash
# Clone the repository
git clone https://github.com/jarmen423/agentic-memory.git
cd agentic-memory

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install in editable mode
pip install -e .

# Verify installation
agent-memory --help
```

**Advantages:**
- Can modify source code directly
- Changes take effect immediately
- Ideal for contributors

---

## Repo Discovery And Per-Repo Config

After you run `agent-memory init` in a repository, Agentic Memory stores repo-local
state under:

- `.agentic-memory/config.json`
- optional `.agentic-memory/.env`

Most commands then discover the target repo from your current working directory.
That means:

- `cd /path/to/m26pipeline && agent-memory index` targets `m26pipeline`
- `cd /path/to/another-repo && agent-memory serve` targets that other repo

You usually do **not** need `--repo` once the repo is initialized. `--repo` is
mainly for clients, wrappers, and explicit automation.

---

## Neo4j Setup

Agentic Memory requires Neo4j 5.18+ with vector search support. Choose one of the following methods:

### Option 1: Docker (Recommended for Local Development)

#### Quick Start with Docker Compose

```bash
# Using the project's docker-compose.yml
docker-compose up -d neo4j

# Check logs
docker-compose logs -f neo4j

# Stop when done
docker-compose down
```

This starts Neo4j with:
- **HTTP UI:** http://localhost:7474
- **Bolt Protocol:** bolt://localhost:7687
- **Default credentials:** neo4j / password

#### Manual Docker Run

```bash
docker run -d \
  --name agentic-memory-neo4j \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_secure_password \
  -e NEO4J_dbms_memory_heap_max__size=2G \
  -e NEO4J_dbms_memory_pagecache_size=1G \
  -v neo4j_data:/data \
  neo4j:5.25-community
```

**Environment Variables:**
- `NEO4J_AUTH` - Set username/password (format: `username/password`)
- `NEO4J_dbms_memory_heap_max__size` - Max JVM heap size
- `NEO4J_dbms_memory_pagecache_size` - Page cache for graph data

#### Security Note for Production

Change the default password:

```bash
# Connect to Neo4j container
docker exec -it agentic-memory-neo4j cypher-shell -u neo4j -p password

# Change password
CALL dbms.security.changePassword('new_secure_password');
```

### Option 2: Neo4j Aura (Free Cloud Instance)

Neo4j offers a free AuraDB instance (limited to 200K nodes):

1. **Sign up:** https://neo4j.com/cloud/aura/
2. **Create free instance:**
   - Select "AuraDB Free"
   - Choose a region closest to you
3. **Get connection details:**
   - Copy the connection URL (format: `neo4j+s://...`)
   - Save the password

**Limitations:**
- 200K nodes limit
- No data persistence after 3 days of inactivity
- May be slow for large codebases

**Use case:** Great for testing, small projects, or quick demos.

### Option 3: Manual Installation

#### Linux

```bash
# Import Neo4j GPG key
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -

# Add Neo4j repository
echo 'deb https://debian.neo4j.com stable latest' | sudo tee /etc/apt/sources.list.d/neo4j.list

# Install
sudo apt update
sudo apt install neo4j

# Start service
sudo systemctl start neo4j
sudo systemctl enable neo4j
```

#### macOS

```bash
# Using Homebrew
brew install neo4j

# Start service
brew services start neo4j

# Or run manually
neo4j start
```

#### Windows

1. Download from: https://neo4j.com/download/
2. Extract to a directory (e.g., `C:\neo4j`)
3. Run as Administrator: `bin\neo4j.bat install-service`
4. Start: `bin\neo4j.bat start`

### Verify Neo4j Installation

```bash
# Check if Neo4j is running
curl http://localhost:7474

# Or using cypher-shell
cypher-shell -u neo4j -p password "RETURN 1"

# Expected output:
# 1
```

---

## Environment Configuration

### Option 1: Interactive Setup (Recommended)

Run the init wizard in your project directory:

```bash
cd /path/to/your/project
agent-memory init
```

The wizard will guide you through:
1. Neo4j connection setup
2. Code embedding provider selection, with Gemini as the default path for multimodal alignment
3. File extension selection
4. Initial indexing

### Option 2: Manual Configuration

#### Create `.env` File

Create a `.env` file in your project root:

```bash
# Neo4j Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Default code embedding provider: Gemini
GEMINI_API_KEY=your-gemini-api-key-here

# Optional: keep code memory separate on OpenAI instead
# CODE_EMBEDDING_PROVIDER=openai
# OPENAI_API_KEY=sk-your-api-key-here

# Optional: Logging
LOG_LEVEL=INFO
```

**Security:** Never commit `.env` to version control. Add `.env` to your `.gitignore`:

```bash
echo ".env" >> .gitignore
```

#### Configuration File (`.codememory/config.json`)

The init wizard creates `.codememory/config.json`:

```json
{
  "neo4j": {
    "uri": "bolt://localhost:7687",
    "user": "neo4j",
    "password": "password"
  },
  "openai": {
    "api_key": null
  },
  "gemini": {
    "api_key": null
  },
  "modules": {
    "code": {
      "embedding_provider": "gemini",
      "embedding_model": "gemini-embedding-2-preview",
      "embedding_dimensions": 3072
    }
  },
  "indexing": {
    "ignore_dirs": [
      "node_modules",
      "__pycache__",
      ".git",
      "dist",
      "build",
      ".venv",
      "venv",
      ".pytest_cache",
      ".mypy_cache",
      "target",
      "bin",
      "obj"
    ],
    "ignore_files": [],
    "extensions": [".py", ".js", ".ts", ".tsx", ".jsx"]
  }
}
```

**Note:** `.codememory/` is automatically gitignored to prevent committing API keys.

---

## Initial Setup

### Step 1: Initialize in Your Repository

```bash
cd /path/to/your/repository
agent-memory init
```

Follow the interactive prompts:
1. Choose Neo4j setup (Docker, Aura, or custom)
2. Choose the code embedding provider
3. Keep the default Gemini path for multimodal alignment, or switch code to another text embedding provider if you want a separate code-memory lane
4. Select file extensions to index
5. Run initial indexing

### Step 2: Verify Installation

```bash
# Check status
agent-memory status

# Expected output:
# 📊 Agentic Memory Status
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Repository: /path/to/your/repo
# Config:     /path/to/your/repo/.codememory/config.json
#
# 📈 Graph Statistics:
#    Files:     42
#    Functions: 156
#    Classes:   23
#    Chunks:    179
#    Last sync: 2025-02-09 14:32:15
```

### Step 3: Index Or Rebuild

```bash
# Normal incremental indexing
agent-memory index

# Full repo rebuild after embedding-model or task-format changes
agent-memory index --full
```

Use `--full` when source files are unchanged but every stored code embedding
still needs to be regenerated.

### Step 4: Test Semantic Search

```bash
agent-memory search "where is the auth logic?"

# Expected output:
# Found 3 result(s):
#
# 1. **authenticate** [`src/auth.py:authenticate`] - Score: 0.89
#    def authenticate(username, password):
#         """Verify user credentials and return session token"""...
#
# 2. **login** [`src/controllers/user.py:login`] - Score: 0.82
#    async def login(request):
#         """Handle user login requests"""...
```

### Step 5: Start MCP Server (Optional)

```bash
agent-memory serve

# Output: 🧠 Starting MCP Interface on port 8000
```

See [MCP_INTEGRATION.md](MCP_INTEGRATION.md) for client configuration.

---

## Troubleshooting

### Issue: "Module not found" Errors

**Symptom:**
```
ModuleNotFoundError: No module named 'agentic_memory'
```

**Solution:**
```bash
# Reinstall the package
pip install --force-reinstall agent-memory-labs

# Or if installing from source
pip install -e .
```

### Issue: Neo4j Connection Refused

**Symptom:**
```
ServiceUnavailable: Unable to connect to bolt://localhost:7687
```

**Solutions:**

1. **Check if Neo4j is running:**
```bash
# Docker
docker ps | grep neo4j

# System service
systemctl status neo4j  # Linux
brew services list      # macOS
```

2. **Start Neo4j:**
```bash
# Docker
docker-compose up -d neo4j

# Manual
docker start agentic-memory-neo4j
```

3. **Verify ports:**
```bash
# Check if port 7687 is listening
netstat -an | grep 7687  # Linux/macOS
netstat -an | findstr 7687  # Windows
```

4. **Check firewall:**
- Ensure port 7687 (Bolt) and 7474 (HTTP) are not blocked

### Issue: Code Embedding API Key Errors

**Symptom:**
```
Error: the configured code embedding API key is not set
```

**Solutions:**

1. **Set the default Gemini environment variable:**
```bash
# Linux/macOS
export GEMINI_API_KEY="your-gemini-key-here"

# Windows (Command Prompt)
set GEMINI_API_KEY=your-gemini-key-here

# Windows (PowerShell)
$env:GEMINI_API_KEY="your-gemini-key-here"
```

2. **Or use `GOOGLE_API_KEY`:**
```bash
export GOOGLE_API_KEY="your-gemini-key-here"
```

3. **If you intentionally configured code to use OpenAI instead, set both the provider override and key:**
```bash
export CODE_EMBEDDING_PROVIDER="openai"
export OPENAI_API_KEY="sk-your-key-here"
```

4. **Add the key to `.env`:**
```bash
echo "GEMINI_API_KEY=your-gemini-key-here" >> .env
```

5. **Verify end-to-end by running a real search:**
```bash
agent-memory search "entrypoint"
```

### Issue: "Out of Memory" During Indexing

**Symptom:**
```
Java heap space error during Neo4j operations
```

**Solutions:**

1. **Increase Neo4j heap size:**
```bash
# Docker: Add to docker-compose.yml
environment:
  - NEO4J_dbms_memory_heap_max__size=4G

# Manual: Edit conf/neo4j.conf
dbms.memory.heap.max_size=4G
```

2. **Index in batches:**
```bash
# Use --watch for incremental indexing instead of full re-index
agent-memory watch
```

### Issue: Parser Errors for Unsupported Languages

**Symptom:**
```
No parser found for .go files
```

**Current Support:**
- Python (.py)
- JavaScript (.js, .jsx)
- TypeScript (.ts, .tsx)

**Solutions:**
- Only index supported file types (configure in `.codememory/config.json`)
- Contribute language support (see [CONTRIBUTING.md](../CONTRIBUTING.md))

### Issue: Slow Indexing Performance

**Symptoms:**
- Indexing takes >10 minutes
- High CPU/memory usage

**Solutions:**

1. **Reduce file extensions:**
```json
{
  "indexing": {
    "extensions": [".py"]  // Only Python files
  }
}
```

2. **Increase ignore_dirs:**
```json
{
  "indexing": {
    "ignore_dirs": [
      "node_modules",
      "__pycache__",
      ".git",
      "dist",
      "build",
      ".venv",
      "venv",
      "tests",  // Add test directories
      "migrations"  // Add migration files
    ]
  }
}
```

3. **Use incremental updates:**
```bash
# Instead of full re-index
agent-memory watch  # Only processes changed files
```

### Issue: Docker Volume Permission Errors

**Symptom:**
```
Permission denied: /data/neo4j
```

**Solution:**
```bash
# Fix volume permissions
sudo chown -R 7474:7474 /var/lib/docker/volumes/neo4j_data

# Or recreate volumes
docker-compose down -v
docker-compose up -d
```

### Issue: MCP Server Not Found by Clients

**Symptom:**
Claude Desktop/Cursor can't connect to the MCP server.

**Solutions:**

1. **Check server is running:**
```bash
agent-memory serve

# Should see: 🧠 Starting MCP Interface on port 8000
```

2. **Verify port is not in use:**
```bash
# Linux/macOS
lsof -i :8000

# Windows
netstat -an | findstr 8000
```

3. **Check client configuration:**
- See [MCP_INTEGRATION.md](MCP_INTEGRATION.md) for proper setup

### Getting Help

If none of these solutions work:

1. **Check logs:**
```bash
# Neo4j logs
docker-compose logs neo4j

# Agentic Memory logs
agent-memory --verbose
```

2. **Enable debug logging:**
```bash
export LOG_LEVEL=DEBUG
agent-memory index
```

3. **Report issues:**
- GitHub Issues: https://github.com/jarmen423/agentic-memory/issues
- Include: OS, Python version, Neo4j version, error messages

---

## Next Steps

After successful installation:

1. **Read [MCP_INTEGRATION.md](MCP_INTEGRATION.md)** - Connect to AI clients
2. **Read [ARCHITECTURE.md](ARCHITECTURE.md)** - Understand the system design
3. **See [examples/](../examples/)** - Usage examples and prompts
4. **Join the community** - Share feedback and contribute

---

## Quick Reference

```bash
# Install
pipx install agent-memory-labs

# Initialize
agent-memory init

# Status
agent-memory status

# Index
agent-memory index

# Watch
agent-memory watch

# Search
agent-memory search "query"

# MCP Server
agent-memory serve
```

For CLI command details, see [API.md](API.md#cli-commands).
