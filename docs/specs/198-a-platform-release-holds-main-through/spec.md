---
spec_id: 198-a-platform-release-holds-main-through
title: A platform release holds main through the merge lock
status: draft
priority: P1
shape: platform
---

# 198 — A platform release holds main through the merge lock

## Problem

A platform release tests the release pull request against `main`, merges it, runs the upgrade e2e on the merge commit and
tags it. Any other merge into `main` in that window invalidates the work: the release stops with "main moved", or the
upgrade e2e on the merge commit is cancelled by the newer push. On 2026-11-13 the 5.21.0 and 5.22.0 releases had to be
restarted or have their benchmarks rerun twice, because a spec doc PR and then spec 189's land unit merged after the
release PR opened. Keeping `main` still was agreed only by chat between sessions, and `cplat dispatch pause` does not stop
a land unit that is already running. Every merge cplat makes already goes through the machine-wide merge lock (ADR-089),
so that lock is the place to hold `main` for a release.

## Stories

As the person releasing the platform, I want every cplat merge into the repo to wait while my release runs, so that the
release does not have to start over because `main` moved.

As a session or dispatcher unit landing a change, I want to see what my merge waits for and have it continue by itself
once the release is done, so that I neither fail nor have to retry by hand.

As the person running the dispatcher, I want `cplat dispatch status` to show a release hold, so that I know why land units
are not merging.

## Acceptance criteria

- **AC-198.1** Given a repo with no release hold, when `cplat platform release` (without `--dry-run`) begins its checks, then before the first check it sets a release hold on the repo's merge lock recording the release version, the start time and its own process, and prints `release hold set on <owner>/<name> for <version>`; if a merge is inside the merge lock at that moment, the release first waits for that merge to end, printing `waiting for the merge of <who> to end before the release`. A `--dry-run` sets no hold.
- **AC-198.2** Given a release hold set by another process, when any cplat merge into that repo reaches its merge (`cplat component ship land`, `cplat dispatch land`, `cplat pr wait --merge`, a system ship's merge), including one that started before the hold was set, then it does not merge, prints `waiting for the release hold of <owner>/<name>: release <version> since <YYYY-MM-DD HH:MM>` when it starts waiting and again every 60 seconds, and the time it waits does not count against its own timeout, so the wait never ends as a timeout, a red check or an escalation.
- **AC-198.3** Given a merge waiting for a release hold, when the hold is cleared or expires, then the merge continues by itself within 30 seconds, printing `release hold of <owner>/<name> cleared` (or `expired`), and merges as it would have without the hold, including bringing a branch that is now behind `main` up to date and waiting for its checks again.
- **AC-198.4** Given a release that holds the repo, when that same release merges its own release pull request, then its merge is not held by its own hold.
- **AC-198.5** Given a release holding the repo, when the release ends by pushing the tag, by an error, or by being interrupted (Ctrl-C), then the hold is cleared before the command exits and it prints `release hold cleared`.
- **AC-198.6** Given a release that stops at `CONFIRM: merge` or `CONFIRM: tag` (exit 3), then the hold stays set, the stop output names the time it expires (2 hours after the stop), merges keep waiting until then, and a later `cplat platform release` run (with or without `--confirm`) takes the hold over, ties it to its own process and lifts the expiry; once it has expired, waiting merges continue (AC-198.3).
- **AC-198.7** Given a release hold whose process is no longer running and which is not at a confirmation stop (for example the release was killed), when a merge or a new release checks the hold, then it treats the hold as cleared, removes it and prints `release hold of <owner>/<name> dropped: process <pid> is gone`; given a hold whose process is still running, a second `cplat platform release` in the same repo stops with an error naming the holding version and process, and changes nothing.
- **AC-198.8** Given a repo, when the user runs `cplat platform hold`, then it prints the hold (version, since, process, `running` or `stopped at confirm merge|tag`, and the expiry when stopped) or `no release hold on <owner>/<name>`, and `--json` prints the same as one object (`null` when there is none); with `--clear` it removes the hold, prints `release hold of <owner>/<name> cleared by hand`, and waiting merges continue (AC-198.3).
- **AC-198.9** Given a release hold on the repo, when the user runs `cplat dispatch status`, then the text output shows a line `release hold: <version> since <YYYY-MM-DD HH:MM>` (with `stopped at confirm merge|tag, expires <time>` when stopped) and `--json` has a `release_hold` object with `version`, `since`, `pid`, `state` and `expires`; without a hold the line is absent and `release_hold` is `null`.

## Non-goals

- Merges made outside cplat (by hand on github.com, `gh pr merge` directly) or from another machine: the hold is machine-local, like the merge lock (ADR-089).
- Releasing from a short-lived release branch cut at a fixed commit, so that `main` never freezes: a later option.
- Stopping the dispatcher from starting, building or opening pull requests during a release: only merges wait.
- A release hold for component or system repos' own releases: only `cplat platform release` sets it.

## Assumptions

- **A1** At a confirmation stop the hold survives the exit for 2 hours after the stop, then expires; running the release again takes it over and lifts the expiry (other option: no expiry, cleared only by hand; or 24 hours; affects AC-198.6).
- **A2** "Declined" means the user does not confirm at a stop; since the stop ends the process, a decline clears the hold through `cplat platform hold --clear` or the expiry (other option: a `--decline` flag on the release; affects AC-198.6, AC-198.8).
- **A3** The time a merge waits for a release hold does not count against its timeout, so a land never fails because a release ran (other option: count it, ending as the retryable merge-lock timeout; affects AC-198.2).
- **A4** The hold is checked at the moment of the merge, inside the merge lock, so runs started before the release are covered; when the release sets the hold it first lets a merge already inside the lock finish (other option: cancel that merge; affects AC-198.1, AC-198.2).
- **A5** The show and clear command is `cplat platform hold [--clear] [--json]` (other option: a subcommand of `cplat dispatch`; affects AC-198.8).
- **A6** Times are shown as local `YYYY-MM-DD HH:MM` because a hold can span hours (other option: `HH:MM:SS` as the merge lock prints; affects AC-198.2, AC-198.9).
- **A7** A second release while a live release holds the repo is refused, not queued (other option: wait for the first; affects AC-198.7).

## Open questions

None.

## Changelog

- 2026-11-14 created
