# Wave Roadmap

## Active Track: `w13-openclaw-dashboard-and-testing`

### Wave 0: Orchestrator lock

- `W13-OC-00`: archive the completed `w12-openclaw-foundation` registry, update
  `.planning` truth, and freeze write ownership and merge gates for the next
  OpenClaw wave.

### Wave 1: Parallel implementation threads

- `W13-OC-01`: backend dashboard read APIs, response models, and backend
  contract coverage.
- `W13-OC-02`: `packages/am-dashboard` workspace plus desktop shell replacement
  and proxy integration.
- `W13-OC-03`: OpenClaw operational harnesses for E2E, load, and chaos
  execution.

### Wave 2: Integration gate

- `W13-OC-04`: wire dashboard CI/build gates, reconcile frontend/backend
  contracts, and close the testing + dashboard merge boundary.

### Wave 3: Verification

- run the backend, contract, and desktop shell merge gates
- run the dashboard workspace build/test/typecheck gates
- run the E2E, load, and chaos harness merge gates
- update task registry statuses and handoffs so the completed W12 wave remains resumable from archive
