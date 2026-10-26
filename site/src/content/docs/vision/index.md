---
title: "Vision"
description: "Where sdlc-foundry is going and the principles that decide what it will and will not do."
---

<p class="lead">A small team should be able to run a system the way a platform team would run it, without hiring a platform team.</p>

## North star

You describe a system in a few sentences and a handful of declarations. The platform creates the repositories, builds and scans the images, renders every Kubernetes manifest, keeps secrets out of git, wires databases and telemetry, checks its own conventions, and moves releases through environments by pull request. People review and approve; machines do the repetitive work, and every step is reproducible by a script, not just by a prompt.

## Principles

1. **Declare once, derive the rest.** The GitOps repository owns every manifest and generates them from one `system.yaml`. A component repository ships only an image. Anything you can derive you should not hand-write ([ADR-017](/sdlc-foundry/reference/adr/017/)).
2. **Scripts do the work, agents orchestrate.** Everything that can be code is a tested script (`cplat`) with a preview and a machine-readable result. Agents decide *what* to do and ask before outward-facing actions: pushes, pull requests, repository creation, anything that touches a cluster ([ADR-012](/sdlc-foundry/reference/adr/012/)).
3. **Secure by default, checked before merge.** Non-root numeric users, read-only filesystems, dropped capabilities, SHA-pinned CI actions, scanned images with an SBOM, secrets created in the cluster, policies evaluated in your pull request ([ADR-018](/sdlc-foundry/reference/adr/018/), [019](/sdlc-foundry/reference/adr/019/), [022](/sdlc-foundry/reference/adr/022/)).
4. **Vendor-neutral where it counts.** OpenTelemetry for telemetry, Gateway API for ingress, standard Kubernetes for everything, a contract in front of every resource so the implementation can change without touching your services ([ADR-020](/sdlc-foundry/reference/adr/020/), [021](/sdlc-foundry/reference/adr/021/)).
5. **Honest about limits.** The platform states what it does not do (see [client value](/sdlc-foundry/value/#honest-limits)) and measures what it claims.
6. **One path for humans, CI and agents.** `devbox run <recipe>` is the only way anything runs, so the three behave identically.

## What it is not

- Not a developer portal or service catalog (revisit past roughly 15 to 20 services).
- Not a cloud abstraction layer: the output is plain Kubernetes, Kustomize and ArgoCD.
- Not an agent framework: it extends the Claude Code plugin model rather than replacing it.
- Not a managed service: you run the clusters, the platform removes the toil of describing what runs on them.

## Roadmap

| Status | Item |
|---|---|
| Done (v1) | Shape registry, Python, Java, Go and Next.js templates, per-shape agents, GitOps repo with ApplicationSets and promotion |
| Done (v2) | GitOps repo owns all manifests, Gateway API exposure, tested `cplat` CLI, native multi-arch builds, end-to-end test in CI, `doctor` and `status` |
| Done (v2.1 and later) | External Secrets, supply-chain hardening, Postgres and OpenTelemetry resources, Kyverno guard rails, report-issue feedback loop, designed web starter UI, open source |
| Next | Real multi-environment and multi-cluster guidance, OpenTelemetry SDK for Go services, more shapes through the documented extension contract, release automation |
| Later, if asked | Backups and pooling for the Postgres resource, per-framework alert rules, additional UI stacks for observability |

The roadmap is a direction, not a promise; priorities follow what real users report through [issues](https://github.com/ika100/sdlc-foundry/issues).

## Where this came from

The original product requirements are kept as [design history](/sdlc-foundry/vision/design-history/); the platform's first end-to-end run is described in the [end-to-end scenario](/sdlc-foundry/vision/end-to-end-scenario/). The decisions since then are the [ADRs](/sdlc-foundry/reference/adr/).
