# Basic Usage Examples

This guide provides practical examples for using Agentic Memory in everyday development workflows.

## Table of Contents

- [Initial Setup](#initial-setup)
- [Everyday Commands](#everyday-commands)
- [Common Workflows](#common-workflows)
- [Real-World Scenarios](#real-world-scenarios)

---

## Initial Setup

### Example 1: Setting Up a New Project

**Scenario:** You just cloned a new Python project and want to index it.

```bash
# Navigate to project
cd ~/projects/my-api

# Initialize Agentic Memory
codememory init

# Follow the interactive wizard:
# 1. Choose Neo4j setup (Docker recommended)
# 2. Enter OpenAI API key
# 3. Select file extensions (.py for Python project)
# 4. Run initial indexing (Y)

# Check status
codememory status

# Expected output:
# 📊 Agentic Memory Status
# Repository: /home/user/projects/my-api
# 📈 Graph Statistics:
#    Files:     45
#    Functions: 234
#    Classes:   38
```

---

### Example 2: Starting from Scratch (Manual Config)

**Scenario:** You prefer manual configuration over the wizard.

```bash
# Create .env file
cat > .env << EOF
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=secure_password
OPENAI_API_KEY=sk-your-api-key-here
EOF

# Start Neo4j (Docker)
docker run -d \
  --name my-neo4j \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/secure_password \
  neo4j:5.25-community

# Wait for Neo4j to start
sleep 10

# Run indexing
codememory index

# Output:
# 🚀 Starting Hybrid GraphRAG Ingestion
# ⏱️  Total Time: 32.15 seconds
# 💰 Estimated Cost: $0.0082 USD
# ✅ Graph is ready for Agent retrieval.
```

---

## Everyday Commands

### Check Repository Health

```bash
$ codememory status

📊 Agentic Memory Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Repository: /home/user/projects/my-api
Config:     /home/user/projects/my-api/.codememory/config.json

📈 Graph Statistics:
   Files:     45
   Functions: 234
   Classes:   38
   Chunks:    272
   Last sync: 2025-02-09 15:42:18
```

**What this tells you:**
- Graph is healthy and populated
- Last update was recent
- Ready for AI agent queries

---

### Quick Semantic Search

```bash
$ codememory search "database connection handling"

Found 5 result(s):

1. **get_db_connection** [`src/db.py:get_db_connection`] - Score: 0.91
   ```
   def get_db_connection():
       """Get database connection from pool"""
       conn = pool.getconn()
       try:
           yield conn
       finally:
           pool.putconn(conn)
   ```

2. **Database** [`src/models.py:Database`] - Score: 0.85
   ```
   class Database:
       """Database connection manager"""
       def __init__(self, url: str):
           self.url = url
           self.pool = None
   ```

3. **connect** [`src/db.py:connect`] - Score: 0.79
   ```
   async def connect():
       """Establish async database connection"""
       return await asyncpg.connect(DATABASE_URL)
   ```

[... 2 more results]
```

---

### Continuous Monitoring

**Scenario:** You're actively developing and want real-time updates.

```bash
# Terminal 1: Start watcher
codememory watch

# Output:
# 👀 Starting Observer on: /home/user/projects/my-api
# 🚀 Running initial full pipeline...
# ✅ Initial scan complete. Watching for changes...

# [You edit src/auth.py in your editor]
# Output:
# ♻️  Change detected: src/auth.py
# ✅ Updated graph for: src/auth.py

# [You create new file src/utils/helpers.py]
# Output:
# ➕ New file detected: src/utils/helpers.py
# ✅ Indexed new file: src/utils/helpers.py
```

**Press Ctrl+C to stop watching.**

---

## Common Workflows

### Workflow 1: Understanding Legacy Code

**Scenario:** You just joined a team and need to understand the authentication system.

```bash
# Step 1: Find authentication-related code
codememory search "authentication login user session"

# Step 2: Get file dependencies for main auth file
codememory search --limit 1 "authentication" | grep -o '`src/[^`]*' | head -1

# Let's say it returns src/auth.py

# Now check what depends on auth (manual inspection via Neo4j browser)
# Open http://localhost:7474
# Run: MATCH (f:File {path: "src/auth.py"})<-[:IMPORTS]-(dep) RETURN dep.path
```

**With MCP (Claude Desktop):**

> "Use agentic-memory to find all files related to user authentication. Show me how the login flow works from request to response."

**Claude will:**
1. Call `search_codebase` for "authentication login"
2. Call `get_file_dependencies` for each relevant file
3. Build a mental model of the flow
4. Explain it in natural language

---

### Workflow 2: Safe Refactoring

**Scenario:** You want to rename `User` model to `Account` and need to know what will break.

```bash
# Step 1: Find the User model
codememory search "class User model database"

# Step 2: Identify impact
# (Manual Cypher query)
cypher-shell -u neo4j -p password

# In Cypher shell:
MATCH (f:File {path: "src/models/user.py"})<-[:IMPORTS*1..3]-(dependent)
RETURN dependent.path, length(path) as depth
ORDER BY depth, dependent.path;

# Output:
# src/services/user.py        depth: 1
# src/api/routes/users.py     depth: 1
# src/api/routes/auth.py      depth: 2
# src/tests/test_users.py     depth: 2
# ...

# Step 3: Make changes systematically
# 1. Rename class in src/models/user.py
# 2. Update all depth 1 dependencies
# 3. Update all depth 2 dependencies
# ...
```

**With MCP (Claude Desktop):**

> "Use agentic-memory to identify what would break if I rename the User model to Account. Show me all affected files organized by dependency depth."

**Claude will:**
1. Call `identify_impact` on `src/models/user.py`
2. Receive organized list of 42 affected files
3. Suggest a refactoring strategy
4. Offer to create a checklist

---

### Workflow 3: Debugging Production Issues

**Scenario:** Production error: "AttributeError: 'NoneType' object has no attribute 'id'". Find where this could originate.

```bash
# Step 1: Search for code that returns None
codememory search "function returns None null"

# Step 2: Search for .id access patterns
codememory search "access id attribute property"

# Step 3: Combine results manually
# Or use Neo4j Browser for visual exploration

# Better: Use MCP with AI reasoning
```

**With MCP (Claude Desktop):**

> "Use agentic-memory to find all functions that could return None when looking up a user by ID. The error is 'NoneType' object has no attribute 'id'."

**Claude will:**
1. Search for "get user by id lookup"
2. Get file dependencies for found functions
3. Trace call chains
4. Identify potential None returns
5. Suggest fixes

---

### Workflow 4: Onboarding New Team Members

**Scenario:** New developer asks "Where do I add a new API endpoint?"

```bash
# You search for existing API endpoints
codememory search "API endpoint route handler"

# You find: src/api/routes/users.py
# Check its structure
codememory search "API route decorator Flask FastAPI" --limit 5

# With Claude, you can explain:
# "Use agentic-memory to show me the structure of API routes in this project.
#  Find an example endpoint and explain how routes are organized."
```

**Claude's response:**
1. Calls `search_codebase` for "API route handler"
2. Calls `get_file_info` for found files
3. Explains routing pattern
4. Provides template for new endpoint

---

## Real-World Scenarios

### Scenario 1: Microservices Architecture

**Context:** You have 10 microservices in a monorepo.

```bash
# Initialize at monorepo root
cd ~/projects/monorepo
codememory init

# After indexing, explore service boundaries
codememory search "service API endpoint microservice"

# Find service dependencies
# (In Neo4j Browser)
MATCH (s1:File)-[:IMPORTS]->(s2:File)
WHERE s1.path CONTAINS "services/" AND s2.path CONTAINS "services/"
RETURN s1.path, s2.path
```

**Use case:** Identify which services are tightly coupled and should be merged or split.

---

### Scenario 2: Finding Unused Code

**Context:** You want to remove dead code to reduce maintenance burden.

```bash
# Find functions that are never called
# (In Neo4j Browser)
MATCH (f:Function)
WHERE NOT (f)<-[:CALLS]-()
RETURN f.signature, f.path
ORDER BY f.path

# Output:
# src/legacy.py:old_authenticate
# src/utils/deprecated.py:md5_hash
# src/models/v1.py:UserV1
```

**With MCP:**

> "Use agentic-memory to find all functions that are never called by other functions. These might be dead code."

---

### Scenario 3: Security Audit

**Context:** You need to find all database queries to check for SQL injection.

```bash
# Search for database queries
codememory search "SQL query execute database cursor"

# Get files with queries
codememory search "SELECT INSERT UPDATE DELETE" --limit 20

# With Claude:
> "Use agentic-memory to find all functions that execute SQL queries.
#  I need to audit them for SQL injection vulnerabilities."
```

**Claude will:**
1. Find query execution functions
2. Get file info to understand context
3. Identify parameterized vs string-concatenated queries
4. Flag potential security issues

---

### Scenario 4: Performance Investigation

**Context:** API is slow, suspect N+1 query problem.

```bash
# Find database queries in request handlers
codememory search "API handler request database query"

# With Claude:
> "Use agentic-memory to trace the call chain from the /users endpoint
#  to any database queries. I suspect N+1 queries."

**Claude will:**
1. Find the `/users` endpoint handler
2. Call `identify_impact` to see what it calls
3. Trace function calls to database queries
4. Identify if queries are in loops
5. Suggest optimization strategy
```

---

### Scenario 5: Documentation Generation

**Context:** You need to generate API documentation.

```bash
# Find all API endpoints
codememory search "API endpoint route handler" --limit 50

# Extract function signatures
# (In Neo4j Browser)
MATCH (f:Function)
WHERE f.signature CONTAINS "routes"
RETURN f.signature, f.docstring

# Output:
# src/api/routes/users.py:get_user - Get user by ID
# src/api/routes/users.py:list_users - List all users
# src/api/routes/users.py:create_user - Create new user
```

**With MCP:**

> "Use agentic-memory to find all public API endpoints and their docstrings.
#  Generate a table of endpoints with descriptions."

---

### Scenario 6: Migration Planning

**Context:** Migrating from Flask to FastAPI.

```bash
# Find all Flask-specific code
codememory search "Flask route decorator request response"

# Identify Flask imports
codememory search "import from flask"

# With Claude:
> "Use agentic-memory to identify all files that depend on Flask.
#  I need to know what needs to be rewritten for FastAPI migration."

**Claude will:**
1. Call `search_codebase` for "Flask"
2. Call `get_file_dependencies` for each file
3. Call `identify_impact` to see ripple effects
4. Prioritize migration order
5. Estimate effort
```

---

## Tips and Tricks

### Tip 1: Combine Search with Grep

```bash
# Find function with semantic search
codememory search "validate user input" --limit 1

# Then use grep to find all usages
grep -r "validate_user" src/
```

### Tip 2: Export Search Results

```bash
# Save to file
codememory search "authentication" > auth_results.txt

# Process with other tools
cat auth_results.txt | jq .  # If formatted as JSON
```

### Tip 3: Visual Exploration

**Use Neo4j Browser for visual graph exploration:**

1. Open http://localhost:7474
2. Run queries like:
```cypher
// Show import graph
MATCH (f1:File)-[:IMPORTS]->(f2:File)
RETURN f1, f2
LIMIT 100

// Show call graph
MATCH (fn1:Function)-[:CALLS]->(fn2:Function)
RETURN fn1, fn2
LIMIT 100
```

### Tip 4: Alias Common Commands

```bash
# Add to ~/.bashrc or ~/.zshrc
alias cms='codememory search'
alias cmw='codememory watch'
alias cmi='codememory index'

# Usage:
cms "database connection"  # Faster!
```

### Tip 5: Batch Operations

```bash
# Index multiple repositories
for repo in ~/projects/*/; do
    echo "Indexing $repo"
    cd "$repo"
    codememory index --quiet
done
```

---

## Next Steps

- Explore [MCP Integration Examples](mcp_prompt_examples.md)
- Read [Architecture Documentation](../docs/ARCHITECTURE.md)
- Check [API Reference](../docs/API.md)

---

**Need more examples?** Open a GitHub issue with your use case!
