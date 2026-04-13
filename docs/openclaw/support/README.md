# OpenClaw Support Operations

This directory holds the support and incident runbooks for the OpenClaw private
beta.

## Files

- `D:\code\agentic-memory\docs\openclaw\support\SUPPORT_RUNBOOK.md`
  - first-stop support triage guide and top-5 failure-mode routing
- `D:\code\agentic-memory\docs\openclaw\support\RB-001_PROVISION_ENVIRONMENT.md`
- `D:\code\agentic-memory\docs\openclaw\support\RB-002_ROTATE_API_KEYS.md`
- `D:\code\agentic-memory\docs\openclaw\support\RB-003_NEO4J_BACKUP_RESTORE.md`
- `D:\code\agentic-memory\docs\openclaw\support\RB-004_CAPACITY_AND_BACKLOG.md`
- `D:\code\agentic-memory\docs\openclaw\support\RB-005_API_ERRORS_AND_EMPTY_RESULTS.md`
- `D:\code\agentic-memory\docs\openclaw\support\RB-006_EMBEDDING_PROVIDER_OUTAGE.md`

## Scope

These runbooks are written for the current beta architecture:

- one `am-server`
- one Neo4j instance
- OpenClaw plugin package `agentic-memory-openclaw`
- runtime plugin id `agentic-memory`

They do not assume:

- hosted multi-tenant control plane
- queue dashboards that do not yet exist
- automatic horizontal scaling in the current beta compose path
