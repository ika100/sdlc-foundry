# ADR-066: Instances scale with a plain HPA or with KEDA, and the platform installs KEDA per cluster when an instance needs it

**Status:** Accepted (2026-10-28)
**Builds on:** [ADR-017](017-gitops-owns-manifests.md) (the gitops repo owns every manifest), [ADR-053](053-domain-model.md) (Instance and Environment are nouns of the model), [ADR-058](058-pinned-versions-and-platform-installed-operators.md) and [ADR-060](060-a-cluster-repo-owns-shared-services.md) (pinned operators, `operators: owner`, cluster repos), [ADR-064](064-a-cache-is-a-platform-rendered-valkey-statefulset.md) (the cache Secret), [ADR-065](065-a-broker-is-nats-jetstream-with-declared-streams-and-per-component-users.md) (durable consumers and the unauthenticated monitoring endpoint), spec 120; the Argo CD side is the companion ADR [067](067-argo-cd-leaves-autoscaled-replica-counts-alone.md)

## Context

Until 5.x an Instance runs a fixed number of replicas. Spec 120 lets an owner declare `scale: {min, max, on: <trigger>}` per component
(the default of its instances) or per instance, with exactly one trigger: CPU or memory utilization of the request, the backlog of the
component's durable consumer on a broker (spec 119), or the length of a list in a cache (spec 118). Queue-driven instances may run at
zero replicas. Kubernetes' own HorizontalPodAutoscaler cannot read a queue and cannot scale to zero; KEDA can, but it is one more
operator per cluster that must be pinned, upgraded (spec 121) and left to the cluster owner where the owner asks for it. A CPU or memory
autoscaler also needs the cluster to serve resource metrics, which most managed clusters and k3s do and some (EKS, kubeadm) do not.

## Decision

1. **`scale` is a property of an Instance**, not of a Resource: declared on `components.<c>` (default for every instance without its own
   `scale` or `replicas`) or on `components.<c>.instances.<env>`; an instance's `scale` replaces the component's as a whole, and `scale`
   and `replicas` exclude each other on one level. Bounds: `max` 1 to 20 (required), `min` 0 to `max` (default 1); zero only with a queue
   trigger and never for a component that is exposed or provides a request API (`openapi`, `grpc`, `graphql`).
2. **CPU and memory use a plain `autoscaling/v2` HorizontalPodAutoscaler**; no KEDA object is rendered for them.
3. **Queue triggers use KEDA** (`ScaledObject`, plus a `TriggerAuthentication` where the scaler needs credentials): the NATS JetStream
   scaler on the component's own durable consumer (lag = pending + unacknowledged messages) and the Redis scaler on a list of the cache.
   The scaler reads credentials only from the Secret the instance itself reads (`<system>-<name>-app` for a cache); nothing secret is
   rendered. An external broker cannot be a trigger: its monitoring endpoint is not part of its contract.
4. **`autoscaling: keda` is a derived property of an Environment** (some instance there has a queue trigger), never declared. KEDA is a
   platform operator in the versions table: `operators/apps/keda.yaml`, one Argo CD application per cluster, exactly when an environment
   without `operators: owner` shows `keda`; cluster repos list it like any operator and their check requires it.
5. **The resource-metrics source is a declared fact of the cluster**, because a render cannot observe a cluster: the gitops repo's
   answer `resource_metrics: provided | install` (default `provided`). With `install`, the pinned `metrics-server` chart is rendered the
   same way, once per cluster, when an instance there uses a CPU or memory trigger. Doctor reports whether the cluster serves metrics.
6. **Timings are platform constants, not knobs**: KEDA polls every 15 s, scales to zero 315 s after the queue was last seen non-empty,
   and the autoscaler waits 345 s before scaling down (5 to 7 minutes after the queue empties); scale-up follows Kubernetes' defaults.

## Consequences

- A system that never declares `scale` renders byte for byte as before; the two closed key lists of spec 114 grow by `scale` only.
- Clusters gain KEDA only where an instance needs it; `/platform:doctor` compares the installed KEDA (and, with `install`, metrics-server)
  with the table and names the queue-triggered instances that depend on it. Spec 121 moves the pins.
- The platform pins the newest KEDA release whose tested Kubernetes range includes the local cluster's k3s (1.32); moving the local
  cluster's Kubernetes lets a later release move KEDA.
- Scaling decisions are visible: `cplat model show` shows the effective `scale` per instance and `autoscaling` per environment,
  `/system:status` the replica count the autoscaler chose next to the bounds.

## Not included

- Cron, HTTP-rate, Prometheus or combined triggers; tuning knobs (polling, cool-down, stabilization); vertical or node autoscaling.
- Scaling resources (databases, caches, brokers) or external components.
- A metrics-source decision per environment (the answer is per gitops repo, which deploys to one cluster).
