# ADR-038 — Alerts reach GitHub through a scheduled poll on the gitops-app's self-hosted runner

**Status:** accepted (2026-10-24, spec 092)

## Context

The observability addon (ADR-021) collects metrics and traces but has no alerting, so a service that is down or failing
is only noticed on a dashboard. Spec 092 turns firing alerts into issues in the repo of the service that causes them,
using the issue convention of ADR-033. The user chose a scheduled poll over a bridge inside the cluster (an
Alertmanager webhook receiver or a Grafana contact point). The poll has to reach the cluster's Prometheus-compatible API,
which only the self-hosted runner can do. It must not be one more component to install in the cluster.

## Decision

- **The poll is `cplat alerts poll`, run by the gitops-app workflow `.github/workflows/alerts.yml`** every 15 minutes
  and on demand. The workflow runs `scripts/alert-poll.sh`. Like `scripts/spec-check.sh`, that script fetches the
  platform at the repo's `.platform-version` ref and runs `cplat.py` from it. So the poll uses `autoissue` (ADR-033)
  itself, not a copy, and a gitops-app repo gets new poll behaviour through `/shared:update-service`.
- **The poll runs only on the self-hosted runner** (`runs-on: ${{ vars.CI_RUNNER }}`, job `if: vars.CI_RUNNER != ''`).
  It never falls back to `ubuntu-latest`. A GitHub-hosted runner cannot reach the cluster, and a run every 15 minutes
  would cost about 3000 billed minutes a month. Without a runner, every job is skipped. The run name and the skipped
  job's name say that the alert poll needs the self-hosted runner.
- **Rules live in `app.yaml`,** under the observability addon. They are plain PromQL with name, severity and summary,
  validated by `render.py`. The built-in `ServiceDown` rule applies to every service with a `metrics:` path. There are
  no `PrometheusRule` CRDs and no Alertmanager install (ADR-021 stays CRD-free). An existing Alertmanager-compatible API
  is only read.
- **GitHub issues are the state of the lifecycle.** Whether an alert is open, resolved, fired again or poll-closed is
  read back from the issue, its labels and the poll's comment markers (`**Resolved** at`, `**Fired again**`). The
  only state outside GitHub issues is the count of failed polls in a row. It is a small JSON file carried from run to
  run as the workflow artifact `alert-poll-state` (3 days retention).
- **Writes into service repos use a dedicated fine-grained token,** `ALERTS_TOKEN` (Issues: read and write on the
  app's service repos). The gitops-app repo itself is written with the workflow's `GITHUB_TOKEN`. When a service repo
  cannot be written to, the issue lands in the gitops-app repo, naming the intended repo, and the run is red.
  `cplat doctor` warns when the secret is missing.
- **Alert signatures are not normalised:** `raw_signature("alert", app, environment, service, alert name)`. These
  names are stable identifiers. Normalising would give `svc-1` and `svc-2` the same signature.

## Consequences

- Alerting needs a self-hosted runner next to the cluster, and that runner needs network access to the query API (for
  `ui: lgtm`, `http://lgtm.observability.svc:9090`, which `cluster-up` now exposes).
- Alerts are seen with up to 15 minutes delay, plus the rule's own window. This is a backlog feed, not paging.
- A gitops-app repo whose `.platform-version` predates 092 has the workflow only after `/shared:update-service`, and
  the poll uses the behaviour of the platform version it is pinned to.
- Run artifacts accumulate for 3 days at a time, at about 300 small files per repo.

## Not included

- Paging, chat or e-mail notification, on-call escalation.
- Recording alert issues in the run store (ADR-032) or the weekly retro.
- Recording rules, dashboards as code, log-based or SLO alerts.
