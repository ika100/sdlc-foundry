# ADR-020: Addons: a stable contract for backing services

**Status:** Accepted
**Date:** 2026-10-07
**Builds on:** ADR-017 (the GitOps repo owns manifests), ADR-018 (secrets)

## Context

Services need a database (later metrics, queues). Hand-written operator manifests per product repeat the same decisions and leak the implementation (CloudNativePG, Prometheus, ...) into every product. We want one declaration, a connection contract services can rely on, and the freedom to change how an addon is implemented.

## Decision

1. **Declare once, use by name.** `app.yaml` `addons:` declares the backing service and its sizing (scalars or per-environment maps, like `replicas`); a service lists `uses: [postgres]`. Services never name the operator.
2. **The contract is the connection Secret and env, not the manifests.** For `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, read with `secretKeyRef` from the operator's Secret `<app>-postgres-app` (CloudNativePG writes keys `uri, host, port, dbname, user, password`; the lowercase keys are not usable through `envFrom`, hence explicit mapping). Credentials never appear in git. One database per application and environment (database and owner are named after the application).
3. **Implementation today: rendered manifests.** `render.py` writes `applications/<app>/addons/<env>/<addon>/cluster.yaml` (+ kustomization) only for environments where a service uses the addon, and a `<app>-addons-<env>` ApplicationSet. `render.py`'s `ADDONS` table is the contract; adding an addon means adding an entry and its manifest function.
4. **Operators are cluster prerequisites.** `cluster-up` installs CloudNativePG locally (k3s `HelmChart`, pinned) when `addons.postgres` is declared; real clusters install it themselves, as with ESO and the Gateway. `cplat doctor` warns when the CRD is missing.
5. **Data safety.** The addon Application has `prune: false`, and removing an addon only makes its Application disappear: the database and its volume stay until a human deletes them. `cplat addon remove` refuses while a service still uses the addon.
6. **Alternative backends** (kro, Crossplane) must implement the same contract. The [kro spike](../spikes/kro.md) (2026-10-07) found no code saved and new Argo ordering traps, so rendered manifests stay the only backend; revisit when kro reaches v1 and several addons share one graph.

## Not included

Backups/PITR, connection pooling (PgBouncer), extensions, cross-environment data copy, and ordering guarantees between the database and its consumers (pods retry until the Secret exists; Argo orders nothing across Applications).
