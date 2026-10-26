---
title: "Promote to production safely"
description: "Move a verified image through dev, staging and production with one reviewable pull request per step."
---

**Situation.** `shop-api` works in `dev`. You want it in staging, then production, with proof of what runs where.

## How versions move

| Environment | Image tag | Who decides |
|---|---|---|
| `dev` | tracks `main` of the service (`latest`) | merge to `main` |
| `staging` | `sha-<40>` of the commit | a green dev smoke in `/svc:ship` (self-merging `pin-staging` PR, spec 093), or `/gitops:promote` |
| `prod` | `X.Y.Z` from the service's `vX.Y.Z` release tag | `/gitops:promote` after `/svc:release` |

Automatic staging promotion is on in new gitops-apps. Switch it off with `promotion: {staging: manual}` in `app.yaml`, or per service in `services.yaml`. Production is never automatic and runs the image staging tested: `/gitops:promote shop-api staging prod` refuses if the release tag's digest differs from the staging build (`--accept-digest-mismatch "<reason>"` overrides, and the reason is recorded). It first prints an evidence summary (smoke in dev and staging, open issues).

If the staging smoke is red, the platform files a `smoke-failure` issue and leaves staging as it is; it does not roll back.

## Steps

```text
/gitops:promote shop-api dev staging
/svc:release                     # in shop-api: quality, tests, security, version bump, changelog, release PR, tag
/gitops:promote shop-api staging prod
```

The command verifies in GHCR that the image tag exists before it opens the pull request, adds the environment to the service's `environments` list, renders the overlay and pins the tag. Promotion only moves forward, one environment at a time. Production pull requests say so in their description.

## What you get

- A pull request per move with the exact tag in the diff; ArgoCD rolls the environment after you merge.
- Rollback is reverting the merged pull request.
- `/shared:status` prints one table: pinned tag per environment, CI state of each service repository, ArgoCD sync and health.

## Why it is safe

- A new service starts in `dev` only; it never reaches production by accident.
- Staging and production never run `latest` (the Kyverno policy rejects it outside dev, if you enabled [guard rails](/sdlc-foundry/concepts/guard-rails/)).
- Nothing applies manifests by hand: ArgoCD owns reconciliation ([ADR-017](/sdlc-foundry/reference/adr/017/)).
