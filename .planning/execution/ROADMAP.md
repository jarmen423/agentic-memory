# Wave Roadmap

## Active Track: `w17-openclaw-hosted-beta-and-dual-mode`

### Wave 0: Orchestrator lock

- `W17-HB-00`: activate Phase 17, freeze the managed vs self-hosted execution
  contract, and seed the hosted-beta registry plus merge gates.

### Wave 1: Contract lock

- `W17-HB-01`: define the hosted-beta contract for deployment mode, workspace
  auth, managed provider-key ownership, and what users vs operators should be
  expected to care about.

### Wave 2: Parallel implementation threads

- `W17-HB-02`: implement backend hosted-beta auth, workspace-bound key
  enforcement, usage metering, and operator provisioning helpers.
- `W17-HB-03`: implement plugin-side hosted vs self-hosted setup/doctor UX so
  the user sees one clear mode and one clear resolved backend target.
- `W17-HB-04`: update managed-beta deployment/docs/runbooks around the current
  GCP VM while keeping self-hosted guidance and validation alive.

### Wave 3: Integration gate

- `W17-HB-05`: reconcile backend tests, plugin tests, and docs truth so the
  managed hosted path and self-hosted fallback cannot silently drift apart.

### Wave 4: Verification

- run the backend and plugin regression gates for the widened contract
- verify hosted-beta docs match the deployed GCP VM assumptions
- verify self-hosted docs still point to the full-stack path rather than a mixed mode
- write handoffs and update the registry so the next follow-on phase starts from
  a truthful hosted-beta baseline
