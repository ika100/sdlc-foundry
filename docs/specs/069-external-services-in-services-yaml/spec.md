---
spec_id: 069-external-services-in-services-yaml
title: External services in services.yaml
status: done
priority: P1
---

# 069 — External services in services.yaml

## Problem

`render.py` generates a Deployment, a Service and optional routes and secrets. Services that need more cannot be composed: stock-manager has CronJobs, a PVC, a CloudNativePG cluster and an oauth2-proxy; ai-ops is a Helm chart with CRDs. Both are deployed by hand-written Argo CD Applications, so pin-dev, `/gitops:promote` and `/shared:status` do not see them, and every deploy is a hand edit (32 "Deploy image" commits in stock-manager, every ai-ops pin in stock-manager-gitops).

## Stories

As a founder, I want to register a service whose manifests the generator cannot express, so that it is pinned, promoted and reported like every other service.

## Acceptance criteria

- **AC-069.1** Given a services.yaml entry with `external: {kustomize: <path>}`, when render runs, then the environment's overlay includes that package (a path under `applications/<app>/`, `{env}` allowed), sets `external.namespace` if given, and pins the entry's image in its `images`; the ApplicationSet lists the service and no Deployment is generated.
- **AC-069.2** Given `external: {helm: {repoURL, path, revision, imageTag}}`, when render runs, then the overlay holds an Argo CD Application for that chart with `values` merged with `envValues[env]` and the pinned tag at `imageTag` (default `image.tag`), in `external.namespace` or `<app>-<env>`, with server-side apply.
- **AC-069.3** Given an external service, when `scripts/pin.py`, `/gitops:promote` or `/shared:status` run, then they pin and read it like a generated service, and `render.py --check` stays green.
- **AC-069.4** Given an external entry with generator keys (port, probes, env, secrets, expose …), a missing package, a helm source without `repoURL` or `path`, or neither or both kinds, when render runs, then it fails and names the problem.

## Non-goals

- Native CronJob, PVC or NetworkPolicy generation.
- Kyverno guard rails for external packages in their own namespace.

## Open questions

None.

## References

- [Review of stock-manager, stock-manager-gitops and ai-ops](../../e2e/2026-10-22-review-unattended-delivery.md)
- [ADR-029](../../adr/029-external-services.md)

## Changelog

- 2026-10-22 created from the review of the three lan repos
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
