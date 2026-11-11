# Design — 182 Logs reach Loki

## Decisions

- **A stdlib log tailer in the collector's pod reads `pods/log` through the API** (AC-182.3): the contrib collector has no API-based
  pod-log receiver, and every file-based one needs hostPath. The tailer is `render.LOG_TAILER_SCRIPT` (Python standard library,
  embedded in the renderer like `CREDENTIALS_SCRIPT`, spec 128) running on the already pinned `CREDENTIALS_IMAGE`: no new image, no
  new tool, and its whole mapping is testable in the platform suite against a fake API server. ADR:
  [docs/adr/098-pod-logs-are-read-through-the-kubernetes-api-next-to-the-collector.md](../../adr/098-pod-logs-are-read-through-the-kubernetes-api-next-to-the-collector.md).
- **The tailer posts OTLP/JSON to the collector in its own pod** (`127.0.0.1:4318`): the collector's existing `logs` pipeline
  (`memory_limiter`, `resource`, `batch`, `debug` + backend) already sends logs wherever traces and metrics go (A2), so
  `collector_config()` does not change.
- **The tailer does the mapping, not OTTL** in the collector: labels, severity and trace context are set in the OTLP record the tailer
  builds, so one unit-tested function owns AC-182.1 and AC-182.2, and the collector config stays as it is.
- **Polling, not watching**: the tailer lists its namespace's pods every 5 s and reconciles one follow-stream per running container.
  One namespace is small; polling has no resourceVersion bookkeeping and stays far inside the 60 s limit (A5).
- **The cluster test switches dev to `ui: lgtm`** so it has a real log backend (AC-182.5) and queries Loki and Tempo through
  `kubectl port-forward` to the `lgtm` pod (ports 3100, 3200); the shared stack's Service is not changed.
- **Java logs JSON** with Spring Boot's built-in structured logging (`logging.structured.format.console: logstash`, Boot 3.5): the
  OpenTelemetry Java agent already puts `trace_id`/`span_id` into the MDC and the logstash format writes MDC keys as top-level
  fields. `InfoController` logs one line per request so the cluster test has a request-scoped line with a known trace id.
- **Python instruments FastAPI** (`FastAPIInstrumentor.instrument_app`, already a dependency, never called) so a request has an
  active span; a structlog processor adds the ids.
- **Go reads `traceparent`** (A7) in a middleware into the request context; a `slog.Handler` wrapper adds the ids to every record
  logged with that context; the request logger logs with `InfoContext`.
- **Next.js gets `lib/logger.ts`**, a tiny JSON logger that reads `trace.getActiveSpan()` from `@opentelemetry/api`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` `LOG_TAILER_SCRIPT` | the tailer program (`tail.py`) | new |
| `render.py` `observability_files()` | adds the tailer container, its ConfigMap, ServiceAccount, Role, RoleBinding | changed |
| `render.py` `allowed_registries()` | adds the pinned tailer image ref when the env has observability | changed |
| `templates/cluster-gitops/scripts/system_render.py` | byte copy of render.py (`scripts/sync-template-copies.py`) | synced |
| `templates/service-python/src/<module>/logging_config.py`, `main.py` | trace-id processor; FastAPI instrumentation | changed |
| `templates/service-go/internal/server/tracelog.go` | `traceparent` middleware + `slog.Handler` wrapper | new |
| `templates/service-java/src/main/resources/application.yml.jinja`, `InfoController.java.jinja` | logstash JSON; one log line per `/api/info` | changed |
| `templates/web-nextjs/lib/logger.ts` | JSON logger with span ids | new |
| `tests/e2e/run.sh` | `ui: lgtm` in dev; log, trace and permission checks | changed |

## Contract

### Rendered files (`applications/<system>/addons/<env>/observability/`, only when the env has `observability`)

Existing: `configmap.yaml`, `collector.yaml`, `service.yaml`, `kustomization.yaml`. New:

| File | Object |
|---|---|
| `serviceaccount.yaml` | `v1/ServiceAccount` `otel-collector`, `automountServiceAccountToken: false` |
| `role.yaml` | `rbac.authorization.k8s.io/v1/Role` `otel-collector-logs`, rules exactly `[{apiGroups: [""], resources: ["pods"], verbs: ["get","list","watch"]}, {apiGroups: [""], resources: ["pods/log"], verbs: ["get"]}]` |
| `rolebinding.yaml` | `RoleBinding` `otel-collector-logs` → Role `otel-collector-logs`, subject ServiceAccount `otel-collector` in `<system>-<env>` |
| `tailer-configmap.yaml` | `v1/ConfigMap` `otel-collector-tailer`, data `tail.py` = `LOG_TAILER_SCRIPT` (a `Literal`, byte-equal) |

All carry the collector's labels (`app.kubernetes.io/name: otel-collector`, `part-of`, `managed-by`). `kustomization.yaml` lists all
eight files, sorted. No ClusterRole, ClusterRoleBinding, DaemonSet or hostPath anywhere.

`collector.yaml` pod spec changes:

- `serviceAccountName: otel-collector`, `automountServiceAccountToken: false`; annotation `checksum/tailer` (sha256[:16] of the
  script) next to `checksum/config`.
- container `collector`: unchanged.
- container `log-tailer`: image `CREDENTIALS_IMAGE`, command `["python3", "/tailer/tail.py"]`; env `PYTHONDONTWRITEBYTECODE=1`,
  `TAILER_NAMESPACE` (downward API `metadata.namespace`), `TAILER_POD` (downward API `metadata.name`), `TAILER_ENVIRONMENT=<env>`,
  `TAILER_SYSTEM=<system>`, `TAILER_OTLP_URL=http://127.0.0.1:4318/v1/logs`; resources requests `cpu: 20m, memory: 32Mi`, limits
  `memory: 128Mi`; securityContext `runAsNonRoot: true, runAsUser: 65534, allowPrivilegeEscalation: false,
  readOnlyRootFilesystem: true, capabilities.drop: [ALL]`; mounts `tailer` (ConfigMap, `/tailer`, readOnly) and `sa-token`
  (`/var/run/secrets/kubernetes.io/serviceaccount`, readOnly).
- volume `sa-token`: projected `serviceAccountToken` (path `token`, `expirationSeconds: 3600`), ConfigMap `kube-root-ca.crt` (key
  `ca.crt`), downwardAPI `namespace`. Only `log-tailer` mounts it.

Guard-rail policy (`policies/<env>/`): rules unchanged; `variables.registries` gains `CREDENTIALS_IMAGE.split("@")[0]`
(`python:3.13.18-alpine3.24`, the exact pinned tag) for an env with observability. An env without observability renders
byte-identical to today (AC-182.4).

### `tail.py` behaviour

Inputs: env above; test overrides `TAILER_API_URL` (else `https://$KUBERNETES_SERVICE_HOST:$KUBERNETES_SERVICE_PORT`),
`TAILER_SA_DIR` (else `/var/run/secrets/kubernetes.io/serviceaccount`; `token` re-read on every request, `ca.crt` for https),
`TAILER_POLL_SECONDS` (default 5), `TAILER_FLUSH_SECONDS` (default 1).

1. Every poll: `GET /api/v1/namespaces/<ns>/pods`. Skip pods labelled `app.kubernetes.io/name=otel-collector` and the pod named
   `TAILER_POD` (AC-182.4). For each container (not init containers) in state `running`, keep exactly one follower keyed by
   `(pod uid, container, restartCount)`; drop followers of keys that vanished.
2. A follower streams `GET .../pods/<pod>/log?container=<c>&follow=true&timestamps=true` plus `sinceTime=<RFC3339>`:
   for a container started after the tailer: its start time; for one already running when the tailer started:
   `max(startedAt, tailer start − 60 s)`; after a reconnect: the last line's timestamp, and lines with a timestamp ≤ the last one sent
   are dropped. Stream end or error: retry after 2 s while the key is still wanted.
3. Each line `<RFC3339Nano> <text>` becomes one OTLP log record (below). Records queue in a bounded queue (10 000; when full the
   oldest is dropped and a count is printed to the tailer's stderr).
4. A sender posts every `TAILER_FLUSH_SECONDS` or at 500 records: `POST TAILER_OTLP_URL`, `Content-Type: application/json`, one
   `resourceLogs` entry per `(pod, container)`. Non-2xx or connection error: retry with backoff 1, 2, 4 s, then drop the batch
   with a stderr line. API 401/403 on list: printed, retried next poll (never exits).
5. It prints only its own status lines to stdout/stderr, never log content (its pod is skipped anyway).

Record mapping (AC-182.1, AC-182.2):

```
resource.attributes:
  service.name        = workload(pod)            # see below
  k8s.namespace.name  = <ns>
  k8s.pod.name        = <pod name>
  k8s.container.name  = <container>
  deployment.environment = TAILER_ENVIRONMENT    # the collector's resource processor upserts it too
  service.namespace   = TAILER_SYSTEM
logRecord:
  timeUnixNano, observedTimeUnixNano  = the kubelet timestamp, now
  body.stringValue    = <text> unchanged (JSON or not)
  if <text> parses as a JSON object:
    level (str, case-insensitive) -> severityText = level.upper();
      severityNumber: trace 1, debug 5, info 9, warn|warning 13, error 17, fatal|critical|panic 21, other 0
    trace_id matching ^[0-9a-fA-F]{32}$ and not all zeros -> traceId = lower(trace_id)
    span_id  matching ^[0-9a-fA-F]{16}$ and not all zeros, and traceId set -> spanId = lower(span_id)
  else: no severity, no traceId/spanId
```

`workload(pod)`: the controller ownerReference's name; for kind `ReplicaSet` with the pod label `pod-template-hash` = `h`, the name
with the suffix `-h` removed (the Deployment name, i.e. the component's name for components); no controller owner: label
`app.kubernetes.io/name`, else the pod name (A1).

The collector's Loki export turns the resource attributes into the labels `service_name`, `k8s_namespace_name`, `k8s_pod_name`,
`deployment_environment` (Loki OTLP conventions, A3); `traceId` becomes the entry's `trace_id`, which Grafana's Tempo and Loki data
sources use to link both ways.

### Component log lines (AC-182.6)

With observability on, inside an active span every JSON log line carries `"trace_id": "<32 lowercase hex>"` and
`"span_id": "<16 lowercase hex>"` equal to the active span's ids; outside a span (or with an invalid span context) neither key is
present. Each template keeps its `level` field.

| Template | Where the ids come from | Mechanism |
|---|---|---|
| service-python | `opentelemetry.trace.get_current_span().get_span_context()` (`is_valid`) | structlog processor `add_trace_ids` before `JSONRenderer`; `main.py` calls `FastAPIInstrumentor.instrument_app(app)` when `tracing_enabled()` |
| service-java | OTel Java agent MDC keys `trace_id`, `span_id` | `logging.structured.format.console: logstash`; `InfoController.info()` logs `"info requested"` at INFO |
| service-go | request header `traceparent` (`00-<32 hex>-<16 hex>-<2 hex>`, version `00`, not all-zero ids); invalid or absent → none | `server.TraceContext` middleware stores it in the context; `server.NewTraceHandler(h slog.Handler) slog.Handler` adds `trace_id`/`span_id` from `ctx`; `requestLogger` uses `InfoContext(req.Context(), ...)`; `main.go` wraps the JSON handler |
| web-nextjs | `trace.getActiveSpan()?.spanContext()` with `isSpanContextValid` | `lib/logger.ts`: `export const logger = { debug, info, warn, error }(msg: string, fields?: Record<string, unknown>)`, one `JSON.stringify({time, level, msg, ...fields, trace_id?, span_id?})` line on stdout (stderr for `error`) |

Go signatures (A7: the "active span" is the caller's context; `span_id` is the caller's span id):

```go
func TraceContext(next http.Handler) http.Handler
func NewTraceHandler(h slog.Handler) slog.Handler
func TraceIDs(ctx context.Context) (traceID, spanID string, ok bool)
```

### Cluster test (AC-182.5, plus AC-182.1–.3 in the cluster)

dev gets `observability: {ui: lgtm}` (cluster-up then installs the stack). After the components run:

- call `e2e-api /api/info` through the Gateway with `traceparent: 00-<fresh 32 hex>-<16 hex>-01`;
- within 120 s Loki (`query_range`, `{service_name="e2e-api", k8s_namespace_name="e2e-dev"}`) returns a line containing
  `info requested`; else fail naming the missing piece (`no stream for service_name=e2e-api`, `no line ... within 120 s`);
- `... | k8s_pod_name="<e2e-api pod>" | deployment_environment="dev"` (label or structured metadata) returns it, and
  `... | trace_id="<the id>"` returns it (AC-182.2); Tempo `/api/traces/<id>` returns the trace;
- the collector's own lines never appear: `{service_name="otel-collector"}` is empty;
- `kubectl auth can-i get pods/log --as=system:serviceaccount:e2e-dev:otel-collector` is `yes` in `e2e-dev` and `no` in `e2e-staging`
  and `kube-system`; no DaemonSet carries `app.kubernetes.io/part-of=e2e`.

## Data

None persisted. The tailer keeps its followers and last timestamps in memory only.

## Decisions taken during the ship (2026-11-11, by the user's delegate)

- AC-182.3's test checks that no workload mounts a host path (volumes of every pod spec), not that the text `hostPath`
  is absent from every rendered file: the unchanged guard-rail policy names `hostPath` in its message and CEL rule.
- Older tests that list the rendered observability files or registries of an environment (for example
  `tests/cplat/test_addons.py`, `tests/cplat/test_system_render_114.py`, `tests/cplat/test_policies.py`) may be updated to
  the new file set (the ServiceAccount, Role and RoleBinding of the namespaced log access); no other assertion changes.
