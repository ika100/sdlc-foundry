---
spec_id: 092-firing-alerts-become-issues-in-the
title: Firing alerts become issues in the owning repo
status: building
priority: P1
---

# 092 — Firing alerts become issues in the owning repo

## Problem

Once a service runs in dev, staging or prod, nothing from the running system reaches the backlog. The observability addon (ADR-021) collects metrics and traces, but on purpose it has no alerting. So a service that is down, failing or slow is only noticed when someone happens to look at a dashboard, and then fixes it by hand outside the spec/triage flow. This is the fourth feedback loop of this round ("running system → issues"). It depends on 088 for the issue convention: signature line, labels, and dedupe. The user decided that alerts reach GitHub through a scheduled poll on the self-hosted CI runner of the gitops-app repo, not through a bridge inside the cluster, and that every filed issue goes through `/shared:triage` before anything is built from it.

## Stories

As the owner of a product, I want a firing alert to show up as an issue in the repo of the service that causes it, so that I can route it in triage like any other bug instead of finding it on a dashboard by chance.

As a service maintainer, I want one issue per alert that tracks when it fires and resolves, not a new issue every poll, so that my issue list stays readable.

As the operator of the gitops-app repo, I want to declare a few alert rules next to the services, without installing operators or CRDs, and to see right away when the poll itself cannot do its job, so that silence means "nothing is firing", not "the poll is broken".

## Acceptance criteria

Setup and scope

- **AC-092.1** Given an application whose `app.yaml` declares the observability addon, when the gitops-app repo is generated or updated with `/shared:update-service`, then the repo has a scheduled alert poll that runs every 15 minutes on the repo's self-hosted runner and can also be started by hand.
- **AC-092.2** Given an application without the observability addon, or with `alerts: false` in the addon, when the poll runs, then it files, comments on and closes nothing, and its run summary says why it skipped.
- **AC-092.3** Given a repo with no self-hosted runner configured, when the poll is due, then it does not run on a GitHub-hosted runner, and its run summary says that the alert poll needs the self-hosted runner.
- **AC-092.4** Given alert rules declared under the observability addon in `app.yaml` (each with a name, a Prometheus query, a severity and an optional summary), when a query returns one or more series at poll time, then that rule is firing for each environment and service the series belong to. A rule whose query returns nothing is not firing.
- **AC-092.5** Given a service in `services.yaml` that declares metrics and the observability addon declared, when no rule of that name is declared, then a built-in rule `ServiceDown` fires for that service and environment when none of its metrics targets has been up for 5 minutes.
- **AC-092.6** Given an `app.yaml` rule with no name, an invalid severity (allowed: `critical`, `warning`, `info`), a name that appears twice, or a query that is not a non-empty string, when the repo renders, then the render fails, naming the rule and the problem, and the repo's quality gate is red.
- **AC-092.19** Given the observability addon with `ui: lgtm`, when the poll runs, then it evaluates the rules against the shared stack's Prometheus-compatible query API. With `exportTo`, it evaluates them against the addon's `queryURL`, sending the credential from the optional `querySecret` Secret. With `exportTo` and no `queryURL` (and no `alertmanagerURL`, AC-092.23), it skips as in AC-092.2, and the summary says that `queryURL` is missing.
- **AC-092.23** Given an `alertmanagerURL` in the observability addon, when the poll runs, then every alert that Alertmanager-compatible API reports as active is treated like a firing rule alert. It is mapped (AC-092.20, AC-092.8), deduplicated (AC-092.11, AC-092.21, AC-092.22), resolved (AC-092.13) and capped (AC-092.15) the same way. Its severity is the alert's `severity` label, or `warning` when that label is missing or not one of the allowed values.
- **AC-092.24** Given the observability addon running in several environments, when the poll runs, then it evaluates every environment where the addon runs. Alerts with the same name and service in different environments are separate issues with different signatures.

Mapping and filing

- ~~**AC-092.7**~~ withdrawn 2026-10-23: title, labels and signature now follow the 088 convention, see AC-092.20.
- **AC-092.20** Given a firing alert whose `service` label (or else `job` label) equals the `name` of a `services.yaml` entry that has a `repo`, when the poll runs, then the issue is filed in that `repo`. Its title is `[auto] [alert] <alert name>: <service> in <environment>`, at most 100 characters. It carries the labels `triage`, `auto-filed`, `alert` and `env:<environment>`, each created first if missing. The body gives the severity, the environment, the time the alert started firing, the rule's summary and the query (or the Alertmanager source), and has exactly one line `Signature: alert:<16 lowercase hex characters>`. The signature is computed from application, environment, service and alert name only.
- **AC-092.8** Given a firing alert that maps to no `services.yaml` entry, or to an entry without `repo`, when the poll runs, then the issue is filed in the gitops-app repo itself, as in AC-092.20, and the body says which label values could not be mapped.
- **AC-092.9** Given a target repo that the poll's credential cannot write issues to, when an alert for it fires, then the issue is filed in the gitops-app repo instead, naming the intended repo and the reason, and the run ends red.
- **AC-092.25** Given a gitops-app repo whose observability addon is declared and whose `services.yaml` has at least one entry with a `repo`, when `cplat doctor` runs and the repo secret `ALERTS_TOKEN` (a token with issue write access to the app's service repos) is not set, then doctor shows a warning. The warning says that alert issues will land in the gitops-app repo and gives the command that sets the secret. With the secret set, or without the addon, there is no warning.
- **AC-092.10** Given any text going into an issue or comment (alert labels, annotations, rule summaries, query results), when the poll writes it, then secrets are redacted with the same redaction as `cplat feedback` and spec 088. Label and annotation values are shown as quoted data, not as Markdown the reader would follow.

Deduplication and lifecycle

- **AC-092.11** Given an open issue with the alert's signature, when the alert is still firing at the next polls, then no new issue is created and no comment is added.
- ~~**AC-092.12**~~ withdrawn 2026-10-23: the repeat is now a counted comment as in 088, see AC-092.21.
- **AC-092.21** Given an open issue with the alert's signature whose last poll comment says it was resolved, when the alert fires again, then one comment "fired again" is added to the oldest such open issue. The comment states the occurrence number (2, 3, …) and the time. No new issue is created.
- **AC-092.13** Given an open issue whose alert is no longer firing at a successful poll, when the poll runs, then one comment "resolved at <time>" is added. The issue is closed only while it still carries the `triage` label, meaning nobody has routed it yet.
- ~~**AC-092.14**~~ withdrawn 2026-10-23: aligned with 088's handling of closed issues and `wontfix`, see AC-092.22.
- **AC-092.22** Given that the only issues with the alert's signature are closed, when the alert fires again, then one of three things happens. If the poll closed the most recent one as resolved in the last 7 days, that issue is reopened with a counted "fired again" comment (AC-092.21). If the most recently closed one carries the label `wontfix`, nothing is filed and the run summary notes `suppressed by #<n>`. Otherwise a new issue is filed whose body says `Seen again after #<n> was closed`.
- **AC-092.15** Given a poll that finds more than 10 alerts with no open issue, when it files, then it files the 10 most severe (`critical` before `warning` before `info`, then oldest first). It adds one summary issue (or a comment on the open summary issue) in the gitops-app repo listing the rest, and the rest are filed at later polls. Comments on existing issues are not capped.

Failure of the poll itself

- **AC-092.16** Given that the metrics query endpoint, the Alertmanager endpoint or the GitHub API cannot be reached, or refuses the credential, when the poll runs, then the run ends red with the endpoint and the reason, and no issue is marked resolved or closed on the basis of that run.
- **AC-092.17** Given three polls in a row that failed as in AC-092.16, when the third one ends, then one deduplicated issue "alert poll is failing" is filed (or commented on) in the gitops-app repo with the last reason, following the 088 convention. It is marked resolved, following AC-092.13, at the next successful poll.
- **AC-092.18** Given a hand-started poll in dry-run mode, when it runs, then it prints every issue it would file, comment on, reopen or close, with target repo and title, and changes nothing on GitHub.

## Non-goals

- A bridge inside the cluster (Alertmanager webhook receiver, Grafana contact point). The user chose the scheduled poll.
- Paging, chat or e-mail notification, and on-call escalation. Issues are the only output.
- Prometheus Operator CRDs (`PrometheusRule`) or installing an Alertmanager. Rules live in `app.yaml` (ADR-021 stays CRD-free). An existing Alertmanager is only read (AC-092.23).
- Dashboards as code, log-based alerts, SLO/burn-rate rule generators.
- Building or fixing anything automatically from an alert issue. The user routes it in `/shared:triage` (round decision 3).
- Recording alert issues in the run store (087) or feeding them to the weekly retro (090). Those specs may read the `alert` label later.
- Smoke-test failures after deploy. Those are spec 091.

## Open questions

- ~~Where does the poll read metrics from?~~ Answered: the lgtm query API for `ui: lgtm`, `queryURL` plus optional credential Secret for `exportTo`, skip otherwise, see AC-092.19.
- ~~Should the poll also read firing alerts from an existing Alertmanager-compatible API?~~ Answered: yes, an optional `alertmanagerURL`, see AC-092.23.
- ~~Which environments are polled?~~ Answered: every environment where the addon runs, with an `env:<name>` label, see AC-092.24 and AC-092.20.
- ~~Confirm: on by default, `alerts: false` switches it off.~~ Confirmed, see AC-092.1 and AC-092.2.
- ~~Confirm: polling every 15 minutes.~~ Confirmed, see AC-092.1.
- ~~Confirm: built-in `ServiceDown` rule after 5 minutes.~~ Confirmed, see AC-092.5.
- ~~Confirm: close on resolve only while still untriaged.~~ Confirmed, see AC-092.13.
- ~~Confirm: reopen a poll-closed issue within 7 days, otherwise a new linked issue.~~ Confirmed, aligned with 088's `wontfix` rule, see AC-092.22.
- ~~Confirm: at most 10 new alert issues per poll.~~ Confirmed, see AC-092.15.
- ~~Confirm: "alert poll is failing" issue after 3 failed polls.~~ Confirmed, see AC-092.17.
- ~~Which credential writes issues into the service repos?~~ Answered: a dedicated fine-grained token with only issue write access on the app's service repos (the gitops-app repo has no cross-repo token today), and `cplat doctor` warns when it is missing, see AC-092.25 and AC-092.9.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended: open questions answered (metrics source, Alertmanager source, all environments, issue-write token with doctor warning, defaults confirmed). Aligned with the 088 issue convention: `[auto] ` titles, `Signature: alert:<16 hex>`, labels `triage`/`auto-filed`/`alert`, counted repeat comments, `wontfix` suppression. AC-092.7, .12 and .14 withdrawn; AC-092.19 to .25 added.
- 2026-10-23 approved
- 2026-10-24 building
