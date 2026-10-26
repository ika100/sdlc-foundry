---
title: "Add Postgres, secrets and observability"
description: "Give a service a database, credentials and telemetry with three declarations."
---

**Situation.** `shop-api` needs a Postgres database, a signing key, a payment-provider key and traces, and you do not want a project for each.

## Steps

In the GitOps repository:

```text
/resource:add postgres
/component:add shop-api --uses postgres --generate shop-api-auth=JWT_KEY --secret shop-api-stripe=STRIPE_KEY
```

Observability is a setting of the environment, not a resource: add `observability: {ui: lgtm}` under `environments.dev` in `system.yaml`. (For an existing component, edit its entry under `components:` in `system.yaml`: add `uses: [postgres]` and the `secrets:` list; the command shows the diff.) Merge the pull requests, then locally:

```bash
devbox run cluster-up                                   # installs the operators the declarations need
/instance:secret set shop-api/dev shop-api-stripe STRIPE_KEY  # hidden prompt; value goes to the local secret store only
```

## What you get

| You declared | The platform renders |
|---|---|
| `resources.postgres` + `uses: [postgres]` | A CloudNativePG cluster per environment where a service uses it; `DATABASE_URL` and `PG*` reach the service from the operator's Secret |
| `generate: [JWT_KEY]` | An `ExternalSecret` plus a password generator: ESO creates a random value in the cluster, once per environment. Nothing in git |
| `remote: {keys: [STRIPE_KEY]}` | An `ExternalSecret` that reads the value from your secret store (locally the `secrets-store` namespace; in production Vault, AWS or GCP) |
| `environments.<env>.observability` | An OpenTelemetry Collector per environment; every service gets the standard `OTEL_*` variables; with `--ui lgtm` a local Grafana at `http://grafana.localhost:8088` |

## Check it

- `/system:status` lists the resources next to the components with their ArgoCD health.
- `/platform:doctor` warns when an operator is missing in the cluster you are pointed at.
- Tracing: call the service, open Grafana, find the trace with `service.name` and `deployment.environment` already set.

## Limits to know

The Postgres resource has no backups, point-in-time recovery or connection pooling; removing it never deletes the data. Observability forwards telemetry but ships no alert rules. See [Resources](/sdlc-foundry/concepts/addons/), [Secrets](/sdlc-foundry/concepts/secrets/) and [ADR-020](/sdlc-foundry/reference/adr/020/), [021](/sdlc-foundry/reference/adr/021/).
