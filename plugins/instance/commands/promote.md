---
description: "Promote components dev→staging→prod by pinning a GHCR-verified image tag; one PR. Usage: /instance:promote <component...|--all> --to <env> [--version vX.Y.Z]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from; one call per Bash invocation, from the repo root:

```bash
cplat instance promote <ARGS>
```

1. **Preview** with `--dry-run`; show it verbatim (it lists each component with the exact `image:tag` and marks production). For `--to prod` it starts with the evidence summary from the run store (smoke outcomes of the release's commit in dev and staging, open `smoke-failure` and `alert` issues); show it verbatim, a `WARNING:` line included. For `--to prod` it also reads the registry digests and prints, per component, `staging: <tag> <digest>`, `prod: <tag> <digest>` and `match` or `mismatch` (spec 106); a mismatch exits 1. Errors carry a `fix:` line — typical: the image is not built yet (wait for CI on the component's `main`), a backwards move, the component has no instance in the source environment, a missing `--to` (4.x wrote `<from> <to>`).
2. **Production gate.** If the target is `prod`, print `ABOUT TO PROMOTE TO PRODUCTION` with the components and tags, repeat any `WARNING:` line of the evidence summary, and wait for the user's explicit yes before running.
3. **Run** with `--pr`.
4. **Report** the script's output. Rollback = revert the merged PR.

**Digest rule (spec 106).** Prod must run what staging tested: before anything is written, every component's staging `sha-<40>` image and release `X.Y.Z` image must have the same registry digest. Any mismatch, missing tag, failed lookup (`gh auth refresh -s read:packages`) or staging tag that is not a `sha-<40>` build refuses the whole promotion: no PR, nothing changed. A mismatch alone can be accepted with `--accept-digest-mismatch "<reason>"` (a sentence of three or more words ending in `.`, `!` or `?`); the output and the PR body then say `digest mismatch accepted: <reason>` with both digests. Never pass it without the user's explicit yes and reason. `--no-verify` skips the check and prints `image identity not verified (--no-verify)`. Release CI re-tags the tested `sha-<40>` image instead of rebuilding it, so a release made from the tested commit always matches.

Rules (enforced by the script; do not work around them): the source is the environment before `--to`; staging pins `sha-<40>` (the full commit sha) of a build of the component's main; prod pins the release image `X.Y.Z` (the `vX.Y.Z` git tag without the `v`); promotion only moves forward and adds the `instances.<env>` entry in `system.yaml`; dev follows main through automatic pin PRs (spec 062), so there is no promotion into dev, with one exception: `--to dev --version <tag>` pins dev back to a version it ran before (the git history of its pin decides), as the rollback of an autonomy engine or its undo (spec 124). Staging also moves automatically after a green dev smoke in `/component:ship` through the self-merging `pin-staging` PR when `environments.staging.promote: after-dev-smoke` is set (spec 093, ADR-041); switch it off with `promote: manual` there, or per component under `instances.staging.promote`. Prod moves only through this command, and its PR always waits for review. Only `applications/` changes; never `kubectl apply`.

Running from a component repo? If `.platform-app.yml` exists, clone the listed gitops-app repo (`gh repo clone <org>/<repo>`) and run the command there.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
