---
spec_id: 207-preflight-checks-trust-and-subagent
title: Preflight checks trust and subagent tools before a ship
status: draft
priority: P1
shape: platform
---

# 207 — Preflight checks trust and subagent tools before a ship

## Problem

An unattended ship, build or system ship runs a preflight before its first session (spec 131): settings layers, git identity, gh login and push access. In week 46, 40 runs still stopped for environment reasons (23 the week before), and the preflight caught none of these stops, because it does not check them. Coder subagents were refused the shell in their worktrees in at least 4 runs, so their work stayed uncommitted. Reviewer subagents, which run on a different model than the coordinator, failed on an API authentication error in 4 runs. Several sessions lost their allow rules in a folder whose trust dialog was never accepted. A dispatcher unit escalated with `gh-auth: gh is not logged in` while gh was logged in a few minutes later, probably because the macOS keychain was still locked. Each of these stops was found only after the run had spent sessions and tokens, and a person had to restart it.

## Stories

As someone shipping unattended, I want the run to refuse to start, with the cause and one fix, when its subagents will not be able to work (no shell in their worktree, a model the account cannot use, a folder whose trust the run depends on), so that I fix the machine once instead of finding a half-done run hours later.

As someone whose machine locks the keychain until it is unlocked, I want a gh login that fails only for a moment to be checked again before the run escalates, so that a dispatcher unit does not stop for a cause that is gone a minute later.

**Repos:** sdlc-foundry (the platform: `cplat headless` and its preflight; the behaviour reaches every repo that runs an unattended ship).

## Acceptance criteria

The new checks. They apply to every covered command (AC-131.8: `/component:build`, `/component:ship`, `/system:ship`) and, for a system ship, also to each repo clone the preflight checks today.

- **AC-207.1** Given a session start folder whose trust dialog Claude Code has not recorded as accepted, when the preflight runs, then it passes only if everything that trust would give the run reaches it another way: the repo's committed permission rules are passed to the session (spec 162), the plugins the repo's committed settings enable are installed on this machine or passed with `--plugin-dir`, and the committed settings set no `env` and no `permissions.additionalDirectories`. It then prints one line `preflight: <folder> is not trusted; its permission rules are passed to the session`. Otherwise it fails with category `untrusted-folder`, naming the setting that would be lost, and the fix `open claude in <folder> once and accept the trust dialog`. The preflight only reads the trust record and never writes it.
- **AC-207.2** Given the run's effective permission rules (managed, user, the repo's committed rules, the run allowlist and the refused rules), when the preflight runs, then each command a coder subagent runs in its worktree is allowed and matched by no deny or ask rule: `cplat component build reset <sha>`, `git add <file>`, `git commit -s -m "<subject>"`, and `devbox run <script>` for each devbox script the plan's tasks name (`devbox run test` when the plan names none). A rule that denies the shell tool as a whole, or denies one of the run's agents (`Agent(<name>)`), counts as a block. A failure has category `subagent-tools` and names the command, the rule and its layer, or the missing allow rule, and the rule to add or remove.
- **AC-207.3** Given the agents a covered command starts that run shell commands (coder, tester, reviewer, security, quality, and the deployment agent where the command uses it), when the preflight runs, then each one resolves to a definition (a repo-level agent definition overrides the plugin's) that grants the shell tool. One that does not fails with category `subagent-tools`, naming the agent, the definition that won, and the fix `add Bash to its tools, or remove the override`.
- **AC-207.4** Given a `/component:build` or `/component:ship`, when the preflight runs, then it creates one git worktree where Claude Code creates agent worktrees, checks that this location lies inside a folder the session may work in (the repo or a folder passed with `--add-dir`), and removes it. Afterwards the repo's worktree list, branches and working tree are exactly as before. A worktree that cannot be created, or that lies outside every such folder, fails with category `agent-worktree`, naming the git error or the location and the fix.
- **AC-207.5** Given the models the run will use (the coordinator model and the model of each agent the command starts, as its winning definition names it), when the preflight runs, then a model that the managed or user settings exclude (an `availableModels` list without it, or a `deniedModels` list with it) fails with category `model-unreachable` without any model call, naming the model, the agents that use it, the setting and its layer, and the fix.
- **AC-207.6** Given models that pass AC-207.5, when every other check has passed, then the preflight makes one minimal model call per distinct model, never more than one per model. A call that fails with an authentication or access error fails with category `model-unreachable`, naming the model, the agents that use it, the error's last line and the fix (`claude /login`, or a model the account may use). A call that fails for want of a network is retried as the gh checks are, and then fails with `could not reach the model API (<error>): check the network, then run again`. A model whose call passed on this machine with the same credentials within the last 60 minutes is not called again. These calls are not counted as invocations or in the run's budget (AC-131.12 still shows 0 invocations and $0), and their tokens are recorded in the run's log under `preflight`.

Checks that pass on the second try.

- **AC-207.7** Given `gh auth status` reports that gh is not logged in for the repo's host, when the preflight runs, then it tries again 15 and then 30 seconds later, so it waits no more than 45 seconds in all. If a later try passes, the check passes and prints `preflight: gh login answered on try <n>`. If all three fail, it fails with category `gh-auth` and the detail `gh is not logged in for <host> (3 tries over 45 s): gh auth login --hostname <host>`. On macOS the detail adds `; if gh is logged in, unlock the login keychain`.

How a failure looks and is recorded.

- **AC-207.8** Given any check of this spec fails, then the outcome is the one AC-131.11 and AC-131.12 give the existing categories. No session starts. The run exits 1 with one line `preflight failed: <category>: <cause>: <fix>`. It is recorded as escalated with cause `environment` and reason `preflight failed: <category>`, and a dispatcher unit's result carries cause `environment`. No settings file and no trust record is created or changed (AC-131.9). The checks run in this order, and the first failure wins: the existing checks, then AC-207.1, AC-207.2, AC-207.3, AC-207.4, AC-207.5 and AC-207.6, so that only a run whose other checks all passed makes a model call.

## Non-goals

- Recording trust for a folder, or writing Claude Code's own config file: cplat never accepts a trust dialog on the person's behalf.
- Credentials that expire or are revoked during a run. The preflight checks them once, at the start.
- Claude Code's own worktree guard, which refuses a git command when it cannot see that the command stays inside the worktree (`cd <path> && git ...`, `git -C <main checkout>`). That is a matter for the coder's instructions, not for a preflight check.
- Retrying checks other than the gh login and the model call. A missing allow rule or a deny rule does not go away on its own.
- Running these checks from `cplat platform doctor` or from interactive (non-headless) sessions.
- The other environment causes in the week 46 retro (the push-to-main deny pattern, item 3): another spec.

## Assumptions

- **A1** A failure keeps today's one-line format `preflight failed: <category>: <cause>: <fix>`, with the fix after the last colon (other option: a second line `fix: <command>`, which would change AC-131.11's one line; affects AC-207.1–AC-207.8).
- **A2** The new categories are `untrusted-folder`, `subagent-tools`, `agent-worktree` and `model-unreachable`. A missing gh login stays `gh-auth` (other option: one category `subagent` for AC-207.2–AC-207.4; affects AC-207.1–AC-207.7).
- **A3** The coder commands checked are `cplat component build reset <sha>`, `git add <file>`, `git commit -s -m "<subject>"` and the devbox scripts the plan names, falling back to `devbox run test` (other option: only the git commands; affects AC-207.2).
- **A4** The model check makes one minimal call per distinct model, cached for 60 minutes per machine and credentials. It is not charged to the run's budget, so AC-131.12's $0 holds (other option: a static check only, with no call, which would not have caught the 4 authentication errors; affects AC-207.6).
- **A5** The gh login is tried 3 times, 15 and 30 seconds apart (45 s at most), and only a "not logged in" answer is retried this way. A network error keeps today's retry (other option: 5 tries over 2 minutes; affects AC-207.7).
- **A6** The worktree probe runs only for `/component:build` and `/component:ship`, the commands with parallel coder batches (other option: also for `/system:ship` repo clones; affects AC-207.4).
- **A7** The subagent and trust checks also run for each repo clone of a system ship, like the existing allowlist and settings checks (`check_repo`). The model call runs once per run (other option: only the start folder; affects AC-207.1–AC-207.3, AC-207.6).
- **A8** In an untrusted folder, the plugins count as available when they are installed on the machine or passed with `--plugin-dir`, because a committed marketplace entry is ignored without trust (other option: require trust whenever the repo declares a marketplace; affects AC-207.1).

## Notes for the architect

- The trust record is per folder in Claude Code's own config file in the home folder. Read it, never write it (spec 162 Non-goals).
- Without trust, Claude Code ignores these keys of the committed settings: `permissions.allow`, `permissions.additionalDirectories`, `extraKnownMarketplaces` and most `env` values. `deny` and `ask` rules apply anyway, and `--settings` applies regardless of trust (Claude Code settings docs). Every template's committed settings declare a marketplace, which is why A8 matters.
- Before building AC-207.2, check the logs of the 4 week-46 runs whose coders were refused the shell. Find out whether the refusal came from a permission rule (which this spec catches) or from Claude Code's worktree guard (Non-goals), so that the criterion targets the real cause.
- The existing gh call retries a dropped network (`_retried`). The new retry covers only the "not logged in" answer.

## Open questions

- May an unattended run start in a folder whose trust dialog was never accepted? (suggested: yes, when everything trust would give reaches the run another way, as AC-207.1 states, so spec 162's fresh clones keep working; refuse otherwise; cplat never records trust itself; affects AC-207.1, AC-207.8)

## Changelog

- 2026-11-17 created
