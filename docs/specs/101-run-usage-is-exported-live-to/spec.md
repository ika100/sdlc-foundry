---
spec_id: 101-run-usage-is-exported-live-to
title: Run usage is exported live to OpenTelemetry
status: approved
priority: P1
---

# 101 — Run usage is exported live to OpenTelemetry

## Problem

Run usage is only known after a run, from the transcripts in the run store (specs 087, 099), and the output-token counts look undercounted. Platform users with the observability stack (Loki, Grafana, Tempo, Mimir) cannot watch tokens and cost while runs happen, nor see them per model or per day. This spec adds live OpenTelemetry export as an optional addition. The run store stays the system of record: a private git repo that works offline and without a cluster, read by `cplat runs report`, the retro (090) and agent metrics (089).

**Assumptions, unverified.** The architect must check each against current Claude Code documentation during `/svc:plan` and report any that fail:
- Claude Code exports metrics and events over OTLP when `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_METRICS_EXPORTER` / `OTEL_LOGS_EXPORTER` are `otlp` and `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- The metrics include token usage by type and model, and cost; there is a per-API-call event.
- Resource attributes can be added with `OTEL_RESOURCE_ATTRIBUTES`.
- It is unknown whether events identify the subagent type.
- Prompt text is off by default.

## Stories

As a platform user, I want run tokens and cost to appear live in Grafana, so that I can see what runs cost without waiting for a report.

As a platform maintainer, I want OTel totals compared with transcript totals, so that I can check whether the transcript counting is wrong.

## Acceptance criteria

- **AC-101.1** Given an OTLP endpoint is configured by a cplat setting or environment variable, when `cplat headless` or `cplat runs benchmark` starts a Claude Code session, then that session's native telemetry is on and exports to the endpoint.
- **AC-101.2** Given the product's gitops-app has the observability addon, when a session is started, then telemetry is on and exports to the addon's collector, unless an endpoint is explicitly configured, in which case that endpoint is used and the collector is not.
- **AC-101.3** Given telemetry is on, when a session is started, then everything it exports carries the resource attributes cplat run id, workflow or kind, repo and platform version.
- **AC-101.4** Given no endpoint is configured and no observability addon is present, when a session is started, then telemetry stays off and the command shows no error, no warning and no added delay.
- **AC-101.5** Given the endpoint is unreachable or rejects data, when a run executes, then the run completes with the same result and its run record is still written; at most one warning is shown.
- **AC-101.6** Given an endpoint that is not on localhost or inside the cluster, when a session is started without its own explicit opt-in setting (never implied by setting the endpoint), then the endpoint is refused, telemetry stays off and one message names the endpoint and hints at the opt-in; with the opt-in it exports.
- **AC-101.7** Given telemetry is on, when a session runs, then no prompt text, tool input or tool output is exported, and prompt logging is off even if the user's own environment turned it on; only counts, model, cost and the attributes of AC-101.3 are exported.
- **AC-101.8** Given the observability addon is installed, when Grafana is opened, then a provisioned dashboard shows tokens and estimated cost per run, per model and per day, and the coordinator's share of tokens and cost.
- **AC-101.9** Given a run with OTel figures available, when its record is written after the run, then the OTel totals are queried from the addon's Mimir by cplat run id and the record notes them, the transcript totals and their difference per token type.
- **AC-101.10** Given a run without OTel figures (telemetry off, Mimir not reachable or no figures for the run id), when its record is written, then it has no difference note, the transcript totals are unchanged, and `cplat runs report` output is the same as before this spec.
- **AC-101.11** Given any run, when phases and agent roles are reported, then they come from the transcripts only; OTel never changes the record's transcript-derived figures.

## Non-goals

- Replacing the run store.
- Budgets or enforcement (#144).
- Instrumenting anything other than Claude Code sessions started by cplat.
- A hosted or public telemetry backend.
- Phases inside one session from OTel alone.

## Open questions

- ~~Source of OTel totals for the difference note?~~ Answered: query the addon's Mimir for the run id after the run when reachable, otherwise omit the note, see AC-101.9 and AC-101.10.
- ~~Confirm: separate explicit opt-in for a non-private endpoint?~~ Answered: yes, see AC-101.6.
- ~~Confirm: explicit endpoint wins over the addon's collector?~~ Answered: yes, see AC-101.2.

## Changelog

- 2026-10-25 created
- 2026-10-25 amended: folded the user's answers into AC-101.2, AC-101.6, AC-101.9 and AC-101.10; open questions closed
- 2026-10-25 approved
