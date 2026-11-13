---
spec_id: 148-transient-errors-never-stop-a-run
title: Transient errors and slow progress never stop a run
status: done
priority: P1
shape: platform
tracks: [539, 540, 541, 542, 543, 544, 545]
---

# 148 — Transient errors and slow progress never stop a run

## Problem

Journey 5 (2026-11-06, [docs/PERFORMANCE.md](../../PERFORMANCE.md)) stopped five times, three of them on a network that dropped for a minute: `gh repo create` in `cplat system new` (#539), the `--resume` after it, which trusted the local folder and skipped a repo that never reached GitHub (#540), and `gh pr ready` in `cplat spec land`, whose failure then surfaced as a merge conflict (#543). Argo CD's repo-server timed out once and `cplat system wait` waited for an app that the root app would never generate (#542). The system ship's wait for the repo builds ran out three times while the builds progressed (#544). In the run store of the last 14 days, `environment` is the second cause of escalations (25 of 75). Each of these was fixed by hand in the run; the platform retried only `git push` (#500) and GitHub's rate limit (spec 137).

Two smaller findings of the same journey belong here too: the manifest's `owner:` did not set the organisation (#541), and the release's security gate named the wrong audit tool and ran no image scan (#545).

## Stories

As someone running a journey unattended, I want a dropped network, a slow repo-server or a long build to be waited out by the platform, so that a run stops only for something a person has to decide or fix.

## Acceptance criteria

- **AC-148.1** Given a `gh` call or a networked git command (fetch, pull, ls-remote, clone) that fails because the network was down (the request never reached GitHub: `dial tcp`, no DNS, refused), when `core.run` sees the error, then it runs the call again with a growing pause (10 s up to 60 s) for up to 5 minutes in total; an error after the request was sent (a reset, a timeout, a 5xx) is retried only for a call that is safe to repeat (a read, `gh pr ready`, `gh repo edit`, `gh api` as GET or PUT); any other error fails at once, as before.
- **AC-148.2** Given `cplat system new`, when it creates a repo, then `gh repo create` and the push of `main` are two steps; a create that failed although the repo exists now goes on with the push, and a stale `origin` left by a create that never reached GitHub is replaced.
- **AC-148.3** Given `cplat system new --resume` and a repo folder that exists locally, when its GitHub repo is missing or empty, then the repo is created on GitHub and pushed from that folder (topics, protection and settings as for a new repo), and the preview says so; a repo that exists on GitHub with a commit is skipped as before.
- **AC-148.4** Given a system manifest without `org:` whose `owner:` names a GitHub organisation, when `cplat system new` resolves where the repos go, then they go to that organisation; an explicit `--org` or `org:` still wins.
- **AC-148.5** Given `cplat system wait --env E`, when an app is still behind the wanted revision, not generated yet, or the system's root app (`<system>-root`) shows a ComparisonError 45 seconds into the wait, then the wait asks Argo CD once for a hard refresh of those apps and of the root app, says so, and keeps waiting.
- **AC-148.6** Given `cplat spec land`, when marking the draft spec PR ready fails, then it stops with an error that names the draft PR and the GitHub error and does not try the merge.
- ~~**AC-148.7**~~ superseded by AC-194.1 on 2026-11-13: Given `cplat system ship next --wait`, when a running repo's ship reaches a new phase or a new commit, then the wait's timeout starts again (for at most six timeouts in all), and a `TIMEOUT:` line says that no repo made progress for the whole wait.
- **AC-148.8** Given `/component:release`, when its security gate runs, then the security agent names the audit tool the repo's `audit` recipe runs, and runs the image scan when the repo has a `Dockerfile` or reports it as skipped; image findings are reported, not a stop.

## Non-goals

- No retry of a write that may have reached GitHub (`gh pr create` keeps its own retry, `gh pr merge` none).
- No change to the rate-limit wait (spec 137) or the push retry (#500).
- No change to how many re-waits `/system:ship` allows; a re-wait now means no progress.

## Open questions

- ~~How long may a call wait for the network?~~ Answered (recommended, self-approved for the 5.13 round on 2026-11-07 as the user asked): 5 minutes; journey 5's drops lasted 1 to 3 minutes.
- ~~Should `system wait` refresh by itself?~~ Answered: once per wait, after 45 seconds; Argo CD polls git every 3 minutes, so this also shortens a normal deploy wait.

## Changelog

- 2026-11-07 created from the journey 5 findings #539–#545 (strategy round 5.13, item "one retry rule"); approved with the recommended answers, as the user asked for this round.
- 2026-11-07 building
- 2026-11-07 done
- 2026-11-13 AC-148.7 superseded by AC-194.1 (spec 194): one `next --wait` call ends within its timeout; progress returns the `wait` action instead of extending the wait
