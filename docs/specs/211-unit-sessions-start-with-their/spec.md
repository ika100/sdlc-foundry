---
spec_id: 211-unit-sessions-start-with-their
title: Unit sessions start with their instructions, less bookkeeping
status: building
priority: P1
shape: platform
tracks: [869]
---

# 211 — Unit sessions start with their instructions, less bookkeeping

## Problem

Unit sessions of a headless ship or build (`--unit <unit>`) spend about a third of their model calls on bookkeeping (#869). Each one starts with `cplat shape`, a read of the unit-mode reference, `cplat component ship start --unit`, often a second `ship start`, and `cplat component ship unit`: five calls before any work. Then it reads all of the build instructions (about 16 KB), although a unit needs only part of them. In journey 21 the unit-mode reference was read 33 times and the build instructions 24 times, about 371 k characters of tool results. About 97 % of tokens are cache reads, so everything a session reads early is paid for again on every later turn. The verification unit also records phases, the security gate and the CI budget stage one call at a time, and `cplat spec test-diff` needs a separate `git log` call to find the red commit. Each call removed saves about 50 k tokens. A knowledge-graph alternative was tried and gave no gain, so this is the chosen route.

## Stories

As someone running ships unattended, I want a unit session to get its own instructions from the call that starts it, so that it spends its calls and tokens on the unit's work and not on reading and bookkeeping.

As a platform maintainer, I want the build instructions to stay one source and a test to fail when a unit's slice of them would lose a rule, so that saving tokens never drops a rule without anyone noticing.

As a platform maintainer, I want the saving measured per journey step against journey 22, so that I know it worked and did not cost quality.

## Acceptance criteria

The unit briefing.

- **AC-211.1** Given a ship or build run in unit mode and a known unit (`plan`, `red-tests`, `batch:<ids>`, `task:<id>`, `verification`, `land`), when the unit session runs `cplat component ship start <spec> --unit <unit>` or `cplat component ship unit`, then one output prints, in this order: the shape line that `cplat shape` prints; where the run stands (phase, units done, the next unit), as `ship unit` prints it today; and the unit's **briefing**. The briefing holds the unit's row of the unit table, the permissions paragraph and the "Rules for every unit" of the unit-mode reference, the general rule paragraph of the build instructions (the "Hard rule:" and practice paragraph, the `## cplat` and `## Rules` sections), and the build-instruction sections mapped to the unit (A2), each copied word for word under its own heading. Every `${CLAUDE_PLUGIN_ROOT}` in the briefing is replaced by the plugin's real root, so that every reference file it names can be read as printed. A second such call in the same session prints the same and changes no run state.
- **AC-211.2** Given the build instructions as released, when the briefing of each unit is printed, then it contains exactly the sections of the mapping in A2 and no other build-instruction section; the briefings of `plan` and of `land` in a ship contain no build-instruction phase section. A test prints every unit's briefing and compares its headings with the mapping.

Guards against silent rule loss.

- **AC-211.3** Given the mapping and the build instructions, when the platform's tests and `cplat platform rules check` run, then they fail naming the heading when a mapped heading is missing from the build instructions (renamed or removed), and fail naming the section when a `##` or `###` section of the build instructions belongs to no unit and is not the general part of AC-211.1.
- **AC-211.4** Given a unit's briefing, when the check of AC-211.3 runs, then it fails naming the unit and the reference when the briefing refers to a build-instruction section it does not contain: a reference of the form `Phase <N>`, `Phase <N>'s …`, `as in Phase <N>` or `<N>.<m>` / `<N>.<m>a` (for example "stops as in Phase 2" in the verification slice). A reference counts as contained when the briefing holds that heading.
- **AC-211.5** Given any unit's briefing, when the check of AC-211.3 runs, then it fails naming the unit when the briefing lacks the general rule paragraph, the `## Rules` section of the build instructions, or any bullet of the unit-mode reference's "Rules for every unit".
- **AC-211.6** Given a unit session whose briefing cannot be built (a mapped heading missing at run time, or the instructions unreadable), when `ship start --unit` or `ship unit` runs, then it still prints the shape and where the run stands, prints `briefing unavailable: <reason>; read the build instructions and the unit-mode reference in full`, and exits 0 as it would with a briefing, so that the session goes on. An unknown unit name exits non-zero, naming the known units. Every briefing ends with one line naming the full build instructions as the fallback for a step the briefing lacks. The build instructions and the unit-mode reference stay in place as the single source; the ship and build instructions no longer tell a unit session to read them before it starts, and stay within their recorded size (spec 168).

Less bookkeeping.

- **AC-211.7** Given an active build run (in a ship or a plain build), when `cplat quiet ci` ends green, then the run records the security gate `passed` and the budget stage `ci passed` exactly as `cplat platform runs gate security passed` and `cplat budget stage ci passed` record them, and prints one line saying it did. When it ends red, it records only the budget stage `ci failed` and leaves the gate to the session (the final `gate security failed` after the last round stays the session's call). Without an active build run it records nothing and its output is unchanged. A later explicit call of either command records no second entry.
- **AC-211.8** Given a `building` spec with a commit "acceptance tests for <spec id>" on the current branch, when `cplat spec test-diff` runs without a base (also with `--task`, `--by`, `--tighten` or `--approve`), then it uses the latest such commit as the base, prints `base: <short sha> (acceptance tests for <spec id>)`, and then behaves exactly as with that commit given as the base (the frozen commit of AC-169.1 and the selection of AC-172.1 apply). With no such commit, or more than one `building` spec and a branch that names none of them, it exits 2 without checking, saying so and naming the form `cplat spec test-diff <base>`. A given base behaves as today.
- **AC-211.9** Given a unit-mode build whose sessions run no `cplat platform runs phase` call, when the units `red-tests`, `batch`/`task` and `verification` finish, then the run record holds the markers `build:tests`, `build:implement`, `build:qa`, `build:verify`, `build:image` and `build:close` in this order, each set by the command that starts that phase (A4). An explicit `cplat platform runs phase <marker>` call is still accepted; a marker already set is not set again, and no command moves the run back to an earlier marker.

Measurement.

- **AC-211.10** Given journey 23 (the first journey on a release carrying this spec) measured with `cplat platform runs journey measure --steps`, when its unit sessions are compared with journey 22's (18 unit sessions, about 21 M tokens, 9 to 36 calls each) on the sum over unit sessions per journey step, for the steps both journeys share, then the model calls are at least 25 % lower and the tokens at least 10 % lower, and the escalations, failed verifications and failed test reviews are each no more than in journey 22. Both rows and the per-step comparison are recorded in the platform's performance record. Since run-to-run noise is about 30 %, a token result between −10 % and +10 % is measured on a second journey and the mean of the two counts.

## Non-goals

- Slicing the plan, ship, system or other instructions; only the build instructions and the unit-mode reference are sliced.
- Changing what any unit does, its order, its gates or its stop rules; the briefing is the same text, cut by heading.
- A second copy of any instruction: no slice is stored, every briefing is cut from the build instructions when printed.
- Folding the one-by-one agent records (`cplat platform runs agent spawned <role>`) into other commands; that is a follow-up if the measurement shows it is worth it.
- The interactive (non-unit) ship and build: they keep reading the full instructions.
- A knowledge graph or index of the instructions (tried and rejected).

## Assumptions

- **A1** The briefing comes from both `ship start --unit` and `ship unit`, for ship units and for the units of a unit-mode build alike (other option: only `ship start --unit`, with `ship unit` printing status alone; affects AC-211.1, AC-211.6).
- **A2** The mapping of build-instruction sections to units: every build unit (`red-tests`, `batch`, `task`, `verification`, `land` in a build) gets Phase 0; `red-tests` adds Phase 1; `batch:<ids>` adds Phase 2 with 2.1, 2.2, 2.3, 2.4 and 2.4a; `task:<id>` adds Phase 2 with 2.1, 2.3, 2.4 and 2.4a; `verification` adds 2.5, 2.6 and Phases 3 to 6; `land` in a build adds Phase 7; `plan` and `land` in a ship add none, since they follow the plan and ship instructions (other option: Phase 0 only for `red-tests`; affects AC-211.2, AC-211.3, AC-211.4).
- **A3** A reference that AC-211.4 flags is fixed by adding the section to the unit's mapping or by rewording the reference in the build instructions so it states the rule itself; the check has no allowlist (other option: an allowlist of deliberate cross-references; affects AC-211.4).
- **A4** The commands that set the phase markers: `build:tests` the start of the `red-tests` unit; `build:implement` the start of a `batch`/`task` unit and `cplat component build schedule`; `build:qa` the recorded acceptance gate (`cplat platform runs gate acceptance passed|failed`); `build:verify` the recorded security gate (an explicit call or the record of AC-211.7); `build:image` `cplat spec mutate <id> --write`; `build:close` `cplat spec set-status <id> done` (other option: keep explicit calls for `build:verify`, `build:image` and `build:close`; affects AC-211.9).
- **A5** `cplat quiet ci` records only the green gate itself; a red result records the budget stage but not `gate security failed`, because the session decides after its fix rounds whether the gate stays red (other option: record `failed` on every red run and overwrite on green; affects AC-211.7).
- **A6** `cplat spec test-diff` without a base picks the spec from the branch `feature/<spec_id>`, else the only `building` spec, and refuses with exit 2 otherwise (other option: a required `--spec`; affects AC-211.8).
- **A7** The measurement thresholds: calls at least 25 % lower (bookkeeping is about a third of the calls and removing it does not depend on the run), tokens at least 10 % lower, compared on per-step sums over unit sessions against journey 22, with a second journey when tokens land within ±10 % (other option: tokens at least 20 % lower on a single journey; affects AC-211.10).
- **A8** The guards run in the platform's test suite and in `cplat platform rules check`, so that CI and the pre-PR check both catch them (other option: tests only; affects AC-211.3, AC-211.4, AC-211.5).

## Open questions

None.

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-20 created
- 2026-11-20 priority P1 proposed: P1: normal bug or feature
- 2026-11-20 approved
- 2026-11-21 building
