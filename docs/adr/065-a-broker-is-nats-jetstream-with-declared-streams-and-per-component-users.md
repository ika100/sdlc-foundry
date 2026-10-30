# ADR-065: A broker is NATS JetStream from the official chart, with declared streams and consumers and one user per component

**Status:** Accepted (2026-10-27)
**Amended by:** [ADR-072](072-a-generated-credential-is-written-once-by-a-create-only-job.md) (point 4, the user passwords are written by a credentials Job)
**Builds on:** [ADR-017](017-gitops-owns-manifests.md) (the gitops repo owns every manifest), [ADR-018](018-secrets-with-external-secrets-operator.md) (secrets from External Secrets Operator), [ADR-022](022-kyverno-policies.md) (guard rails), [ADR-057](057-named-typed-resources-with-fixed-contracts.md) (named, typed resources, the `broker` slot), [ADR-058](058-pinned-versions-and-platform-installed-operators.md) and [ADR-060](060-a-cluster-repo-owns-shared-services.md) (pinned operators, shared with cluster repos), [ADR-062](062-environment-backups-with-velero.md) (environment backups), spec 119; used by spec 120 (scaling consumers on their backlog) and spec 121 (upgrades)

## Context

Since 5.0 a system declares APIs of `type: events` with one provider and any number of consumers, but nothing carries the events. Spec
119 adds the resource type `broker` behind them: one broker per environment where a component of an events API runs, a stream per
API, a durable consumer per consuming component, and an environment contract that is the same whether the broker runs in the cluster
or at a provider such as Synadia Cloud. It has to run on a laptop, survive configuration changes without losing messages, and give
spec 120 the names and the monitoring endpoint to scale on.

## Decision

1. **The broker is NATS with JetStream**, one small server (or three with `replicas: 3`) per environment, installed from the official
   `nats` Helm chart as a nested Argo CD application that the broker's addon directory renders. Chart and server image are pinned in
   the renderer's versions table (`NATS_CHART`, `NATS_IMAGES` per minor line).
2. **Streams and consumers are declared objects of the NATS JetStream controller (NACK)**, which is a platform operator in the versions
   table (`operators/apps/nack.yaml`, or a cluster repo's `operators:` list), running in its default mode with one `Account` object per
   broker instance. The platform never calls the broker itself.
3. **Names are derived, never configured**: stream `<system>-<api>` capturing `<system>.<api>.>`, kept 7 days; the durable (pull)
   consumer is named after the component, acknowledgement within 30 seconds. Retention and delivery settings are not per API.
4. **Each component has its own user per environment**, created once by a credentials Job (amended by [ADR-072](072-a-generated-credential-is-written-once-by-a-create-only-job.md): ESO wrote it twice, #316) into
   `<system>-<name>-<component>-app` (`url`, `user`, `password`). Rights are subject permissions: the provider publishes under its API's
   prefix, a consumer only fetches from and acknowledges on its own durable consumer, and everybody subscribes only to its own inbox
   prefix `_INBOX.<component>` (handed over as `NATS_INBOX_PREFIX`). NACK has a separate admin user.
5. **Components reach a broker through events APIs**, not through `uses`: an API binds to `broker: <name>` or to the system's only
   broker, and its provider and consumers get `NATS_URL`, `NATS_USER`, `NATS_PASSWORD`, `NATS_INBOX_PREFIX` and `EVENTS_<API>_STREAM`,
   `EVENTS_<API>_SUBJECT_PREFIX`, `EVENTS_<API>_CONSUMER`.
6. **Nothing that holds messages is deleted by a render or a sync**: streams and consumers carry NACK's `preventDelete`, Argo CD's
   `Delete=false` and `IgnoreExtraneous`, and the addon application never prunes. The render that drops one prints it; a person deletes it.
7. **An external broker is NATS too**: the platform renders no server and no NACK object, reads each component's credentials from the
   secret store, and lists the streams and consumers the broker's owner must create.

## Consequences

- An in-cluster broker needs External Secrets Operator and NACK on its cluster; `operators: owner` leaves NACK to the cluster's owner,
  and doctor compares NACK and each broker's chart and image with the table.
- Spec 120 scales a consumer on `num_pending` of its durable consumer, read from the server's monitoring endpoint
  (`http://<system>-<name>.<system>-<env>.svc:8222`), which is unauthenticated on the ClusterIP Service (design decision 17).
- Rights changes are hot-reloaded by the config reloader (the chart's `podTemplate.configChecksumAnnotation` defaults to `false`, verified
  in the nats chart 2.15.1 `values.yaml`). Adding or removing a component restarts the broker pods once, because its password reaches the
  server as a container variable (decision 5).
- Broker volumes are part of the environment backup (ADR-062); there is no stream-level backup or replay.
- Spec 121 moves the chart, image and NACK pins; this ADR defines no upgrade procedure.
- The resource-instance-as-a-chart pattern (a nested Argo CD application in an addon directory) is available to later resource types
  that ship as charts.

## Not included

- Kafka, RabbitMQ or any other broker; NATS accounts, leaf nodes, request/reply, plain subjects, key-value and object stores.
- Event schemas, per-API retention or delivery settings, more than one provider per API, sharing a broker between systems.
- Publisher or subscriber code in the templates (the docs carry one Python example).
