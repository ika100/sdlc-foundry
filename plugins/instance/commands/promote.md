---
description: "Promote components dev→staging→prod by pinning a GHCR-verified image tag; one PR. Usage: /instance:promote <component...|--all> --to <env> [--version vX.Y.Z | <component>=vX.Y.Z,…]"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

One `cplat` call per Bash invocation, from the repo root:

```bash
cplat instance promote <ARGS>
```

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

1. **Preview** with `--dry-run`; show it verbatim. For `--to prod` it starts with the evidence summary from the run store (smoke outcomes in dev and staging, open `smoke-failure` and `alert` issues); show it verbatim, a `WARNING:` line included. For `--to prod` it also prints the registry digests of staging and prod per component, `match` or `mismatch` (spec 106); a mismatch exits 1. Errors carry a `fix:` line (an image not built yet means waiting for CI on the component's `main`).
2. **Production gate.** If the target is `prod`, print `ABOUT TO PROMOTE TO PRODUCTION` with the components and tags and repeat any `WARNING:` line of the evidence summary. **Hard rule:** never run it without the user's explicit yes, because a prod promotion changes what the users run.
3. **Run** with `--pr`.
4. **Report** the script's output. Rollback = revert the merged PR.
5. **Wait** once the PR is merged (a prod PR waits for review; merge what the user asked you to merge with `cplat pr wait <pr> --merge`): `cplat system wait --env prod --refresh` for `--to prod`, with no component named: a prod PR also renders the environment's databases and the buckets they back up to, and a wait for named components skips them (#600); `--refresh` right after a merge you made (without it when the user merged). The wait counts an app once it runs the tag the merge pins. It ends `READY:` (exit 0), `RED:` (exit 1: a sync error, failed sync or `Degraded` at the new revision; show its lines and stop, nothing is retried) or `TIMEOUT:` (exit 2: run the same wait again, the command it prints, at most twice; then escalate with cause `environment`: `cplat component ship escalate '<the TIMEOUT line>' --cause environment` inside a ship run, otherwise report the `TIMEOUT:` lines to the user as an environment problem). Never write a polling loop on `kubectl`, `gh` or `cplat`, because the wait already ends on the synced revision. For `--to staging` run `cplat instance promote <component…> --to staging --smoke [--refresh]` instead of the wait: the same wait, then each component's staging smoke from its clone next to this repo (cloned when missing), recorded like `/instance:verify staging` so the prod evidence finds it; exit 1 = a red smoke, show its lines.

**Several components, one PR.** Name them (or `--all`) without `--version` to pin each one's newest release, or give the versions as `--version api=v0.1.0,web=v0.1.0`; `--version vX.Y.Z` alone is for one component.

**Digest rule (spec 106).** Prod runs what staging tested: before anything is written, every component's staging `sha-<40>` image and release `X.Y.Z` image have the same registry digest. Any mismatch, missing tag, failed lookup (`gh auth refresh -s read:packages`) or staging tag that is not a `sha-<40>` build refuses the whole promotion: no PR, nothing changed. A mismatch alone can be accepted with `--accept-digest-mismatch "<reason>"`; the output and the PR body then say `digest mismatch accepted: <reason>` with both digests. **Hard rule:** never pass it without the user's explicit yes and reason, because it lets prod run an image that staging did not test. `--no-verify` skips the check and prints `image identity not verified (--no-verify)`.

The script enforces its rules: the source is the environment before `--to`; staging pins `sha-<40>` of a build of the component's main; prod pins the release image `X.Y.Z`; promotion moves forward and adds the `instances.<env>` entry in `system.yaml`; dev follows main through automatic pin PRs (spec 062), so there is no promotion into dev, with one exception: `--to dev --version <tag>` pins dev back to a version it ran before (spec 124). Staging also moves automatically after a green dev smoke in `/component:ship` through the self-merging `pin-staging` PR when `environments.staging.promote: after-dev-smoke` is set (spec 093, ADR-041); switch it off with `promote: manual` there, or per component under `instances.staging.promote`. Prod moves through this command, and its PR waits for review. The script changes `applications/` alone. **Hard rule:** never `kubectl apply`, because the gitops repo and Argo CD own the cluster.

From a component repo with `.platform-app.yml`, clone the listed gitops-app repo (`gh repo clone <org>/<repo>`) and run there.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
