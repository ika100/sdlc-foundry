---
spec_id: 087-every-run-is-recorded-in-a-private-run
title: Every run is recorded in a private run store
status: draft
priority: P0
---

# 087 — Every run is recorded in a private run store

## Problem

Ship, build, headless and PR-wait runs leave no history. When a run ends, the only traces are a ship state that the next run overwrites, local headless logs and the PR. Of the last 23 specs (062–084), 18 hardened the PR→dev stretch, and each one started from a failure someone happened to notice by hand (#102–#132). Nobody can say which phase takes longest, which escalation reasons keep coming back or which CI checks keep needing reruns. Specs 088–097 (platform-failure issues, agent quality, weekly retro, smoke results, auto-promotion, fleet updates) all need a durable, comparable record of every run. That record must never land in the public platform repo and must never make a run fail.

## Stories

- As the platform owner, I want every unattended or interactive run to leave one structured record in a private store, so that I can judge the platform from evidence instead of from the failures I happened to see.
- As the platform owner, I want `cplat runs report` to show time per phase, the top escalation reasons and the rerun causes across all my repos, so that I can choose the next spec from data.
- As a developer running `/svc:ship` offline or without the store set up, I want my run to behave exactly as before, so that recording never costs me a run.
- As the author of a later spec (088–097), I want a stable record format with a version and room for extra sections, so that I can extend the record without breaking older records or the report.

## Acceptance criteria

The record contract. Every record is one JSON object on its own line and carries these fields:
`schema` (format version, starting at 1), `run_id` (unique, stable across retries), `kind` (`ship` | `build` | `headless` | `pr-wait`), `repo` (`owner/name` of the repo the run worked on), `spec` (spec id or `null`), `platform_version` (the platform release that ran the command), `mode` (`interactive` | `headless`), `started_at` and `ended_at` (UTC, ISO 8601), `phases` (ordered list of `{name, started_at, ended_at}`), `ci_rounds` (number of CI waits that reached a conclusion), `reruns` (list of `{check, reason}` with reason `stale` | `stuck` | `transient`), `escalation` (reason text or `null`), `outcome` (`done` | `escalated` | `failed` | `abandoned`), `resumes` (`run_id` of the escalated run this one continues, or `null`).

- **AC-087.1** Given a run store is configured and reachable, when a `cplat ship` run of a spec ends in phase `done`, then exactly one record with `kind` `ship`, that spec's id, `outcome` `done`, `escalation` `null` and every phase it entered (in order, with start and end times) is appended to the store.
- **AC-087.2** Given a ship run, when it is escalated (by `cplat ship escalate <reason>` or by the stop gate giving up), then one record with `outcome` `escalated` and the escalation reason is appended. When the same spec's ship is started again afterwards, the new run's record names the escalated run's `run_id` in `resumes`.
- **AC-087.3** Given an unfinished, unescalated ship run, when a ship of another spec takes it over, then the run that was taken over gets one record with `outcome` `abandoned`.
- **AC-087.4** Given a ship run whose land or deploy watch saw two red CI conclusions before green, plus one stuck run and one transient job failure that were rerun, when its record is written, then `ci_rounds` is 3 and `reruns` holds two entries naming each check with reason `stuck` and `transient`.
- **AC-087.5** Given `/svc:build` or `cplat pr wait` runs outside a ship run, when it ends, then one record with `kind` `build` or `pr-wait` is appended. `pr wait` records green or merged as `done` and red or a timeout as `failed`. When either runs inside a ship run, its phases, CI rounds and reruns count toward the ship record and no separate record is written.
- **AC-087.6** Given `cplat headless "<command>"`, when the invocation ends, then one record with `kind` `headless` and `mode` `headless` is appended. It holds the command (redacted), the number of sessions started, the stop reason (`done`, `escalated`, `out of runs`, `quiet window` or `error`) and the `run_id`s of the ship runs it drove. Those ship records carry `mode` `headless`.
- **AC-087.7** Given the store is unreachable (offline, no permission, rejected write) or not configured, when a run ends, then the run's outcome, exit code and output are unchanged except for one warning line stating that the record was buffered locally and how many records are buffered. Recording adds at most 20 seconds to the run.
- **AC-087.8** Given buffered records and a reachable store, when the next record is written or `cplat runs flush` runs, then every buffered record is appended in `ended_at` order and removed from the buffer. A record that is flushed again after an interrupted flush, or written concurrently from another repo or machine, appears in the store exactly once per `run_id`, and no record is lost.
- **AC-087.9** Given the configured store repo is public, when a run ends, then nothing is written to it, the record is buffered, and the warning says that the store is public and that records are only written to a private repo.
- **AC-087.10** Given an escalation reason or headless command containing a secret (for example `GH_TOKEN=ghp_abc123…` or `Authorization: Bearer …`), when the record is written, then the secret appears as `<redacted>`, exactly as `cplat feedback` redacts it. Records contain no log output, diffs or issue text.
- **AC-087.11** Given `cplat doctor` runs, then the run store check reports: `warn` with the configuration hint when no store is configured; `fail` when the configured repo is public; `warn` naming the repo when it is unreachable; `warn` with the buffered count and `cplat runs flush` when records are buffered; otherwise `ok` naming the repo. The overall doctor result is never `fail` because the store is missing.
- **AC-087.12** Given records from several repos in the store, when `cplat runs report` runs (default window: last 30 days; `--since <days>` and `--repo <owner/name>` narrow it), then it shows: runs per kind and outcome; median and 90th-percentile duration per phase; the top 10 escalation reasons with counts (identical texts grouped); rerun counts by reason and by check name; and the number of locally buffered records not included.
- **AC-087.13** Given `cplat runs report --json`, then the same aggregates are printed as one JSON document with stable keys (`window`, `runs`, `phases`, `escalations`, `reruns`, `buffered`) and nothing else on standard output.
- **AC-087.14** Given the store holds records of an older `schema`, records with fields the reader doesn't know (sections added by later specs such as 089) and one malformed line, when `cplat runs report` runs, then it succeeds. Unknown fields are ignored, missing fields count as unknown, and the report states how many lines were skipped as malformed.
- **AC-087.15** Given no store is configured, or the store is unreachable, when `cplat runs report` or `cplat runs flush` runs, then it exits non-zero with a message naming the problem and the hint to fix it (the configuration setting, or the repo it could not reach).

## Non-goals

- Agent-quality metrics (plan accuracy, reviewer findings, fix rounds): spec 089 adds them as a record section.
- Filing or deduplicating issues from runs: spec 088. The weekly retro: spec 090. Smoke results: spec 091.
- Recording `/svc:spec`, `/svc:plan` or other commands that run outside a ship, build, headless or PR-wait run.
- Storing logs, diffs, prompts or transcripts in the record.
- Dashboards, a web UI, retention or deletion policies for the store.
- A default store repo. Each owner configures their own (`ika100/sdlc-runs` is only an example).

## Open questions

- When no store is configured, should records still be buffered locally so they can be flushed once the store is set up? (suggested: yes, capped at 1000 records with the oldest dropped first, and doctor reports the count; affects AC-087.7, AC-087.11)
- Should there be a `cplat runs init <owner/name>` that creates the private store repo when it is missing and prints the configuration line to set? (suggested: yes, it refuses an existing public repo; affects a new criterion and the AC-087.11 hint)
- Confirm: recording adds at most 20 seconds to a run before it falls back to the buffer. (suggested: yes; affects AC-087.7)
- Confirm: `cplat runs report` defaults to the last 30 days and shows the top 10 escalation reasons. (suggested: yes; affects AC-087.12)
- Confirm: a public store repo is a doctor `fail`, not a `warn`, because it would leak private repo names and escalation text. (suggested: yes; affects AC-087.9, AC-087.11)
- Confirm: an escalated run ends its record, and a resumed ship is a new run linked through `resumes`, so every escalation is counted once. The alternative is one record per spec across all its resumptions. (suggested: yes, a new linked run; affects AC-087.2)

## Changelog

- 2026-10-23 created
