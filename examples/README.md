# Agentic Memory Examples

This directory contains practical examples for using Agentic Memory.

---

## Quick Links

| Example | Description |
|---------|-------------|
| **[Basic Usage](basic_usage.md)** | Get started with your first repository |
| **[Docker Setup](docker_setup.md)** | Run Neo4j and Agentic Memory with Docker |
| **[MCP Prompt Examples](mcp_prompt_examples.md)** | Example prompts for AI agents using Agentic Memory tools |

---

## Example Workflow

Here's a typical workflow for using Agentic Memory:

```bash
# 1. Install globally (once)
pipx install agentic-memory

# 2. Start Neo4j (once per session)
docker-compose up -d neo4j

# 3. Initialize in your repository
cd /path/to/your/repo
codememory init

# 4. Check status
codememory status

# 5. Start continuous monitoring
codememory watch

# In another terminal, start MCP server for AI agents
codememory serve
```

---

## What You'll Learn

### Basic Usage ([`basic_usage.md`](basic_usage.md))

- **First-time setup** - Interactive configuration wizard
- **Common commands** - `status`, `index`, `watch`, `serve`, `search`
- **Configuration** - Understanding `.codememory/config.json`
- **Example output** - What to expect from each command

**Best for:** First-time users, understanding the core workflow

### Docker Setup ([`docker_setup.md`](docker_setup.md))

- **Quick start** - One-command Neo4j setup
- **Docker Compose** - Complete stack with Agentic Memory services
- **Neo4j Browser** - Explore your code graph visually
- **Troubleshooting** - Common Docker issues

**Best for:** Users who prefer containerized environments, team deployments

### MCP Prompt Examples ([`mcp_prompt_examples.md`](mcp_prompt_examples.md))

- **Semantic search** - Natural language code queries
- **Impact analysis** - Understanding change blast radius
- **Dependency exploration** - Finding imports and dependents
- **File structure** - Getting file overviews

**Best for:** AI agent users, prompt engineering, integration testing

---

## Example Repository

If you want to test Agentic Memory without using your own codebase:

```bash
# Clone a sample repository
git clone https://github.com/jarmen423/agentic-memory.git /tmp/test-repo
cd /tmp/test-repo

# Initialize
codememory init

# Test semantic search
codememory search "where is the MCP server?"
codememory search "how does the file watcher work?"
```

---

## Tips for Learning

1. **Start small** - Use a small repository for your first test
2. **Check status often** - `codememory status` shows you what's indexed
3. **Use Neo4j Browser** - Visualizing the graph helps understanding (http://localhost:7474)
4. **Read the output** - Indexing shows cost and progress
5. **Experiment with prompts** - Try different queries in `codememory search`

---

## Next Steps

After working through these examples:

- 📖 Read the [full documentation](../docs/)
- 🔧 Learn about the [architecture](../docs/ARCHITECTURE.md)
- 🤖 Set up [MCP integration](../docs/MCP_INTEGRATION.md)
- 🐛 Check [troubleshooting](../docs/TROUBLESHOOTING.md) if you hit issues

---

## Contributing Examples

Have a great example to share? Contributions welcome!

- Fork the repository
- Add your example to `examples/`
- Submit a pull request

Examples should be:
- ✅ Self-contained (can run independently)
- ✅ Well-commented
- ✅ Tested on real codebases
- ✅ Following the existing format
