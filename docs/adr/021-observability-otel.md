# ADR-021: Observability: an OpenTelemetry base, a UI stack as an option

**Status:** Accepted
**Date:** 2026-10-07
**Builds on:** ADR-020 (addons)
**Superseded in part by:** ADR-098

## Context

Generated services already expose Prometheus metrics (and, per shape, some OpenTelemetry tracing), but nothing collected them and each shape configured telemetry differently (Python used a private `OTLP_ENDPOINT`, Java shipped the OTel agent disabled, Go only had `/metrics`). We want one vendor-neutral path, and no obligation to run a particular UI.

## Decision

1. **OpenTelemetry is the base.** Declaring `addons.observability` in `app.yaml` renders, for each environment, an **OpenTelemetry Collector** (contrib image pinned, non-root numeric user, read-only filesystem, plain manifests, no operator or CRDs) in the application namespace, and injects the standard variables into **every service**: `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318`, `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` (`service.namespace`, `deployment.environment`) and `OTEL_SDK_DISABLED=false`. A value in a service's own `env` still wins.
2. **The collector receives OTLP and scrapes Prometheus.** Pipelines for traces, metrics and logs: OTLP in; a Prometheus scrape job per service that declares `metrics:` (the path comes from `shapes.yml` `runtime.metrics`, copied into the explicit `services.yaml` entry like port and probes); `memory_limiter`, `resource` (adds environment and application) and `batch` processors; `debug` plus an optional OTLP/HTTP exporter.
3. **The backend is a choice, not a dependency.** `exportTo: <OTLP/HTTP endpoint>` sends everything to your own backend (Grafana Cloud, Tempo/Mimir/Loki, Honeycomb, SigNoz, ...), with `headersSecret` (a Secret whose key `AUTHORIZATION` becomes the `Authorization` header; never in git). With neither option the collector only logs, which still proves the wiring.
4. **UI stack option: `ui: lgtm`.** `cluster-up` installs Grafana's all-in-one `otel-lgtm` image (Grafana, Tempo, Loki, Prometheus-compatible store) as a shared dev stack in its own `observability` namespace, reachable at `http://grafana.localhost:<port>/`, and the collectors export to it. It runs as root with non-persistent storage, so it is **for local and demo use only** and lives outside the application namespaces (and their policies). Other `ui:` values can be added later without changing the base.
5. **Config addon, so it is pruned.** Unlike databases, the observability Application has `prune: true` (a separate ApplicationSet per prune policy), so removing the addon removes the collector.
6. **Template alignment.** The Python template now configures tracing from the standard variables (HTTP/protobuf by default, `grpc` honoured; `OTLP_ENDPOINT` kept as a fallback). Java (agent) and web (`instrumentation.ts`) already used them.

## Not included

Alerting and dashboards-as-code (no Prometheus Operator CRDs on purpose), stdout log collection (superseded by [ADR-098](098-pod-logs-are-read-through-the-kubernetes-api-next-to-the-collector.md): the collector's pod reads pod logs through the Kubernetes API, namespaced, with no node access), OpenTelemetry in Go services (metrics are scraped; the Go SDK is a follow-up), tail sampling and HA/multi-tenant backends.
