# Wave Roadmap

## Completed Track: `w14-openclaw-scaling-and-packaging`

### Wave 0: Orchestrator lock

- `W14-OC-00`: archive the completed `w13-openclaw-dashboard-and-testing`
  registry, update `.planning` truth, and freeze write ownership and merge
  gates for the scaling + packaging wave.

### Wave 1: Parallel implementation threads

- `W14-OC-01`: backend scale-path hardening for ingest/search/observability and
  the GTM plan's 10-agent readiness work.
- `W14-OC-02`: `packages/am-openclaw` packaging/distribution preparation,
  release metadata, and install artifact work.
- `W14-OC-03`: production deployment/release artifacts, Docker/release workflow
  scaffolding, and operations-facing packaging docs.

### Wave 2: Integration gate

- `W14-OC-04`: wire CI/release validation gates, reconcile backend/package
  boundaries, and close the scaling + packaging merge boundary.

### Wave 3: Verification

- run the backend, contract, and desktop shell regression gates
- run the OpenClaw plugin build/test/typecheck/package gates
- run the production deployment/release artifact validation gates
- update task registry statuses and handoffs so the completed W14 wave remains resumable from archive
