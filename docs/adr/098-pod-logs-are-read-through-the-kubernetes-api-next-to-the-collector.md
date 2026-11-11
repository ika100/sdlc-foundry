# ADR-098: Pod logs are read through the Kubernetes API, next to the environment's collector

**Status:** Accepted (2026-11-10, spec 182)
**Supersedes in part:** [ADR-021](021-observability-otel.md) ("Not included": stdout log collection)
**Builds on:** [ADR-022](022-kyverno-policies.md) (guard rails), [ADR-072](072-a-generated-credential-is-written-once-by-a-create-only-job.md) (a stdlib program embedded in the renderer)

## Context

ADR-021 left standard-output log collection out because the usual collectors (filelog receiver, Promtail, Fluent Bit, Vector,
Alloy's file sources) read `/var/log/pods` on the node: a DaemonSet with a hostPath volume, often as root. The guard rails forbid
both, and the components push no logs over OTLP, so Loki stayed empty (issue 657). The OpenTelemetry Collector contrib image has no
receiver that reads pod logs through the API server's `pods/log` endpoint; the one tool that does (Grafana Alloy's
`loki.source.kubernetes`) is a second agent with its own configuration language, image pin and stability gate.

## Decision

1. **Logs are read through the Kubernetes API, per environment namespace.** The environment's `otel-collector` pod gets a second
   container, `log-tailer`: a Python standard-library program embedded in the renderer (`render.LOG_TAILER_SCRIPT`, shipped in a
   ConfigMap like the credentials Job's `create.py`) on the already pinned `CREDENTIALS_IMAGE`. It lists the pods of its own
   namespace, follows each container's `pods/log` stream and posts the lines as OTLP/JSON to the collector in the same pod
   (`http://127.0.0.1:4318/v1/logs`). The collector's existing `logs` pipeline adds the environment and exports wherever traces and
   metrics go.
2. **Least privilege.** A ServiceAccount `otel-collector` with a namespaced Role (`pods`: get, list, watch; `pods/log`: get) and
   RoleBinding in the environment's namespace only. The pod does not automount the token; only `log-tailer` mounts a projected
   token. Both containers run as a numeric non-root user, read-only root filesystem, no privilege, no host namespace, no hostPath.
   No DaemonSet, no ClusterRole.
3. **The tailer owns the mapping.** Resource attributes `service.name` (the workload name), `k8s.namespace.name`, `k8s.pod.name`,
   `k8s.container.name`; a JSON line's `level` becomes the severity and its `trace_id`/`span_id` the record's trace context; any
   other line is the body unchanged. Its own pod is skipped, so its output never feeds back.
4. **Components put the active span's ids into their JSON log lines** as `trace_id` (32 hex) and `span_id` (16 hex), the field names
   of the OpenTelemetry log data model, in all four component templates. `service-go` takes them from the incoming `traceparent`
   until it has a tracing library.
5. **The guard rails' rules do not change.** The registry list of an environment with observability gains exactly the pinned
   tailer image reference, as it already carries the collector's.

## Consequences

- Every pod of an environment's namespace with observability on reaches the log backend; logs of platform namespaces and nodes
  stay out (they need node access, which this decision keeps refusing).
- The platform maintains a small log tailer, tested in the platform suite against a fake API server and a fake OTLP receiver.
  It suits dev and demo volumes (one namespace, polling every 5 seconds); a busy production namespace may want a node-level
  agent, which needs a new decision because it needs node access.
- A collector restart can resend up to 60 seconds of lines of containers that were already running; lines written while the
  collector is down for longer are lost (no position store, no persistent volume).
- Environments with observability off render exactly as before.
