---
title: "Add databases, caches, brokers and buckets"
description: "Give components a database, a cache, a message broker, file storage, secrets and telemetry by declaring them in system.yaml."
---

**Situation.** `shop-api` needs a Postgres database for orders, a cache for sessions, a bucket for catalog images, a signing key and a payment-provider key. It publishes order events that `shop-mailer` reads. You want neither a project for each nor a credential in git.

## Steps

In the GitOps repository, declare the resources, then the components that use them:

```text
/resource:add orders-db --type database
/resource:add sessions --type cache
/resource:add images --type bucket
/resource:add bus --type broker
/component:add shop-api --uses orders-db --uses sessions --uses images --provides orders:events --generate shop-api-auth=JWT_KEY --secret shop-api-stripe=STRIPE_KEY
/component:add shop-mailer --consumes orders
```

Each command opens one pull request with the `system.yaml` change and the rendered manifests. Observability is a setting of the environment, not a resource: add `observability: {ui: lgtm}` under `environments.dev` in `system.yaml`. Merge the pull requests, then locally:

```bash
devbox run cluster-up                                         # installs the operators the declarations need
/instance:secret set shop-api/dev shop-api-stripe STRIPE_KEY  # hidden prompt; the value goes to the local secret store only
```

## What you get

| You declared | The platform renders | The component gets |
|---|---|---|
| `orders-db`, `type: database` | A CloudNativePG cluster per environment | `DATABASE_URL` and `PG*` |
| `sessions`, `type: cache` | One Valkey server per environment (Redis protocol) | `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` |
| `images`, `type: bucket` | An S3-compatible store per environment (SeaweedFS) | `S3_*` and `AWS_*` |
| `bus`, `type: broker`, and the events API `orders` | A NATS server with JetStream per environment, one stream for `orders` and one durable consumer for `shop-mailer` | `NATS_URL`, its own `NATS_USER` and `NATS_PASSWORD`, and `EVENTS_ORDERS_*` |
| `--generate shop-api-auth=JWT_KEY` | An `ExternalSecret` with a generator: a random value created in the cluster, once per environment | `JWT_KEY` |
| `--secret shop-api-stripe=STRIPE_KEY` | An `ExternalSecret` that reads the value from your secret store (locally the `secrets-store` namespace; in production Vault, AWS or GCP) | `STRIPE_KEY` |
| `environments.<env>.observability` | An OpenTelemetry Collector per environment; with `ui: lgtm` a local Grafana | the standard `OTEL_*` variables |

Every resource can live outside the cluster instead: `/resource:add orders-db --type database --external` renders no server, only the `ExternalSecret` that fills the same variables from your secret store. The variables stay the same in every environment, in the cluster or outside it.

## Check it

- `/system:status` lists the resources next to the components with their Argo CD health.
- `/resource:query orders-db --env dev "select count(*) from orders"` reads the database without `kubectl`.
- `/platform:doctor` warns when an operator is missing in the cluster you are pointed at.
- Tracing: call the service, open Grafana, find the trace with `service.name` and `deployment.environment` already set.

## Limits to know

Removing a resource never deletes its data. Cache data is not backed up; databases, buckets and broker volumes are, once you declare a backup ([Back up and restore data](/sdlc-foundry/scenarios/backup-and-restore/)). A new major version goes one environment at a time with `/resource:upgrade`. Every key and default is on [Resources](/sdlc-foundry/concepts/addons/) and [Secrets](/sdlc-foundry/concepts/secrets/).
