---
spec_id: 087-every-run-is-recorded-in-a-private-run
title: Every run is recorded in a private run store
status: building
priority: P0
---

# 087 — Every run is recorded in a private run store

## Problem

Ship, build, headless and PR-wait runs leave no history. When a run ends, the only traces are a ship state that the next run overwrites, local headless logs and the PR. Of the last 23 specs (062–084), 18 hardened the PR→dev stretch, and each one started from a failure someone happened to notice by hand (#102–#132). Nobody can say which phase takes longest, which escalation reasons keep coming back or which CI checks keep needing reruns. Specs 088–097 (platform-failure issues, agent quality, weekly retro, smoke results, auto-promotion, fleet updates) all need a durable, comparable record of every run. That record must never land in the public platform repo and must never make a run fail.

## Stories

- As the platform owner, I want every unattended or interactive run to leave one structured record in a private store, so that I can judge the platform from evidence instead of from the failures I happened to see.
- As the platform owner, I want `cplat runs report` to show time per phase, the top escalation reasons and causes, and the rerun causes across all my repos, so that I can choose the next spec from data.
- As a developer running `/svc:ship` offline or without the store set up, I want my run to behave exactly as before, so that recording never costs me a run.
- As the author of a later spec (088–097), I want a stable record format with a version and room for extra sections, so that I can extend the record without breaking older records or the report.

## Acceptance criteria

The record contract. Every run record is one JSON object on its own line, written once when the run ends, and carries these fields:
- `schema`: the format version, starting at 1.
- `run_id`: unique, and stable across retries of the same write.
- `kind`: `ship` | `build` | `headless` | `pr-wait` | `fleet` | `retro` | `product-ship`. The list is open-ended: a later spec may add a kind, and readers count an unknown kind under its own name.
- `repo`: `owner/name` of the repo the run worked on, or ran from.
- `spec`: the spec id, or `null`.
- `platform_version`: the platform release that ran the command.
- `mode`: `interactive` | `headless`.
- `started_at` and `ended_at`: UTC, ISO 8601.
- `phases`: an ordered list of `{name, started_at, ended_at}`.
- `ci_rounds`: the number of CI waits that reached a conclusion.
- `reruns`: a list of `{check, reason}`, with reason `stale` | `stuck` | `transient`.
- `escalation`: `null`, or `{reason, cause}` with cause `platform` | `code` | `decision` | `environment` | `unknown`.
- `filed`: a list of `{signature, url, result}`, with result `new` | `+1` | `suppressed` | `pending`.
- `outcome`: `done` | `escalated` | `failed` | `abandoned`.
- `resumes`: the `run_id` of the escalated run this one continues, or `null`.

Later specs add their own sections (`agents` from 089, `smoke` from 091, `patches` from 095, and so on), and readers ignore fields they don't know.

- **AC-087.1** Given a run store is configured and reachable, when a `cplat ship` run of a spec ends in phase `done`, then exactly one record with `kind` `ship`, that spec's id, `outcome` `done`, `escalation` `null` and every phase it entered (in order, with start and end times) is appended to the store.
- ~~**AC-087.2**~~ withdrawn 2026-10-23: replaced by AC-087.16, which adds the escalation cause.
- **AC-087.3** Given an unfinished, unescalated ship run, when a ship of another spec takes it over, then the run that was taken over gets one record with `outcome` `abandoned`.
- **AC-087.4** Given a ship run whose land or deploy watch saw two red CI conclusions before green, plus one stuck run and one transient job failure that were rerun, when its record is written, then `ci_rounds` is 3 and `reruns` holds two entries naming each check with reason `stuck` and `transient`.
- **AC-087.5** Given `/svc:build` or `cplat pr wait` runs outside a ship run, when it ends, then one record with `kind` `build` or `pr-wait` is appended. `pr wait` records green or merged as `done` and red or a timeout as `failed`. When either runs inside a ship run, its phases, CI rounds, reruns and sections count toward the ship record and no separate record is written.
- **AC-087.6** Given `cplat headless "<command>"`, when the invocation ends, then one record with `kind` `headless` and `mode` `headless` is appended. It holds the command (redacted), the number of sessions started, the stop reason (`done`, `escalated`, `out of runs`, `quiet window` or `error`) and the `run_id`s of the ship runs it drove. Those ship records carry `mode` `headless`.
- **AC-087.7** Given the store is unreachable (offline, no permission, rejected write) or not configured, when a run ends, then the run's outcome, exit code and output are unchanged except for one warning line stating that the record was buffered locally and how many records are buffered. Recording adds at most 20 seconds to the run.
- **AC-087.8** Given buffered records and a reachable store, when the next record is written or `cplat runs flush` runs, then every buffered record is appended in `ended_at` order and removed from the buffer. A record that is flushed again after an interrupted flush, or written concurrently from another repo or machine, appears in the store exactly once per `run_id`, and no record is lost.
- **AC-087.9** Given the configured store repo is public, when a run ends, then nothing is written to it, the record is buffered, and the warning says that the store is public and that records are only written to a private repo.
- **AC-087.10** Given an escalation reason, headless command or filed-issue evidence containing a secret (for example `GH_TOKEN=ghp_abc123…` or `Authorization: Bearer …`), when the record is written, then the secret appears as `<redacted>`, exactly as `cplat feedback` redacts it. Records contain no log output, diffs or issue text.
- **AC-087.11** Given `cplat doctor` runs, then the run store check reports:
  - `warn` with the hint `cplat runs init <owner/name>` when no store is configured;
  - `fail` when the configured repo is public;
  - `warn` naming the repo when it is unreachable;
  - `warn` with the buffered record count, the pending filing count and `cplat runs flush` when either is non-zero;
  - otherwise `ok` naming the repo.

  A missing store never makes the overall doctor result `fail`.
- ~~**AC-087.12**~~ withdrawn 2026-10-23: replaced by AC-087.17, which adds causes and filed issues.
- ~~**AC-087.13**~~ withdrawn 2026-10-23: replaced by AC-087.18, which adds the `causes` and `filed` keys.
- **AC-087.14** Given the store holds records of an older `schema`, records with fields or a `kind` the reader doesn't know (sections added by later specs such as 089) and one malformed line, when `cplat runs report` runs, then it succeeds. Unknown fields are ignored, missing fields count as unknown, and the report states how many lines were skipped as malformed.
- **AC-087.15** Given no store is configured, or the store is unreachable, when `cplat runs report` or `cplat runs flush` runs, then it exits non-zero with a message naming the problem and the hint to fix it (`cplat runs init <owner/name>` and the configuration setting, or the repo it could not reach).
- **AC-087.16** Given a ship run, when it is escalated (by `cplat ship escalate <reason>` or by the stop gate giving up), then one record with `outcome` `escalated` and `escalation` holding the reason and its cause is appended. The cause is `unknown` when no cause was given. When the same spec's ship is started again afterwards, it is a new run whose record names the escalated run's `run_id` in `resumes`, so each escalation is counted once.
- **AC-087.17** Given records from several repos in the store, when `cplat runs report` runs, then it shows:
  - runs per kind and outcome;
  - median and 90th-percentile duration per phase;
  - escalations per cause;
  - the top 10 escalation reasons with counts (identical texts grouped);
  - rerun counts by reason and by check name;
  - filed issues per result;
  - the number of locally buffered records not included.

  The default window is the last 30 days; `--since <days>` and `--repo <owner/name>` narrow it.
- **AC-087.18** Given `cplat runs report --json`, then the same aggregates are printed as one JSON document with stable keys (`window`, `runs`, `phases`, `causes`, `escalations`, `reruns`, `filed`, `buffered`) and nothing else on standard output.
- **AC-087.19** Given no store is configured, or the store is unreachable, when records keep ending, then they are kept in the local buffer up to 1000 records. Beyond that, the oldest record is dropped first, and the run's warning line says how many were dropped. Once a store is configured and reachable, the buffered records are flushed per AC-087.8.
- **AC-087.20** Given `cplat runs init <owner/name>`:
  - when the repo does not exist, it is created as a private repo, and the command prints the configuration line to set (`CPLAT_RUNS_REPO=<owner/name>`);
  - when it exists and is private, the command only prints that line;
  - when it exists and is public, the command exits non-zero, changes nothing and says that the store must be private.
- **AC-087.21** Given a run in progress, when a step records or changes an event (for example a merge-conflict event whose outcome moves from `re-planned` to `resolved`, spec 089), then nothing about the run is in the store yet. The record written at run end holds each event once, in its last state.
- **AC-087.22** Given a run that filed an issue or added a +1 comment (spec 088), when its record is written, then `filed` holds the signature, the issue URL and the result. When the filing could not be done, the entry's result is `pending`, and the filing is kept locally with its `run_id`. Each later `cplat runs flush` or record write retries it once. When it succeeds, one follow-up line naming the `run_id`, the signature, the URL and the result is appended, and the report counts that run's filing with its final result. A retried filing is filed or +1'd at most once per run and signature.
- **AC-087.23** Given `cplat fleet update` (spec 096), `cplat retro` (spec 090) or a product ship (spec 097), when it ends, then one record with `kind` `fleet`, `retro` or `product-ship` is appended, with the common fields above and the sections those specs define. For `product-ship`, `spec` is the product spec id and the record lists the `run_id` of each repo ship it drove.

## Non-goals

- The content of the `agents`, `smoke`, `patches` and other later sections; the specs that add them define it (089, 091, 095, 096, 097).
- Classifying escalation causes, computing signatures and filing or deduplicating issues: spec 088. This spec only stores their results and retries pending filings. The weekly retro: spec 090.
- Recording `/svc:spec`, `/svc:plan` or other commands that are not one of the kinds listed above.
- Storing logs, diffs, prompts or transcripts in the record.
- Writing a run's record before the run ends (no start or heartbeat records).
- Dashboards, a web UI, retention or deletion policies for the store.
- A default store repo. Each owner configures their own (`ika100/sdlc-runs` is only an example).

## Open questions

- ~~When no store is configured, should records still be buffered locally?~~ Answered: yes, capped at 1000 with the oldest dropped first, and doctor reports the count; see AC-087.19 and AC-087.11.
- ~~Should there be a `cplat runs init <owner/name>`?~~ Answered: yes; it refuses a public repo; see AC-087.20 and AC-087.11.
- ~~Confirm: recording adds at most 20 seconds to a run.~~ Answered: yes; see AC-087.7.
- ~~Confirm: the report defaults to the last 30 days and the top 10 escalation reasons.~~ Answered: yes; see AC-087.17.
- ~~Confirm: a public store repo is a doctor `fail`.~~ Answered: yes; see AC-087.9 and AC-087.11.
- ~~Confirm: an escalated run ends its record, and a resumed ship is a new run linked through `resumes`.~~ Answered: yes; see AC-087.16.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended: folded in the user's answers (buffer cap of 1000, `cplat runs init`, 20 s bound, 30-day / top-10 report, public store fails doctor, resumed run is linked); added `escalation.cause` and `filed` with retried pending filings for 088, in-place events until run end for 089, and the `fleet`, `retro` and `product-ship` kinds for 090, 096 and 097 (`kind` is open-ended); withdrew AC-087.2, AC-087.12 and AC-087.13 in favour of AC-087.16 to AC-087.18
- 2026-10-23 approved
- 2026-10-24 building
