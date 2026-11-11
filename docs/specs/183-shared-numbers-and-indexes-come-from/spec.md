---
spec_id: 183-shared-numbers-and-indexes-come-from
title: Shared numbers and indexes come from cplat
status: done
priority: P1
shape: platform
tracks: [659, 660, 477, 577]
---

# 183 — Shared numbers and indexes come from cplat

## Problem

Parallel sessions share numbers and indexes that today are picked or edited by hand, and each seam has already broken. `cplat spec new` looks only at the local specs, so it handed out spec 176 twice while 176 and 177 sat on another session's open PRs (#659). New ADRs and their index rows are written by hand: an architect overwrote the ADR index with one line, and parallel branches conflict at the end of the table (#660). A later spec that replaces a criterion leaves the old one active, so trace, verify and readers check behaviour that no longer holds (#477); in journey 2 the new criterion said "This replaces AC-001.12." in free text, which no step reads, and no prompt tells the spec writers to mark it any other way. And a cplat command whose output is piped into a reader that stops early dies with a traceback, which the platform then files as an issue (#577). This is a consolidation round: no new features, only these seams closed.

## Stories

As a session working next to other sessions, I want `cplat spec new` to hand out a spec number nobody else uses, so that two specs never share a number.

As the architect, I want one command that writes the next ADR and its index row, so that I never hand-edit the shared index and parallel branches do not conflict there.

As a reviewer, I want a criterion that a later spec replaces to be marked superseded, so that trace, verify and "done" count only the behaviour that holds today.

As a user piping cplat output into `head`, I want the command to stop quietly, so that I see no traceback and no issue is filed.

## Acceptance criteria

- **AC-183.1** Given spec numbers in use on main, on any pushed branch (as of the last fetch) and in the files of any open PR, when `cplat spec new` runs, then the new spec gets one more than the highest of all these numbers (with 175 on main and 176, 177 only in open PRs, it creates 178). When open PRs cannot be read, it still creates the spec from main and the branches, and prints one warning line saying open PRs were not checked.
- **AC-183.2** Given a branch that adds a spec whose number another pushed branch or an open PR also adds, when `cplat spec check` runs, then it reports an error naming the number, both spec folders and where the other one lives, and tells to take a new number from `cplat spec new`; a number only this branch uses passes.
- **AC-183.3** Given a repo with ADRs, when `cplat adr add <slug> --decision "<one line>"` runs, then it creates one new ADR from the platform's ADR template with the next free ADR number (the same number `cplat spec adr-next` gives), appends exactly one row with that number, link and decision to the end of the ADR index, leaves every other line of the index unchanged, and prints the new ADR's path. A slug that is not lowercase words joined by hyphens, an empty decision, or a slug an existing ADR already uses exits non-zero with the reason and writes nothing.
- **AC-183.4** Given the architect agent and the commands that write ADRs, when their prompts are read, then they tell to create an ADR with `cplat adr add` and no longer tell to write an ADR file or an index row by hand, `cplat platform rules check` passes, and the total prompt size is not larger than before this spec.
- **AC-183.5** Given a criterion that ends with `(replaces AC-<NNN>.<n>)` naming a criterion of another spec in the same repo, when `cplat spec check` runs while that criterion is still active, then it reports an error naming both criteria and the fix (strike the old one through as "superseded by" the new one); when the named criterion does not exist it reports that as an error; when the old criterion is struck through, the check passes.
- **AC-183.6** Given a criterion struck through as `~~**AC-<NNN>.<n>**~~ superseded by AC-<MMM>.<m> on <date>`, when `cplat spec trace`, verify or the "done" count read the spec, then it counts like a withdrawn criterion (not required, not counted as met or missing), and trace shows it as "superseded by AC-<MMM>.<m>".
- **AC-183.7** Given any cplat command whose standard output goes to a pipe that the reader closes early (for example `cplat shape | head -1`), when the command writes further output, then it exits with status 141 without a traceback or any other output on standard error, and no issue is filed for it.
- **AC-183.8** Given the product-manager and the system planner (which writes repo specs, spec 147), when they write a criterion that changes behaviour an active criterion of another spec in the same repo defines, then their prompts and the spec format reference tell them to end the new criterion with `(replaces AC-<NNN>.<n>)` and, in the same change, strike the old one through as in AC-183.6 with one Changelog line in the old spec; each new prompt rule has an entry in the rules register, `cplat platform rules check` passes, and the total prompt size after this spec's prompt changes (AC-183.4 and this one together) is not larger than before this spec.

## Non-goals

- Reserving numbers by network calls beyond what `cplat spec adr-next` already does (no lock service, no reservation file in the repo).
- Renumbering specs or ADRs that already clash.
- Replacing criteria across repos (a system spec replacing a component's criterion); only specs within one repo.
- Detecting conflicting criteria that carry no `(replaces …)` marker.
- New ADR content rules or a new index format.

## Assumptions

- **A1** A pushed branch counts as of the last fetch; `cplat spec new` does not fetch by itself, like `cplat spec adr-next` (other option: fetch first; affects AC-183.1).
- **A2** When open PRs cannot be read, `cplat spec new` warns and proceeds rather than refusing (other option: refuse; affects AC-183.1).
- **A3** A spec number clash found by `cplat spec check` is an error, matching the ADR clash rule (other option: a warning; affects AC-183.2).
- **A4** In a repo without an ADR index, `cplat adr add` creates the index with its header and the first row (other option: refuse; affects AC-183.3).
- **A5** The prompt change replaces the hand-edit instructions with the command and adds no other text, so the prompt byte baseline does not grow (other option: raise the baseline; affects AC-183.4).
- **A6** A replaced criterion is named by a `(replaces AC-<NNN>.<n>)` marker at the end of the new criterion, and the old one is struck through with "superseded by"; the format reference documents both, and the old spec keeps its status and gets one Changelog line (other option: a front matter list of replaced ids, or reopening the old spec; affects AC-183.5, AC-183.6).
- **A7** An unresolved `(replaces …)` is an error in `cplat spec check`, not a warning (other option: a warning, as #477 suggested; affects AC-183.5).
- **A8** A closed pipe exits with status 141, the shell's code for SIGPIPE (other option: status 0; affects AC-183.7).

- **A9** The writer strikes the old criterion through in the same spec change that adds the replacing one, so the spec approval already passes AC-183.5's check; the old behaviour stays in the code until the new spec ships (other option: strike it through only when the new spec is done, and make AC-183.5 a warning until then; affects AC-183.5, AC-183.8).

## Open questions

## Changelog

- 2026-11-10 created
- 2026-11-10 approved
- 2026-11-10 amended: AC-183.8, the spec writers mark a replaced criterion (#477, journey 2), A9
- 2026-11-10 approved
- 2026-11-11 building
- 2026-11-11 done
