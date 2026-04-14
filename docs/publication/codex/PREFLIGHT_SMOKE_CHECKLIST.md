# Codex Preflight Smoke Checklist

Current as of April 12, 2026.

Use this before claiming the Codex path is ready for wider operator use.

## Hosted handshake target

- `https://mcp.agentmemorylabs.com/mcp-codex`

## Smoke checks

1. Connection
   - Codex can reach the hosted MCP endpoint.
   - The endpoint does not redirect to an internal-only surface.
2. Auth behavior
   - Public Codex auth behavior matches the chosen hosted posture.
   - Failures produce understandable public-surface errors rather than raw backend exceptions.
3. Tool inventory
   - The visible tool set matches the frozen nine-tool public contract.
   - No internal/admin tools are exposed.
4. Read flow
   - One code search succeeds.
   - One dependency lookup or execution trace succeeds.
   - One conversation-memory retrieval succeeds.
5. Write flow
   - One explicit memory write succeeds.
   - One research-memory write succeeds.

## Example preflight prompts

- `Use search_codebase to find the public MCP surface definition.`
- `Use get_file_dependencies on src/am_server/app.py.`
- `Use trace_execution_path starting from a known function signature in the repo.`
- `Use search_conversations to find prior discussion about plugin publication.`
- `Use add_message to save a short Codex preflight note to memory.`

## Expected operator evidence

- Date and operator name
- Environment used for the test
- Whether auth was enabled
- Whether the handshake succeeded
- Any tool mismatch or auth mismatch observed

## Self-serve readiness notes

- Local/preflight readiness does not imply Codex marketplace/discovery readiness by itself.
- Any public discovery or listing behavior that depends on OpenAI publication must be tracked separately in the launch/status lane.
