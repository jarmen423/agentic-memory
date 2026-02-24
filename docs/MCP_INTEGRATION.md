# MCP Integration Guide

This guide explains how to integrate Agentic Memory with AI clients using the Model Context Protocol (MCP).

## Table of Contents

- [What is MCP?](#what-is-mcp)
- [Integration Recommendation Policy (PR7)](#integration-recommendation-policy-pr7)
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

## Integration Recommendation Policy (PR7)

Current recommendation policy (as of 2026-02-24):

1. **Default recommendation:** use `mcp_native` integration.
2. **Optional path:** use the `skill_adapter` workflow when you specifically want shell/script-driven operations.
3. **Promotion criteria:** promote `skill_adapter` to first-class only after benchmark parity evidence is recorded.

No new benchmark execution results are included in this PR, so the default remains `mcp_native`.

Evaluation references:

- [Evaluation decision memo](evaluation-decision.md)
- [Benchmark tasks](../evaluation/tasks/benchmark_tasks.json)
- [Metrics schema](../evaluation/schemas/benchmark_results.schema.json)
- [Run scaffold script](../evaluation/scripts/create_run_scaffold.py)
- [Summary script](../evaluation/scripts/summarize_results.py)
- [Skill-adapter workflow doc](../evaluation/skills/skill-adapter-workflow.md)

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
      "args": ["serve", "--repo", "/absolute/path/to/your/project"],
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
      "args": ["serve", "--repo", "/absolute/path/to/your/project"],
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

**Version note:** `--repo` requires the release that adds explicit repo targeting to `codememory serve`.
If your installed version does not support `--repo`, use `cwd` if your client supports it,
or a wrapper script that runs:
```bash
cd /absolute/path/to/your/project && codememory serve
```

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
      "args": ["serve", "--repo", "/absolute/path/to/your/project", "--port", "8000"]
    }
  }
}
```

**Fallback for older versions:** if `--repo` is unavailable in your installed `codememory`, use:
```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "codememory",
      "args": ["serve", "--port", "8000"],
      "cwd": "/absolute/path/to/your/project"
    }
  }
}
```

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
      "args": ["serve", "--repo", "/absolute/path/to/your/project"],
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
    "limit": 5,
    "domain": "code"
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
    limit: 5,
    domain: 'code'
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
    "limit": 5,
    "domain": "code"
})

print(result.content)
```

---

## Available Tools

Agentic Memory supports explicit query routing:
- `domain="code"`: code graph only (default behavior).
- `domain="git"`: git history graph only.
- `domain="hybrid"`: merged code + git signals.

> Compatibility note: some installed builds may not yet include `domain` parameters or git-domain tools.
> If unavailable, continue with code-domain tools and update to a git-enabled release.

### Tool Matrix

| Tool | Domain | Status |
|------|--------|--------|
| `search_codebase(query, limit=5, domain="code")` | code/git/hybrid | code: available, git/hybrid: rollout |
| `get_file_dependencies(file_path, domain="code")` | code/git/hybrid | code: available, git/hybrid: rollout |
| `identify_impact(file_path, max_depth=3, domain="code")` | code/git/hybrid | code: available, git/hybrid: rollout |
| `get_file_info(file_path, domain="code")` | code/git/hybrid | code: available, git/hybrid: rollout |
| `get_git_file_history(file_path, limit=20, domain="git")` | git | rollout |
| `get_commit_context(sha, include_diff_stats=true)` | git | rollout |
| `find_recent_risky_changes(path_or_symbol, window_days, domain="hybrid")` | hybrid | rollout |

### Domain Selection Guide

| If your question is about... | Use |
|------------------------------|-----|
| Current implementation and structure | `domain="code"` |
| Ownership, recency, commit provenance | `domain="git"` |
| Refactoring risk + historical churn | `domain="hybrid"` |

### Core Tool Examples

#### 1. Code-domain semantic search

```python
search_codebase(
    query="Where is the JWT token validation logic?",
    limit=3,
    domain="code",
)
```

#### 2. Git-domain file history (rollout)

```python
get_git_file_history(
    file_path="src/auth/tokens.py",
    limit=10,
    domain="git",
)
```

#### 3. Git-domain commit context (rollout)

```python
get_commit_context(
    sha="9b31ce0",
    include_diff_stats=True,
)
```

#### 4. Hybrid risk scan (rollout)

```python
find_recent_risky_changes(
    path_or_symbol="src/database/connection.py",
    window_days=30,
    domain="hybrid",
)
```

#### 5. Impact analysis with explicit domain

```python
identify_impact(
    file_path="src/models/user.py",
    max_depth=2,
    domain="code",
)
```

## Usage Examples

### Example 1: Code-Only Root Cause Analysis

**Prompt to Claude:**
```
Use agentic-memory with domain=code to find where JWT validation failures are handled.
```

**What happens:**
1. Claude calls `search_codebase(query=..., domain="code")`.
2. Claude follows up with `get_file_dependencies(file_path=..., domain="code")`.
3. You get concrete implementation context and callers/importers.

---

### Example 2: Ownership and Commit Provenance (Git Domain)

**Prompt to Cursor:**
```
Use domain=git to show who changed src/services/payment.py most recently and summarize the commit context.
```

**What happens:**
1. Cursor calls `get_git_file_history(file_path="src/services/payment.py", domain="git")`.
2. Cursor selects a commit SHA from results.
3. Cursor calls `get_commit_context(sha=...)` for message and diff stats.

---

### Example 3: Hybrid Refactor Risk Check

**Prompt to Claude:**
```
Before I refactor src/database/connection.py, run a hybrid risk check over the last 30 days.
```

**What happens:**
1. Claude calls `identify_impact(..., domain="code")` for blast radius.
2. Claude calls `find_recent_risky_changes(..., domain="hybrid")` for churn and recency.
3. You get an ordered risk view before changing critical infrastructure.

---

### Example 4: Codebase Onboarding with Domain Routing

**Prompt to Claude:**
```
Give me a tour of authentication. Start with domain=code, then use domain=git for recent changes.
```

**What happens:**
1. Claude maps structure with `search_codebase(..., domain="code")` and `get_file_info(..., domain="code")`.
2. Claude pivots to `get_git_file_history(..., domain="git")` to show recent ownership/activity.
3. You get both architecture context and change history.

---

### Example 5: Backward-Compatible Fallback

If your build does not support `domain` yet:
1. Call `search_codebase`, `get_file_dependencies`, `identify_impact`, and `get_file_info` without `domain`.
2. Keep workflows code-only.
3. Upgrade to a git-enabled build to use git/hybrid routing.

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

2. **Preferred: set explicit repo in args (newer versions):**
```json
{
  "mcpServers": {
    "agentic-memory": {
      "command": "codememory",
      "args": ["serve", "--repo", "/absolute/path/to/your/project"]
    }
  }
}
```

3. **Fallback for older versions: set `cwd` in client config:**
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

4. **Or use environment variables:**
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
1. `search_codebase(..., domain="code")` to find relevant files
2. `get_file_dependencies(..., domain="code")` to understand context
3. `identify_impact(..., domain="code")` for blast radius
4. `get_git_file_history(..., domain="git")` when ownership/history is needed
5. `find_recent_risky_changes(..., domain="hybrid")` for recent churn risk

### 4. Verify Before Major Changes

Before refactoring:
```bash
codememory search "function_name"
codememory impact path/to/file.py
# Optional git graph sync (git-enabled builds)
codememory git-sync --repo /absolute/path/to/repo --incremental
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
| `search_codebase` | Semantic retrieval with domain routing | `search_codebase(query="auth", domain="code")` |
| `get_file_dependencies` | Dependency graph lookup | `get_file_dependencies(file_path="src/auth.py", domain="code")` |
| `identify_impact` | Transitive blast radius | `identify_impact(file_path="src/models/user.py", domain="code")` |
| `get_file_info` | File structure overview | `get_file_info(file_path="src/app.py", domain="code")` |
| `get_git_file_history` | File commit history and ownership | `get_git_file_history(file_path="src/app.py", domain="git")` |
| `get_commit_context` | Commit message + diff stats | `get_commit_context(sha="9b31ce0")` |
| `find_recent_risky_changes` | Hybrid churn + structural risk | `find_recent_risky_changes(path_or_symbol="src/db.py", domain="hybrid")` |
