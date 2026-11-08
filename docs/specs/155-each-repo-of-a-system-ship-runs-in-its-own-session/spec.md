---
spec_id: 155-each-repo-of-a-system-ship-runs-in-its-own-session
title: Each repo of a system ship runs in its own session
status: approved
priority: P1
shape: platform
tracks: [560]
---

# 155 — Each repo of a system ship runs in its own session

## Problem

`/system:ship` runs every component repo's ship as a subagent of the gitops session (`plugins/system/commands/ship.md`, phase `repos`). A subagent cannot start subagents, so a repo's ship inside a system ship is not the ship that `/component:ship` runs on its own:

- its coders run one after another even where the plan marks tasks `parallel_safe` (#560: "Coder implements t2 (sequential)");
- it runs in one long context instead of unit mode's fresh session per unit (spec 131), so every turn rereads the whole repo ship;
- its architect, tester and reviewer run inline in the same context.

In journey 6 the step "Plan and ship it to dev" took 51 of 164 minutes and 21.7 of 40.3 M tokens. The cause is structural, not specific to that system: it applies to every system ship with at least one component repo, of any shape or language.

## Stories

As someone shipping a system spec, I want each repo's part to be built exactly as `/component:ship` builds a repo on its own, so that a system ship is as fast and as cheap per repo as the component route, and independent repos are built at the same time.

## Acceptance criteria

- **AC-155.1** Given `/system:ship` with a component repo whose dependencies have passed, when the scheduler starts it, then cplat writes and approves the repo spec from the plan (`cplat spec new --from-plan`, spec 147) and starts `cplat headless "/component:ship <repo spec>"` for that clone as its own process, linked to the gitops repo. It records the process and its log path in the system ship state. The gitops session starts no subagent for a component repo.
- **AC-155.2** Given a plan with repos that do not depend on each other, when they are ready, then their headless ships run at the same time, up to `--max` (default 3); a test with a fake `headless` shows the runs overlapping. A repo starts only after every repo it depends on has passed, as today.
- **AC-155.3** Given a repo ship started by a system ship, when it runs, then it uses the same code path as a standalone `/component:ship`: unit mode (spec 131) and the coordinator model and budget rules of `cplat headless`. Nothing in a component ship depends on whether a system ship started it, except the link to the gitops repo. (Amended 2026-11-08: unit mode runs a repo's tasks one after another, so concurrent coders are spec 157's, not this spec's.)
- **AC-155.4** Given the gitops session in phase `repos`, when it waits, then `cplat system ship next --wait` reads each running repo's ship state and whether its process is alive. It reports a finished repo through `repo result` as today. A commit or phase change in any repo counts as progress for the wait and for the Stop hook (spec 148).
- **AC-155.5** Given a repo whose headless process ended while its ship is neither finished nor escalated (a crash, a closed laptop, a killed process), when the wait sees it, then the scheduler starts it once more, resuming from disk. A second such end escalates the repo with cause `environment`, naming the log path.
- **AC-155.6** Given a repo ship that ends with open questions or escalates, when the wait records it, then the repo is escalated with the reason and questions verbatim (cause from the repo ship). Repos already running finish, nothing new starts, and `/system:ship <spec>` resumes the run as today.
- **AC-155.7** Given one system ship, when its repo sessions run, then they share the system ship's budget (spec 102) instead of each getting a fresh one. Every session's usage is recorded in the run store under the system ship's run, so `cplat platform runs` and the journey measurement count each token once.
- **AC-155.8** Given several repo ships that reach the merge at once, when they merge, then they go through the existing merge slot one at a time, and a repo's dev pin follows the joint-run rules of spec 144 unchanged.
- **AC-155.9** Given `--max 1`, or a plan in which every repo depends on the previous one, when the system ship runs, then it runs the repos one at a time with the same results. Tests cover one repo, three independent repos, and a diamond (two repos depending on one, a fourth depending on both).
- **AC-155.10** Given this change, when it ships, then the subagent-per-repo instructions are removed from `plugins/system/commands/ship.md` (one path, not two). `docs/AGENTS.md` describes the new process model, and an ADR records why a repo ship runs as its own session rather than as a subagent.

## Non-goals

- The gitops entry repo: the gitops session still builds it in its worktree, because it is the session's own repo.
- The land phase of a joint run (spec 144) and anything after dev.
- Several processes working in one clone: one repo, one clone, one ship.
- Remote or cloud sessions: the repo sessions run on the same machine as the gitops session.

## Open questions

- ~~Should `--max` keep its default of 3?~~ Answered (recommended, approved 2026-11-08): keep 3. A local machine runs three repo sessions without trouble, and `--max` stays the knob.
- ~~Gitops session's coordinator model or the repo's own?~~ Answered (recommended, approved 2026-11-08): the repo's own (`.platform-settings.yml`, else the user default), as a standalone `/component:ship` would. AC-155.3 asks for the same behavior.

## Changelog

- 2026-11-08 drafted from #560 and the journey 6 analysis; approved as recommended on 2026-11-08.
- 2026-11-08 AC-155.3 amended with the user's approval: the first benchmark run showed that unit mode runs a repo's tasks one after another, so concurrent coders move to spec 157.
