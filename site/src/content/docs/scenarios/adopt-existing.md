---
title: "Adopt an existing repository"
description: "Bring existing services or a v1 setup onto the platform without starting over."
---

**Situation.** You have working repositories and want the platform's flow (agents, CI, GitOps) without rebuilding them.

## Steps

1. **Install the plugins** in the repository and run `/platform:doctor`.
2. **Add the platform reference** and adopt the template for skeleton updates so CI, Dockerfile, `devbox` recipes and `CLAUDE.md` can be pulled in later with `/platform:update` ([Adopting](/sdlc-foundry/guides/adopting/) has the exact steps per shape).
3. **Review the update branch.** `/platform:update` writes to a review branch and lists which skeleton files it overwrote; keep your customisations in the files that are project-owned (application code, tests, documentation).
4. **Add the component to a system's GitOps repository**: `/component:add <component>` writes a complete, reviewable `system.yaml` entry using the component type's runtime defaults.

## Migrating from platform v1 (components shipped Kubernetes manifests)

```text
/component:add <component...> --from-k8s   # seeds port, probes, env, replicas, resources from the old k8s/base
/platform:update --migrate                 # in each component repo: removes k8s/ and obsolete recipes on a review branch
```

Existing image pins are kept, so ArgoCD updates the running Deployments in place instead of recreating them. If some services are still in the old format the command refuses and prints the single command that migrates them together.

## What you get

A service repository that contains code and an image build, a GitOps repository that owns every manifest, and an update path for the skeleton that never touches your code.

## If something looks wrong

`/platform:doctor` first; then see [Troubleshooting](/sdlc-foundry/guides/adopting/#troubleshooting); then `/issue:report`.
