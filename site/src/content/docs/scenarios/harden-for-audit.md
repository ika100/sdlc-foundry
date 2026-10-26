---
title: "Harden for an audit"
description: "Answer \"how are supply chain, secrets and runtime controlled?\" with configuration and evidence."
---

**Situation.** A customer or auditor asks how you control your software supply chain, secrets and runtime.

## Turn on and show

| Control | How | Evidence you can show |
|---|---|---|
| Pinned, least-privilege CI | Generated workflows pin every Action by commit SHA, declare `permissions: contents: read`, and Dependabot updates the pins monthly | The workflow files; `python3 scripts/pin-actions.py --check` |
| Image scanning and SBOM | Trivy scans each pushed architecture; release builds fail on fixable HIGH or CRITICAL findings; a CycloneDX SBOM per architecture is kept 90 days | CI run artifacts |
| Secrets | `generate:` and `remote:` secrets via External Secrets Operator; no values in git; secret-looking `env` values are rejected | `system.yaml`, [ADR-018](/sdlc-foundry/reference/adr/018/) |
| Runtime hardening | Rendered Deployments run as numeric non-root users with read-only filesystems, dropped capabilities, resource limits | `applications/*/overlays/*/*/deployment.yaml` |
| Policy | Set `policy:` per environment in `system.yaml`: Kyverno policies (`audit` in dev and staging, `enforce` in production by default) and an offline check in `devbox run validate` | Policy files and the CI run |
| Change control | Every composition and promotion is a pull request; GitHub branch protection on `main` | Pull request history |
| Credentials | Separate tokens for ArgoCD (contents: read) and the pull secret (read:packages) | `cluster-up` environment variables |

## Steps

```text
# GitOps repo, system.yaml
environments:
  dev:  {policy: audit}            # audit | enforce | off, per environment
  prod: {policy: enforce}
```

Then `devbox run render` and `devbox run validate`: any workload that violates a rule fails your pull request with the rule's message.

## Be precise about scope

The platform makes these controls the default and checkable; it does not certify you. Operators' own pods are outside the Deployment policies, the Postgres resource has no backup policy, and your cloud account, identity provider and secret backend remain your responsibility. See [Client value](/sdlc-foundry/value/#honest-limits) and [SECURITY.md](/sdlc-foundry/community/security/).
