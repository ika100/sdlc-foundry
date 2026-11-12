---
spec_id: 182-logs-reach-loki
shape: platform
spec_hash: e9c250c21d01
summary: A stdlib log tailer next to each environment's collector reads pod logs through the Kubernetes API; the four component templates log trace and span ids; the cluster test proves logs arrive in Loki
tasks:
  - id: t1
    title: render.py LOG_TAILER_SCRIPT, the log tailer program (tail.py)
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-182.1, AC-182.2, AC-182.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: observability_files renders the tailer container, its ConfigMap and the namespaced RBAC; registries gain the tailer image
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-182.1, AC-182.3, AC-182.4]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: service-python logs trace_id and span_id of the active span (FastAPI instrumented)
    files: ["templates/service-python/src/{{ module_name }}/logging_config.py", "templates/service-python/src/{{ module_name }}/main.py", templates/service-python/tests/test_log_trace.py, templates/service-python/copier.yml]
    covers: [AC-182.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: service-go reads traceparent and logs its trace and span id
    files: [templates/service-go/internal/server/tracelog.go, templates/service-go/internal/server/tracelog_test.go, templates/service-go/internal/server/server.go.jinja, "templates/service-go/cmd/{{ project_name }}/main.go.jinja", templates/service-go/copier.yml]
    covers: [AC-182.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: service-java logs JSON (logstash) with the agent's trace ids; /api/info logs one line
    files: [templates/service-java/src/main/resources/application.yml.jinja, "templates/service-java/src/main/java/{{ package_path }}/InfoController.java.jinja", "templates/service-java/src/test/java/{{ package_path }}/LogFormatTest.java.jinja", templates/service-java/copier.yml, templates/service-java/CLAUDE.md.jinja]
    covers: [AC-182.6, AC-182.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: web-nextjs lib/logger.ts, a JSON logger with the active span's ids
    files: [templates/web-nextjs/lib/logger.ts, templates/web-nextjs/tests/logger.test.ts, templates/web-nextjs/copier.yml, templates/web-nextjs/CLAUDE.md.jinja]
    covers: [AC-182.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: Cluster test turns on ui lgtm in dev and finds a component's log line, its trace and the tailer's limits
    files: [tests/e2e/run.sh]
    covers: [AC-182.5, AC-182.1, AC-182.2, AC-182.3]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: t8
    title: Docs - how it works, ADR-021 superseded in part, ADR index, gitops CLAUDE.md, changelog fragment
    files: [docs/HOW-IT-WORKS.md, docs/adr/021-observability-otel.md, docs/adr/README.md, templates/gitops-app/CLAUDE.md.jinja, docs/changelog.d/182-logs-reach-loki.added.md]
    covers: [AC-182.3]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 182 Logs reach Loki

Design: [design.md](design.md). ADR: [ADR-098](../../adr/098-pod-logs-are-read-through-the-kubernetes-api-next-to-the-collector.md).
Every render.py change is copied to `templates/cluster-gitops/scripts/system_render.py` with `uv run scripts/sync-template-copies.py`
(never edited by hand); `tests/cplat/test_sync_template_copies.py::test_real_repo_is_in_sync` fails otherwise.

## t1 — render.py LOG_TAILER_SCRIPT, the log tailer program (tail.py)

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-182.1, AC-182.2, AC-182.4
**Goal:** the program that follows every container of its namespace through `pods/log` and posts each line as an OTLP/JSON log
record to the collector in its own pod, exactly as design.md "tail.py behaviour" and "Record mapping" say.

**Implementation notes:**
- A plain module-level string `LOG_TAILER_SCRIPT = r'''...'''` next to `CREDENTIALS_SCRIPT` (no f-string; the rendered `tail.py`
  equals it). Standard library only (`json`, `os`, `re`, `ssl`, `sys`, `threading`, `time`, `queue`, `urllib.request`, `http.client`,
  `datetime`).
- API access as in `CREDENTIALS_SCRIPT`: `TAILER_API_URL` override, `TAILER_SA_DIR`; re-read the token on every request (projected
  tokens rotate); `ca.crt` only for https.
- Poll loop (`TAILER_POLL_SECONDS`, default 5): list pods, skip the collector's pod (label `app.kubernetes.io/name=otel-collector`,
  and `TAILER_POD`), reconcile followers keyed by `(uid, container, restartCount)` for running containers.
- Follower thread: `follow=true&timestamps=true&sinceTime=...` per the design's start-position rule; reconnect after 2 s; drop lines
  at or before the last sent timestamp.
- Keep the mapping a pure function in the script (`to_record(line, ts)` and `workload(pod)`), so tests can exec the script's
  functions as well as run it end to end.
- Sender thread: bounded queue 10 000 (drop oldest, count on stderr), flush every `TAILER_FLUSH_SECONDS` or 500 records, one
  `resourceLogs` per `(pod, container)`, retry 1/2/4 s then drop with a stderr line.
- Never print log content; status lines only. Never exit on API or OTLP errors.

**Done when:** the platform tests for the tailer (fake API server serving pods and log streams, fake OTLP receiver) pass:
labels, severity mapping, JSON vs plain body, trace/span ids and their rejection rules, the collector's own pod skipped,
reconnect without duplicates.

## t2 — observability_files renders the tailer container, its ConfigMap and the namespaced RBAC; registries gain the tailer image

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-182.1, AC-182.3, AC-182.4
**Goal:** an environment with observability renders the four new files and the changed pod spec of design.md "Rendered files";
an environment without it renders byte-identical output to before.

**Implementation notes:**
- `observability_files()`: add `serviceaccount.yaml`, `role.yaml`, `rolebinding.yaml`, `tailer-configmap.yaml` (data `tail.py` as
  `Literal(LOG_TAILER_SCRIPT)`); kustomization lists all eight, sorted.
- Pod spec: `serviceAccountName`, `automountServiceAccountToken: false`, `checksum/tailer`, the `log-tailer` container (image
  `CREDENTIALS_IMAGE`, env incl. downward API, resources, securityContext), the projected `sa-token` volume mounted only by it.
- Role rules exactly the two in the design; no ClusterRole, no DaemonSet, no hostPath.
- `allowed_registries()`: when `env in cfg["observability"]`, add `CREDENTIALS_IMAGE.split("@")[0]`. No other policy change.
- Comment at `CREDENTIALS_IMAGE`: it also runs the log tailer (spec 182). The versions-table row stays `credentials-job`.
- Run the existing render, policy and addon tests (`test_addons.py`, `test_policies.py`, `test_system_render_114.py`); the
  rendered manifests must pass `devbox run validate`'s Kyverno check.

**Done when:** the render tests for AC-182.3 and AC-182.4 pass (RBAC exact, security contexts, policy admits the Deployment, no
change with observability off, the script in the ConfigMap byte-equal to `LOG_TAILER_SCRIPT`), and the sync check is green.

## t3 — service-python logs trace_id and span_id of the active span (FastAPI instrumented)

**Files:** templates/service-python/src/{{ module_name }}/logging_config.py, templates/service-python/src/{{ module_name }}/main.py, templates/service-python/tests/test_log_trace.py, templates/service-python/copier.yml
**Covers:** AC-182.6
**Goal:** with observability on, every structlog line inside an active span carries the span's `trace_id`/`span_id`; outside a
span neither.

**Implementation notes:**
- `logging_config.py`: processor `add_trace_ids(logger, method, event_dict)` using `trace.get_current_span().get_span_context()`;
  when `is_valid`, `trace_id = format(ctx.trace_id, "032x")`, `span_id = format(ctx.span_id, "016x")`; placed before `JSONRenderer`.
- `main.py`: `FastAPIInstrumentor.instrument_app(app)` after `app` is created, only when `tracing_enabled()`.
- `tests/test_log_trace.py`: the template's own test (in a span with an in-memory provider: both ids equal the span's; outside:
  absent); excluded by `copier.yml` when `needs_observability` is false, like `tests/test_metrics.py`.

**Done when:** the platform test for AC-182.6 (service-python) passes and the rendered repo's `devbox run quality` and tests pass.

## t4 — service-go reads traceparent and logs its trace and span id

**Files:** templates/service-go/internal/server/tracelog.go, templates/service-go/internal/server/tracelog_test.go, templates/service-go/internal/server/server.go.jinja, templates/service-go/cmd/{{ project_name }}/main.go.jinja, templates/service-go/copier.yml
**Covers:** AC-182.6
**Goal:** A7: a request with a valid `traceparent` logs its trace id and the caller's span id on every line logged with the
request context; a request without one logs neither.

**Implementation notes:**
- `tracelog.go`: `TraceContext` middleware (parse `00-<32hex>-<16hex>-<2hex>`, reject all-zero ids and other versions),
  `TraceIDs(ctx)`, `NewTraceHandler(h)` wrapping `Handle` to add `slog.String("trace_id", ..)`, `slog.String("span_id", ..)`;
  `WithAttrs`/`WithGroup` return wrapped handlers.
- `server.go.jinja`: `r.Use(TraceContext)` before `requestLogger` (observability only); `requestLogger` calls
  `logger.InfoContext(req.Context(), "request", ...)`.
- `main.go.jinja`: with observability, `slog.New(server.NewTraceHandler(slog.NewJSONHandler(...)))`.
- `tracelog_test.go`: the template's own test (valid header → both ids; none/invalid → neither). Both new files excluded by
  `copier.yml` without observability, like `internal/server/metrics.go`. No new module dependency.

**Done when:** the platform test for AC-182.6 (service-go) passes and the rendered repo's `go test ./...` and lint pass.

## t5 — service-java logs JSON (logstash) with the agent's trace ids; /api/info logs one line

**Files:** templates/service-java/src/main/resources/application.yml.jinja, templates/service-java/src/main/java/{{ package_path }}/InfoController.java.jinja, templates/service-java/src/test/java/{{ package_path }}/LogFormatTest.java.jinja, templates/service-java/copier.yml, templates/service-java/CLAUDE.md.jinja
**Covers:** AC-182.6, AC-182.2
**Goal:** with observability on, the service writes JSON lines whose top-level `trace_id`/`span_id` come from the Java agent's MDC,
and `/api/info` writes one request-scoped line the cluster test can find.

**Implementation notes:**
- `application.yml.jinja`: under `needs_observability`, `logging.structured.format.console: logstash`.
- `InfoController`: an SLF4J logger; `info()` logs `"info requested"` at INFO.
- `LogFormatTest` (observability only, excluded otherwise in `copier.yml`): with `OutputCaptureExtension`, an MDC `trace_id`/`span_id`
  appears as top-level JSON keys with `level`; without MDC neither key appears.
- `CLAUDE.md.jinja`: the Logging convention says JSON on stdout with `trace_id`/`span_id`.

**Done when:** the platform test for AC-182.6 (service-java) passes and the rendered repo's `mvn verify` passes; the cluster test
(t7) proves the agent's ids end to end.

## t6 — web-nextjs lib/logger.ts, a JSON logger with the active span's ids

**Files:** templates/web-nextjs/lib/logger.ts, templates/web-nextjs/tests/logger.test.ts, templates/web-nextjs/copier.yml, templates/web-nextjs/CLAUDE.md.jinja
**Covers:** AC-182.6
**Goal:** a logger route handlers and server code use; inside an active span each line carries its ids.

**Implementation notes:**
- `lib/logger.ts` as the design's contract: `isSpanContextValid(trace.getActiveSpan()?.spanContext())` decides; `error` to stderr,
  the rest to stdout; one JSON object per line.
- `tests/logger.test.ts`: the template's own vitest (a span via `@opentelemetry/api` with a test tracer/context manager: ids equal;
  outside: absent).
- `copier.yml`: exclude `lib/logger.ts` and `tests/logger.test.ts` without observability (the API package is absent then).
- `CLAUDE.md.jinja`: log through `@/lib/logger`.

**Done when:** the platform test for AC-182.6 (web-nextjs) passes and the rendered repo's `pnpm test:fast`, lint and typecheck pass.

## t7 — Cluster test turns on ui lgtm in dev and finds a component's log line, its trace and the tailer's limits

**Files:** tests/e2e/run.sh
**Covers:** AC-182.5, AC-182.1, AC-182.2, AC-182.3
**Goal:** the steps of design.md "Cluster test", failing with a message that names the missing label or line.

**Implementation notes:**
- Environments step: `envs["dev"]["observability"] = {"ui": "lgtm"}` (cluster-up then installs the stack; update the comments
  and the header block's description).
- After the OpenTelemetry step: port-forward the `lgtm` pod's 3100 and 3200 (background PID, killed in `cleanup`; wait on the PID,
  never `pgrep -f`); a fresh trace id; `curl` `/api/info` with `traceparent`; poll Loki `query_range` up to 120 s.
- Checks: stream labels, `| k8s_pod_name=... | deployment_environment="dev"`, `| trace_id=...`, Tempo `/api/traces/<id>`,
  `{service_name="otel-collector"}` empty, `kubectl auth can-i` yes/no, no DaemonSet of the system.
- The shared setup runs in every part (spec 134), so these checks run in each PR part; keep them under 3 minutes after the stack is up.
- If otel-lgtm's provisioned data sources do not link Loki's `trace_id` to Tempo, report it as a BLOCKER instead of changing the
  shared stack (non-goal).

**Done when:** `tests/e2e/run.sh` passes locally or in the e2e job, and fails with a named message when the tailer container is
removed from the rendered collector.

## t8 — Docs: how it works, ADR-021 superseded in part, ADR index, gitops CLAUDE.md, changelog fragment

**Files:** docs/HOW-IT-WORKS.md, docs/adr/021-observability-otel.md, docs/adr/README.md, templates/gitops-app/CLAUDE.md.jinja, docs/changelog.d/182-logs-reach-loki.added.md
**Covers:** AC-182.3
**Goal:** the docs say how logs get to the backend and what access it takes (A6).

**Implementation notes:**
- HOW-IT-WORKS "Observability": the collector also reads every pod's stdout in the namespace through the Kubernetes API (namespaced
  read of pods and pod logs only), labels, trace link; link ADR-098.
- ADR-021: "Not included" stdout entry marked superseded by ADR-098 (keep the rest); header line `Superseded in part by: ADR-098`.
- `docs/adr/README.md`: row 098 (the ADR file exists).
- gitops-app `CLAUDE.md.jinja`: one line on log collection in the observability notes.
- Changelog fragment per `docs/changelog.d/README.md`; `uv run scripts/check-docs.py` and `check-links.py` pass.

**Done when:** `cplat platform pr-check` passes for the fragment and links; the docs check is green.
