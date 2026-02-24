# Installation Guide

This guide covers installing and configuring Agentic Memory for local development or production use.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation Methods](#installation-methods)
- [Neo4j Setup](#neo4j-setup)
- [Environment Configuration](#environment-configuration)
- [Initial Setup](#initial-setup)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

| Software | Minimum Version | Recommended | Purpose |
|----------|----------------|-------------|---------|
| **Python** | 3.10 | 3.11+ | Runtime environment |
| **Neo4j** | 5.18 | 5.25+ | Graph database with vector search |
| **OpenAI API Key** | - | - | For semantic embeddings |
| **Git** | 2.0+ | Latest | For version control (optional) |

### System Requirements

- **RAM:** 4GB minimum (8GB recommended for larger codebases)
- **Disk Space:** 500MB for Neo4j + additional space for graph data
- **OS:** Linux, macOS, or Windows 10+

### API Keys Required

- **OpenAI API Key** - Required for semantic search (embeddings)
  - Get yours at: https://platform.openai.com/api-keys
  - Pricing: ~$0.13 per 1M tokens (text-embedding-3-large)
  - Typical cost: $0.50-2.00 for a medium codebase (10K-50K LOC)

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
pipx install codememory

# Verify installation
codememory --version
```

**Advantages:**
- Isolated from system Python
- No dependency conflicts
- Easy to uninstall: `pipx uninstall codememory`

### Method 2: uv / uvx (Global Tooling)

```bash
# Install globally as a Python tool
uv tool install codememory

# Run without installing globally
uvx codememory --help
```

**Advantages:**
- Fast dependency resolution and installs
- Great for ephemeral tool usage via `uvx`

### Method 3: pip (System-wide Installation)

```bash
# Install directly
pip install codememory

# Or with user-only installation
pip install --user codememory
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
codememory --help
```

**Advantages:**
- Can modify source code directly
- Changes take effect immediately
- Ideal for contributors

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
codememory init
```

The wizard will guide you through:
1. Neo4j connection setup
2. OpenAI API key configuration
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

# OpenAI Configuration
OPENAI_API_KEY=sk-your-api-key-here

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
codememory init
```

Follow the interactive prompts:
1. Choose Neo4j setup (Docker, Aura, or custom)
2. Enter OpenAI API key (or use environment variable)
3. Select file extensions to index
4. Run initial indexing

### Step 2: Verify Installation

```bash
# Check status
codememory status

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

### Step 3: Test Semantic Search

```bash
codememory search "where is the auth logic?"

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

### Step 4: Start MCP Server (Optional)

```bash
codememory serve

# Output: 🧠 Starting MCP Interface on port 8000
```

See [MCP_INTEGRATION.md](MCP_INTEGRATION.md) for client configuration.

---

## Troubleshooting

### Issue: "Module not found" Errors

**Symptom:**
```
ModuleNotFoundError: No module named 'codememory'
```

**Solution:**
```bash
# Reinstall the package
pip install --force-reinstall codememory

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

### Issue: OpenAI API Errors

**Symptom:**
```
Error: The OPENAI_API_KEY environment variable is not set
```

**Solutions:**

1. **Set environment variable:**
```bash
# Linux/macOS
export OPENAI_API_KEY="sk-your-key-here"

# Windows (Command Prompt)
set OPENAI_API_KEY=sk-your-key-here

# Windows (PowerShell)
$env:OPENAI_API_KEY="sk-your-key-here"
```

2. **Add to `.env` file:**
```bash
echo "OPENAI_API_KEY=sk-your-key-here" >> .env
```

3. **Verify API key is valid:**
```bash
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
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
codememory watch
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
codememory watch  # Only processes changed files
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
codememory serve

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
codememory --verbose
```

2. **Enable debug logging:**
```bash
export LOG_LEVEL=DEBUG
codememory index
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
pipx install codememory

# Initialize
codememory init

# Status
codememory status

# Index
codememory index

# Watch
codememory watch

# Search
codememory search "query"

# MCP Server
codememory serve
```

For CLI command details, see [API.md](API.md#cli-commands).
