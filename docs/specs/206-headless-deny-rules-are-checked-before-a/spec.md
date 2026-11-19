---
spec_id: 206-headless-deny-rules-are-checked-before-a
title: Headless deny rules are checked before a session starts
status: done
priority: P1
shape: platform
---

# 206 — Headless deny rules are checked before a session starts

## Problem

An unattended build, ship or system ship passes each session a set of refused rules (spec 131, AC-131.10) so that no session can push to the default branch, force-push or merge outside the land step. In week 2026-W46, 5 runs ended "no progress after two sessions without a commit" and 3 environment escalations ended the same way, over 6 hours of run time, because a refused rule matched more than it was meant to and the session could not do ordinary work. In Claude Code a `*` in a Bash rule matches any text, spaces included, so a rule such as "refuse every `gh api` call that contains `merge`" also refuses a read-only query of a pull request's `mergeable` state. Nothing checks the rules against the commands a run needs before the sessions spend money: the fault shows only after two sessions have stalled.

## Stories

As a person who starts an unattended ship, I want a wrong refused rule to stop the run at once with the corrected rule, so that I do not lose two sessions and hours of run time to a stall.

As a platform maintainer, I want CI to fail when a refused rule over- or under-matches, so that a wrong rule never reaches a release.

## Acceptance criteria

- **AC-206.1** Given an unattended `/component:build`, `/component:ship` or `/system:ship` whose repo has default branch D and run branch B (`feature/<spec-id>`, or `feature/x` for a system ship), when the run starts, then before the first session it checks that no refused rule matches any command of the must-allow sample: `git push -u origin B`, `git push origin B`, `git push origin feature/x-fix`, `git push origin feature/D-page`, `git push --follow-tags origin B`, `git push origin v1.2.0`, `git fetch origin D && git push origin B`, `gh pr create --base D --head B --title t --body-file .pr-body.md`, `cplat pr wait 7`, `cplat pr wait 7 -R acme/shop-api`, `gh api repos/acme/x/pulls/7 --jq .mergeable`, `gh api graphql -f query='{repository(owner:"acme",name:"x"){pullRequest(number:7){mergeStateStatus}}}'`, `git switch -c feature/x-force-field`, `git rm tests/test_x.py`, `git rm -r --cached build`.
- **AC-206.2** Given the same run, when it starts, then before the first session it checks that every command of the must-refuse sample matches at least one refused rule: `git push origin D`, `git push -u origin D`, `git push origin HEAD:D`, `git push origin D:D`, `git push origin B:refs/heads/D`, `GIT_TRACE=1 git push origin D`, `git status && git push origin D`, `git push --force origin B`, `git push -f origin B`, `git push origin B --force-with-lease`, `git push origin +B`, `gh pr merge 7 --squash`, `gh api repos/acme/x/pulls/7/merge -X PUT`, `gh api graphql -f query='mutation{mergePullRequest(input:{pullRequestId:"x"}){clientMutationId}}'`, `cplat pr wait 7 --merge`, `git rm -f x`, `git rm -rf src`.
- **AC-206.3** Given the checks of AC-206.1 and AC-206.2, when a rule is compared with a command, then it matches as Claude Code's permission rules do: a `*` matches any text including spaces, a trailing ` *` or `:*` also matches the bare command, a refused rule matches past a leading variable assignment and the wrappers `timeout`, `time`, `nice`, `nohup` and `stdbuf`, and a refused rule matches a compound command (`&&`, `||`, `;`, `|`) when it matches any one of its parts.
- **AC-206.4** Given a refused rule that matches a must-allow command, when the run starts, then it prints `preflight failed: deny-rules: <rule> refuses "<command>", which the run needs; use: <corrected rule>`, exits 1, starts no session and makes no model call, and the run ends with reason `preflight failed: deny-rules`; the corrected rule passes the whole sample, and where no single rule does the line ends `use: remove the rule`.
- **AC-206.5** Given a must-refuse command that no refused rule matches, or a default branch whose name contains `*`, `(`, `)`, `,` or whitespace, when the run starts, then it prints `preflight failed: deny-rules: no rule refuses "<command>"; add: <rule>` or `preflight failed: deny-rules: default branch "<name>" cannot be guarded by a rule`, exits 1 and starts no session.
- **AC-206.6** Given the refused rules as the platform generates them today, when a session of an unattended run queries a pull request with `gh api repos/<owner>/<repo>/pulls/<n> --jq .mergeable` or a GraphQL query that reads `mergeStateStatus`, then the query is not refused, while every merge command of AC-206.2 still is.
- **AC-206.7** Given the platform's test suite, when it runs in CI, then it performs the checks of AC-206.1 and AC-206.2 for default branches `main`, `master`, `trunk` and `develop` and for both the component and the system ship branches, and a rule that over- or under-matches fails CI with a message naming the rule and the command.

## Non-goals

- Allowing a force push of the run's own feature branch (`--force-with-lease`) after a rebase: AC-131.10 keeps refusing it; landing a branch that conflicts with main is retro item 5.
- Checking deny or ask rules of the user's own settings layers: AC-131.11 already refuses a run that such a rule blocks.
- Guarding pushes written another way (`git -C . push`, a full path to git, `sh -c`): a Bash rule cannot match them (spec 131 limits stay).
- Changing which actions are refused; this spec only makes the existing refusals exact.

## Assumptions

- **A1** Spec 131 (AC-131.10) owns the refused-rule list; this spec adds the startup check, the sample and the `gh api` fix without replacing AC-131.10, because the refused actions stay the same (other option: amend spec 131; affects AC-206.1, AC-206.2, AC-206.6).
- **A2** The over-matching rule fixed here is the one that refuses every `gh api` call containing `merge`; reading the code and tests, the other generated rules match none of the must-allow sample under Claude Code's documented matching, and the sample guards against any further cause the retro data did not name (other option: explore the W46 run logs first; affects AC-206.6).
- **A3** A failed check is a preflight failure with the new category `deny-rules`, in the same line format and exit code as the other preflight failures of AC-131.11 (other option: a separate exit code; affects AC-206.4, AC-206.5).
- **A4** The sample is fixed in the platform and not configurable per repo (other option: a repo may add commands; affects AC-206.1, AC-206.2).
- **A5** The check runs once at the start of a run, before the first session, not before every session, because the rules do not change within a run (other option: before each session; affects AC-206.1, AC-206.2).
- **A6** A tag push (`git push origin v1.2.0`) is in the must-allow sample only to prove that no refused rule catches it; it does not add an allow rule (other option: leave tags out of the sample; affects AC-206.1).
- **A7** CI covers the default branches `main`, `master`, `trunk` and `develop` (other option: `main` only; affects AC-206.7).

## Notes for the architect

- The refused rules and a matcher already exist next to the run allowlist, with an import-time self-check and test lists of refused and fine commands for AC-131.10; the matcher today does not strip leading assignments and wrappers, split compound commands or let a trailing ` *` match the bare command, which AC-206.3 requires.

## Open questions

- ~~AC-206.6 narrows a refused rule: a `gh api` call that contains `merge` but is not a merge request will no longer be refused. Is that acceptable as long as every merge command of AC-206.2 stays refused?~~ Answered (user, 2026-11-17): yes, see AC-206.6.

## Changelog

- 2026-11-17 created
- 2026-11-17 approved
- 2026-11-18 building
- 2026-11-18 done
