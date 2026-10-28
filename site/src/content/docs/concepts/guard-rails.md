---
title: "Guard rails"
description: "The platform's own conventions as Kyverno policy, checked before merge and enforced in the cluster."
sidebar:
  order: 7
---

Each environment has a `policy` in `system.yaml`: `audit`, `enforce` or `off`. Unless it is `off`, the platform renders a namespaced Kyverno policy per environment that encodes its conventions for every Deployment:

- numeric non-root user, read-only root filesystem, no privilege escalation, all capabilities dropped,
- no privileged containers, host namespaces or `hostPath` volumes,
- CPU and memory requests and a memory limit,
- the `app.kubernetes.io/part-of` label,
- images only from allowed registries (derived from your components' images, plus resource images and the system's `registries`),
- no `:latest` or untagged images outside dev.

**Modes per environment:** `audit` (report), `enforce` (deny) or `off`; defaults are Audit in dev and staging, Enforce in production.

**Shift-left:** `devbox run validate` (and CI) build each overlay and evaluate it with the Kyverno CLI, so a violating change fails its pull request in every mode. Together with pinned CI actions, image scanning with an SBOM and least-privilege tokens this is the platform's [security posture](/sdlc-foundry/scenarios/harden-for-audit/) ([ADR-019](/sdlc-foundry/reference/adr/019/), [ADR-022](/sdlc-foundry/reference/adr/022/)).
