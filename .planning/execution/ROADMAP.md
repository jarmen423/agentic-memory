# Wave Roadmap

## Active Track: `w12-openclaw-foundation`

### Wave 0: Orchestrator lock

- `W12-OC-00`: archive the existing `w11-calls` registry, update `.planning`
  truth, and freeze write ownership and merge gates for the OpenClaw wave.

### Wave 1: Foundation threads

- `W12-OC-01`: backend auth, machine-readable errors, `/metrics`, and backend tests.
- `W12-OC-02`: SQLite-backed `ProductStateStore` plus durability/concurrency tests.
- `W12-OC-03`: `packages/am-openclaw` retry/backoff hardening and package-local TypeScript tests.

### Wave 2: Integration gate

- `W12-OC-04`: reconcile shared contracts, add explicit OpenClaw contract tests,
  and update CI to enforce Python + TypeScript merge gates.

### Wave 3: Verification

- run the Python merge gates for backend, shared-memory, product-state, and OpenClaw contract tests
- run the OpenClaw package build/typecheck/test gates
- update task registry statuses and handoffs so paused Phase 10/11 work remains resumable
