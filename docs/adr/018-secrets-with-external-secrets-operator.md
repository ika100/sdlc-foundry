# ADR-018: Secrets come from External Secrets Operator; git holds references, never values

**Status:** Accepted
**Date:** 2026-10-07
**Amended by:** [ADR-072](072-a-generated-credential-is-written-once-by-a-create-only-job.md) (`generate` is written by a credentials Job, an exception to this ADR)
**Builds on:** ADR-017 (the GitOps repo owns every manifest)

## Context

`secretRefs` only named Secrets that had to exist already; nothing created them. Secret values must not live in git: history is permanent, and every clone, fork and CI token of the GitOps repo would read the secrets of all environments. Sealed Secrets / SOPS keep encrypted values in git, but add a key-management burden (controller keys or an Argo plugin) and still make rotation a git change. The platform already assumes ArgoCD and external stores.

## Decision

1. **External Secrets Operator (ESO)** creates every application Secret. `services.yaml` declares them per service under `secrets:`; `render.py` emits one `ExternalSecret` per entry (plus a `Password` generator when needed) and exposes the resulting Secret through `envFrom`. `secretRefs` stays for Secrets managed elsewhere.
2. **Two modes, never mixed in one Secret:**
   - `generate: [KEY, ...]`: ESO's `Password` generator creates random values **in the cluster**, once per environment (`refreshInterval: "0"`, `creationPolicy: Owner`). For secrets the product owns: DB passwords, signing keys, internal tokens. No store, no human, identical locally and on real clusters. **Amended by [ADR-072](072-a-generated-credential-is-written-once-by-a-create-only-job.md):** generated values are no longer written by ESO; a create-only credentials Job writes each Secret exactly once (an exception to "every Secret comes from External Secrets"). `remote:` is unchanged. Deleting the Secret regenerates (rotates) the values on the next sync.
   - `remote: {keys: [...], path?}`: read from the `secretStore` named in `app.yaml` (default `ClusterSecretStore/platform-secrets`, path `{app}-{env}-<secret>`), refreshed hourly. For credentials someone else issues (payment, mail, third-party APIs).
3. **Local cluster**: `cluster-up` installs ESO with a k3s `HelmChart` (no helm binary; pinned chart version) and a `platform-secrets` store using ESO's Kubernetes provider over the `secrets-store` namespace. `cplat secret set|list` (`/gitops:secret`) writes remote values there from a hidden prompt or stdin; they never touch git or a command line.
4. **Real clusters** bring their own ClusterSecretStore (Vault, AWS Secrets Manager, GCP Secret Manager, ...) under the name configured in `app.yaml`; the platform does not provision a backend.
5. **Guard rail**: `render.py` rejects secret-looking keys (`*PASSWORD*`, `*TOKEN*`, `*API_KEY*`, ...) with a value in `env:` and points to `secrets:`.

## Consequences

- A fresh service gets working credentials with one flag (`compose add --generate app-auth=DB_PASSWORD`).
- Isolation between environments by name convention in the local store only; production stores enforce it with their own policies.
- ESO becomes a cluster prerequisite for any service that declares `secrets:`.
