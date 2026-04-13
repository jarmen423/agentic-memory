# OpenClaw Publishing Checklist

## Package Identity

- [x] npm package name locked to `agentic-memory-openclaw`
- [x] OpenClaw plugin id remains `agentic-memory`
- [x] release workflow enforces the locked package name
- [x] CI verifies the manifest name before package build/test/typecheck/pack

## Listing Inputs

- [ ] final marketplace title
- [ ] final marketplace icon/screenshots
- [ ] final support contact and issue-routing copy
- [ ] final compatibility statement for the target OpenClaw host version

## Install Surface

- [x] install command locked: `openclaw plugin install agentic-memory-openclaw`
- [x] doctor command locked: `openclaw agentic-memory doctor`
- [x] setup command locked: `openclaw agentic-memory setup`
- [ ] operator docs reconciled so no placeholder package-name text remains

## Publish Gates

- [ ] `npm run build`
- [ ] `npm run typecheck`
- [ ] `npm run build:openclaw`
- [ ] `npm run test:openclaw`
- [ ] `npm run typecheck:openclaw`
- [ ] `npm run pack:openclaw`
- [ ] `npm run validate:release-artifacts`

## Release Notes Reminder

State clearly in the listing and release notes that:

- the npm artifact is the OpenClaw plugin package
- the supported first-run path is `install -> doctor -> setup`
- the backend is configured separately
- the runtime plugin id inside OpenClaw remains `agentic-memory`
