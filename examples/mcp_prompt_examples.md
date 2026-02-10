# MCP Prompt Examples for AI Agents

This guide provides example prompts for AI agents (Claude, Cursor, Windsurf) using Agentic Memory's MCP tools.

## Table of Contents

- [Getting Started](#getting-started)
- [Code Navigation Prompts](#code-navigation-prompts)
- [Refactoring Prompts](#refactoring-prompts)
- [Debugging Prompts](#debugging-prompts)
- [Understanding Codebases](#understanding-codebases)
- [Advanced Multi-Tool Prompts](#advanced-multi-tool-prompts)

---

## Getting Started

### Basic Setup

1. **Start the MCP server:**
```bash
cd /path/to/your/project
codememory serve
```

2. **Verify connection in your AI client:**
   - **Claude Desktop:** Check tools menu for "agentic-memory"
   - **Cursor:** Check MCP servers in settings
   - **Windsurf:** Verify MCP connection status

3. **Try a simple prompt:**
```
Use agentic-memory to search for the main application entry point.
```

**What should happen:**
- AI calls `search_codebase` tool
- Returns main.py, app.py, or index.py
- AI explains what it found

---

## Code Navigation Prompts

### Find Functionality

**Prompt 1: Finding Authentication Logic**
```
Use agentic-memory to find all code related to user authentication and login.
Show me the main authentication functions and where they're located.
```

**AI will:**
1. Call `search_codebase("user authentication login")`
2. Get results with scores and code snippets
3. Call `get_file_info` for each relevant file
4. Summarize authentication flow

**Expected response:**
> "I found several authentication-related functions:
>
> **Primary authentication:**
> - `src/auth.py:authenticate()` - Main authentication function (Score: 0.94)
> - `src/auth/tokens.py:create_access_token()` - JWT token creation (Score: 0.89)
>
> **Login handlers:**
> - `src/api/routes/auth.py:login()` - HTTP login endpoint (Score: 0.87)
> - `src/controllers/auth.py:AuthController.login()` - Controller method (Score: 0.82)
>
> The main flow is: `login()` endpoint → `authenticate()` → `create_access_token()`
> Would you like me to show you the full implementation of any of these?"

---

**Prompt 2: Finding Database Operations**
```
Use agentic-memory to find all functions that interact with the database.
Group them by operation type (CREATE, READ, UPDATE, DELETE).
```

**AI will:**
1. Search for "database query execute"
2. Search for "CRUD operations"
3. Analyze function signatures and docstrings
4. Categorize by operation type

---

### Navigate Dependencies

**Prompt 3: Understanding Module Dependencies**
```
Use agentic-memory to show me what files src/services/user.py depends on
and what files depend on it. I want to understand the coupling.
```

**AI will:**
1. Call `get_file_dependencies("src/services/user.py")`
2. Analyze import relationships
3. Explain upstream and downstream dependencies

**Expected response:**
> "**Dependencies for `src/services/user.py`**:
>
> **📥 Imports (this file depends on):**
> - `src/models/user.py` - User data model
> - `src/database/connection.py` - Database connection
> - `src/utils/hash.py` - Password hashing
>
> **📤 Imported By (files that depend on this):**
> - `src/api/routes/users.py` - User API endpoints
> - `src/api/routes/auth.py` - Authentication endpoints
> - `src/tests/test_users.py` - User tests
>
> This suggests `src/services/user.py` is a core service layer. Changes here would affect
> API endpoints and tests. The coupling is moderate - it depends on models and database,
> and is used by API routes."

---

**Prompt 4: Tracing Data Flow**
```
Use agentic-memory to trace the data flow from when a user creates an account
to when the data is saved in the database. Show me all the functions involved.
```

**AI will:**
1. Search for "create account register user"
2. Get file dependencies for each relevant file
3. Build a mental model of the flow
4. Explain the call chain

---

## Refactoring Prompts

### Impact Analysis

**Prompt 5: Renaming a Model**
```
I want to rename the User model to Account. Use agentic-memory to:
1. Find the User model definition
2. Identify all files that would be affected
3. Organize them by dependency depth
4. Suggest a refactoring strategy
```

**AI will:**
1. Call `search_codebase("class User model")` to find definition
2. Call `identify_impact("src/models/user.py", max_depth=3)`
3. Analyze affected files
4. Create a refactoring plan

**Expected response:**
> "**Impact Analysis for renaming User → Account:**
>
> **Definition found:** `src/models/user.py:User` class
>
> **Affected files:** 23 total
>
> **Depth 1 (Direct dependents):** 5 files
> - `src/services/user.py` - User service layer
> - `src/api/routes/users.py` - User API endpoints
> - `src/controllers/user.py` - User controller
> - `src/repositories/user.py` - User repository
> - `src/factories/user.py` - Test factory
>
> **Depth 2 (2-hop dependents):** 12 files
> - `src/api/routes/auth.py` - Uses user service
> - `src/tests/test_auth.py` - Tests that use User model
> - [...]
>
> **Refactoring Strategy:**
> 1. Rename class in `src/models/user.py`
> 2. Update all depth 1 files (service, API, controller, repository)
> 3. Update all depth 2 files
> 4. Update tests (depth 3)
> 5. Run tests to verify
>
> **Estimated effort:** 1-2 hours. Would you like me to help with the renaming?"

---

**Prompt 6: Extracting a Service**
```
I want to extract payment processing logic into a separate microservice.
Use agentic-memory to:
1. Find all payment-related code
2. Identify dependencies
3. Show what would need to be changed for extraction
```

**AI will:**
1. Search for "payment process charge refund"
2. Get dependencies for each file
3. Identify cross-cutting concerns
4. Outline extraction strategy

---

### Safe Code Changes

**Prompt 7: Changing Function Signature**
```
I want to add a new parameter to the authenticate() function.
Use agentic-memory to find all functions that call authenticate()
so I can update them too.
```

**AI will:**
1. Find `authenticate()` function
2. Search for callers via call graph
3. List all call sites
4. Suggest updates

---

**Prompt 8: Removing Deprecated Code**
```
Use agentic-memory to find functions that are never called by other functions.
These might be dead code that I can safely remove.
```

**AI will:**
1. Query for functions with no incoming CALLS relationships
2. Check if they're part of public APIs
3. Flag potential dead code
4. Suggest safe removal candidates

---

## Debugging Prompts

### Find Bugs

**Prompt 9: Investigating Error**
```
I'm getting "AttributeError: 'NoneType' object has no attribute 'id'"
in production. Use agentic-memory to find all functions that look up users
by ID and could return None. Show me the code so I can add proper error handling.
```

**AI will:**
1. Search for "get user by id lookup find"
2. Analyze function implementations
3. Identify functions that might return None
4. Show code without error handling
5. Suggest fixes

---

**Prompt 10: Race Condition Investigation**
```
I suspect a race condition in order processing. Use agentic-memory to find
all code that updates order status and show me the call chains. I need to
identify where concurrent access might cause issues.
```

**AI will:**
1. Search for "update order status save"
2. Get file dependencies
3. Trace call chains
4. Identify potential race conditions
5. Suggest locking strategies

---

### Performance Investigation

**Prompt 11: N+1 Query Problem**
```
The /users endpoint is slow. Use agentic-memory to trace from the endpoint
handler to any database queries. I suspect there's an N+1 query problem.
```

**AI will:**
1. Find `/users` endpoint handler
2. Trace function calls
3. Identify database queries in the call chain
4. Look for queries in loops
5. Suggest optimization (eager loading, batch queries)

---

**Prompt 12: Memory Leak Investigation**
```
Use agentic-memory to find all functions that create database connections
or open files. I want to make sure resources are properly closed.
```

**AI will:**
1. Search for "database connection open file"
2. Check for context managers (with statements)
3. Find resources without cleanup
4. Suggest proper resource management

---

## Understanding Codebases

### Onboarding

**Prompt 13: Architecture Overview**
```
I'm new to this codebase. Use agentic-memory to give me a high-level overview.
Show me:
1. The main application entry point
2. Key architectural layers (models, services, controllers)
3. How requests flow through the system
```

**AI will:**
1. Find main entry point
2. Search for architectural patterns
3. Explore import dependencies
4. Build mental model of architecture
5. Explain the structure

---

**Prompt 14: Feature Tour**
```
Use agentic-memory to find all API endpoints in this project and organize them
by feature area (authentication, users, payments, etc.). Give me a tour of the
available functionality.
```

**AI will:**
1. Search for "API endpoint route handler"
2. Categorize by feature
3. Explain each feature area
4. Show relationships

---

### Code Documentation

**Prompt 15: Generate API Docs**
```
Use agentic-memory to find all public API endpoint functions and their
docstrings. Generate a table of endpoints with their HTTP methods, paths,
and descriptions.
```

**AI will:**
1. Search for "API route endpoint handler"
2. Extract function signatures
3. Parse docstrings
4. Format as documentation table

---

**Prompt 16: Explain Complex Logic**
```
Use agentic-memory to find and explain the permission checking logic in this
codebase. Show me all the functions involved and how they work together.
```

**AI will:**
1. Search for "permission check authorization"
2. Get file dependencies
3. Trace call chains
4. Explain the logic step-by-step

---

## Advanced Multi-Tool Prompts

### Complex Analysis

**Prompt 17: Security Audit**
```
Use agentic-memory to perform a mini security audit:
1. Find all functions that execute SQL queries
2. Find all functions that handle file uploads
3. Find all functions that deal with authentication tokens
4. For each category, identify potential security vulnerabilities
```

**AI will:**
1. Multiple `search_codebase` calls for each category
2. `get_file_info` for context
3. Analyze code for security issues
4. Provide vulnerability report

---

**Prompt 18: Test Coverage Analysis**
```
Use agentic-memory to compare production code with test code:
1. Find all functions in src/ (production)
2. Find all test functions in tests/
3. Identify production functions that don't have corresponding tests
```

**AI will:**
1. Search for production functions
2. Search for test functions
3. Match by naming patterns
4. Identify untested code

---

### Migration Planning

**Prompt 19: Framework Migration**
```
I'm planning to migrate from Flask to FastAPI. Use agentic-memory to:
1. Find all Flask-specific code (decorators, request objects)
2. Identify what needs to change
3. Estimate migration effort
4. Suggest migration order
```

**AI will:**
1. Search for "Flask route request"
2. Analyze Flask patterns
3. Identify dependencies
4. Create migration plan

---

**Prompt 20: Database Migration**
```
I want to migrate from PostgreSQL to MongoDB. Use agentic-memory to find:
1. All SQL query code
2. All ORM model definitions
3. Files that would need complete rewrites vs simple changes
```

**AI will:**
1. Search for SQL queries and ORM code
2. Categorize by complexity
3. Identify files needing major changes
4. Prioritize migration work

---

## Best Practices for Prompting

### 1. Be Specific

**Bad:**
```
Find authentication code.
```

**Good:**
```
Use agentic-memory to find the main user authentication functions,
specifically the login and token validation logic. Show me the code
and explain how they work together.
```

---

### 2. Request Multiple Tools

**Bad:**
```
Search for user service.
```

**Good:**
```
Use agentic-memory to:
1. Search for the user service implementation
2. Show me what files it depends on
3. Show me what files depend on it
4. Identify the impact of changes to this service
```

---

### 3. Ask for Analysis

**Bad:**
```
Find User model.
```

**Good:**
```
Use agentic-memory to find the User model and explain:
1. What fields it has
2. What relationships it has to other models
3. What services use it
4. Where it's created/updated/deleted
```

---

### 4. Request Actionable Output

**Bad:**
```
Show me API endpoints.
```

**Good:**
```
Use agentic-memory to find all API endpoints and create a table with:
- HTTP method
- Path
- Function name
- Description from docstring
- File location

Organize them by feature area (auth, users, payments, etc.)
```

---

## Tips for Different AI Clients

### Claude Desktop

**Best for:** Complex reasoning, multi-step analysis

**Tip:** Use conversation context
```
[First message]
Use agentic-memory to find the authentication functions.

[Follow-up message]
Now show me what files depend on those authentication functions.
```

---

### Cursor IDE

**Best for:** In-editor assistance, code generation

**Tip:** Combine with file context
```
I'm currently viewing src/services/user.py.
Use agentic-memory to show me what this file depends on
and what depends on it.
```

---

### Windsurf

**Best for:** Quick lookups, navigation

**Tip:** Keep prompts focused
```
Use agentic-memory to find the function that validates email addresses.
```

---

## Troubleshooting Prompts

### When Results Are Poor

**Prompt:**
```
The previous search didn't find what I needed. Try searching with
different keywords: "login auth signin verify credentials"
```

### When You Need More Context

**Prompt:**
```
You found the function, but I need more context. Use agentic-memory to:
1. Get file info for the file containing this function
2. Show me what other functions are in the same file
3. Show me what imports this file has
```

### When You Want to Verify

**Prompt:**
```
Use agentic-memory to search for "X" again, but this time return
10 results instead of 5 so I can see more options.
```

---

**Need more examples?** Check out:
- [Basic Usage Guide](basic_usage.md)
- [MCP Integration Documentation](../docs/MCP_INTEGRATION.md)
- [API Reference](../docs/API.md)
