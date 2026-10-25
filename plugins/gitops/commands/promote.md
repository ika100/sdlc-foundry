---
description: "Promote services dev→staging→prod in a gitops-app repo by pinning a GHCR-verified image tag; one PR. Usage: /gitops:promote <service...|--all> <from> <to> [--version vX.Y.Z]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from; one call per Bash invocation, from the repo root:

```bash
cplat promote <ARGS>
```

1. **Preview** with `--dry-run`; show it verbatim (it lists each service with the exact `image:tag` and marks production). For `staging` → `prod` it starts with the evidence summary from the run store (smoke outcomes of the release's commit in dev and staging, open `smoke-failure` and `alert` issues); show it verbatim, a `WARNING:` line included. Errors carry a `fix:` line — typical: the image is not built yet (wait for CI on the service's `main`), a backwards move, the service is not in the source environment.
2. **Production gate.** If the target is `prod`, print `ABOUT TO PROMOTE TO PRODUCTION` with the services and tags, repeat any `WARNING:` line of the evidence summary, and wait for the user's explicit yes before running.
3. **Run** with `--pr`. 
4. **Report** the script's output. Rollback = revert the merged PR.

Rules (enforced by the script; do not work around them): staging pins `sha-<40>` (the full commit sha; `sha-<7>` for images built before 4.4.0) of a build of the service's main; prod pins the release image `X.Y.Z` (the `vX.Y.Z` git tag without the `v`); promotion only moves forward; dev follows main through automatic pin PRs (spec 062), so there is no promotion into dev. Staging also moves automatically after a green dev smoke in `/svc:ship` through the self-merging `pin-staging` PR when `promotion.staging: auto` is set (spec 093, ADR-041); switch it off with `promotion: {staging: manual}` in `app.yaml`, or per service in `services.yaml`. Prod moves only through this command, and its PR is never auto-merged (`promotion.prod` is rejected unless `manual`). Only `applications/` changes; never `kubectl apply`.

Running from a service repo? If `.platform-app.yml` exists, clone the listed gitops-app repo (`gh repo clone <org>/<repo>`) and run the command there.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/shared:report-issue` so the user can file it. Never file anything without their OK.
