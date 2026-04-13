# Wave Roadmap

## Active Track: `w16-openclaw-whole-stack-onboarding`

### Wave 0: Orchestrator lock

- `W16-OC-00`: archive the completed `w15-openclaw-docs-and-private-beta`
  registry, update `.planning` truth, and freeze write ownership plus merge
  gates for the onboarding wave.

### Wave 1: Contract lock

- `W16-OC-01`: define the onboarding contract for what the plugin, backend,
  shell, and local services must validate, report, or treat as optional before
  the user sees a "setup complete" result.

### Wave 2: Parallel implementation threads

- `W16-OC-02`: add plugin-side doctor/setup UX so OpenClaw validates the real
  backend path instead of only persisting config.
- `W16-OC-03`: clean up whole-stack bootstrap and temporal-target assumptions so
  local services do not rely on saved aliases or silent port defaults.
- `W16-OC-04`: rewrite install, troubleshooting, and whole-stack onboarding
  docs so the supported path matches the actual validated flow.

### Wave 3: Integration gate

- `W16-OC-05`: reconcile CI, release validation, and onboarding regression
  coverage so the stack cannot drift back into hidden local assumptions.

### Wave 4: Verification

- run the backend, contract, dashboard, package, and whole-stack regression gates
- verify the temporal packages still build/typecheck with the new bootstrap path
- write handoffs and update the registry so the next follow-on track can start
  from a truthful onboarding snapshot
