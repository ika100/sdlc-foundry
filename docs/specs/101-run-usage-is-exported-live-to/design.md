# Design — 101 Run usage is exported live to OpenTelemetry

## Verified assumptions (Claude Code monitoring docs, code.claude.com/docs/en/monitoring-usage, 2026-10-25)

- Telemetry: `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_METRICS_EXPORTER=otlp`, `OTEL_LOGS_EXPORTER=otlp`,
  `OTEL_EXPORTER_OTLP_ENDPOINT`, and `OTEL_EXPORTER_OTLP_PROTOCOL` (no default; must be set). Holds.
- Metrics `claude_code.token.usage` (attribute `type`: `input`, `output`, `cacheRead`, `cacheCreation`; `model`;
  `agent.name`) and `claude_code.cost.usage` (USD; `model`, `agent.name`); event `claude_code.api_request` per call.
  Holds.
- `OTEL_RESOURCE_ATTRIBUTES` adds `key=value` pairs (no spaces in values) to every datapoint and event. Holds.
- Subagent type: `agent.name` on metrics and `api_*` events; absent for the main session. Holds (answers the open
  point: the coordinator is the series without `agent.name`).
- Content is off by default (`OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_TOOL_DETAILS`, `OTEL_LOG_TOOL_CONTENT`,
  `OTEL_LOG_ASSISTANT_RESPONSES`, `OTEL_LOG_RAW_API_BODIES`). Holds; cplat sets each to `0` explicitly (AC-101.7).
- OTEL variables in a repo's `.claude/settings.json` are ignored, so cplat must pass them in the process environment.
- **Does not hold as written:** the addon's local backend is `grafana/otel-lgtm`, whose metrics store is Prometheus,
  not Mimir. The query API is the same PromQL HTTP API, so AC-101.9 reads "the addon's metrics store (Prometheus or
  Mimir query API)"; the spec is amended in wording only.

## Decisions

- **One module, `telemetry.py`, decides the environment of a session.** `telemetry.session_env(repo, run_id, kind)`
  returns `(env, note, forward)`: the OTEL variables to add to `claude -p`'s environment, at most one note line,
  and an optional port-forward to start. `cplat headless` (`run_once`) and `cplat runs benchmark` call it; nothing
  else changes for them.
- **Where the endpoint comes from** (AC-101.1, AC-101.2, AC-101.4): in order, `CPLAT_OTLP_ENDPOINT`, then
  `telemetry.endpoint` in the settings files (`settings.py`, project over user), then the addon: the repo's
  gitops-app (`.platform-app.yml`, or the repo itself for a gitops-app) has `observability: {ui: lgtm}` in its
  `app.yaml` **and** a kube context is configured (`telemetry.context` in settings or `CPLAT_KUBE_CONTEXT`). Then cplat
  runs `kubectl --context C -n observability port-forward svc/lgtm <free port>:4318` for the session and exports to
  `http://127.0.0.1:<port>`. An explicit endpoint always wins and no port-forward starts. Nothing found → no
  variables, no output, no extra process (AC-101.4). A context is never guessed.
- **Locality rule** (AC-101.6): an endpoint whose host is `localhost`, `127.0.0.0/8`, `::1`, a `*.svc` /
  `*.svc.cluster.local` name or a `*.localhost` name is local. Any other host needs `telemetry.allow_remote: true` (or
  `CPLAT_OTLP_ALLOW_REMOTE=1`); without it telemetry stays off with one line naming the endpoint and that setting.
- **Variables set** (AC-101.3, AC-101.7): `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_METRICS_EXPORTER=otlp`,
  `OTEL_LOGS_EXPORTER=otlp`, `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
  `OTEL_METRIC_EXPORT_INTERVAL=10000`, `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=cumulative`, the five
  `OTEL_LOG_*` content switches `=0` (overriding the user's environment), and
  `OTEL_RESOURCE_ATTRIBUTES=cplat.run_id=<id>,cplat.kind=<workflow or kind>,cplat.repo=<slug>,cplat.platform_version=<v>`
  (values percent-encoded; the user's own `OTEL_RESOURCE_ATTRIBUTES` pairs are kept after ours).
- **Failure never changes a run** (AC-101.5): the export is Claude Code's own and runs in the background. cplat checks
  the endpoint once per command with a 1 s TCP connect; unreachable → one warning line, the variables are still set
  (Claude Code drops what it cannot send), and the run goes on. A failed port-forward is the same single warning
  and no variables. The port-forward is stopped in a `finally`.
- **The difference note** (AC-101.9, AC-101.10, AC-101.11): `runs.finish` calls `telemetry.compare(run_id, usage)`
  after the transcript usage is collected, only when the run had telemetry on (`telemetry` section with the backend).
  It queries the PromQL API of the same backend (port-forward `svc/lgtm` port 9090 for the addon, or
  `telemetry.query_url` for an explicit backend; none configured → no note), 5 s total budget:
  `sum by (type) (max_over_time(claude_code_token_usage_tokens_total{cplat_run_id="<id>"}[<run duration>]))` and the
  same for `claude_code_cost_usage_USD_total`. The record gets `usage.otel = {totals: {input, output, cache_read,
  cache_write, cost_usd}, difference: {<type>: otel - transcript}}`. No figures, an error or a timeout → no `otel`
  key at all. The transcript-derived figures, phases and roles are never changed; `cplat runs report` ignores
  `usage.otel`.
- **Dashboard** (AC-101.8): `templates/gitops-app/observability/dashboards/claude-code-usage.json`, provisioned into
  the otel-lgtm pod by `scripts/local-cluster.sh` (a ConfigMap mounted at the image's Grafana dashboard provisioning
  directory; the coder verifies the path against the `grafana/otel-lgtm:0.35.0` image). Panels: tokens and estimated
  cost per run (`cplat_run_id`), per model, per day, and the coordinator's share (series without `agent_name` over
  all).

## Contract

```
telemetry.session_env(repo: Path, run_id: str | None, kind: str) -> (env: dict[str, str], note: str | None, forward: Forward | None)
telemetry.compare(run_id: str, usage: dict) -> dict | None          # the usage.otel value, or None
settings: telemetry: {endpoint, context, allow_remote, query_url}
env: CPLAT_OTLP_ENDPOINT, CPLAT_OTLP_ALLOW_REMOTE, CPLAT_KUBE_CONTEXT
record: telemetry: {backend: "endpoint"|"addon", endpoint}, usage.otel: {totals, difference}
```
