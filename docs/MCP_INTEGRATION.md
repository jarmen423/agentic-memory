# MCP Integration Guide

This guide explains how to integrate Agentic Memory with AI clients using the Model Context Protocol (MCP).

## Table of Contents

- [What is MCP?](#what-is-mcp)
- [Starting the MCP Server](#starting-the-mcp-server)
- [Client Configuration](#client-configuration)
- [Available Tools](#available-tools)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)

---

## What is MCP?

The **Model Context Protocol (MCP)** is a standardized protocol for connecting AI assistants to external tools and data sources. With MCP, Agentic Memory exposes high-level "skills" to AI agents, allowing them to:

- Search your codebase semantically
- Understand file dependencies
- Analyze the impact of changes
- Navigate complex code relationships

**Benefits:**
- No raw database access required
- Structured, LLM-friendly responses
- Works across multiple AI platforms
- Secure and controlled

---

## Starting the MCP Server

### Prerequisites

1. **Agentic Memory installed:** See [INSTALLATION.md](INSTALLATION.md)
2. **Repository initialized:** Run `codememory init` in your project
3. **Neo4j running:** The server requires a live connection

### Start the Server

```bash
# In your project directory
cd /path/to/your/project

# Start MCP server (default port 8000)
codememory serve

# Custom port
codememory serve --port 3000
```

**Expected Output:**
```
📂 Using config from: /path/to/project/.codememory/config.json
✅ Connected to Neo4j at bolt://localhost:7687
🚀 Starting Agentic Memory MCP server on port 8000
```

**Note:** The server must remain running while you use AI clients. Keep it in a separate terminal.

### Environment Variables (Optional)

If you don't have a local `.codememory/config.json`, the server will use environment variables:

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
export OPENAI_API_KEY="sk-..."

codememory serve
```

---

## Client Configuration

### Claude Desktop

**Claude Desktop** is the most popular MCP client. Configuration depends on your OS.

#### macOS

1. **Open config directory:**
```bash
open ~/Library/Application\ Support/Claude
```

2. **Edit `claude_desktop_config.json`:**
```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "codememory",
      "args": ["serve"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "OPENAI_API_KEY": "sk-your-api-key-here"
      }
    }
  }
}
```

3. **Restart Claude Desktop**

#### Windows

1. **Open config directory:**
```powershell
notepad "%APPDATA%\Claude\claude_desktop_config.json"
```

2. **Edit config:**
```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "codememory",
      "args": ["serve"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "OPENAI_API_KEY": "sk-your-api-key-here"
      }
    }
  }
}
```

3. **Restart Claude Desktop**

#### Linux

1. **Config location:** `~/.config/Claude/claude_desktop_config.json`

2. **Edit config** (same as macOS above)

#### Verify Claude Desktop Integration

1. Open Claude Desktop
2. Click the "Attachments" or "Tools" icon
3. You should see "agentic-memory" listed
4. Start chatting!

**Example prompts:**
- "Use agentic-memory to find the authentication logic"
- "What files import from `src/utils/helpers.py`?"
- "Show me the impact of changing `User` model"

---

### Cursor IDE

Cursor is a code-focused AI editor with built-in MCP support.

#### Configuration

1. **Open Cursor Settings:**
   - Press `Ctrl+,` (Windows/Linux) or `Cmd+,` (macOS)
   - Or: File > Preferences > Settings

2. **Navigate to MCP settings:**
   - Search for "MCP" in settings
   - Or: Settings > Features > MCP Servers

3. **Add Agentic Memory:**
```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "codememory",
      "args": ["serve", "--port", "8000"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

**Note:** The `cwd` (current working directory) is important - it tells Cursor where to find `.codememory/config.json`.

#### Usage in Cursor

1. **Inline Chat:** Press `Ctrl+K` (Windows/Linux) or `Cmd+K` (macOS)
2. **Prompt examples:**
   ```
   Use agentic-memory to find all files that use the Database class
   ```
   ```
   What would break if I modify src/api/routes.py?
   ```

3. **Sidebar Panel:**
   - Open the AI sidebar
   - Agentic Memory tools appear as available actions
   - Click to run tools directly

#### Keyboard Shortcuts (Custom)

Create custom keybindings in `keybindings.json`:

```json
[
  {
    "key": "ctrl+shift+s",
    "command": "agentic-memory.search",
    "when": "editorTextFocus"
  }
]
```

---

### Windsurf

Windsurf is another AI-powered IDE with MCP support.

#### Configuration

1. **Config location:** `~/.windsurf/mcp_config.json`

2. **Add server:**
```json
{
  "servers": {
    "agentic-memory": {
      "command": "codememory",
      "args": ["serve"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687"
      }
    }
  }
}
```

#### Usage

1. **AI Chat Panel:** Use the built-in chat interface
2. **Code Context:** Right-click code > "Ask AI with Context"
3. **Tool Integration:** Agentic Memory appears in the tools menu

---

### Generic MCP Clients

For custom MCP clients or HTTP-based integrations:

#### HTTP Endpoint

The MCP server runs on `http://localhost:8000` (default).

#### Example with Python

```python
import requests

# Call search_codebase tool
response = requests.post("http://localhost:8000/tools/search_codebase", json={
    "query": "authentication logic",
    "limit": 5
})

results = response.json()
print(results)
```

#### Example with JavaScript/TypeScript

```typescript
const response = await fetch('http://localhost:8000/tools/search_codebase', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    query: 'authentication logic',
    limit: 5
  })
});

const results = await response.json();
console.log(results);
```

#### MCP SDK Integration

For building custom MCP clients:

```python
from mcp import Client

# Connect to server
client = Client()
await client.connect("stdio", command="codememory", args=["serve"])

# Call tools
result = await client.call_tool("search_codebase", {
    "query": "find user authentication",
    "limit": 5
})

print(result.content)
```

---

## Available Tools

Agentic Memory exposes 4 MCP tools to AI agents:

### 1. `search_codebase`

**Purpose:** Semantic search for code functionality

**Parameters:**
- `query` (string, required): Natural language search query
- `limit` (integer, optional): Maximum results (default: 5)

**Example:**
```python
search_codebase(
    query="Where is the JWT token validation logic?",
    limit=3
)
```

**Returns:**
```markdown
Found 3 relevant code result(s):

1. **verify_token** (`src/auth/tokens.py:verify_token`) [Score: 0.94]
   ```
   def verify_token(token: str) -> bool:
       """Verify JWT signature and expiration"""
   ...
   ```

2. **decode_jwt** (`src/auth/utils.py:decode_jwt`) [Score: 0.87]
   ```
   def decode_jwt(encoded: str) -> dict:
       """Decode JWT payload without verification"""
   ...
   ```
```

**Use cases:**
- Finding implementation of specific features
- Locating bug-prone code areas
- Understanding codebase organization

---

### 2. `get_file_dependencies`

**Purpose:** Get imports and dependents for a file

**Parameters:**
- `file_path` (string, required): Relative path to file

**Example:**
```python
get_file_dependencies("src/services/user.py")
```

**Returns:**
```markdown
## Dependencies for `src/services/user.py`

### 📥 Imports (this file depends on):
- `src/models/user.py`
- `src/database/connection.py`
- `src/utils/hash.py`

### 📤 Imported By (files that depend on this):
- `src/api/routes/users.py`
- `src/api/routes/auth.py`
- `src/scripts/migrate_users.py`
```

**Use cases:**
- Understanding module dependencies
- Refactoring without breaking imports
- Identifying tightly coupled code

---

### 3. `identify_impact`

**Purpose:** Blast radius analysis for changes

**Parameters:**
- `file_path` (string, required): Relative path to file
- `max_depth` (integer, optional): Depth for transitive deps (default: 3)

**Example:**
```python
identify_impact(
    file_path="src/models/user.py",
    max_depth=2
)
```

**Returns:**
```markdown
## Impact Analysis for `src/models/user.py`

**Total affected files:** 8

### Depth 1 (direct dependents): 3 files
- `src/services/user.py`
- `src/api/routes/users.py`
- `src/api/routes/auth.py`

### Depth 2 (2-hop transitive dependents): 5 files
- `src/api/routes/admin.py`
- `src/tests/test_users.py`
- `src/tests/test_auth.py`
- `src/scripts/init_db.py`
- `src/controllers/user_controller.py`
```

**Use cases:**
- Assessing risk before refactoring
- Pre-commit impact checks
- Planning incremental changes

---

### 4. `get_file_info`

**Purpose:** Get detailed file structure overview

**Parameters:**
- `file_path` (string, required): Relative path to file

**Example:**
```python
get_file_info("src/services/user.py")
```

**Returns:**
```markdown
## File: `user.py`

**Path:** `src/services/user.py`
**Last Updated:** 2025-02-09 14:32:15

### 📦 Classes (2)
- `UserService`
- `UserProfile`

### ⚡ Functions (5)
- `create_user()`
- `get_user_by_id()`
- `update_user()`
- `delete_user()`
- `list_users()`

### 📥 Imports (3)
- `src/models/user.py`
- `src/database/connection.py`
- `src/utils/hash.py`
```

**Use cases:**
- Quick file overview
- Understanding file organization
- Navigating large codebases

---

## Usage Examples

### Example 1: Finding Bug-Prone Code

**Prompt to Claude:**
```
Use agentic-memory to search for error handling in the authentication flow.
I need to understand how JWT validation failures are handled.
```

**What happens:**
1. Claude calls `search_codebase` with query "JWT validation error handling"
2. Returns relevant functions with high similarity scores
3. Claude reads the code and explains the logic
4. You get context-aware insights without manual searching

---

### Example 2: Safe Refactoring

**Prompt to Cursor:**
```
I want to rename the `User` model to `Account`. Use agentic-memory to identify
all files that would be affected by this change.
```

**What happens:**
1. Cursor calls `identify_impact` on `src/models/user.py`
2. Gets a list of 15 files across 3 depth levels
3. Cursor can now guide you through systematic refactoring
4. Reduce risk of missing dependent files

---

### Example 3: Understanding Legacy Code

**Prompt to Claude:**
```
Use agentic-memory to find all files related to payment processing.
I need to understand how the payment flow works in this legacy codebase.
```

**What happens:**
1. Claude calls `search_codebase` with query "payment processing flow"
2. Gets functions like `process_payment`, `handle_charge`, `refund_transaction`
3. Claude then calls `get_file_dependencies` for each file
4. Builds a mental model of the payment system
5. Provides a detailed explanation of the architecture

---

### Example 4: Impact Analysis Before Commit

**Prompt to Cursor:**
```
I'm about to modify src/database/connection.py. Use agentic-memory to show me
what would break if I introduce a breaking change here.
```

**What happens:**
1. Cursor calls `identify_impact` on `src/database/connection.py`
2. Discovers 42 files depend on this (directly or transitively)
3. Highlights critical paths like authentication, payment processing
4. Suggests testing strategy and rollback plan

---

### Example 5: Onboarding to New Codebase

**Prompt to Claude:**
```
Use agentic-memory to give me a tour of this codebase. Start by finding the main
application entry point and then explore the key components.
```

**What happens:**
1. Claude searches for "main application entry point"
2. Finds `main.py`, `app.py`, or `index.py`
3. Uses `get_file_info` to understand structure
4. Follows `IMPORTS` relationships to map dependencies
5. Builds an interactive "tour" of the architecture

---

## Troubleshooting

### Issue: "Server not found" or Connection Refused

**Symptoms:**
- Client can't connect to MCP server
- "Connection refused" errors
- Tools appear but fail when called

**Solutions:**

1. **Verify server is running:**
```bash
codememory serve

# Should see:
# 🚀 Starting Agentic Memory MCP server on port 8000
```

2. **Check port conflicts:**
```bash
# Check if port 8000 is in use
lsof -i :8000  # Linux/macOS
netstat -an | findstr 8000  # Windows

# Use different port if needed
codememory serve --port 3000
```

3. **Test with HTTP client:**
```bash
curl http://localhost:8000/tools/search_codebase \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "limit": 1}'
```

---

### Issue: Tools Return Empty Results

**Symptoms:**
- `search_codebase` returns "No relevant code found"
- `get_file_dependencies` returns "File not found"

**Solutions:**

1. **Check if repository is indexed:**
```bash
codememory status

# Look for:
# Files:     0  ← This means nothing is indexed!
```

2. **Run initial indexing:**
```bash
codememory index
```

3. **Verify file path format:**
```bash
# Must be relative to project root
get_file_info("src/auth.py")  ✅ Correct
get_file_info("/absolute/path/auth.py")  ❌ Wrong
```

---

### Issue: "Graph not initialized" Error

**Symptoms:**
```
❌ Graph not initialized. Check Neo4j connection.
```

**Solutions:**

1. **Check Neo4j is running:**
```bash
# Docker
docker ps | grep neo4j

# System service
systemctl status neo4j
```

2. **Test Neo4j connection:**
```bash
cypher-shell -u neo4j -p password "RETURN 1"

# Expected: 1
```

3. **Check configuration:**
```bash
cat .codememory/config.json

# Verify NEO4J_URI matches your setup
```

4. **Restart MCP server:**
```bash
# Stop server (Ctrl+C)
# Start again
codememory serve
```

---

### Issue: Semantic Search Returns Poor Results

**Symptoms:**
- Search results don't match query
- Low similarity scores (< 0.5)
- Returns random code

**Solutions:**

1. **Check OpenAI API key:**
```bash
echo $OPENAI_API_KEY

# Should start with: sk-
```

2. **Verify embeddings were created:**
```bash
# Connect to Neo4j
cypher-shell -u neo4j -p password

# Run query
MATCH (ch:Chunk) RETURN count(ch) as total_chunks;

# Should be > 0
```

3. **Re-index if needed:**
```bash
codememory index --force
```

---

### Issue: Claude Desktop Shows "Disconnected"

**Symptoms:**
- Claude Desktop shows "agentic-memory" with red icon
- Hover shows "Disconnected" status

**Solutions:**

1. **Check Claude Desktop logs:**
```bash
# macOS
tail -f ~/Library/Logs/Claude/claude-desktop.log

# Windows
notepad %APPDATA%\Claude\logs\claude-desktop.log
```

2. **Verify config syntax:**
```bash
# Validate JSON
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | jq .

# Should not have syntax errors
```

3. **Check `codememory` is in PATH:**
```bash
which codememory

# Should return: /usr/local/bin/codememory (or similar)
```

4. **Restart Claude Desktop completely:**
```bash
# Quit Claude Desktop (not just close window)
# Kill any remaining processes
pkill Claude

# Restart from Applications
```

---

### Issue: Cursor Can't Find `.codememory/config.json`

**Symptoms:**
```
Warning: No local config found, using environment variables
```

**Solutions:**

1. **Verify config exists:**
```bash
ls -la .codememory/config.json
```

2. **Set `cwd` in Cursor config:**
```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "codememory",
      "args": ["serve"],
      "cwd": "/absolute/path/to/your/project"
    }
  }
}
```

3. **Or use environment variables:**
```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "codememory",
      "args": ["serve"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

---

## Best Practices

### 1. Run Server Continuously

Keep `codememory serve` running in a dedicated terminal while working. This ensures:
- Instant tool responses
- Real-time graph updates
- No startup latency

### 2. Use Specific Queries

Better: "Find JWT token validation in authentication middleware"
Worse: "Show me auth stuff"

### 3. Combine Tools

Use multiple tools together:
1. `search_codebase` to find relevant files
2. `get_file_dependencies` to understand context
3. `identify_impact` to assess changes

### 4. Verify Before Major Changes

Before refactoring:
```bash
codememory search "function_name"
codememory identify-impact path/to/file.py
```

### 5. Keep Index Updated

After significant changes:
```bash
codememory index

# Or use watch mode
codememory watch
```

---

## Advanced Configuration

### Custom Tool Aliases

Create aliases for complex queries in your AI client settings:

```json
{
  "aliases": {
    "find-deps": "get_file_dependencies",
    "blast-radius": "identify_impact"
  }
}
```

### Rate Limiting

To prevent abuse, configure rate limits in `codememory/config.json`:

```json
{
  "mcp": {
    "rate_limit": {
      "requests_per_minute": 60,
      "burst_size": 10
    }
  }
}
```

### Custom Logging

Enable debug logging for troubleshooting:

```bash
export LOG_LEVEL=DEBUG
codememory serve
```

Logs will show:
- Incoming tool calls
- Cypher queries executed
- Timing information
- Error details

---

## Next Steps

- Explore [examples/mcp_prompt_examples.md](../examples/mcp_prompt_examples.md) for more prompts
- Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand graph structure
- See [API.md](API.md#mcp-tools) for complete tool reference

---

## Quick Reference

| Tool | Purpose | Example |
|------|---------|---------|
| `search_codebase` | Semantic search | "Find authentication logic" |
| `get_file_dependencies` | Import graph | What imports `utils.py`? |
| `identify_impact` | Blast radius | What breaks if I change `User` model? |
| `get_file_info` | File overview | Show structure of `app.py` |
