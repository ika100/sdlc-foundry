---
title: "Client value"
description: "What sdlc-foundry gives you, by role, with the measured evidence and the honest limits."
---

<p class="lead">Fewer decisions to remember, fewer places for mistakes to hide, and every outward step reviewable.</p>

## By role

### Founder or lead of a small team

- **Time to first deploy:** one slash command creates a repository that already builds, tests, scans and publishes a multi-arch image; the GitOps repository runs it locally in a few minutes (`devbox run cluster-up` took about 1m40s from no cluster to every ArgoCD application healthy in the platform's own test).
- **You do not become a platform team.** Secrets, a database, telemetry and policy are declarations in one file, not projects.
- **Reviewable change:** adding a service or promoting a version is a pull request with the generated diff, not a sequence of commands you hope you remembered.
- **Leave any time:** the output is plain Kubernetes, Kustomize, ArgoCD, Gateway API and OpenTelemetry; the platform is Apache-2.0.

### Developer working on one service

- `/component:spec` → `/component:plan` → `/component:build` (spec-driven pipeline) and `/component:fix` (small change) work the same in Python, Java, Go and Next.js repositories; the right agents are routed automatically.
- You never need to know the manifests. A service repository contains code and a Dockerfile, nothing about Kubernetes.
- `devbox run <recipe>` runs identically on your laptop, in CI and for agents.

### Platform or DevOps engineer

- **Everything that can be code is tested code.** The `cplat` CLI has an automated test suite, and an end-to-end test builds three repositories, a cluster and the whole flow in CI.
- **Defaults are policy.** The conventions (non-root, read-only filesystem, limits, allowed registries, no `latest` outside dev) are checked in the pull request and enforced in the cluster.
- **Extensible by contract:** a new language is a new *shape* (a registry entry, a template, a plugin) following a documented contract; a new resource type implements a stable connection contract, so your services never depend on the implementation.

### Security and compliance

| Control | What the platform does | Evidence |
|---|---|---|
| Secrets | Created in the cluster by External Secrets Operator; never stored in git | [ADR-018](/sdlc-foundry/reference/adr/018/) |
| Supply chain | CI actions pinned by commit SHA, least-privilege tokens, Trivy image scan that blocks release builds, CycloneDX SBOM per architecture | [ADR-019](/sdlc-foundry/reference/adr/019/) |
| Runtime hardening | Numeric non-root user, read-only filesystem, no privilege escalation, capabilities dropped | Generated manifests, [ADR-017](/sdlc-foundry/reference/adr/017/) |
| Guard rails | Kyverno policies evaluated offline in your pull request and enforced in the cluster | [ADR-022](/sdlc-foundry/reference/adr/022/) |
| Change control | Promotion and composition happen through reviewed pull requests; a protected `main` | [Promote safely](/sdlc-foundry/scenarios/promote-safely/) |
| Licenses | REUSE-compliant repository, third-party notices, SBOMs for generated images | [Third-party notices](/sdlc-foundry/community/third-party-notices/) |

This supports an audit; it is not a certification. You remain responsible for your own controls.

### Finance and operations

- **CI minutes:** pull requests run only what a change needs; documentation-only changes run the cheap validation jobs, superseded runs are cancelled and dependency updates arrive monthly in groups.
- **Agent cost:** always-on prompt text shrank by 28 percent and the product-manager agent runs on a smaller model; scripts replace long prompts, so common commands spend fewer tokens. Headless runs start on a Sonnet coordinator: a small task measured about $0.48 before and $0.15 after, a full build $1.94 and $1.26, and a full ship $1.20 to $1.60 (first measured, LAN cluster); one budget per run ($15 per ship) caps the worst case (estimated list prices, one benchmark repository).
- **No platform to license or host:** it is a repository, a CLI and plugins.

## Evidence

| Claim | Number | Source |
|---|---|---|
| Defects found by running the real chain, each now guarded | 12 | [Changelog 1.1.1](/sdlc-foundry/reference/changelog/) |
| Multi-arch Next.js image build | about 9 min to about 3 min | [Baselines](/sdlc-foundry/reference/baselines/) |
| Multi-arch Java image build | about 3 min to about 2 min | [Baselines](/sdlc-foundry/reference/baselines/) |
| Always-on prompt tokens | 28 percent fewer | [Changelog](/sdlc-foundry/reference/changelog/) |
| Local cluster from nothing to all applications healthy | about 1m40s | Measured on the test application |

Measured on one test application and Apple-silicon laptops with GitHub-hosted runners; your numbers will differ, the method is in the baselines page.

## Honest limits

- **Claude Code and GitHub are assumed.** The commands are Claude Code plugins, the templates target GitHub Actions and GHCR. Other hosts need work.
- **Slash commands are prompts around scripts.** The scripts are tested; the prompts that call them are not deterministic and always ask before outward actions.
- **Cross-repository work is planned centrally, built per repository.** `/system:spec` and `/system:plan` produce a system spec and a validated plan that assigns every criterion to a repository; each repository builds its part from its own spec, and nothing merges without you.
- **The cluster is yours.** The platform installs operators and ArgoCD on a local k3d cluster; real clusters are bootstrapped by a human once (`devbox run bootstrap`), and operators (External Secrets, CloudNativePG, Kyverno) must exist there if you use their features.
- **Resources are deliberately small.** The Postgres resource has no backups, point-in-time recovery or pooling; observability collects and forwards but ships no alert rules; Go services expose Prometheus metrics but no OpenTelemetry traces yet.
- **Guard rails cover what the platform renders.** Policies check Deployments; pods created by operators are out of scope.
- **Single maintainer.** It is an open-source project with best-effort support.

Next: [usage scenarios](/sdlc-foundry/scenarios/) or [get started](/sdlc-foundry/get-started/).
