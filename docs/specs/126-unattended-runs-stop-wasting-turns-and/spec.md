---
spec_id: 126-unattended-runs-stop-wasting-turns-and
title: Unattended runs stop wasting turns and CI rounds
status: draft
priority: P1
shape: platform
---

# 126 — Unattended runs stop wasting turns and CI rounds

## Problem

Escalated ship runs cost more than delivered ones. In the run records of 2026-10-21 to 2026-10-28 (`cplat platform runs report --since 7`, 369 records), 8 delivered ships cost $136 and 32 escalated ships cost $191. 14 escalations came from the Stop hook giving up ("gave up after 8 attempts to stop in phase build/plan/land", 10) or from headless "no progress" (4). The hook pushes a stuck session eight times before it lets go and records the cause `environment` (AC-088.18), although the usual cause is a model that cannot get further. The hook also holds sessions that never started the run, because every session that shares the checkout sees the same run state: one research session was held on a stale run of spec 087, which was already merged. On the CI side, 8 `pr-title` and 7 `spec-required` checks went red in the same week. Both could have been checked before the push, and each red check costs at least one CI round (the median land phase took 20m43s).

## Stories

- As a developer running an unattended ship, I want the Stop hook to let a session go after two pushes that changed nothing, so that a stuck run escalates early instead of spending six more turns.
- As a developer working in a checkout where a ship run is open, I want sessions that did not start the run to stop normally, so that a research question or a second session is never pulled into someone else's run.
- As the platform maintainer reading the weekly retro, I want a stuck-run escalation to name a cause that says who must act, so that the counts per cause show where runs really stop.
- As a developer opening a PR through the platform, I want the PR title rule and the platform's spec rule checked before anything is pushed, so that these rules never cost a CI round.

**Repos:** sdlc-foundry (the platform repo; the stop rules apply in every repo that runs `/component:ship` or `/system:ship`).

## Acceptance criteria

Who the Stop hook holds. A run is **owned** by the session that started it, or by the latest session that resumed it (`/component:ship <spec>`, `/system:ship`, or a session started by `cplat headless` for it).

- **AC-126.1** Given an unfinished ship run owned by session A, when another session B in the same checkout tries to stop (a second session, or a session in a worktree that shares the run state), then B stops without being blocked and the hook prints nothing, and the run's phase, stop counters and escalation stay unchanged.
- **AC-126.2** Given a run owned by session A, when session C resumes it, then C owns the run from then on, A is no longer blocked, and `cplat component ship status` shows the owning session's id.
- **AC-126.3** Given a run state that names no owner (written before this change), when any session tries to stop, then the session is not blocked and the stop prints one line naming the spec, its phase and the command that resumes it.

Progress. A stop of the owning session shows **progress** when the feature branch has a commit that it did not have at the previous blocked stop, or when the run's phase changed since then. The first stop after the run starts or resumes always counts as progress.

- **AC-126.4** Given the owning session tries to stop with progress while the run is unfinished, then the stop is blocked as today, the no-progress count goes back to 0, and the block reason shows `stops without progress: 0/2`.
- **AC-126.5** Given the owning session tries to stop without progress, then the no-progress count goes up by 1. While the count is below 2 the stop is blocked and the reason shows the count (`stops without progress: 1/2`). When it reaches 2, the session is allowed to stop and the run escalates with the reason `no progress: 2 stops in phase <phase> without a new commit or phase change`, followed by up to 200 characters of the session's last message (secrets redacted as in spec 087). No escalation reads `gave up after <n> attempts` any more.
- **AC-126.6** Given an owning session that shows progress at every stop, then the Stop hook never escalates it on a count of stops. The run is limited only by the budget of spec 102 (AC-102.3).
- **AC-126.7** Given a no-progress escalation from the Stop hook (AC-126.5) or from `cplat headless` (two sessions in a row ended in the same phase with nothing changed), then its cause is chosen in this order and recorded with `cause_source` `given`: (a) the cause of the AC-088.16 rule that matches the session's last message, if one matches; (b) `code` if the phase is plan or build and the hook's build status shows criteria without a test or red fast tests, or if the phase is land or deploy and a required check of the PR is red; (c) `decision` otherwise. The cause is never `platform` and never `unknown`. This replaces the `environment` of AC-088.18 for these two escalations.
- **AC-126.8** Given a product ship run (`/system:ship`), then its Stop hook follows AC-126.1 to AC-126.7 in the same way.

Checks before the push. "The PR title rule" is the rule of the platform repo's `pr-title` job (Conventional Commits type, optional scope, subject of 1 to 72 characters). "The spec rule" is the rule of its `spec-required` job (a PR whose body closes an issue and whose diff touches platform code must also touch a spec, or carry the `no-spec` label).

- **AC-126.9** Given `cplat component ship pr` (or the single finishing command of quick-task and fix-bug, AC-100.7) in the platform repo, with a PR body that closes an issue and a diff against the base branch that changes platform code but no spec, when it runs, then it refuses before `devbox run ci` and before anything is pushed, prints the same message as the `spec-required` job, opens no PR, and leaves the run's phase unchanged.
- **AC-126.10** Given the same command run with `--no-spec`, when it opens the PR, then the PR carries the `no-spec` label and the local spec rule passes.
- **AC-126.11** Given any platform command that opens or retitles a PR (ship, quick-task and fix-bug finishing, spec draft PRs, product ship PRs, gitops PRs, cluster repo PRs, platform update PRs), when it runs, then the title it sends satisfies the PR title rule, and a title it builds itself is shortened to fit. For example, the draft PR of a spec whose id and title together exceed 72 characters still gets a valid title. A title given by the caller that breaks the rule is refused before the push, with the rule in the message.
- **AC-126.12** Given `cplat component ship pr` on a branch whose PR is already open under another title, when it runs, then the open PR's title is set to the title that was given and checked.
- **AC-126.13** Given `devbox run ci` in the platform repo on a branch with an open PR, then it checks that PR's title, body, labels and diff with the PR title rule and the spec rule, and fails with the same messages as the CI jobs. Given a branch without an open PR and no title or body handed to it, then both checks print `skipped (no pull request yet)` and do not fail the run.
- **AC-126.14** Given a fixed list of sample titles and PR bodies (valid, invalid, 72 and 73 characters, with and without `no-spec`), then the local checks and the CI jobs reach the same verdict for every sample.

Success measure.

- **AC-126.15** Given the run records of the first 7 days after the release that ships this spec (`cplat platform runs report --since 7`), then no escalation reads `gave up after`, no escalation records a session that did not start or resume the run, the stop-gate and headless no-progress escalations have no cause `environment` unless an AC-088.16 rule matched, and no PR opened by a platform command in the platform repo has a red `pr-title` or `spec-required` check.

## Non-goals

- Changing the budget of spec 102, its equivalent-failure stop (AC-102.9) or the 3-fix-round escalation of `cplat ship`; they stay as they are.
- Red checks of the shape registry, detection and cplat test shards (7 and 9 in the same week). The shape registry already runs in `devbox run ci`; choosing tests for a change is spec 103.
- A spec rule in component repos; that rule belongs to the platform repo only.
- A local PR title check in the `devbox run ci` of component repos; their titles are checked by the platform commands that open the PRs (AC-126.11).
- Deciding with a model whether a session made progress or why it stopped; progress and cause come from fixed rules.
- Blocking or editing PRs that people open by hand with `gh` outside platform commands.

## Open questions

- ~~What counts as progress between two stops?~~ Answered: a new commit on the feature branch or a phase change; uncommitted edits do not count, see AC-126.4 and AC-126.5.
- ~~How many stops without progress before the run escalates?~~ Answered: 2, see AC-126.5.
- ~~Should a session that keeps making progress have a cap on blocked stops besides the budget of spec 102?~~ Answered: no, the budget bounds it, see AC-126.6.
- ~~Which cause does a no-progress escalation get?~~ Answered: the AC-088.16 rule on the last message, else `code` when tests, criteria or a required check are red, else `decision`; this replaces AC-088.18 for these escalations, see AC-126.7.
- ~~Should a session that did not start or resume the run ever be blocked?~~ Answered: never; a run without an owner only prints a one-line notice, see AC-126.1 and AC-126.3.
- ~~Confirm: a session that resumes a run takes it over.~~ Answered: yes, see AC-126.2.
- ~~Confirm: the stop of a non-owning session prints nothing.~~ Answered: yes, see AC-126.1 and AC-126.3.
- ~~How does a run declare the `no-spec` exemption before the PR exists?~~ Answered: a `--no-spec` choice on the PR-opening commands that adds the label when the PR is opened, see AC-126.10.
- ~~Do component repos get the local PR title check in their `devbox run ci` too?~~ Answered: no, see Non-goals.
- ~~Confirm: `cplat component ship pr` retitles an already open PR.~~ Answered: yes, see AC-126.12.

## Changelog

- 2026-10-28 created
- 2026-10-28 amended: folded in the user's answers (all suggested answers: progress is a new commit or a phase change, 2 stops without progress, no cap beyond the budget of spec 102, cause rule replacing AC-088.18 for these escalations, non-owning sessions never blocked and silent, takeover on resume, `--no-spec`, no local title check in component repos, retitle of an open PR); kept as one spec.
