---
spec_id: 070-headless-runs-resume-until-finished
title: Headless runs resume until finished
status: done
priority: P1
---

# 070 — Headless runs resume until finished

## Problem

A long unattended run ends when its session ends: the context fills up, the time runs out, or the model stops. stock-manager's morning watch (`deploy/watch/run-watch.sh`) shows the pattern the user built by hand: `claude -p` with `--permission-mode dontAsk`, a time limit, a log, a notification. It also shows the risk: it allowlists all of Bash. Nothing in the platform resumes a run in a fresh session or keeps it out of the nightly window that stock-manager's reviews need for the shared subscription.

## Stories

As a founder, I want to start `/svc:ship <spec>` unattended and have it resumed in fresh sessions until it is done or needs me, outside my quiet hours, with a log and a notification.

## Acceptance criteria

- **AC-070.1** Given `cplat headless <prompt>`, when it runs, then each session is `claude -p <prompt> --permission-mode dontAsk` in the repo, so only the repo's committed allowlist applies; a repo without `.claude/settings.json` is refused.
- **AC-070.2** Given a ship run that is unfinished and not escalated when a session ends, when runs are left (`--max-runs`, `--max-minutes` counted from the first session), then the next session starts with the same prompt; an escalated, finished or capped run ends the loop.
- **AC-070.3** Given `--quiet HH:MM-HH:MM` (may wrap midnight), when a session would start inside it, then the run waits for the window to end, or exits with code 3 with `--no-wait`.
- **AC-070.4** Given the end of a run, when it reports, then one `HEADLESS <repo>: <result>` line goes to stdout and to `summary.log` next to the session logs, a desktop notification is sent where available, and the exit code is 0 for shipped or finished, 1 otherwise.

## Non-goals

- Scheduling (launchd, cron, `/schedule`); the guide shows a launchd example.

## Open questions

None.

## References

- [Review of stock-manager, stock-manager-gitops and ai-ops](../../e2e/2026-10-22-review-unattended-delivery.md)
- [ADR-028](../../adr/028-unattended-delivery-without-branch-protection.md)

## Changelog

- 2026-10-22 created from the review of the three lan repos
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
