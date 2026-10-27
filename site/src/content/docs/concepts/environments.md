---
title: "Environments and promotion"
description: "dev, staging and production, opt-in per service, moved by pull request."
sidebar:
  order: 4
---

Each system has three environments, each in its own namespace `<system>-<env>`. A component is rendered only for the environments that are keys of its `instances` (default dev only), so a new component never reaches production by accident.

| Environment | Pinned image tag | Moves when |
|---|---|---|
| `dev` | `latest` (tracks the service's `main`) | the service's CI publishes |
| `staging` | `sha-<first 7 of the commit>` | `/instance:promote <component> --to staging` |
| `prod` | `X.Y.Z` (the component's release tag without `v`) | `/instance:promote <component> --to prod` |

`/instance:promote` verifies in GHCR that the tag exists, adds the environment to the component's `instances`, renders the overlay, pins the tag and opens one pull request. It only moves forward; rollback is reverting the merged pull request. Staging can follow dev automatically: with `promote: after-dev-smoke` on the staging environment in `system.yaml` (the default in new systems), a green dev smoke in `/component:ship` opens a self-merging pin-staging pull request and runs the smoke tests against staging; a red one files a `smoke-failure` issue and does not roll back. A deploy counts only after its checks pass: the dev smoke records the image digest the cluster runs, a failure is classed as environment or application, an unreadable digest gives NOT VERIFIED, and staging is pinned only while the registry digest still matches. Production stays manual, and its promotion first prints the evidence from earlier runs ([ADR-041](/sdlc-foundry/reference/adr/041/)). Production runs the exact image staging tested: `cplat instance promote` compares the registry digests of the staging `sha-` tag and the release tag and refuses on a mismatch (`--accept-digest-mismatch "<reason>"` accepts one with a stated reason), and release CI re-tags that image as `X.Y.Z` instead of rebuilding it. Details and a walk-through: [Promote to production safely](/sdlc-foundry/scenarios/promote-safely/).
