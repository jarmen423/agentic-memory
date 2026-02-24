# Troubleshooting

Common issues and solutions when using Agentic Memory.

---

## Table of Contents

- [Installation Issues](#installation-issues)
- [Neo4j Connection Issues](#neo4j-connection-issues)
- [Indexing Issues](#indexing-issues)
- [MCP Server Issues](#mcp-server-issues)
- [Performance Issues](#performance-issues)

---

## Installation Issues

### `pip install` fails with build errors

**Symptom:** Error during installation, especially with tree-sitter packages.

**Solution:**
```bash
# Make sure you have Python 3.10+
python --version

# Install build tools
# On Ubuntu/Debian:
sudo apt-get install python3-dev build-essential

# On macOS:
xcode-select --install

# Use a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install codememory
```

### `codememory: command not found`

**Symptom:** Command not found after installation.

**Solution:**
```bash
# If using pip, ensure ~/.local/bin is in your PATH
export PATH="$HOME/.local/bin:$PATH"

# Or use pipx for isolated installation (recommended)
pipx install codememory
```

---

## Neo4j Connection Issues

### "Failed to connect to Neo4j"

**Symptom:** `Connection refused` or `Failed to establish connection` error.

**Solutions:**

1. **Check Neo4j is running:**
```bash
# Using Docker:
docker ps | grep neo4j

# Start if not running:
docker-compose up -d neo4j
# or
docker run -p 7474:7474 -p 7687:7687 neo4j:5.25
```

2. **Verify connection details:**
```bash
# Check your config
cat .codememory/config.json

# Test connection manually
curl http://localhost:7474
```

3. **Neo4j Aura users:** Make sure your Aura instance is running and you have the correct connection string (`neo4j+s://...`).

### "Authentication failed"

**Symptom:** `Unauthorized` or authentication error.

**Solution:**
```bash
# For local Neo4j, default password is "password" (change this!)
# Reset password via Neo4j browser at http://localhost:7474

# For Aura, copy password from Aura console
# Update config:
codememory init
```

### "Vector index not found"

**Symptom:** Error about missing `code_embeddings` index.

**Solution:**
```bash
# Re-run indexing to recreate indexes
codememory index

# Or manually in Neo4j Browser:
CALL db.index.vector.drop('code_embeddings');
# Then re-run: codememory index
```

---

## Indexing Issues

### "OpenAI API key not found"

**Symptom:** Semantic search doesn't work, errors about missing API key.

**Solution:**
```bash
# Option 1: Set environment variable
export OPENAI_API_KEY="sk-..."

# Option 2: Add to config
codememory init
# Choose option 1 to enter API key

# Verify:
codememory search "test"
```

### "No files indexed"

**Symptom:** `codememory status` shows 0 files.

**Solutions:**

1. **Check file extensions:**
```bash
# Verify your repo has supported files
find . -name "*.py" -o -name "*.js" -o -name "*.ts"

# Check config
cat .codememory/config.json | grep extensions
```

2. **Check ignore patterns:**
```bash
# You might be ignoring too much
cat .codememory/config.json | grep ignore_dirs
```

3. **Re-run indexing:**
```bash
codememory index
```

### Indexing is very slow

**Symptom:** Indexing takes hours for large codebases.

**Solutions:**

1. **Reduce extensions** - Only index what you need:
```json
{
  "indexing": {
    "extensions": [".py"]
  }
}
```

2. **Check OpenAI rate limits:** You may be hitting rate limits. The code automatically retries, but it slows things down.

3. **Use a smaller repository for testing:**
```bash
codememory init
# Only point to a subdirectory during init
```

---

## MCP Server Issues

### "MCP server not responding"

**Symptom:** AI agent can't connect to MCP server.

**Solutions:**

1. **Check server is running:**
```bash
codememory serve
# Should see: "🧠 Starting MCP Interface"
```

2. **Verify port:**
```bash
# Check if port 8000 is in use
netstat -an | grep 8000  # Linux/macOS
netstat -an | findstr 8000  # Windows

# Use different port:
codememory serve --port 8001
```

3. **Check MCP configuration:**

   **Claude Desktop:**
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

   If `--repo` is not recognized, update to a release that includes explicit repo targeting,
   or temporarily run from repo root / use client `cwd`.

   Make sure `codememory` is in your PATH.

### "Tools not available in agent"

**Symptom:** Agent doesn't show Agentic Memory tools.

**Solutions:**

1. **Restart the AI agent** after starting MCP server.

2. **Check server logs:**
```bash
codememory serve
# Look for: "✅ Connected to Neo4j"
```

3. **Verify config is found:**
```bash
# Run from your repo directory
cd /path/to/your/repo
codememory serve

# Should see: "📂 Using config from: .codememory/config.json"
```

---

## Performance Issues

### High OpenAI costs

**Symptom:** Embedding costs add up quickly.

**Solutions:**

1. **Only index what changes:** Use `codememory watch` instead of full re-indexes.

2. **Check cost after indexing:**
```bash
codememory index
# Look for: "💰 Estimated Cost: $X.XX USD"
```

3. **Skip semantic search:** You can still use structural queries (dependencies, impact) without embeddings.

### Slow semantic search

**Symptom:** `codememory search` takes more than a few seconds.

**Solutions:**

1. **Check Neo4j performance:**
```bash
# Open Neo4j Browser: http://localhost:7474
# Run: CALL db.index.vector.list()
# Should show: code_embeddings
```

2. **Reduce result limit:**
```bash
codememory search "query" --limit 3
```

3. **Neo4j might need more RAM:**
```yaml
# docker-compose.yml:
services:
  neo4j:
    environment:
      NEO4J_dbms_memory_heap_max__size: 4G  # Increase from 2G
```

---

## Getting More Help

If you're still stuck:

1. **Check logs:**
```bash
# Enable verbose logging
codememory index 2>&1 | tee debug.log
```

2. **Verify your setup:**
```bash
codememory status
```

3. **Report issues:**
   - GitHub: https://github.com/jarmen423/agentic-memory/issues
   - Include: OS, Python version, error message, config file (redacted)

4. **Community:**
   - Check existing issues
   - Discussions tab on GitHub

---

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `ModuleNotFoundError: No module named 'codememory'` | Not installed or in wrong venv | `pip install codememory` |
| `Neo4j timeout` | Neo4j not responding | Restart Neo4j: `docker-compose restart neo4j` |
| `OpenAI rate limit` | Too many embedding requests | Wait 60s, re-run; costs should still be low |
| `File not found in graph` | File not indexed yet | Run `codememory index` |
| `Path not found` | Wrong working directory | Run from repo root where `.codememory/` exists |
