# ADR-067: Argo CD leaves the replica count of an autoscaled Deployment alone

**Status:** Accepted (2026-10-28)
**Builds on:** [ADR-014](014-gitops-app-composition-spec.md) (one ApplicationSet per environment over the component overlays), [ADR-017](017-gitops-owns-manifests.md), [ADR-066](066-instances-scale-with-an-hpa-or-keda-installed-per-cluster.md), spec 120

## Context

An autoscaler (an HPA, or the HPA that KEDA owns) writes `spec.replicas` of its Deployment. Argo CD applies the rendered Deployment with
automated sync and self-heal, so a rendered `replicas` would be reset on every sync and the two controllers would fight. The usual
remedies each break something the platform needs: omitting `spec.replicas` makes a client-side apply delete the field when an instance
switches from a fixed count to `scale`, which drops the Deployment to 1 replica; ignoring the fields that the controller manager owns
(`managedFieldsManagers`) keeps ignoring them after the instance switches back to a fixed count; `Replace=true` recreates objects on
every sync. The component ApplicationSet of an environment is one template for all its components and uses fasttemplate, so a
per-component field cannot be switched on by a parameter.

## Decision

1. **A scaled Deployment keeps `spec.replicas`, set to `min`**: it is what a new Deployment starts with, and what a sync that reaches a
   Deployment before its ignore rule applies sets (never below the new `min`).
2. **The environment's component ApplicationSet ignores `/spec/replicas` of each scaled Deployment by name** (one
   `ignoreDifferences` entry per scaled instance of that environment) **and syncs with `RespectIgnoreDifferences=true`**, so neither the
   diff nor a sync (self-heal included) touches the live count. An environment without a scaled instance keeps its ApplicationSet byte for
   byte.
3. **Autoscaler objects are files of the component overlay** (`hpa.yaml`, `scaledobject.yaml`, `triggerauthentication.yaml`), so removing
   `scale` removes them and Argo CD's prune deletes them; the Deployment then gets its fixed count with the next sync because its name
   left the ignore list.
4. **KEDA objects sync in wave 1, after the Deployment and after the prune of an HPA they replace**, with
   `SkipDryRunOnMissingResource=true`; an environment with a KEDA instance retries its sync (the platform's `RETRY`). No sync option
   recreates an object.

## Consequences

- An Argo CD application with a scaled instance stays Synced while the autoscaler works, and a switch in either direction never runs fewer
  replicas than the new `min` (or the new fixed count).
- The ignore list names Deployments, not fields owned by a manager, so a fixed count takes effect again as soon as `scale` is removed.
- KEDA's own HPA (`keda-hpa-<component>`) is a child of the `ScaledObject` and not tracked by Argo CD; this holds with Argo CD's annotation
  tracking (the default since Argo CD 3.0). A cluster that tracks by label must switch to annotation tracking.

## Not included

- Ignoring any other field (resources, images): only the replica count is handed to the autoscaler.
- Changing the ApplicationSet to Go templates or per-component ApplicationSets (both would change every system's rendered tree).
