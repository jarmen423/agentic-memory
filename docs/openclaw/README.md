# OpenClaw Beta Operations

This directory contains the operator-facing artifacts added during Phase 14 for
the OpenClaw scaling and packaging wave.

These docs focus on the pieces that make the OpenClaw integration releasable as
a controlled beta:

- deployment shape for the backend that OpenClaw talks to
- release workflow expectations for the npm plugin package
- rollout checkpoints for inviting beta operators without pretending GA exists

## Files In This Directory

- `docs/openclaw/DEPLOYMENT_RUNBOOK.md`
  - step-by-step backend deployment and smoke-test flow
- `docs/openclaw/BETA_ROLLOUT.md`
  - release gates, operator checklist, and rollout sequencing

## Package Identity

The OpenClaw npm package name is now locked to:

- `agentic-memory-openclaw`

The runtime plugin id inside OpenClaw still remains:

- `agentic-memory`

That means operators install:

- `openclaw plugin install agentic-memory-openclaw`

but they configure and use the plugin through:

- `openclaw agentic-memory setup`

## Expected User-Facing Install Pattern

```bash
openclaw plugin install agentic-memory-openclaw
openclaw agentic-memory setup
```

The goal is that the OpenClaw operator installs one plugin package while your
beta backend remains separately managed through the production compose stack.
