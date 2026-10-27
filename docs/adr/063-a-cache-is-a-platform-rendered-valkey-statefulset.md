# ADR-063: A cache is a platform-rendered single-node Valkey StatefulSet, without an operator; its password is generated once in the cluster

**Status:** Accepted (2026-10-27)
**Builds on:** [ADR-018](018-secrets-with-external-secrets-operator.md) (secrets from External Secrets Operator), [ADR-022](022-kyverno-policies.md) (guard rails), [ADR-057](057-named-typed-resources-with-fixed-contracts.md) (named, typed resources, the `cache` contract slot), [ADR-058](058-pinned-versions-and-platform-installed-operators.md) (pinned versions, operators under `operators/`), [ADR-062](062-environment-backups-with-velero.md) (caches left out of environment backups), spec 118; used by spec 120 (scaling on a list length) and spec 121 (upgrades)

## Context

Spec 118 delivers the `cache` resource type: a Redis-protocol key-value store per environment, a Secret `<system>-<name>-app` with the
keys `url`, `host`, `port` and `password`, and the variables `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT` and `REDIS_PASSWORD` whether the
cache runs in the cluster or at a provider. It runs Valkey (BSD-licensed; Redis 8 is offered only under AGPLv3, RSAL or SSPL), one
node per environment, with no high availability, no backups and no data that must survive an upgrade.

Databases (ADR-058) and buckets (ADR-059) run through operators the platform installs per cluster. An operator earns its place when the
engine needs failover, backups or multi-object coordination. A single Valkey node needs none of that: a StatefulSet, a Service and a
Secret describe it completely, and every Valkey operator or chart would add a CRD, a cluster-wide controller and a second version to
pin and upgrade.

## Decision

1. **The renderer writes a cache instance itself**: one `StatefulSet` `<system>-<name>` (one replica, the official `valkey/valkey`
   image pinned per major in the versions table), one `ClusterIP` Service on port 6379, and, with `persistence: true`, a volume from
   `volumeClaimTemplates` holding an append-only file synced every second. No operator, CRD or Helm chart is installed for a cache;
   `operators: owner` changes nothing for it and doctor has no row for it.
2. **Sizing is the server's memory, not the node's**: the container's memory limit is `memory`, and the server's `maxmemory` is 80 % of
   it with the declared eviction policy, so the server evicts or refuses writes before the kernel kills it.
3. **The password is generated in the cluster once.** A `Password` generator (letters and digits only, so the `url` needs no escaping)
   and an `ExternalSecret` with `refreshPolicy: CreatedOnce` write the four keys of `<system>-<name>-app`; the server reads the
   password from the same Secret. Renders, syncs, restarts and image upgrades never change it. No secret value is in git.
4. **One connection Secret per cache instance is the contract** other specs build on (spec 120's scaler reads the same Secret). Every
   component that uses the cache shares database `0` and the password; the host is namespace-qualified (`<n>.<ns>.svc`).
5. **Every object of a cache instance carries `app.kubernetes.io/name: <name>`**, which is how ADR-062's Velero schedule leaves cache
   objects and volumes out of every environment backup. Cache data is never backed up.
6. **The workload satisfies the guard rails without being matched by them**: non-root, read-only root filesystem, no privilege
   escalation, all capabilities dropped, memory limit and requests. ADR-022's policies (Deployments only) do not change.

## Consequences

- A cache costs one pod (and one volume with persistence) per environment; it needs only External Secrets Operator, which every
  in-cluster resource already needs.
- `/platform:doctor` and `cluster-up` know nothing about caches; a local cluster runs one as soon as a component uses it.
- A change of `persistence` or `storage` stops at the StatefulSet's immutable `volumeClaimTemplates`: delete it with
  `kubectl delete statefulsets.apps <system>-<name> -n <system>-<env> --cascade=orphan` and sync; the pod restarts and an existing
  volume is reused, not resized. No sync option replaces the StatefulSet, so ordinary syncs never restart or empty a cache.
- The Valkey pins move under spec 121's rules (environments in order, downgrades refused, no backup precondition for a cache).
- High availability (replicas, Sentinel, cluster mode) would need a different design, most likely an operator; this ADR would then be
  superseded for that case.

## Not included

- Redis itself, or a choice between Redis and Valkey.
- Per-component users, ACLs or database numbers; TLS inside the cluster; password rotation.
- Valkey modules and server settings beyond `memory`, `maxmemoryPolicy`, `persistence` and `storage`.
- Creating caches at a cloud provider: an external cache's Secret comes from the secret store (ADR-057).
