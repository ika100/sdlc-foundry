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

1. **Preview** with `--dry-run`; show it verbatim. For `--to prod` it starts with the evidence summary from the run store (smoke outcomes in dev and staging, open `smoke-failure` and `alert` issues); show it verbatim. For `--to prod` it also prints per component the registry digests of staging and prod, `match` or `mismatch` (spec 106); a mismatch exits 1. Errors carry a `fix:` line.
2. **Production gate.** If the target is `prod`, print `ABOUT TO PROMOTE TO PRODUCTION` with the components and tags and repeat any `WARNING:` line of the evidence summary. **Hard rule:** never run it without the user's explicit yes, because a prod promotion changes what the users run.
3. **Run** with `--pr`.
4. **Report** the script's output. Rollback = revert the merged PR.
5. **Wait** once the PR is merged (merge what the user asked you to merge with `cplat pr wait <pr> --merge`; a prod PR waits for review): `cplat system wait --env prod --refresh` for `--to prod`, naming no component, because a wait for named components skips the databases and backup buckets a prod PR renders (#600); `--refresh` after a merge you made. It ends `READY:` (exit 0), `RED:` (exit 1: show its lines and stop, nothing is retried) or `TIMEOUT:` (exit 2: run the printed command again, at most twice; then escalate with cause `environment`: `cplat component ship escalate '<the TIMEOUT line>' --cause environment` inside a ship run, otherwise report the `TIMEOUT:` lines to the user as an environment problem). Never write a polling loop on `kubectl`, `gh` or `cplat`, because the wait already ends on the synced revision. For `--to staging` run `cplat instance promote <component…> --to staging --smoke [--refresh]` instead: the same wait, then each component's staging smoke from its clone next to this repo (cloned when missing), recorded like `/instance:verify staging` so the prod evidence finds it; exit 1 = a red smoke, show its lines.

**Several components, one PR.** Name them (or `--all`) to pin each one's newest release, or give `--version api=v0.1.0,web=v0.1.0`; `--version vX.Y.Z` alone is for one component.

**Digest rule (spec 106).** Prod runs what staging tested: before anything is written, every component's staging `sha-<40>` image and release `X.Y.Z` image have the same registry digest. A mismatch, missing tag, failed lookup (`gh auth refresh -s read:packages`) or non-`sha-<40>` staging tag refuses the whole promotion. A mismatch alone can be accepted with `--accept-digest-mismatch "<reason>"`; the output and PR body then say `digest mismatch accepted: <reason>`. **Hard rule:** never pass it without the user's explicit yes and reason, because it lets prod run an image that staging did not test. `--no-verify` skips the check and prints `image identity not verified (--no-verify)`.

**Environment limit (spec 190).** A building or done spec whose `environments:` lacks the target refuses staging and prod, the automatic staging pin included, so that no environment runs what its spec forbids. The refusal says `environment limit` with a `fix:` line, and `--dry-run` lists `REFUSED:` lines. `--accept-environment-limit "<reason>"` overrides it; the output then says `environment limit accepted: <spec_id> (<envs>): <reason>`. **Hard rule:** never pass `--accept-environment-limit` without the user's explicit yes and reason, and an unattended run stops and asks, because it lets a system run where an approved spec forbids it.

The script enforces its rules: the source is the environment before `--to`; staging pins `sha-<40>` of a build of the component's main; prod pins the release image `X.Y.Z`; promotion moves forward and adds the `instances.<env>` entry in `system.yaml`; dev follows main through automatic pin PRs (spec 062), so there is no promotion into dev, with one exception: `--to dev --version <tag>` pins dev back to a version it ran before (spec 124). Staging also moves automatically after a green dev smoke in `/component:ship` through the self-merging `pin-staging` PR when `environments.staging.promote: after-dev-smoke` is set (spec 093, ADR-041); `promote: manual` there, or per component under `instances.staging.promote`, switches it off. Prod moves through this command; its PR waits for review. The script changes `applications/` alone. **Hard rule:** never `kubectl apply`, because the gitops repo and Argo CD own the cluster.

From a component repo with `.platform-app.yml`, clone the listed gitops-app repo and run there.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; the platform posts only `platform` escalations and milestone comments itself.
