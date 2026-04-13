# OpenClaw Design-Partner Onboarding Runbook

This runbook is the canonical checklist for onboarding one private-beta design
partner onto the OpenClaw integration.

## Definition Of Done

One partner is considered onboarded when all of the following are true:

1. their backend is reachable and healthy
2. the OpenClaw plugin installs successfully
3. `openclaw agentic-memory doctor` reports the requested mode ready
4. `openclaw agentic-memory setup` completes
5. `openclaw agentic-memory project status` succeeds
6. the backend records at least:
   - one `/openclaw/session/register`
   - one `/openclaw/memory/search`
   - one `/openclaw/memory/ingest-turn`

## Preflight

Collect these facts before the live onboarding session:

- partner name
- operator contact
- target OS
- OpenClaw host version
- backend deployment model:
  - local Docker
  - hosted VM
  - other operator-managed environment
- backend URL
- bearer token delivery method:
  - literal value
  - env interpolation template

## Operator Prerequisites

The partner must have:

- OpenClaw host available
- backend deployed and reachable
- a real `AM_SERVER_API_KEYS` token from the backend operator

Backend validation commands:

```bash
curl http://127.0.0.1:8765/health
curl -H "Authorization: Bearer replace-with-real-rest-key" \
  http://127.0.0.1:8765/openclaw/health/detailed
curl -H "Authorization: Bearer replace-with-real-rest-key" \
  http://127.0.0.1:8765/metrics
```

## Install And Setup

Install the plugin:

```bash
openclaw plugin install agentic-memory-openclaw
```

Configure it:

```bash
openclaw agentic-memory doctor --backend-url http://127.0.0.1:8765
openclaw agentic-memory setup --backend-url http://127.0.0.1:8765
```

If `doctor` says the backend is not ready, stop there and fix the blocking
services before proceeding. Do not count a partner as onboarded merely because
the backend answered `/health`.

Important identity split:

- npm package name: `agentic-memory-openclaw`
- runtime plugin id inside OpenClaw: `agentic-memory`

## Live Validation Checklist

Run:

```bash
openclaw agentic-memory project status
```

Then confirm on the backend side that:

- `/openclaw/session/register` is being hit
- `/openclaw/memory/search` returns a valid response
- `/openclaw/memory/ingest-turn` starts recording new turns

If the operator wants context augmentation enabled, verify:

- `/openclaw/context/resolve` returns successfully

## What Counts As An Active Beta User

For Phase 15 tracking, count a partner as active only if all of the following
happened within the trailing 7 days:

- at least one registered OpenClaw session
- at least one successful memory search
- at least one ingested turn

This is intentionally stricter than "the plugin is installed."

## First-Week Success Checks

Within the first 7 days, review:

- install success
- time to first successful memory search
- whether the operator stayed in `capture_only` or enabled `augment_context`
- whether any auth, health, or search incidents occurred
- whether the partner can name one concrete workflow improved by memory capture

## Required Capture In Partner Notes

Record:

- install date
- package version
- OpenClaw host version
- backend URL host
- selected mode:
  - `capture_only`
  - `augment_context`
- first successful validation timestamp
- first meaningful feedback

## Escalate When

Escalate immediately if:

- install fails repeatedly on a supported host
- backend health is unstable
- every search returns empty results after turn ingestion
- auth breaks after initial success
- context augmentation materially harms prompt quality

Use:

- `D:\code\agentic-memory\docs\openclaw\support\SUPPORT_RUNBOOK.md`
