# Troubleshooting

Common issues and solutions when using Agentic Memory.

---

## Table of Contents

- [Installation Issues](#installation-issues)
- [Neo4j Connection Issues](#neo4j-connection-issues)
- [Indexing Issues](#indexing-issues)
- [MCP Server Issues](#mcp-server-issues)
- [Git Graph Issues](#git-graph-issues)
- [Integration Path Policy](#integration-path-policy)
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
pip install agentic-memory
```

### `agentic-memory: command not found`

**Symptom:** Command not found after installation.

**Solution:**
```bash
# If using pip, ensure ~/.local/bin is in your PATH
export PATH="$HOME/.local/bin:$PATH"

# Or use pipx for isolated installation (recommended)
pipx install agentic-memory
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
agentic-memory init
```

### "Vector index not found"

**Symptom:** Error about missing `code_embeddings` index.

**Solution:**
```bash
# Re-run indexing to recreate indexes
agentic-memory index

# Or manually in Neo4j Browser:
CALL db.index.vector.drop('code_embeddings');
# Then re-run: agentic-memory index
```

---

## Indexing Issues

### "Configured code embedding API key not found"

**Symptom:** Semantic search doesn't work, errors about missing API key.

**Solution:**
```bash
# Option 1: Default Gemini path
export GEMINI_API_KEY="your-gemini-key"
# or
export GOOGLE_API_KEY="your-gemini-key"

# Option 2: Keep code separate on OpenAI instead
export CODE_EMBEDDING_PROVIDER="openai"
export OPENAI_API_KEY="sk-..."

# Option 3: Add the provider key through init
agentic-memory init
# Choose the code embedding provider and then enter the matching key

# Verify:
agentic-memory search "test"
```

### Mixed code embedding providers in one Neo4j

**Symptom:** Search results feel cross-contaminated when different codebases share
one Neo4j but use different code embedding providers.

**Cause:** Current code retrieval queries the shared `code_embeddings` vector
index directly and does not namespace results by repo or provider.

**Solution:**
- Keep all codebases on the same code embedding provider when they share one Neo4j code index.
- Or use separate Neo4j databases / instances for codebases that use different code embedding providers.
- Do not rely on matching dimensions alone. OpenAI and Gemini vectors can both be 3072d while still living in incompatible embedding spaces.

### "No files indexed"

**Symptom:** `agentic-memory status` shows 0 files.

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
agentic-memory index
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

2. **Check embedding provider rate limits:** You may be hitting Gemini, OpenAI, or other provider limits. The code retries some transient failures, but rate limiting still slows indexing down.

3. **Use a smaller repository for testing:**
```bash
agentic-memory init
# Only point to a subdirectory during init
```

4. **Remember the new default behavior:** Normal `agentic-memory index` now stops
   after structural graph construction. If you are waiting for repo-wide
   `CALLS`, that no longer happens automatically. Use:
```bash
agentic-memory build-calls
```
   only when you explicitly want the older experimental repo-wide `CALLS` path.

### "I need to know what one function calls"

**Symptom:** You do not want a full repo-wide call graph. You want to inspect
one function's likely execution neighborhood.

**Solution:**
```bash
agentic-memory trace-execution src/app.py:run_checkout --json
```

**Notes:**
- prefer an exact `path:qualified_name` signature when possible
- if the symbol is ambiguous, the command will return candidates instead of guessing
- use `--force-refresh` if you want to bypass a valid cached trace

---

## MCP Server Issues

### "MCP server not responding"

**Symptom:** AI agent can't connect to MCP server.

**Solutions:**

1. **Check server is running:**
```bash
agentic-memory serve
# Should see: "🧠 Starting MCP Interface"
```

2. **Verify port:**
```bash
# Check if port 8000 is in use
netstat -an | grep 8000  # Linux/macOS
netstat -an | findstr 8000  # Windows

# Use different port:
agentic-memory serve --port 8001
```

3. **Check MCP configuration:**

   **Claude Desktop:**
   ```json
   {
     "mcpServers": {
       "agentic-memory": {
         "command": "agentic-memory",
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
agentic-memory serve
# Look for: "✅ Connected to Neo4j"
```

3. **Verify config is found:**
```bash
# Run from your repo directory
cd /path/to/your/repo
agentic-memory serve

# Should see: "📂 Using config from: .codememory/config.json"
```

---

## Git Graph Issues

### `invalid choice: 'git-init'` (or `git-sync`, `git-status`)

**Symptom:** CLI does not recognize git graph commands.

**Cause:** Installed package version does not include git graph command surfaces yet.

**Solution:**
```bash
agentic-memory --help
# Verify git-init/git-sync/git-status appear under commands
```

If missing, upgrade to a git graph-enabled release/build.

### `Not a git repository`

**Symptom:** `git-init` or `git-sync` fails because repo metadata cannot be found.

**Solution:**
```bash
agentic-memory git-init --repo /absolute/path/to/repo --mode local --full-history
# Confirm /absolute/path/to/repo contains a .git directory
```

### `git-sync` runs but reports zero work

**Symptom:** Sync completes with no new commits.

**Expected when no history delta:**
```text
✅ Git sync complete
Mode: incremental
New commits: 0
```

**Action:** create or fetch new commits, then re-run incremental sync.

### `partial_history: true` in `git-status`

**Symptom:** status indicates incomplete history coverage.

**Cause:** shallow clone or detached history.

**Solution:**
```bash
git fetch --unshallow
agentic-memory git-sync --repo /absolute/path/to/repo --full
```

### Sync errors after force push / rewritten history

**Symptom:** checkpoint no longer matches reachable commit graph.

**Solution:**
```bash
agentic-memory git-sync --repo /absolute/path/to/repo --full
```

If your build exposes reconcile flags, use `agentic-memory git-sync --help` and run the documented reconcile mode.

### GitHub enrichment fails, local ingestion should still proceed

**Symptom:** GitHub API auth/rate-limit errors during `local+github` mode.

**Expected behavior:** local git ingestion still succeeds; enrichment is marked stale/disabled in status.

**Action:**
- Verify provider token and repository mapping.
- Re-run `git-sync` later; do not block local-only ingestion.

---

## Integration Path Policy

### Should I use `mcp_native` or `skill_adapter`?

Use `mcp_native` as the recommended default.

Use `skill_adapter` only when you need script-driven/operator workflow control.
It remains optional until benchmark parity is demonstrated.

Policy and benchmark references:

- [Integration decision memo](evaluation-decision.md)
- [Evaluation harness overview](../evaluation/README.md)
- [Benchmark tasks](../evaluation/tasks/benchmark_tasks.json)
- [Metrics schema](../evaluation/schemas/benchmark_results.schema.json)
- [Skill-adapter workflow doc](../evaluation/skills/skill-adapter-workflow.md)

If both workflows eventually meet parity targets, documentation can promote them
as first-class options. Until then, keep `mcp_native` as default.

---

## Performance Issues

### High embedding-provider costs

**Symptom:** Embedding costs add up quickly.

**Solutions:**

1. **Only index what changes:** Use `agentic-memory watch` instead of full re-indexes.

2. **Check cost after indexing:**
```bash
agentic-memory index
# Look for: "💰 Estimated Cost: $X.XX USD"
```

3. **Skip semantic search:** You can still use structural queries (dependencies, impact) without embeddings.

### Slow semantic search

**Symptom:** `agentic-memory search` takes more than a few seconds.

**Solutions:**

1. **Check Neo4j performance:**
```bash
# Open Neo4j Browser: http://localhost:7474
# Run: CALL db.index.vector.list()
# Should show: code_embeddings
```

2. **Reduce result limit:**
```bash
agentic-memory search "query" --limit 3
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
agentic-memory index 2>&1 | tee debug.log
```

2. **Verify your setup:**
```bash
agentic-memory status
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
| `ModuleNotFoundError: No module named 'agentic_memory'` | Not installed or in wrong venv | `pip install agentic-memory` |
| `Neo4j timeout` | Neo4j not responding | Restart Neo4j: `docker-compose restart neo4j` |
| `Embedding provider rate limit` | Too many embedding requests | Wait 60s, re-run; verify the configured provider key and quota |
| `File not found in graph` | File not indexed yet | Run `agentic-memory index` |
| `Path not found` | Wrong working directory | Run from repo root where `.codememory/` exists |
