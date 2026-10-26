# Spike: kro as the resource backend

**Date:** 2026-10-07 · **Branch:** `spike/kro-postgres` (code not merged; the branch was deleted on 2026-10-22 once this write-up was kept) · **kro:** v0.9.4 (alpha) · **Cluster:** k3d/k3s v1.32.5 with CloudNativePG 1.30

Question (ADR-020): can kro implement the resource contract (`uses: [postgres]` → Secret `<app>-postgres-app`) better than rendered manifests?

## What was built

- `docs/spikes/kro/postgres-rgd.yaml`: a 40-line `ResourceGraphDefinition` that defines a `Postgres` kind (`version`, `instances`, `storage`, `database`) and expands to one CNPG `Cluster`, with status `ready` and `secretName`.
- `render.py` (spike branch only, not kept): `resources.postgres.backend: kro` emits the small `Postgres` instance (instead of the CNPG `Cluster`) plus the RGD in `bootstrap/<app>-kro-postgres.yaml`. Services and their wiring are byte-for-byte unchanged (test `test_kro_backend_renders_the_same_contract`).

## Measurements

| | rendered CNPG (Part 1) | kro |
|---|---|---|
| Platform code in `render.py` | `postgres_cluster` ≈ 18 lines | ≈ 12 lines + the RGD (40 lines, duplicated as a constant) |
| Instance ready (image cached) | ~20 s | 19 s (+ ~15 s one-off to install kro) |
| Extra cluster components | CNPG operator | CNPG operator **+ kro controller + 2 CRDs + one CRD per RGD kind** |
| Defaults/composition lives in | our Python | the RGD (cluster-side, CEL) |

Installing kro needs no helm binary: k3s' `HelmChart` accepts `oci://registry.k8s.io/kro/charts/kro` directly.

## Findings

**Good**
- Definition-time validation is excellent: a typo in a CEL expression (`schema.spec.nme`) makes the RGD `Inactive` with a precise, type-checked message; an invalid instance (`instances: "three"`) is rejected at admission by the generated CRD schema.
- Status propagation works: `status.ready` / `status.secretName` on the instance summarise the graph, which is what `cplat system status` wants.

**Bad**
- **Deleting an RGD while instances exist orphans them**: the instances keep a finalizer nobody reconciles, the namespace sticks in `Terminating`, and the fix is a manual finalizer patch. Safe order is instances first, then the RGD. With Argo (prune on a shared RGD) this is a trap.
- Generated kinds are dynamic CRDs: `kubeconform` has no schema for `Postgres` (the validate recipe would need `-ignore-missing-schemas` for it, so real validation moves to the cluster), and Argo needs the RGD synced before the first instance (sync wave / `SkipDryRunOnMissingResource`). I did **not** test Argo against it; this is analysis, not measurement.
- Everything the platform ships is v0.x-alpha API (`kro.run/v1alpha1`); the RGD schema changed between recent releases (`GraphRevision` appeared in this one).
- The RGD is cluster-scoped and shared by all environments; it cannot live in a per-environment resource Application, so it becomes another cluster prerequisite (like the operator), applied with the root app.

## Decision criteria (written before the spike) and result

| Criterion | Result |
|---|---|
| Removes platform code | **No**: about the same (12 + 40 vs 18 lines), and the RGD is duplicated |
| e2e stays within +1 min | Likely yes (+~15 s), not measured in CI |
| Argo ordering works without manual sync waves | **Not shown**; needs a wave/option, untested |

## Recommendation

Keep the rendered-manifest backend as the default and the only supported one. The contract (ADR-020) already isolates services from the implementation, so kro can be revisited without touching any `system.yaml`. Revisit when kro reaches v1 **and** at least two resources share enough structure (database, cache, queue) for a common graph to remove code, or when the platform needs cluster-side status/composition (e.g. a self-service portal). Crossplane remains the answer if resources start provisioning cloud resources.
