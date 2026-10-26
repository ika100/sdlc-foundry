---
title: "Addons"
description: "Backing services behind a stable connection contract: Postgres and OpenTelemetry observability."
sidebar:
  order: 4
---

An **addon** is declared once in `app.yaml` and used by name. Services see a **contract** (a Secret and environment variables), never the implementation.

| Addon | Declare | Services get | Implementation |
|---|---|---|---|
| `postgres` | `addons: {postgres: {version: 17, instances: {dev: 1, prod: 3}}}` and `uses: [postgres]` on a service | `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` from the operator's Secret | CloudNativePG `Cluster` per environment |
| `observability` | `addons: {observability: {ui: lgtm}}` (no `uses` needed) | `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` and friends | an OpenTelemetry Collector per environment that receives OTLP and scrapes each service's Prometheus path; backend is `ui: lgtm` (local Grafana, dev only) or your own `exportTo` endpoint |

A Spring Boot service generated with `--data needs_database=true` is already wired to these variables (JPA, Flyway, Testcontainers tests, `devbox run db-up` for local development).

With the observability addon, firing alerts become issues. A scheduled poll on the gitops-app repo's self-hosted runner (every 15 minutes) evaluates rules declared under the addon in `app.yaml` (plus a built-in `ServiceDown`) and files one `[auto] [alert]` issue per alert in the owning service's repository, falling back to the gitops-app. A repeat comments on the existing issue, and a resolved alert is commented on (and closed if nobody triaged it). Route these issues with `/shared:triage`.

The service-python and web-nextjs templates count every request in one metrics middleware with a `route` label (the matched path template; this was `endpoint` before 4.7.0, so update dashboards and alerts that used it). For run usage, an optional live OpenTelemetry export (metrics only) feeds a Grafana dashboard in the lgtm stack.

Operators are cluster prerequisites: `cluster-up` installs them locally; real clusters need them installed by the cluster owner. Removing an addon never deletes a database (its Argo Application is not pruned).

Because the contract is stable, an implementation can be swapped without touching any service ([ADR-020](/sdlc-foundry/reference/adr/020/), [ADR-021](/sdlc-foundry/reference/adr/021/)). Try it: [Add Postgres, secrets and observability](/sdlc-foundry/scenarios/addons-secrets-observability/).
