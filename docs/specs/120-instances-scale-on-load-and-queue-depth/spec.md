---
spec_id: 120-instances-scale-on-load-and-queue-depth
title: Instances scale on load and queue depth
status: done
priority: P1
---

# 120 — Instances scale on load and queue depth

## Problem

In 5.0 (spec 114) an Instance runs a fixed number of replicas: `components.<c>.replicas` or `instances.<env>.replicas`. A web API that gets a burst of traffic stays at that number, and a consumer of an events API (spec 119) or a worker reading a list from a cache (spec 118) runs all day although its queue is empty most of the time, or falls behind when the queue fills. Today the only fix is to raise `replicas` by hand in a PR and lower it again later. With the broker and cache resources of specs 118 and 119 arriving, queue-driven workers become a normal part of a system, so scaling has to become something the owner declares once per Instance and the platform renders, installs and shows. Scaling is a property of an Instance (a component in one environment), not a Resource. This spec is an additive 5.x extension of the closed key lists of spec 114 (one new key, `scale`); spec 114 itself stays as approved.

## Stories

- As a system owner, I want to declare `scale: {min, max, on: {cpu: 70}}` on an instance, so that its replica count follows the load between two bounds without PRs.
- As the owner of a consumer of an events API, I want it to scale on the number of messages waiting for its durable consumer, down to zero when idle, so that it keeps up with bursts and costs nothing when there is no work.
- As the owner of a worker that reads a list in the cache, I want it to scale on the length of that list, so that the same works for cache-backed queues.
- As an operator, I want the scaling operator installed only on clusters that need it, at a version the platform pins, and Argo CD not to undo what the autoscaler does, so that scaling is not a constant fight between two controllers.
- As a developer, I want `cplat model show` and `/system:status` to show the bounds and the current replica count of a scaled instance, so that I can see what the autoscaler decided.

## Acceptance criteria

### Declaring scale

- **AC-120.1** Given `instances.<env>.scale` on a service or website component, when it is rendered, then its allowed keys are `min`, `max` and `on`; `max` is required and an integer from 1 to 20, `min` is an integer from 0 to `max` and defaults to 1, and another key, a missing `max` or a value out of range fails the render naming the component, the environment, the key and the allowed range.
- **AC-120.2** Given `components.<c>.scale`, when it is rendered, then it applies to every instance of the component that has neither its own `scale` nor its own `replicas`; an instance `scale` replaces the component's `scale` as a whole (no key-by-key merge), and an instance `replicas` makes that instance run the fixed number with no autoscaler.
- **AC-120.3** Given `scale` and `replicas` on the same level (both on the component, or both on one instance), when it is rendered, then the render writes nothing and fails naming the component, the environment if any, and both keys.
- **AC-120.4** Given `scale.on`, when it is rendered, then it must be exactly one of `{cpu: <percent>}`, `{memory: <percent>}`, `{consumes: <api>, lag: <n>}` or `{cache: <resource>, list: <key>, length: <n>}`; an empty `on`, two triggers, a queue trigger missing its number or an unknown key fails listing the four forms.
- **AC-120.5** Given `/component:set <name> --instance <env> --replicas <n>` on an instance whose effective configuration has `scale`, when it runs, then it changes nothing and fails saying the instance is scaled and naming the `scale` key to remove first.

### Scaling on CPU and memory

- **AC-120.6** Given `on: {cpu: <percent>}` or `on: {memory: <percent>}` with an integer from 1 to 100, when the instance is deployed, then a plain Kubernetes HorizontalPodAutoscaler keeps the instance's average utilization of its request near that percent between `min` and `max`, and no KEDA object is rendered for it; another value fails naming the allowed range.
- **AC-120.7** Given a `cpu` (or `memory`) trigger on an instance whose effective `resources` (component `resources` with the instance's override) set no CPU (or memory) request, when it is rendered, then it fails naming the component, the environment and the missing request.
- **AC-120.8** Given `min: 0` with a `cpu` or `memory` trigger, when it is rendered, then it fails saying scale to zero needs a queue trigger (`consumes` or `cache`).

### Scaling on queue depth

- **AC-120.9** Given `on: {consumes: <api>, lag: <n>}`, when it is rendered, then `<api>` must be listed in the component's `consumes`, be of type `events` and be bound to a broker resource as spec 119 defines, and `lag` must be an integer of at least 1; a violation fails naming the component, the API and the reason.
- **AC-120.10** Given a deployed instance with `on: {consumes: <api>, lag: 10}`, `min: 1` and `max: 5`, when the durable consumer spec 119 gives this component for that API has 30 pending messages, then the instance runs 3 replicas within 2 minutes; with 100 pending it runs 5 (never more than `max`).
- **AC-120.11** Given `on: {cache: <resource>, list: <key>, length: <n>}`, when it is rendered, then `<resource>` must be a cache resource (spec 118) listed in the component's `uses`, `list` a non-empty string and `length` an integer of at least 1; a violation fails naming the component, the key and the reason.
- **AC-120.12** Given a deployed instance with `on: {cache: <resource>, list: jobs, length: 10}`, `min: 1` and `max: 5`, when the list `jobs` in that cache's instance of the same environment holds 30 entries, then the instance runs 3 replicas within 2 minutes; with 100 entries it runs 5.
- **AC-120.13** Given a queue trigger whose broker or cache requires credentials, when it is deployed, then the scaler authenticates with the same Secret the instance reads its connection settings from: `<system>-<name>-app` for a cache resource `<name>`, and `<system>-<name>-<component>-app` for the component's own credentials on a broker resource `<name>`; the rendered tree contains no credential value.
- **AC-120.14** Given a queue-triggered instance with `min: 0` and an empty queue, when it has been idle for the cool-down, then it runs 0 replicas; when one message (or list entry) arrives, then it runs at least 1 replica within 60 seconds.
- **AC-120.15** Given a queue-triggered instance above `min`, when its queue stays empty, then it returns to `min` replicas no earlier than 5 minutes and no later than 7 minutes after the queue became empty.
- **AC-120.28** Given `min: 0` on an instance of a component with `expose`, or of a component that provides an `openapi`, `grpc` or `graphql` API, when it is rendered, then it fails saying an instance at zero replicas cannot answer requests and naming the exposed host or the provided APIs.

### Environment and cluster

- **AC-120.16** Given a system, when `cplat model show --json` runs, then an environment where at least one instance has a queue trigger shows `autoscaling: keda`, and an environment whose instances use only `cpu`/`memory` triggers or no `scale` shows `autoscaling: null`; this value is derived from the instances, and an `autoscaling` key under `environments.<env>` fails the render as any unknown environment key does (AC-114.4).
- **AC-120.17** Given the platform's local cluster set-up, when it creates a cluster for a system, then the cluster has a resource-metrics source so that a `cpu` HorizontalPodAutoscaler reports current utilization within 2 minutes of the instance starting, and KEDA is installed when some environment of the system shows `autoscaling: keda` and not otherwise.
- **AC-120.27** Given a cluster that hosts one or more environments, when the system is rendered, then the platform installs KEDA there as one pinned Argo CD application per cluster (never one per environment) exactly when some environment on that cluster without `operators: owner` shows `autoscaling: keda`, and renders no KEDA application for a cluster where none does; when an instance on that cluster uses a `cpu` or `memory` trigger and the cluster serves no resource metrics, a pinned metrics-source application is installed the same way.
- **AC-120.18** Given an environment with `operators: owner` that shows `autoscaling: keda`, when `/platform:doctor` runs, then it compares the KEDA version installed on that environment's cluster with the version the platform release expects, and warns naming the environment, the scaled instances and the expected version when KEDA is missing or at another version; the platform installs nothing for that environment.

### Argo CD and the autoscaler

- **AC-120.19** Given a scaled instance whose autoscaler has changed its replica count, when Argo CD compares or syncs the instance's application (including a self-heal), then the application stays Synced and the sync does not change the current replica count.
- **AC-120.20** Given an instance changed from `replicas: <n>` to `scale` (or back), when the change syncs, then the running replica count does not drop below the new `min` (or the new fixed number) at any point, and switching back removes the instance's autoscaler object.

### Seeing it

- **AC-120.21** Given a scaled instance, when `cplat model show --json` runs, then the instance shows `scale` with `min`, `max` and `on` as effective for that environment and `replicas: null`; an unscaled instance shows its `replicas` and `scale: null`.
- **AC-120.22** Given `/system:status` and a scaled instance, when it runs, then that instance's cell adds the current replica count read from the cluster and the bounds, as `3 (1–5)`; when the cluster cannot be reached it shows `? (1–5)`; cells of unscaled instances do not change.

### End to end

- **AC-120.23** Given the end-to-end cluster test with a system whose consumer component `consumes` an events API bound to a broker, with `scale: {min: 0, max: 5, on: {consumes: <api>, lag: 10}}` in dev, when the test publishes 100 messages, then the consumer runs 5 replicas within 2 minutes, and after it has processed them it runs 0 replicas within 7 minutes; the Argo application stays Synced throughout.
- **AC-120.24** Given `docs/DOMAIN-MODEL.md` and the `system.yaml` schema docs, when this spec is built, then they describe `scale` as an Instance property with the four trigger forms, the component-level default, the exclusivity with `replicas` and `autoscaling` as a derived Environment property, with one example per trigger form.

### Upgrades and the 5.0 schema

- **AC-120.25** Given a platform release, when KEDA (or the metrics source of AC-120.27) is installed or upgraded on a cluster, then it is the exact version that release pins in spec 121's versions table (no range, no "latest"), and an upgrade to a new pinned version follows spec 121: environment by environment in promotion order, with every queue-triggered instance still scaling across the upgrade.
- **AC-120.26** Given the closed key lists of spec 114 (AC-114.12 for a component, AC-114.13 for an instance), when a 5.x `system.yaml` is rendered, then `scale` is accepted as one more key on a service or website component and on its instances, every other unknown key still fails as AC-114.12 and AC-114.13 say, and a `system.yaml` without `scale` renders exactly as it did before this spec.

## Non-goals

- Amending spec 114: this spec only extends its closed key lists.
- Scaling a Resource (database, cache, broker, bucket replicas stay as their own specs define them).
- Cron, HTTP-request-rate, Prometheus-query or other triggers; combining several triggers on one instance.
- Vertical scaling (changing requests and limits automatically) and node or cluster autoscaling.
- Scale flags on `/component:set`; `scale` is edited in `system.yaml`.
- `/instance:promote` copying `scale` from the source instance; scaling stays per instance or comes from the component default.
- Off-the-shelf components (for example Node-RED) and scaling them.
- The upgrade procedure for KEDA and the metrics source; spec 121 owns it.
- Tuning knobs beyond `min`, `max` and the trigger's number (polling interval, cool-down, stabilization windows).

## Open questions

- ~~Confirm: `scale` may be set on the component as a default for all its instances.~~ Answered: yes. See AC-120.2, AC-120.5 and AC-120.21.
- ~~Is the need for KEDA derived or declared as `environments.<env>.autoscaling: keda`?~~ Answered: derived, no `autoscaling` key. See AC-120.16.
- ~~Who installs KEDA outside the local cluster?~~ Answered (cross-cutting decision for specs 115–121): the platform, as one pinned Argo CD application per cluster when needed; an environment opts out with `operators: owner` and `/platform:doctor` checks the version. See AC-120.27, AC-120.18 and AC-120.25.
- ~~Confirm the bounds: `max` required and at most 20, `min` defaults to 1.~~ Answered: yes. See AC-120.1.
- ~~Confirm: scale to zero only with a queue trigger.~~ Answered: yes. See AC-120.8 and AC-120.14.
- ~~Should `min: 0` be refused for exposed components and providers of request APIs?~~ Answered: yes. See AC-120.28.
- ~~Confirm the timings (5 min cool-down, 60 s wake, 2 min scale-up).~~ Answered: yes. See AC-120.10, AC-120.12, AC-120.14, AC-120.15 and AC-120.23.
- ~~Confirm: exactly one trigger per instance.~~ Answered: yes. See AC-120.4 and Non-goals.
- ~~Confirm: `cpu`/`memory` targets are integers from 1 to 100 percent.~~ Answered: yes. See AC-120.6.

## Changelog

- 2026-10-26 created
- 2026-10-26 open questions answered: KEDA installed per cluster as a pinned Argo CD application with `operators: owner` opt-out (AC-120.27, AC-120.18 reworded), Secret names in AC-120.13, scale to zero refused for request-serving components (AC-120.28), additive extension of spec 114's key lists (AC-120.26), pinned versions per spec 121 (AC-120.25)
- 2026-10-26 approved
- 2026-10-28 readings recorded at plan time (design.md, "Spec readings"): `on` is required (AC-120.1); an external broker is refused as a trigger and the broker trigger needs no credentials because the monitoring endpoint is unauthenticated (AC-120.9, AC-120.13); whether a cluster serves resource metrics is declared by the gitops repo's `resource_metrics` answer, since a render cannot see it (AC-120.27); the 5-minute lower bound of AC-120.15 holds for `min: 0` and, for `min` ≥ 1, when the last `min × lag` items are worked off within 30 s; the local cluster installs KEDA from `operators/apps/keda.yaml`, and a cluster whose KEDA environments are all `operators: owner` forces it with `WITH_KEDA=1` and `WITH_ARGO=0` (AC-120.17); without Argo CD in the e2e, AC-120.23's "stays Synced" is shown by an unchanged replica count and generation plus render tests of the ignore rule
- 2026-10-28 building
- 2026-10-28 done
