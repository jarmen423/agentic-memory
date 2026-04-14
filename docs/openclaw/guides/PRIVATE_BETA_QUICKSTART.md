# OpenClaw Private Beta Quickstart

This guide is the shortest supported path from "I have an OpenClaw environment"
to "the Agentic Memory integration is installed, configured, and validated."

## What You Need First

- an Agentic Memory backend that is already reachable
- a real bearer token from the backend's `AM_SERVER_API_KEYS`
- an OpenClaw host version compatible with the plugin package

If you still need the backend, start here:

- `D:\code\agentic-memory\docs\openclaw\DEPLOYMENT_RUNBOOK.md`

## Install The Plugin

```bash
openclaw plugin install agentic-memory-openclaw
```

Important identity split:

- npm package name: `agentic-memory-openclaw`
- runtime OpenClaw plugin id after install: `agentic-memory`

## Configure The Plugin

Choose the mode that matches the backend you are pointing at:

- managed hosted beta
- self-hosted backend

Managed hosted example:

```bash
openclaw agentic-memory doctor --hosted --backend-url https://backend.agentmemorylabs.com
openclaw agentic-memory setup --hosted --backend-url https://backend.agentmemorylabs.com
```

Self-hosted example:

```bash
openclaw agentic-memory doctor --self-hosted --backend-url http://127.0.0.1:8765
openclaw agentic-memory setup --self-hosted --backend-url http://127.0.0.1:8765
```

Recommended order:

1. `openclaw plugin install agentic-memory-openclaw`
2. `openclaw agentic-memory doctor ...`
3. `openclaw agentic-memory setup ...`

Why `doctor` comes first:

- it reads the backend onboarding contract from `/health/onboarding`
- it tells you whether the backend is merely reachable or actually ready
- `setup` now uses that same contract and can refuse to save config if the
  requested mode is not honestly ready yet

The setup flow records:

- backend URL
- API key or env interpolation template
- workspace id
- device id
- agent id
- mode: `capture_only` or `augment_context`

If you intentionally want to save config before the backend is ready, use:

```bash
openclaw agentic-memory setup --self-hosted --backend-url http://127.0.0.1:8765 --allow-degraded
```

## Verify The Connection

```bash
openclaw agentic-memory project status
```

Then verify the backend directly:

```bash
curl http://127.0.0.1:8765/health
curl -H "Authorization: Bearer replace-with-real-rest-key" \
  http://127.0.0.1:8765/openclaw/health/detailed
curl -H "Authorization: Bearer replace-with-real-rest-key" \
  http://127.0.0.1:8765/metrics
```

## Expected Runtime Behavior

- `capture_only`
  - turn capture and memory search are active
  - custom context blocks are not injected into prompts
- `augment_context`
  - turn capture and memory search are active
  - Agentic Memory also resolves context for prompt augmentation

## Session-Level Project Commands

```bash
openclaw agentic-memory project init <project-id>
openclaw agentic-memory project use <project-id>
openclaw agentic-memory project status
openclaw agentic-memory project stop
```

These commands are session-scoped. They do not permanently bake one project id
into the install-time plugin config.

## Roll Back

Plugin rollback:

- disable or remove the installed OpenClaw plugin through your host's plugin
  management flow
- if you are testing multiple package revisions, reinstall the desired version
  and re-run `openclaw agentic-memory setup`

Backend rollback:

- `D:\code\agentic-memory\docs\openclaw\DEPLOYMENT_RUNBOOK.md`

## Related References

- `D:\code\agentic-memory\docs\openclaw\BETA_ROLLOUT.md`
- `D:\code\agentic-memory\docs\openclaw\openapi\README.md`
- `D:\code\agentic-memory\docs\openclaw\openapi\agentic-memory-openclaw.openapi.json`
