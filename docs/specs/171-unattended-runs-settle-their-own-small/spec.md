---
spec_id: 171-unattended-runs-settle-their-own-small
title: Unattended runs settle their own small problems
status: done
priority: P1
shape: platform
tracks: [613, 621, 622, 623, 624, 625, 626, 633]
---

# 171 — Unattended runs settle their own small problems

## Problem

The round of specs 167 and 168 and journey 9 (5.16.0) ran mostly unattended, but eight small problems still cost a person's reply, a manual workaround or a long retry. A headless ship cannot run in the platform repo at all: its committed settings have no allowlist, every session is refused `cplat`, and the preflight passes anyway (#621). `ship land` reports "merge conflicts" and suggests an escalation after GitHub already merged the PR, because a local cleanup could not switch to `main` (#622). The merge lock reads an unknown PR head but does not guard the merge with it (#623). `cplat platform pr-check` crashes with a traceback and an auto-filed issue on a body path in a linked worktree (#613). A test-helper fix that changes no assertion was asked of the person, the journey's only stop for one (#624). A resumed repo ship landed without pushing its local commits, judged the old red CI and stopped with "no progress" (#625). Waits started in the background count as stops without progress for the Stop hook (#626). And a conflict confined to the generated backlog index stopped `ship land` twice, each retry costing about 25 minutes of CI (#633). Each has an obvious answer; this spec makes the run take it.

## Stories

As someone shipping unattended, I want a run to settle a problem whose answer is obvious (a missing push, a failed cleanup after a merge, a conflict in a generated file, a test-helper fix) and to stop only on a decision that is really mine, so that my time goes to decisions and not to workarounds.

As the platform maintainer, I want platform specs to ship headless and through the dispatcher like any component repo's, so that the platform is built the way it builds others.

**Repos:** sdlc-foundry (the platform; the behaviour reaches every component and system repo through `cplat` and the plugins).

## Acceptance criteria

Preflight and the platform repo's allowlist.

- **AC-171.1** Given a repo whose committed settings file has no allowlist (no allow rules), or one that allows neither `cplat` commands nor reading the installed plugins, when an unattended run of a covered command (AC-131.8) starts, then no session starts, the run exits 1 with one line `preflight failed: no-repo-allowlist: <the missing rule>` naming the rule to add, and the run is recorded as escalated with cause `environment`, 0 invocations and $0 used (AC-131.11, AC-131.12).
- **AC-171.2** Given the platform repo, when its committed settings file is compared with the allowlist the library template ships, then it holds every allow and ask rule of that template, the repository checks (`devbox run validate` and CI) fail naming each template rule it lacks, and the preflight of `cplat headless "/component:ship <spec>"` in the platform repo passes (a test with a fake session shows no `preflight failed` line).

Landing and merging.

- **AC-171.3** Given `cplat component ship land` or `cplat pr wait --merge` whose merge GitHub accepted (the PR is `MERGED`), when a local step after it fails (switching to or updating `main`, deleting the branch), then the command exits 0 reporting the merge, the ship records it as merged, and each failed step prints one `WARNING:` line naming the step and the git error; no line mentions merge conflicts or `ship escalate`. Given `main` checked out in another worktree, then no step tries to switch to `main` and the command prints no warning for it. The "merge conflicts" fix line appears only when GitHub reports the PR as conflicting with its base.
- **AC-171.4** Given a merge under the repo merge lock (AC-167.7, ADR-089) whose PR head was not known before the lock was taken, when the land step reads the head to judge its checks, then the merge is made only if the PR head is still that commit; a test in which a commit is pushed between the checks and the merge shows that nothing is merged and the land step waits for the checks of the new head.
- **AC-171.5** Given the land phase of a ship, including a resumed repo ship of a system ship, whose feature branch has commits the PR's head lacks, when `cplat component ship land` runs, then it first pushes them the way `cplat component ship pr` does (its local checks, no force, the open PR reused) and judges only the checks of the pushed commit, never those of the old head. If the push is refused, it exits 1 with `local commits not pushed: <n> commit(s) ahead of the PR head` and a `fix:` line naming `cplat component ship pr`, and judges no checks.
- **AC-171.6** Given `cplat component ship land` or `cplat pr wait --merge` whose PR conflicts with `main` only in files `cplat` generates (the backlog index written by `cplat spec index`), when it lands, then it merges `main` into the feature branch, regenerates those files with their generator, commits with sign-off, pushes without force, waits for the checks of the new head and merges when they are green, printing one line that names the regenerated files; after 3 such rounds in one land, or for a conflict that touches any other file, it stops as today with "rebase is a human decision", and the merge attempt that stopped is aborted, so the feature branch holds no half-merged state.

Frozen tests.

- **AC-171.7** Given a test helper of the acceptance tests (a fixture or support file that defines no test) changed since the red commit, with no assertion removed and no criterion id changed, when the build handles it, then the session records it with `cplat spec test-diff $RED --tighten <file> --reason '<why>'` without asking the person, the check accepts it, and the PR's "How this was built" block lists the file, the task and the reason with the tightened tests (AC-165.3); a helper change that removes an assertion, a test or a criterion id is refused by the check and still needs the person.

The Stop hook.

- **AC-171.8** Given the owning session of an unfinished ship run (`/component:ship` or `/system:ship`) that tries to stop while a `cplat` wait it started in the run's checkout is still running (`cplat pr wait`, `cplat system ship next --wait`, `cplat dispatch wait` or another wait of ADR-082), when the Stop hook judges the stop, then it blocks the stop as today, leaves the count of stops without progress unchanged, and the block reason names the running wait (`waiting: <command>; stops without progress: <n>/2`); once no such wait runs, stops count as in AC-126.4 and AC-126.5.

pr-check.

- **AC-171.9** Given `cplat platform pr-check --body-file F`, when F is `.git/PR_BODY.md` in a linked worktree, then it reads the body from that worktree's git dir as the other PR commands do; when F does not exist, is a directory or cannot be read, then it prints one `ERROR: body file <F>: <reason>` line, exits 1, prints no traceback and files no automatic issue.

Tracked issues.

- **AC-171.10** Given `cplat spec new` or any other `cplat` command that takes `--tracks`, when the flag is given more than once (`--tracks 613 --tracks 621`), alone or mixed with several values after one flag (`--tracks 613 621`), then every value is kept: the spec's `tracks:` lists each issue once in the order given, and each of them is claimed for the spec's branch (spec 082); a repeated issue number is kept once.

## Non-goals

- Seeing background subagents from the Stop hook: only `cplat` waits are visible to it, and the prompts keep running subagents in the foreground.
- Resolving a conflict in any hand-written file, rebasing, or force-pushing: these stay a person's decision.
- Changing the allowlists the templates ship, or letting the preflight write any settings file (AC-131.9 holds).
- Conflicts in the assembled changelog: changelog fragments (ADR-078) already avoid them, and the changelog is assembled only by a release.
- A merge lock across machines (spec 167 Non-goals).

## Assumptions

- **A1** The platform repo commits the allow and ask rules of the library template only, not its plugin and marketplace keys, because the platform develops those plugins itself (other option: the whole template settings file; affects AC-171.2).
- **A2** The preflight's minimum for an allowlist is allowing `cplat` commands and reading the installed plugins, the two things every unit session needs before anything else (other option: require the template's full rule list; affects AC-171.1).
- **A3** When `main` is checked out in another worktree, the cleanup after a merge skips switching to `main` silently and never moves that worktree's branch (other option: update the local `main` ref behind that worktree; affects AC-171.3).
- **A4** The land step pushes unpushed local commits itself, with the same local checks as `cplat component ship pr` (other option: refuse and let the session run `cplat component ship pr`; affects AC-171.5).
- **A5** The generated files that may be regenerated in a conflict are a fixed list, today only the backlog index of `cplat spec index`; a new generated file joins by adding it to that list (other option: any file with a "generated" marker; affects AC-171.6).
- **A6** At most 3 regeneration rounds per land, so a busy `main` cannot keep a land looping (other option: bounded only by the budget; affects AC-171.6).
- **A7** A helper fix is listed together with the tightened tests in the PR rather than under a heading of its own (other option: a separate "test helpers changed" list; affects AC-171.7).
- **A8** A running wait holds the no-progress count where it is instead of resetting it to 0, so a session that only waits is bounded by the wait's own timeouts (AC-148.7) and the budget (other option: a running wait counts as progress and resets the count; affects AC-171.8).
- **A9** A repeated `--tracks` adds to the list, keeping first-given order and dropping duplicates, rather than being refused as an error (other option: refuse a repeated flag with a message; affects AC-171.10).

## Open questions

None.

## Changelog

- 2026-11-10 created
- 2026-11-10 amended: AC-171.10 added (a repeated `--tracks` keeps every value; the created spec had kept only the last of eight issues), with A9
- 2026-11-10 approved
- 2026-11-10 building
- 2026-11-10 done
