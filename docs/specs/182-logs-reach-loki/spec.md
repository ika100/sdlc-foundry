---
spec_id: 182-logs-reach-loki
title: Logs reach Loki
status: done
priority: P1
shape: platform
tracks: [657]
---

# 182 — Logs reach Loki

## Problem

With a system's observability setting on, Grafana's Loki data source stays empty: in journey 10 (issue 657, dev and staging) Loki reported no labels for 24 hours while traces and metrics arrived. The environment's collector only accepts logs that a service pushes over OpenTelemetry; the generated components write their logs as JSON to standard output and push none, and nothing reads the pods' output (ADR-021 left stdout collection out because it needed node access). The docs and the site promise logs in the Grafana dev stack, so an operator who follows a failing request from its trace finds no log line, and no check notices the gap.

## Stories

As an operator of a system with observability on, I want the standard output of every pod of the system in an environment to be searchable in the log backend by namespace, component and pod, so that I can read what a component did without `kubectl logs`.

As an operator following a slow or failing request, I want to jump from a log line that carries a trace id to its trace and back, so that logs and traces of one request are read together.

As a developer of a generated component, I want my JSON log lines to carry the trace and span id of the request being handled, so that every log line can be opened next to its trace without extra code.

As a platform maintainer, I want the cluster test to prove that a component's log line arrives, so that the gap cannot come back unnoticed.

**Repos:** the gitops-app template (rendered observability addon), the component templates (`service-python`, `service-java`, `service-go`, `web-nextjs`) and the platform's cluster test.

## Acceptance criteria

- **AC-182.1** Given a system with observability on in an environment and a log backend configured (`ui: lgtm` or `exportTo`), when a component's pod writes a line to standard output, then within 60 seconds that line is in the log backend with the labels `k8s_namespace_name` (the environment's namespace), `service_name` (the component's name), `k8s_pod_name` and `deployment_environment`; a JSON line's `level` becomes the entry's severity and a line that is not JSON arrives unchanged as plain text.
- **AC-182.2** Given the same environment, when a component logs a JSON line that carries a 32-character hex `trace_id` (and optionally `span_id`) while handling a traced request, then the log entry in the backend carries that trace id so that Grafana links the entry to the trace in Tempo, and the trace in Tempo shows that entry under "logs for this span".
- **AC-182.3** Given the rendered environment with observability on and the guard-rail policy in `Enforce`, when it is synced, then every workload is admitted unchanged by the existing policy: the logs are read through the Kubernetes API by the environment's existing collector, which runs as a non-root numeric user with a read-only root filesystem, no privilege, no host namespace and no host path, and whose permission is limited to reading the pods and pod logs of its own environment's namespace (a read of another namespace's pod logs is refused); no node-level collector is added.
- **AC-182.4** Given an environment with observability off, when the system is rendered, then its output is identical to the output before this change (no log collection, no new permissions); and given observability on, the collector's own output is not collected, so its log lines do not feed back into the backend.
- **AC-182.5** Given the platform's cluster test with observability on, when it calls a component, then it finds that component's log line in the log backend by `service_name` and `k8s_namespace_name` within 120 seconds, and the test fails with a message naming the missing label or line when stdout collection is absent or broken.
- **AC-182.6** Given a newly generated `service-python`, `service-java`, `service-go` or `web-nextjs` repo with observability on, when it handles a request inside an active span, then every JSON log line written for that request carries `trace_id` (32 hex characters) and `span_id` (16 hex characters) equal to the active span's ids, and a line written outside any span carries neither field; the platform's test suite checks this for each of the four templates and fails when a field is missing or differs from the span.

## Non-goals

- Making the component templates push logs over OpenTelemetry; logs travel only through standard output.
- Adding a tracing library to `service-go` (still a follow-up per ADR-021); see A7.
- Rewriting existing generated repos' own code; they get the trace ids with the next template update.
- Collecting logs of the platform's own namespaces (Argo CD, Kyverno, operators, the shared observability stack) or of the node itself.
- Log retention, persistent log storage, dashboards, log-based alerts and sampling.
- Changing the guard-rail policies or the shared Grafana stack's security posture.

## Assumptions

- **A1** All pods of the system's namespace in that environment are collected, not only components (databases, caches and brokers too), labelled by their workload name; only the collector's own output is skipped (other option: components only; affects AC-182.1, AC-182.4).
- **A2** Collected logs go wherever traces and metrics already go: the shared stack with `ui: lgtm`, the configured backend with `exportTo`, only the collector's debug output with neither (other option: logs only to the shared stack; affects AC-182.1).
- **A3** Label names follow the backend's OpenTelemetry conventions (`service_name`, `k8s_namespace_name`, `k8s_pod_name`, `deployment_environment`), so they match the labels traces and metrics already use (other option: short names `namespace`, `component`, `pod`; affects AC-182.1, AC-182.5).
- **A4** The trace id is recognised in a JSON field named `trace_id` (span in `span_id`), the field names the OpenTelemetry log data model uses (other option: also `traceId` and `trace.id`; affects AC-182.2, AC-182.6).
- **A5** Arrival limits: 60 seconds for an operator, 120 seconds in the cluster test to absorb a cold start (other option: 30 / 60 seconds; affects AC-182.1, AC-182.5).
- **A6** ADR-021's "Not included" entry for stdout collection is superseded by a new decision record that states the access chosen in AC-182.3.
- **A7** `service-go` has no tracing library, so its "active span" is the request's incoming W3C trace context (`traceparent` header): it logs that trace id and the caller's span id, and a request without one logs neither field (other option: add a Go tracing library in this spec; affects AC-182.6).

## Open questions

- ~~Reading pods' standard output needs new access. Which access may log collection have?~~ Answered 2026-11-10: the existing collector in each environment's namespace reads its pods' logs through the Kubernetes API with a permission limited to that namespace; no host path, no root, no node-level collector. See AC-182.3.

## Changelog

- 2026-11-10 created
- 2026-11-10 amended: folded in the user's answers (access through the Kubernetes API limited to the namespace, AC-182.3; the component templates log `trace_id`/`span_id`, new AC-182.6).
- 2026-11-10 approved
- 2026-11-10 building
- 2026-11-11 done
