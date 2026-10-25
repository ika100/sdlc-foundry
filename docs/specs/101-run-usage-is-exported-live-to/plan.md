---
spec_id: 101-run-usage-is-exported-live-to
spec_hash: 4f3ef3ba0368
summary: telemetry.py sets Claude Code's native OTLP export for headless and benchmark sessions (explicit endpoint,
  else the gitops-app's lgtm addon through a port-forward on a configured context), local-only unless opted in,
  content logging forced off, run attributes added; a post-run PromQL comparison note; a provisioned Grafana dashboard
tasks:
  - id: t1
    title: telemetry.py session_env — endpoint resolution, locality rule and opt-in, variables, port-forward, one warning
    files: [scripts/cplat/telemetry.py, scripts/cplat/settings.py]
    covers: [AC-101.1, AC-101.2, AC-101.3, AC-101.4, AC-101.5, AC-101.6, AC-101.7]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: headless and runs benchmark start sessions with session_env; telemetry section in the record
    files: [scripts/cplat/headless.py, scripts/cplat/runs_bench.py, scripts/cplat/runs.py]
    covers: [AC-101.1, AC-101.2, AC-101.5]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: telemetry.compare — PromQL totals by run id, usage.otel note, nothing else changes
    files: [scripts/cplat/telemetry.py, scripts/cplat/runs.py]
    covers: [AC-101.9, AC-101.10, AC-101.11]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: Grafana dashboard JSON and its provisioning in local-cluster.sh
    files: [templates/gitops-app/observability/dashboards/claude-code-usage.json, templates/gitops-app/scripts/local-cluster.sh]
    covers: [AC-101.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: Docs — unattended-delivery.md telemetry section, shared README, CHANGELOG
    files: [docs/unattended-delivery.md, plugins/shared/README.md, docs/CHANGELOG.md]
    covers: [AC-101.4, AC-101.6]
    parallel_safe: false
    depends_on: [t3, t4]
    done: true
---

# Plan — 101 Run usage is exported live to OpenTelemetry

Design: [design.md](design.md). Red tests first (`tests/cplat/test_telemetry.py`), then t1–t4, one coder, docs, reviewer.
