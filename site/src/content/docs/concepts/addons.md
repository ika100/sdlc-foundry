---
title: "Resources"
description: "Backing services behind a stable connection contract: the Postgres resource and OpenTelemetry observability."
sidebar:
  order: 5
---

A **resource** is declared once under `resources:` in `system.yaml` and used by name from a component's `uses`. Components see a **contract** (a Secret and environment variables), never the implementation. Observability is not a resource: it is switched on per environment.

| Resource or setting | Declare | Components get | Implementation |
|---|---|---|---|
| any name, `type: database` | `resources: {orders-db: {type: database, version: 17, instances: {prod: {replicas: 3}}}}` and `uses: [orders-db]` on a component (or `/resource:add orders-db`); `external: true` (with optional `remote.path`) for a database outside the cluster | `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` from the Secret `<system>-orders-db-app`; with two databases used, prefixed: `ORDERS_DB_DATABASE_URL`, `USERS_DB_PGHOST` | CloudNativePG `Cluster` (majors 15 to 18) per environment, or an ExternalSecret from the secret store |
| `observability` | `environments.<env>.observability: {ui: lgtm}` (no `uses` needed) | `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` and friends | an OpenTelemetry Collector per environment that receives OTLP and scrapes each component's Prometheus path; backend is `ui: lgtm` (local Grafana, dev only) or your own `exportTo` endpoint |

A Spring Boot component generated with `--data needs_database=true` is already wired to these variables (JPA, Flyway, Testcontainers tests, `devbox run db-up` for local development).

With observability on, firing alerts become issues. A scheduled poll on the gitops-app repo's self-hosted runner (every 15 minutes) evaluates rules declared under the environment's `observability` in `system.yaml` (plus a built-in `ServiceDown`) and files one `[auto] [alert]` issue per alert in the owning component's repository, falling back to the gitops-app. A repeat comments on the existing issue, and a resolved alert is commented on (and closed if nobody triaged it). Route these issues with `/issue:triage`.

The service-python and web-nextjs templates count every request in one metrics middleware with a `route` label (the matched path template; this was `endpoint` before 4.7.0, so update dashboards and alerts that used it). For run usage, an optional live OpenTelemetry export (metrics only) feeds a Grafana dashboard in the lgtm stack.

Operators are cluster prerequisites: `cluster-up` installs them locally; the platform installs them on real clusters from the `operators/` folder of the gitops repo (apply `operators/root.yaml` once), unless an environment sets `operators: owner`. Removing a resource never deletes a database (its Argo Application is not pruned).

Because the contract is stable, an implementation can be swapped without touching any service ([ADR-020](/sdlc-foundry/reference/adr/020/), [ADR-021](/sdlc-foundry/reference/adr/021/)). Try it: [Add Postgres, secrets and observability](/sdlc-foundry/scenarios/addons-secrets-observability/).
