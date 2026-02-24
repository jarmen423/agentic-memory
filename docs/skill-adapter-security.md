# Skill Adapter Security

This document defines secret-handling rules for the skill-adapter workflow.

## Security Rules

1. Never hardcode API keys or passwords directly in MCP client JSON.
2. Prefer repo-scoped `.env` files or shell environment variables.
3. Keep secrets out of logs, terminal captures, screenshots, and issue comments.
4. Use explicit repo targeting (`--repo`) to reduce accidental cross-repo leakage.

## No Secrets In MCP JSON

### Avoid

```json
{
  "mcpServers": {
    "codememory": {
      "command": "codememory",
      "args": ["serve", "--repo", "/abs/path/repo"],
      "env": {
        "OPENAI_API_KEY": "sk-live-plaintext",
        "NEO4J_PASSWORD": "plaintext-password"
      }
    }
  }
}
```

### Prefer

```json
{
  "mcpServers": {
    "codememory": {
      "command": "codememory",
      "args": [
        "serve",
        "--repo", "/abs/path/repo",
        "--env-file", "/abs/path/repo/.env"
      ]
    }
  }
}
```

The `.env` file stays local, gitignored, and can be permission-restricted.

## Secret Loading Patterns

### Pattern A: Repo `.env` (recommended default)

```bash
cat > /abs/path/repo/.env <<'EOF'
OPENAI_API_KEY=sk-...
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
EOF
chmod 600 /abs/path/repo/.env
```

Then run:

```bash
codememory serve --repo /abs/path/repo --env-file /abs/path/repo/.env --port 8000
```

### Pattern B: Shell Environment

```bash
export OPENAI_API_KEY='sk-...'
export NEO4J_URI='bolt://localhost:7687'
export NEO4J_USER='neo4j'
export NEO4J_PASSWORD='...'
codememory serve --repo /abs/path/repo --port 8000
```

Use for ephemeral sessions. Clear when done:

```bash
unset OPENAI_API_KEY NEO4J_URI NEO4J_USER NEO4J_PASSWORD
```

### Pattern C: macOS Keychain -> Shell Export

Store once:

```bash
security add-generic-password -a "$USER" -s codememory-openai -w '<openai-key>'
security add-generic-password -a "$USER" -s codememory-neo4j-password -w '<neo4j-password>'
```

Load per session:

```bash
export OPENAI_API_KEY="$(security find-generic-password -a "$USER" -s codememory-openai -w)"
export NEO4J_PASSWORD="$(security find-generic-password -a "$USER" -s codememory-neo4j-password -w)"
```

## Redaction Guidance

Before sharing logs:

```bash
sed -E \
  -e 's/sk-[A-Za-z0-9_-]+/[REDACTED_OPENAI_KEY]/g' \
  -e 's/(OPENAI_API_KEY=).*/\1[REDACTED]/g' \
  -e 's/(NEO4J_PASSWORD=).*/\1[REDACTED]/g' \
  input.log > redacted.log
```

Before sharing screenshots:

1. Hide terminal history lines that contain exports/keys.
2. Hide `.env` editors and credential dialogs.
3. Crop status bars/tabs that may include hostnames or usernames if sensitive.
4. Prefer text snippets from `redacted.log` instead of full-screen captures.

## Incident Response (If a Secret Leaks)

1. Rotate exposed keys/passwords immediately.
2. Invalidate/revoke leaked credentials at provider level.
3. Replace local `.env` and shell exports with new values.
4. Re-run health checks to confirm restored access.
5. Remove leaked values from commit history/log artifacts when applicable.
