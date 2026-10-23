---
spec_id: 092-firing-alerts-become-issues-in-the
title: Firing alerts become issues in the owning repo
status: draft
priority: P1
---

# 092 — Firing alerts become issues in the owning repo

## Problem

Once a service runs in dev, staging or prod, nothing from the running system reaches the backlog. The observability addon (ADR-021) collects metrics and traces, but on purpose it has no alerting. So a service that is down, failing or slow is only noticed when someone happens to look at a dashboard, and then fixes it by hand outside the spec/triage flow. This is the fourth feedback loop of this round ("running system → issues"). It depends on 088 for the convention that keeps issues deduplicated. The user decided that alerts reach GitHub through a scheduled poll on the self-hosted CI runner of the gitops-app repo, not through a bridge inside the cluster, and that every filed issue goes through `/shared:triage` before anything is built from it.

## Stories

As the owner of a product, I want a firing alert to show up as an issue in the repo of the service that causes it, so that I can route it in triage like any other bug instead of finding it on a dashboard by chance.

As a service maintainer, I want one issue per alert that tracks when it fires and resolves, not a new issue every poll, so that my issue list stays readable.

As the operator of the gitops-app repo, I want to declare a few alert rules next to the services, without installing operators or CRDs, and to see right away when the poll itself cannot do its job, so that silence means "nothing is firing", not "the poll is broken".

## Acceptance criteria

Setup and scope

- **AC-092.1** Given an application whose `app.yaml` declares the observability addon, when the gitops-app repo is generated or updated with `/shared:update-service`, then the repo has a scheduled alert poll that runs every 15 minutes on the repo's self-hosted runner and can also be started by hand.
- **AC-092.2** Given an application without the observability addon, or with `alerts` switched off in the addon, when the poll runs, then it files, comments on and closes nothing, and its run summary says why it skipped.
- **AC-092.3** Given a repo with no self-hosted runner configured, when the poll is due, then it does not run on a GitHub-hosted runner, and its run summary says that the alert poll needs the self-hosted runner.
- **AC-092.4** Given alert rules declared under the observability addon in `app.yaml` (each with a name, a Prometheus query, a severity and an optional summary), when a query returns one or more series at poll time, then that rule is firing for each environment and service the series belong to. A rule whose query returns nothing is not firing.
- **AC-092.5** Given a service in `services.yaml` that declares metrics and the observability addon declared, when no rule of that name is declared, then a built-in rule `ServiceDown` fires for that service and environment when none of its metrics targets has been up for 5 minutes.
- **AC-092.6** Given an `app.yaml` rule with no name, an invalid severity (allowed: `critical`, `warning`, `info`), a name that appears twice, or a query that is not a non-empty string, when the repo renders, then the render fails, naming the rule and the problem, and the repo's quality gate is red.

Mapping and filing

- **AC-092.7** Given a firing alert whose `service` label (or else `job` label) equals the `name` of a `services.yaml` entry that has a `repo`, when the poll runs, then the issue is filed in that `repo`, with the labels `alert` and `triage` (each created first if missing). The title is `[alert] <alert name>: <service> in <environment>`. The body gives the severity, the environment, the time the alert started firing, the rule's summary, the query, and the 088 signature built from application, environment, service and alert name.
- **AC-092.8** Given a firing alert that maps to no `services.yaml` entry, or to an entry without `repo`, when the poll runs, then the issue is filed in the gitops-app repo itself, as in AC-092.7, and the body says which label values could not be mapped.
- **AC-092.9** Given a target repo that the poll's credential cannot write issues to, when an alert for it fires, then the issue is filed in the gitops-app repo instead, naming the intended repo and the reason, and the run ends red.
- **AC-092.10** Given any text going into an issue or comment (alert labels, annotations, rule summaries, query results), when the poll writes it, then secrets are redacted with the same redaction as `cplat feedback`, and label and annotation values are shown as quoted data, not as Markdown the reader would follow.

Deduplication and lifecycle

- **AC-092.11** Given an open issue with the alert's signature, when the alert is still firing at the next polls, then no new issue is created and no comment is added.
- **AC-092.12** Given an open issue with the alert's signature that has been marked resolved, when the alert fires again, then one comment "fired again at <time>" is added to that issue and its fire count in the body goes up by one. No new issue is created.
- **AC-092.13** Given an open issue whose alert is no longer firing at a successful poll, when the poll runs, then one comment "resolved at <time>" is added. The issue is closed only while it still carries the `triage` label, meaning nobody has routed it yet.
- **AC-092.14** Given an issue the poll closed as resolved in the last 7 days, when the same signature fires again, then that issue is reopened with a "fired again" comment. If a human closed the issue, or the poll closed it more than 7 days ago, a new issue is filed that links the earlier one.
- **AC-092.15** Given a poll that finds more than 10 alerts with no open issue, when it files, then it files the 10 most severe (`critical` before `warning` before `info`, then oldest first). It adds one summary issue (or a comment on the open summary issue) in the gitops-app repo listing the rest, and the rest are filed at later polls.

Failure of the poll itself

- **AC-092.16** Given that the metrics query endpoint or the GitHub API cannot be reached, or refuses the credential, when the poll runs, then the run ends red with the endpoint and the reason, and no issue is marked resolved or closed on the basis of that run.
- **AC-092.17** Given three polls in a row that failed as in AC-092.16, when the third one ends, then one deduplicated issue "alert poll is failing" is filed (or commented on) in the gitops-app repo with the last reason. It is marked resolved, following AC-092.13, at the next successful poll.
- **AC-092.18** Given a hand-started poll in dry-run mode, when it runs, then it prints every issue it would file, comment on, reopen or close, with target repo and title, and changes nothing on GitHub.

## Non-goals

- A bridge inside the cluster (Alertmanager webhook receiver, Grafana contact point). The user chose the scheduled poll.
- Paging, chat or e-mail notification, and on-call escalation. Issues are the only output.
- Prometheus Operator CRDs (`PrometheusRule`) or installing an Alertmanager. Rules live in `app.yaml` (ADR-021 stays CRD-free).
- Dashboards as code, log-based alerts, SLO/burn-rate rule generators.
- Building or fixing anything automatically from an alert issue. The user routes it in `/shared:triage` (round decision 3).
- Recording alert issues in the run store (087) or feeding them to the weekly retro (090). Those specs may read the `alert` label later.
- Smoke-test failures after deploy. Those are spec 091.

## Open questions

- Where does the poll read metrics from? (suggested: for `ui: lgtm`, the shared stack's Prometheus-compatible query API by default. For `exportTo`, a `queryURL` (plus an optional credential Secret) declared in the addon; with `exportTo` and no `queryURL`, the poll skips as in AC-092.2 and says so. Affects AC-092.2, AC-092.4, AC-092.16.)
- Should the poll also read already-firing alerts from an existing Alertmanager-compatible API (for example Grafana Cloud or a team's own Alertmanager), as well as evaluating `app.yaml` rules? (suggested: yes, as an optional `alertmanagerURL` in the addon whose alerts are mapped and deduplicated exactly like rule alerts. Affects a new criterion and AC-092.7.)
- Which environments are polled? (suggested: every environment where the addon runs, with the environment in title, signature and an `env:<name>` label. Affects AC-092.4, AC-092.7.)
- Confirm: the poll is on by default when the observability addon is declared and can be switched off with `alerts: false` in the addon (affects AC-092.1, AC-092.2).
- Confirm: polling every 15 minutes (affects AC-092.1).
- Confirm: the built-in `ServiceDown` rule after 5 minutes without a healthy metrics target, for every service that declares metrics (affects AC-092.5).
- Confirm: an issue is closed on resolve only while it is still untriaged (`triage` label), otherwise it only gets a comment (affects AC-092.13).
- Confirm: a poll-closed issue is reopened if the alert fires again within 7 days, otherwise a new linked issue is filed (affects AC-092.14).
- Confirm: at most 10 new alert issues per poll, the rest summarised in the gitops-app repo (affects AC-092.15).
- Confirm: the "alert poll is failing" issue after 3 failed polls in a row (affects AC-092.17).
- Which credential writes issues into the service repos? The workflow's own token can only write to the gitops-app repo. (suggested: reuse the cross-repo credential the gitops-app repo already holds for its service-repo interactions, or a dedicated fine-grained token limited to "issues: write" on the app's service repos, with `cplat doctor` warning when it is missing. Affects AC-092.9 and a new doctor criterion.)

## Changelog

- 2026-10-23 created
