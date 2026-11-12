---
spec_id: 184-parallel-ships-do-not-stop-each-other
title: Parallel ships do not stop each other
status: done
priority: P1
shape: platform
tracks: [663, 666, 670, 671]
---

# 184 — Parallel ships do not stop each other

## Problem

The consolidation round of 2026-11-10 (specs 178, 179, 181, 182) ran four `cplat headless` ships in one repo at once, and most of its stops were caused by the ships, not by the work. All four hit the subscription's usage limit in the same minute. Every `claude -p` session then ended at once with no output, and each unit escalated as "no progress". After the reset, a resumed unit committed and still escalated, because the empty sessions from the pause were counted. The overnight pause also used up a run's `minutes` budget (#663). One ship's tests starved another ship's `devbox run ci` of processes (#671). Each merge into `main` made the next land stop on a conflict in the ADR index, five times. Once two specs both took rule id R14 (#670). Spec 182's land went red on a template lint error that `devbox run ci` had not checked. CI hid the violation behind `-q`, and the land session was not allowed to read its own CI logs, so it escalated without a diagnosis (#666). A verification step written in spec 178 (`TEST_FAKE_DELAY=2 devbox run test-fast`) was refused because of its environment prefix. Each of these has an obvious answer. This spec makes the run take it, so that the next round runs without these stops.

## Stories

As someone shipping unattended, I want a run that hits the usage limit to wait for the reset and continue by itself, so that a pause in the environment never becomes an escalation or uses up my budget.

As someone shipping several specs, I want a second ship in the same repo to wait for the first one instead of running alongside it, and I want a land to settle index conflicts by itself, so that parallel work does not stop on conflicts, starved processes or a shared limit.

As someone reading an escalation, I want a red land to have read its own CI logs and a template lint error to be found before the pull request, so that a one-line fix never reaches me as an undiagnosed red check.

**Repos:** sdlc-foundry (the platform; the behaviour reaches every component and system repo through `cplat` and the plugins).

## Acceptance criteria

Usage limit: a pause, not a stop.

- **AC-184.1** Given a `cplat headless` run whose session prints the CLI's usage-limit message with a reset time (as a Unix time after `|`, or as `resets <time>`), when the session ends, then the run prints one line `paused: usage limit, resumes at <local time>` and starts no session before that time plus 1 minute. It then starts the same unit (or, outside unit mode, the same prompt) again and continues. The run is not escalated, and its exit code and result are those of the rest of the run.
- **AC-184.2** Given a session that ends within 60 seconds with no output at all, or with the usage-limit message without a reset time, when the run handles it, then it pauses as in AC-184.1 for 5, 10, 20, 40 and then 60 minutes between tries, printing `paused: usage limit, next try at <local time>`. Once the pauses of one run would exceed 360 minutes in total, or a given reset time lies beyond that, the run starts no further session. It exits 1 with `environment pause: usage limit resets at <time or "unknown">`, is recorded as escalated with cause `environment`, and running the same command again continues it.
- **AC-184.3** Given a run with sessions that ended in a usage-limit pause (AC-184.1, AC-184.2), when its limits are judged, then those sessions do not count as stops without progress or as invocations, and the pause time does not count against the budget's `minutes` or `--max-minutes`. Given a unit with sessions without a commit before the pause, when a later session of that unit ends with a checkpoint, then the count of sessions without progress is 0 again. A test with a fake `claude` reproduces the 179 case (two empty sessions, then a checkpoint) and the run continues to the next unit.

Land diagnosis and template lint.

- **AC-184.4** Given a `/component:ship` or `/system:ship` run, when its run allowlist is printed and passed to the sessions (`cplat headless --dry-run` shows it), then it allows reading the failed-check logs `cplat` saved for this repo (spec 108) and `gh run view <id> --log-failed` with or without `-R <owner/repo>`. It allows no other `gh run` or `gh api` command (no rerun, cancel, delete or watch), and the refused rules stay as before.
- **AC-184.5** Given a branch that changes files of one or more templates, when `devbox run ci` runs, then for each changed template it renders a project with the template's defaults and runs the lint that template's smoke job runs in CI. A lint violation makes `devbox run ci` fail, and its output names each violation's file, line and rule (for Checkstyle, e.g. `ConstantName`), not only a count. The CI smoke jobs print the same lines. A branch that changes no template renders none.

Index conflicts on land.

- **AC-184.6** Given a land that catches up with `main` (AC-178.4) and whose merge of `main` conflicts in the ADR index, when it lands, then it writes the index as the union of both sides' rows sorted by ADR number. If the branch adds an ADR whose number `main` already uses for another ADR, it renumbers the branch's ADR to the next free number from `cplat spec adr-next` (spec 183): file name, title, index row, and every reference to it in the files the branch changed. It then commits with sign-off, pushes without force, waits for the new head's checks as in AC-178.2, and prints one line per file, e.g. `renumbered ADR-095 to ADR-097 (3 references)`.
- **AC-184.7** Given a land as in AC-184.6 whose merge of `main` conflicts in a prompt's rule register file (`docs/rules/**.yml`), when it lands, then it keeps the entries of both sides. An id the branch added that `main` uses for a different entry is renumbered to the next free `R<n>` in that file, together with every reference to it in the files the branch changed, and `cplat platform rules check` passes on the result. A conflict in any other file, or in a part of a register file that is not an id-keyed entry (such as the baseline), stops the land as today ("rebase is a human decision") with the merge aborted. The rounds of AC-171.6, AC-184.6 and this criterion share its limit of 3 per land.

One ship at a time per repo.

- **AC-184.8** Given a `cplat headless` run in a repo where as many runs already hold a slot as the repo allows (`slots` in `.platform/dispatch.yml`, else 1), counting every worktree and clone of that repo on the machine, when the second run starts, then it starts no session and prints `waiting for a slot: held by <command> (pid <pid>, since <time>, <checkout>)`. It starts within 60 seconds after the holder ends. With `--no-wait` it instead exits 1 with `slot busy: held by <command> …`. A slot whose holding process no longer runs is freed with the line `freed a stale slot of <command> (pid <pid> gone)`. Time spent waiting does not count against the run's budget, and `--dry-run` takes no slot.
- **AC-184.9** Given a repo with a dispatcher policy and a manual `cplat headless` run that holds a slot, when a dispatch cycle runs, then it counts that run against `slots`: it starts no unit while all slots are taken, and `cplat dispatch plan` and `status` show the slot as `held by <command> (manual)`. A test with a fake headless shows no two runs in one repo overlapping beyond `slots`.

Verification commands with an environment prefix.

- **AC-184.10** Given a ship or build whose spec folder's plan or design names a command of the form `NAME=value [NAME=value …] devbox run <script> [args]` (e.g. `TEST_FAKE_DELAY=2 devbox run test-fast`), when the run starts, then its run allowlist allows exactly that command, so the unit runs it without a refusal or an escalation. A command written that way is not added, and the allowlist block lists it as `not allowed: <command>`, when another program follows the prefix (e.g. `FOO=1 sh -c …`), when it chains or substitutes (`;`, `&&`, `||`, `|`, `$(`, backticks), or when a name is not uppercase or is a refused name: `PATH`, `HOME`, `SHELL`, `ENV`, `BASH_ENV`, `NODE_OPTIONS`, `PYTHONPATH`, or any name starting with `LD_`, `DYLD_`, `CPLAT_`, `GIT_` or `GH_`.

## Non-goals

- A central scheduler across repos or machines, and slots across machines; the slot holds for the worktrees and clones of one repo on one machine, like the merge lock (spec 167).
- Predicting or spreading the usage limit across repos (counting concurrent sessions machine-wide); this spec only survives the limit.
- Resolving a conflict in any hand-written file, rebasing or force-pushing (spec 171 Non-goals hold).
- Renumbering spec numbers on land; spec numbers come from `cplat spec new` (spec 183).
- Limiting a test run's processes or memory; the slot keeps ships apart, nothing more.
- Raising the prompt byte baseline (spec 180): any prompt change of this spec fits in the recorded size.
- Allowing environment-prefixed commands other than `devbox run`, or commands the spec does not name.

## Assumptions

- **A1** A session counts as a usage-limit pause when it prints the usage-limit message, or when it ends within 60 seconds with no output at all (other option: only the message; affects AC-184.1, AC-184.2).
- **A2** After a given reset time the run waits 1 more minute. Without a reset time it backs off 5, 10, 20, 40 and then 60 minutes (other option: a fixed 30 minutes; affects AC-184.1, AC-184.2).
- **A3** The pauses of one run are capped at 360 minutes in total. A reset time beyond the cap stops the run at once with cause `environment` instead of waiting (other option: wait for any reset time; affects AC-184.2).
- **A4** Paused sessions count neither as stops without progress nor as invocations, and the pause time is excluded from `minutes` and from `--max-minutes` (other option: exclude it from `minutes` only; affects AC-184.3).
- **A5** A checkpoint resets the count of sessions without progress to 0, in unit mode and in the legacy loop alike (other option: unit mode only; affects AC-184.3).
- **A6** The land session may read only the logs `cplat` saved for this repo and `gh run view --log-failed`. It may not rerun or cancel runs, which stays with `cplat` (other option: also `gh run rerun --failed`; affects AC-184.4).
- **A7** `devbox run ci` lints only the templates the branch changes, rendered with their defaults, through the same lint the smoke job runs (other option: every template on every run; affects AC-184.5).
- **A8** On land, a clashing ADR number or rule id is always the branch's to change, never `main`'s. ADR numbers come from `cplat spec adr-next`, and rule ids are the next free `R<n>` in the same register file (other option: stop and ask on any clash; affects AC-184.6, AC-184.7).
- **A9** Every `cplat headless` run except `--dry-run` takes a slot, fixes included, because they share the usage limit, the machine and `main` (other option: only ships and builds; affects AC-184.8).
- **A10** The slot count is the `slots` key of `.platform/dispatch.yml`, else 1, with no extra flag. A waiting run waits without a time limit unless `--no-wait` is given (other option: a `--slots` flag, and a wait timeout; affects AC-184.8, AC-184.9).
- **A11** The slot is shared by every worktree and clone of the same repo on the machine, keyed like the merge lock (other option: per clone; affects AC-184.8).
- **A12** Environment-prefixed commands are taken from the spec folder's plan and design, written in backticks, and allowed only verbatim (other option: any `NAME=value devbox run <script>` pattern; affects AC-184.10).

## Open questions

- ~~Which variable names may an environment prefix not set, given that the plan is written by an agent and an unattended session will run the command?~~ Answered 2026-11-11: refuse `PATH`, `HOME`, `SHELL`, `ENV`, `BASH_ENV`, `NODE_OPTIONS`, `PYTHONPATH` and every name starting with `LD_`, `DYLD_`, `CPLAT_`, `GIT_` or `GH_`; any other uppercase name is allowed, see AC-184.10.

## Changelog

- 2026-11-11 created
- 2026-11-11 amended: open question answered; the refused environment-prefix names are folded into AC-184.10
- 2026-11-11 approved
- 2026-11-11 building
- 2026-11-11 done
