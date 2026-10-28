# ADR-059: An in-cluster bucket is its own SeaweedFS, run by the platform-installed SeaweedFS operator; its keys are generated in the cluster and Argo CD never deletes it

**Status:** Accepted (2026-10-26)
**Builds on:** [ADR-018](018-secrets-with-external-secrets-operator.md) (secrets from External Secrets Operator), [ADR-020](020-addons-contract.md) (the resource contract), [ADR-057](057-named-typed-resources-with-fixed-contracts.md) (named, typed resources, the `bucket` contract slot), [ADR-058](058-pinned-versions-and-platform-installed-operators.md) (pinned versions, operators under `operators/`), spec 116; used by spec 117 (backups) and spec 121 (upgrades)

## Context

Spec 116 delivers the `bucket` resource type: an S3-compatible bucket `<system>-<name>` per environment, a Secret `<system>-<name>-app` with six keys, and the same variables whether the bucket runs in the cluster or at a provider. The user chose SeaweedFS as the in-cluster backend, installed by the platform as a pinned Argo CD application per cluster when needed, with `operators: owner` as the opt-out.

Three facts shape how it runs:

- The bucket name `<system>-<name>` is the same in every environment, and dev, staging and prod share one cluster locally (and may share one in production). One shared SeaweedFS per cluster would need three buckets of the same name, which S3 does not allow.
- `storage` is the bucket's capacity, and the spec rules out quotas beyond the volume size. A volume per bucket instance gives exactly that.
- The credentials of one environment must be refused by another environment's bucket, and no key may be in git.

## Decision

1. **The cluster-level piece is the SeaweedFS operator** (`seaweedfs-operator` chart), rendered as `operators/apps/seaweedfs.yaml` (Argo application `operator-seaweedfs`) under ADR-058's rules. It is rendered only when some system has an in-cluster bucket instance in an environment without `operators: owner`. It plays the part CloudNativePG plays for databases.
2. **Each in-cluster bucket instance is its own SeaweedFS** (`Seaweed` custom resource `<system>-<name>`: one master, one volume server with a `storage`-sized volume, one filer with a persistent metadata store, and the filer's embedded S3 endpoint), in the instance's namespace and Argo application `addon-<name>-<env>`. The bucket, the IAM identity and its access grant are the operator's `Bucket`, `S3Identity` and `S3Credentials` resources. The SeaweedFS image is pinned in the renderer's versions table (`SEAWEEDFS_IMAGE`) next to the operator chart.
3. **Keys are generated in the cluster by External Secrets Operator and adopted by the SeaweedFS operator.** An `ExternalSecret` with two `Password` generators writes `<system>-<name>-app` once (all six contract keys, through a template). `S3Credentials` points at that Secret, and the operator adopts an existing key pair. One identity per bucket instance has read and write access to that bucket only. Environments never share a store or a key.
4. **Argo CD never deletes a bucket.** Every object of an in-cluster bucket carries `argocd.argoproj.io/sync-options: Delete=false`. The `Bucket` and `S3Credentials` use `reclaimPolicy: Retain`. Removing the resource, or its Argo application, leaves the store, its volume, its data and its Secret in the cluster until a human deletes them.
5. **`versioning: false` renders the S3 state `Suspended`, not `Off`.** S3 (and the operator's CRD) never lets a bucket go back to `Off` once versioning was on, and the renderer has no history. `Suspended` behaves as unversioned for new writes and allows switching both ways.
6. **The embedded S3 endpoint of the filer is used, not the standalone S3 gateway.** The gateway is a Deployment, and the platform's Kyverno guard rails (ADR-022) check every Deployment in an environment's namespace. The filer is a StatefulSet, so the guard rails stay unchanged for every system. The embedded endpoint is deprecated upstream. Moving to the gateway is a later spec, which must also exempt or satisfy the guard rails.

## Consequences

- A bucket instance costs three pods and two small volumes (master and filer metadata, 1Gi each) next to its data volume. That is acceptable for dev clusters and keeps every instance independent.
- In-cluster buckets need External Secrets Operator in the cluster, as `secrets.generate` already does.
- `cluster-up` installs the operator locally like CloudNativePG: from `operators/` with Argo CD, or as a k3s HelmChart without it. `devbox run bootstrap` waits for the `buckets.seaweed.seaweedfs.com` CRD before applying the system roots.
- A cluster whose owner installed the SeaweedFS operator by hand sets `operators: owner` before applying `operators/root.yaml`, and `/platform:doctor` compares the installed operator version with the table's.
- A bucket that was ever versioned keeps its old versions after `versioning: false`. Only new writes stop creating versions.
- Spec 117 writes backups to such a bucket, and spec 121 moves both pins (`SEAWEEDFS_IMAGE`, the operator chart) through the environments.

## Not included

- One shared SeaweedFS per cluster, a store per system, or bucket quotas.
- Per-component credentials, read-only access, lifecycle rules, replication or public access (spec 116 non-goals).
- Creating buckets or keys at a cloud provider: an external bucket's Secret comes from the secret store (ADR-057).
