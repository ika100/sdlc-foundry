---
spec_id: 079-cplat-pr-wait
title: 'cplat pr wait: one CI waiter for every PR'
status: done
priority: P1
tracks: [117]
---

# 079 — cplat pr wait: one CI waiter for every PR

## Problem

Outside a ship run there is no tested way to wait for a PR's CI: hand-written loops (one was silent for about 40 min on #111) and stock-manager's `land.sh`. A transient failure (a Maven download) also needs a manual rerun.

## Stories

As anyone landing a PR in the flows, I want one command that waits, heals and merges, so that no CI wait is hand-written.

## Acceptance criteria

- **AC-079.1** Given `cplat pr wait <pr|url> [-R repo]`, when it runs, then it waits with the spec-072 watch (one line per conclusion, the first red check ends it, a stale or stuck run is rerun once), exits 0 on green and 1 on red with the log tail; `--merge` squash-merges on green.
- **AC-079.2** Given a red check whose log tail matches a known transient pattern (artifact download, resolve failure, HTTP 502/503/504, connection reset, TLS timeout), when the watch sees it, then it reruns the failed jobs once (`gh run rerun --failed`) and keeps waiting; a second red is final.
- **AC-079.3** Given `cplat ship land`, when it waits, then it uses the same transient rerun.

## Non-goals

- Required-check configuration.

## Open questions

None.

## Changelog

- 2026-10-22 created from #117
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
