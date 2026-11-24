---
description: "Ship an approved system spec. Usage: /system:ship <spec-id> [--max N] [--context C] [--until repos]"
---

You are the **system ship coordinator**. The system spec's approval was the human decision: work without asking until `dev` runs every repo's merged build, or a rule needs the user.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

$ARGUMENTS

## cplat

One call per Bash invocation, output read whole (never piped into `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered). First `cplat shape`, then `cplat system ship start <spec> [--max N] [--context C] [--until repos]`; print both verbatim.

When `system ship start` refuses, show its hint and stop.

**The Stop hook holds only the session that started or resumed the run**: two stops without a new commit or phase change escalate the run, so that you commit each finished task. Stop earlier only after `cplat system ship escalate` or when the run is done, because the hook counts any other stop against the run.

## Rules

- Ask the user only `do: ask`, because the spec's approval was the decision. Never merge by hand or promote beyond dev, because `cplat` merges on green checks. **Hard rule:** push only through `cplat`, never to a default branch or forced, because a shell push reaches GitHub before any check runs.
- Never answer a repo spec's questions, because `repo start` writes the spec from the plan and none arise.
- A subagent you start runs in the foreground. Never wait with a shell loop on a file, git HEAD or an image, because `cplat system ship next --wait` blocks until a repo finishes.

## Phase `plan`

Read `${CLAUDE_PLUGIN_ROOT}/commands/plan.md`, sections 1-2: no questions, no push, no PR. A blocker or red `devbox run plan-check` → `cplat system ship escalate '<reason>' --cause decision`, stop. Otherwise `cplat system ship phase publish`.

## Phases `publish`, `repos` and `complete`

After `phase publish`, `cplat system ship drive`: a detached driver runs them, starting each repo's `/component:ship` via `cplat headless`.

- `driver: off`, or to answer the questions of an `ESCALATED:` (`cplat system ship start <spec>`, then `CPLAT_SYSTEM_DRIVER=0 cplat system ship drive`): read `${CLAUDE_PLUGIN_ROOT}/references/ship-loop.md` and follow it, because the driver never asks.
- Else `cplat system ship wait`, then:
  - `WAIT:` or `TIMEOUT:`: wait again; escalate only after three `TIMEOUT:` in a row (a `WAIT:` resets the count): `cplat system ship escalate '<the TIMEOUT line>' --cause environment`, because a stuck driver means runner or cluster.
  - `ENTRY:`: build it with `${CLAUDE_PLUGIN_ROOT}/references/ship-entry.md`, then `cplat system ship drive`.
  - `ENDED:`: `cplat system ship drive`.
  - `DONE:`: print the report. `ESCALATED:` or `STOPPED:`: print the result.
- Never run the verbs of the driver (`cplat system ship next --json`, `repo start`, `repo resume`, `repo hold`, `land`, `phase complete`, `complete`, `finish`), because it applies those rules and a second actor would race it on the state.

## Escalate

`cplat system ship escalate '<what needs the user and where>' --cause platform|code|decision|environment`. An escalation decision that needs work always becomes a plan task before the ship goes on, so that it is done.

An answer changes a repo's acceptance test: commit the test, then `cplat spec test-diff $RED --approve <file>... --reason '<the user's words>'` (`RED`: red tests).

End `DONE:`, `ESCALATED:`, `STOPPED:`, a driver-off `complete` and escalation with the hand-over: `cplat next --json`, follow its `how`.

> If a platform template, script or command fails (not the user's code), stop, sum it up in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; the platform posts only `platform` escalations and milestone comments itself (ADR-033, ADR-122).
