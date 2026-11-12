---
spec_id: 179-unattended-runs-ask-less
title: Unattended runs ask less
status: done
priority: P1
shape: platform
tracks: [616, 653, 654, 655]
---

# 179 — Unattended runs ask less

## Problem

Journeys 9 and 10 (5.16.0, 5.17.0) still asked the person questions whose answer the platform already had. Journey 10's system spec asked for two API replicas, but the system plan carried no gitops task for it, so the ship could not apply it and the coordinator opened a separate gitops PR as a "Decision for you" (#653). The web build's headless session was not allowed to `git rm` three template starter files the feature replaced, stopped, and the coordinator asked and deleted them by hand (#654). A type annotation in a frozen web acceptance test, needed for the type check and changing no assertion, test or criterion id, was put to the person (#655). Across the last round, agent-written acceptance tests contradicted their own spec or design six times (a fixture whose data contradicts its assertion, a pinned message the contract does not define, an entry text that cannot match); each became a stop or an approval because the tests were already frozen. Journey 8 asked the person whether to narrow a dev smoke test whose locator also matched the header's navigation list, though smoke tests are not frozen acceptance tests and tightening one is ordinary build work (#616). And escalations of runs in the platform repo itself were posted as GitHub issues in the public platform repo (#642, #643). This is a consolidation round: no new feature, only fewer questions.

## Stories

As someone shipping unattended, I want a run to apply what the approved spec already decided (instance settings, removing replaced files, a type-only test fix) and to catch contradictory acceptance tests before they freeze, so that a run stops only on decisions that are really mine.

As the platform maintainer, I want escalations of my own platform runs to reach me on the desktop, not as issues in the public repo, so that the issue list holds only what others and the auto-filer report.

**Repos:** sdlc-foundry (the platform; the behaviour reaches every component and system repo through `cplat`, the agents and the plugins).

## Acceptance criteria

System plan and instance settings (#653).

- **AC-179.1** Given an approved system spec with a criterion that states an instance setting `/component:set` can express (replicas, host, resources or an environment variable of a component in an instance), when the system planner writes the plan, then the plan has a task in the gitops repo with `order: before-merge` that sets that value and names the criterion, and `/system:ship` applies it before the component PR merges (AC-076.3) without opening any other gitops PR and without a "Decision for you" about it.
- **AC-179.2** Given a system plan, when its plan check runs, then it refuses the plan if a system criterion names an instance setting key (`replicas`, `host`, `resources`, `env`) and no gitops-repo task names that criterion, printing the criterion id and the key; a plan whose such criteria each have a gitops task passes.

Removing replaced files (#654).

- **AC-179.3** Given an unattended run of a covered command (AC-131.8), when the supervisor prints the run allowlist, then it includes `git rm`, and a session's `git rm <path>` (also `-r`) of a file tracked in the repo succeeds without a permission stop; `git rm` of a path outside the repo or of an untracked file fails as git refuses it, `git rm -f` stays outside the run allowlist, and removing a frozen acceptance test is still flagged by `cplat spec test-diff` and needs the person (spec 165 Non-goals).

Type-only changes to frozen tests (#655).

- **AC-179.4** Given an acceptance test changed since the red commit where every test definition, every assertion line and every criterion id is unchanged and only other lines differ (type annotations, casts, imports), when the build handles it, then the session records it with `cplat spec test-diff $RED --tighten <file> --reason '<why>'` without asking the person, the check accepts it, and the PR's "How this was built" block lists the file, the task and the reason with the tightened tests (AC-165.3); a change that alters an assertion line is not type-only and follows the rules of spec 165 and 171.

Acceptance tests checked before they freeze.

- **AC-179.5** Given a build whose red-tests step has written the acceptance tests, when that step ends and before the tests freeze (AC-169.1), then a review compares each acceptance test with its criterion and the design's contract and reports each contradiction with the test, the criterion id and what contradicts (at least: fixture data that contradicts the test's own assertion, an asserted message or field the contract does not define, an expected text that the specified behaviour cannot produce); with no finding, the tests freeze at once with no further tester round.
- **AC-179.6** Given review findings from AC-179.5, when the build handles them, then the tester (acceptance mode) gets them once, changes only the tests named, and the tests freeze at the commit after that round (the `red-tests` unit is recorded done there, so `cplat spec test-diff` compares against it); the review does not run a second time, and every finding the tester did not resolve is listed in `verification.md` and the PR's "How this was built" block with its test and criterion id.

Loose smoke tests (#616).

- **AC-179.9** Given a build whose review reports a finding on a smoke test (a test outside the frozen acceptance tests, which `cplat spec test-diff` does not cover), for example a locator that also matches elements the feature does not render so the test can pass without the feature, when the build handles the finding, then the tester tightens that smoke test in the build's fix round and the build goes on without asking the person or escalating; the smoke test passes after the change, the PR's "How this was built" block lists the file and the finding, and a finding that names a frozen acceptance test still follows AC-179.4 and spec 165.

Notifications of platform-repo runs.

- **AC-179.7** Given a run in a repo whose shape is `platform` and no notify setting the user wrote for `escalation` on `github`, when the run escalates with cause `code`, `decision`, `environment` or `unknown`, then a desktop notification is sent and no issue or comment is created in any GitHub repo; in a repo of any other shape, escalations are notified as today.
- **AC-179.8** Given a run in the platform repo that escalates with cause `platform` or ends in an internal crash, when it is recorded, then it is filed or +1'd as an auto-filed issue exactly as AC-088.1 and AC-088.4 say (ADR-033); and given the user's notify file sets `escalation` on `github` explicitly, then that setting applies in the platform repo too.

## Non-goals

- Applying an instance setting that no system criterion states, or changing settings of `prod` without its promotion: the planner turns stated criteria into tasks, nothing more.
- `git rm` of files outside the repo, force removal, or any history rewrite; deleting, skipping or loosening an acceptance test stays the person's decision (spec 165).
- The review changing tests itself, or more than one review and fix round before the freeze: the tester owns the tests, and a second round costs a further agent round per build.
- Changing the notify presets of any shape other than `platform`, or the events other than `escalation`.
- A mechanical proof that a change is type-only beyond the line comparison of AC-179.4.

## Assumptions

- **A1** An instance setting in a system criterion is recognised by the setting keys `/component:set` accepts (`replicas`, `host`, `resources`, `env`), matched as words in the criterion text (other option: the planner alone decides, no plan check; affects AC-179.2).
- **A2** The gitops task for an instance setting is `order: before-merge`, so the setting is live when the component change lands (other option: `after-release`; affects AC-179.1).
- **A3** `git rm` is granted as a command; git itself refuses untracked files and paths outside the repo, so the allowlist does not inspect paths (other option: a wrapper command that checks each path; affects AC-179.3).
- **A4** Type-only means the test definitions, assertion lines and criterion ids are textually unchanged (after trimming whitespace); everything else may change (other option: a per-language parse of type syntax; affects AC-179.4).
- **A5** The pre-freeze review is done by the reviewer agent in a test-review mode, inside the build's existing budget (other option: the architect who wrote the contract; affects AC-179.5).
- **A6** Findings go to the tester exactly once; unresolved ones do not block the freeze but are listed for the person in the PR (other option: escalate on any unresolved finding; affects AC-179.6).
- **A7** The platform repo is recognised by `shape: platform` in its committed settings (ADR-056); in it, the default for `escalation` is desktop only, and an explicit user setting still wins (other option: never post escalations from the platform repo to GitHub, whatever the file says; affects AC-179.7, AC-179.8).
- **A8** A smoke-test finding is fixed in the build's existing review fix round, no extra round; if the tightened smoke test then fails, that is an ordinary build failure handled like any other (other option: a separate smoke fix round after verification; affects AC-179.9).

## Open questions

None.

## Changelog

- 2026-11-10 created
- 2026-11-10 approved
- 2026-11-10 amended: tracks #616; added AC-179.9 (a reviewer finding on a loose smoke test is fixed by the build, not asked of the person) and A8
- 2026-11-10 draft: amend: add #616 (loose smoke-test finding fixed by the build)
- 2026-11-10 approved
- 2026-11-10 building
- 2026-11-11 done
