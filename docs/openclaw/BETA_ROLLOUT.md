# OpenClaw Beta Rollout

This document is the release-ops checklist for Phase 14.

It answers a narrower question than the full GTM plan:

- what must be true before we invite controlled beta operators to use the
  OpenClaw integration?

## Beta Goal

Ship a repeatable OpenClaw install and backend deployment story that lets a
small set of operators:

- install the plugin
- run a preflight doctor against a real backend
- save config only after the backend clears that readiness check
- verify memory search and turn capture
- recover from the most likely operational failures

## Current Deliberate Limits

This beta does **not** claim:

- marketplace submission
- hosted multi-tenant auth
- public internet rate limiting
- GA-grade deployment automation
- GA completeness outside the locked beta package/install path

## Release Inputs That Must Exist

- a repo revision you are comfortable running for beta
- the locked npm package name `agentic-memory-openclaw`
- npm publish credentials if you intend to publish from CI
- a production `.env.production` file for the backend stack

## Release Gates

Backend and OpenClaw regression gates:

```bash
python -m pytest tests/test_am_server.py tests/test_openclaw_contract.py desktop_shell/tests/test_app.py -q
python -m pytest tests/e2e/test_openclaw_e2e.py tests/load/test_openclaw_load.py tests/chaos/test_openclaw_chaos.py -q
```

OpenClaw package gates:

```bash
npm run build --workspace packages/am-openclaw
npm run test --workspace packages/am-openclaw
npm run typecheck --workspace packages/am-openclaw
npm pack --workspace packages/am-openclaw --dry-run
```

Deployment gate:

```bash
docker compose -f docker-compose.prod.yml config
```

## Suggested Rollout Order

1. Build the package artifact and deployment docs through the release workflow.
2. Render `docker-compose.prod.yml` with the real production env file.
3. Deploy the backend stack and verify `/health`, `/openclaw/health/detailed`,
   and `/metrics`.
4. Publish the npm package only after the repo revision and release gates are green.
5. Install the plugin into one internal OpenClaw environment first.
6. Run `openclaw agentic-memory doctor --backend-url ...` before the first
   `setup` on that environment.
7. Expand to a very small external beta set after smoke testing succeeds.

## Manual Release Workflow

The release workflow is intentionally manual-first:

- file: `D:\code\agentic-memory\.github\workflows\release.yml`
- trigger: `workflow_dispatch`

Why it is manual:

- npm publish is still a deliberate beta action, not an automatic push-side effect
- the deployment artifact path is useful even before the publish step is ready
- operator rollout should stay gated on the beta smoke-test checklist

## Package-Name Rule

The package identity is locked:

- install command: `openclaw plugin install agentic-memory-openclaw`
- doctor command: `openclaw agentic-memory doctor`
- runtime plugin id: `agentic-memory`

Do block the final npm publish step if the manifest drifts away from that
locked name.

## Exit Criteria For W14-OC-03

This task should be considered complete when:

- `D:\code\agentic-memory\.github\workflows\release.yml` exists
- `D:\code\agentic-memory\docker-compose.prod.yml` exists
- `D:\code\agentic-memory\docs\openclaw\` contains deployment and rollout docs
- `docker compose -f docker-compose.prod.yml config` renders successfully

The final npm publish wiring and any package-name-dependent integration cleanup
belong to the later integration gate.
