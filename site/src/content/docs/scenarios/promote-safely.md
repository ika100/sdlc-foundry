---
title: "Promote to production safely"
description: "Move a verified image through dev, staging and production with one reviewable pull request per step."
---

**Situation.** `shop-api` works in `dev`. You want it in staging, then production, with proof of what runs where.

## How versions move

| Environment | Image tag | Who decides |
|---|---|---|
| `dev` | `sha-<40>` of each merge to `main`, pinned by a self-merging pin PR | merge to `main` |
| `staging` | `sha-<40>` of the commit | a green dev smoke in `/component:ship` (self-merging `pin-staging` PR), or `/instance:promote` |
| `prod` | `X.Y.Z` from the service's `vX.Y.Z` release tag | `/instance:promote` after `/component:release` |

Automatic staging promotion is on in new gitops-apps. Switch it off with `promote: manual` on `environments.staging` in `system.yaml`, or per component under its `instances`. Production is never automatic and runs the image staging tested: `/instance:promote shop-api --to prod` refuses if the release tag's digest differs from the staging build (`--accept-digest-mismatch "<reason>"` overrides, and the reason is recorded). It first prints an evidence summary (smoke in dev and staging, open issues).

If the staging smoke is red, the platform files a `smoke-failure` issue and leaves staging as it is; it does not roll back.

## Steps

```text
/instance:promote shop-api --to staging
/component:release              # in shop-api: tags the commit staging runs after its gates; changelog follows in a PR
/instance:promote shop-api --to prod
```

The command verifies in GHCR that the image tag exists before it opens the pull request, adds the environment to the component's `instances`, renders the overlay and pins the tag. Promotion only moves forward, one environment at a time. Production pull requests say so in their description.

## When a spec limits the environments

A spec can say where its behaviour may run: `environments: [dev]` in its front matter, out of `dev`, `staging` and `prod`. While such a spec is `building` or `done`, promotion refuses every target it leaves out, so a half-finished feature does not reach staging or production by accident. The rule covers `/instance:promote` and the automatic staging pin; moving a version back in `dev` is never refused.

```text
$ /instance:promote shop-api --to staging
ERROR: environment limit: 042-anonymous-use allows dev, not staging (Anonymous use)
  fix: widen the spec with /system:spec --amend 042 once the work that lifts the limit has shipped, or promote anyway with --accept-environment-limit "<reason>" (a person's decision)
```

With `--dry-run` the preview lists one `REFUSED:` line per limiting spec and the `fix:` line, and exits 1. Automatic staging promotion does not fail: it skips and says `not promoted: environment limit 042-anonymous-use allows dev`; the next deploy promotes once the spec is widened.

The usual way out is to widen the spec with `/system:spec --amend` after the work that lifts the limit has shipped. To promote anyway, a person passes `--accept-environment-limit "<reason>"` (a sentence of 3 or more words); the output and the pull request record `environment limit accepted: <spec> (<environments>): <reason>`. Only a person decides this: an unattended run stops and asks instead.

## What you get

- A pull request per move with the exact tag in the diff; ArgoCD rolls the environment after you merge.
- Rollback is reverting the merged pull request.
- `/system:status` prints one table: pinned tag per environment, CI state of each component repository, ArgoCD sync and health.

## Why it is safe

- A new service starts in `dev` only; it never reaches production by accident.
- Staging and production never run `latest` (the Kyverno policy rejects it outside dev, if you enabled [guard rails](/sdlc-foundry/concepts/guard-rails/)).
- Nothing applies manifests by hand: ArgoCD owns reconciliation ([ADR-017](/sdlc-foundry/reference/adr/017/)).
