---
spec_id: 188-explore-a-feature-before-its-spec-is
title: Explore a feature before its spec is written
status: building
priority: P1
shape: platform
tracks: [662]
---

# 188 — Explore a feature before its spec is written

## Problem

`/component:spec` and `/system:spec` start writing a spec as soon as they are called. When a person wants to think a feature through first (read the code, compare options, sketch the flow), they do it in plain chat today, and the decisions from that chat get lost at the handoff. The product-manager then works them out again, often differently, which shows up later as revised assumptions and amendments. An explicit, read-only "explore first" conversation that hands its decisions to the spec as decided input keeps that thinking and removes the rework. Only a person starts it, so it does not conflict with unattended runs asking less (spec 179).

## Stories

As a person with a half-formed feature idea, I want to talk it through with an agent that reads the code, compares options and draws diagrams without writing anything, so that I can make the decisions before a spec exists.

As a person ending an exploration, I want my decisions handed to the spec as decided input, so that the product-manager writes them in instead of deriving them again.

As the platform owner, I want to see whether explored specs need fewer revisions than other specs, so that I can keep or retire the explore commands on evidence.

## Acceptance criteria

- **AC-188.1** Given `/component:explore <topic>` or `/system:explore <topic>`, when its definition is checked, then its allowed tools are Read, Grep, Glob, AskUserQuestion and Bash limited to `cplat explore *` and read-only git, with no Write, Edit or NotebookEdit; and given a whole session that ends in "stop", then the working tree and the branch's commits are the same as before it started.
- **AC-188.2** Given a topic, when `cplat explore context "<topic>" --json` runs, then it exits 0 with `shape`, `project_map`, `specs` (id, title, status; matched on title or criteria text), `issues` (open ones: number, title), `adrs` (number, title) and, in a gitops-app repo only, `components`, `resources` and `apis` of the system; a topic that matches nothing gives empty lists, and an empty topic exits 2 with a usage line.
- **AC-188.3** Given an explore session, when the agent ends a turn that changed the decisions, and at least every 3rd turn, then it prints the running decisions list and offers exactly three ways out: "spec it", "keep exploring", "stop"; and when the person asks it to implement, plan tasks, write the design or pick a library, then it declines, names the command that does that, and offers the same three ways out.
- **AC-188.4** Given "spec it", when the handoff runs, then the agent prints the decisions list with each decision marked `behaviour`, `constraint` or `hint`, and starts `/component:spec` (from `/system:explore`: `/system:spec`) with the request plus a `DECIDED:` block holding those lines; no decisions file is written.
- **AC-188.5** Given a request with a `DECIDED:` block, when the product-manager writes the spec, then each `behaviour` becomes an acceptance criterion, each `constraint` an assumption ending `(decided in explore)`, and each `hint` a bullet under a "Notes for the architect" section, which `cplat spec check` accepts and does not count as criteria; and when the architect departs from such a note, then the design names the note and the reason.
- **AC-188.6** Given a decided item that contradicts an active criterion of another spec or an accepted ADR listed by `cplat explore context`, when the product-manager writes the spec, then that item becomes an open question naming the spec criterion or ADR, not a criterion or assumption.
- **AC-188.7** Given a spec created through the explore handoff, when it is created, then its front matter has `explored: true`, and `cplat spec list --json` reports `explored` (true or false) for every spec.
- **AC-188.8** Given the weekly `/platform:retro`, when it reports, then it shows explored and other specs created since the release that ships explore, side by side: count, mean revised assumptions and mean amendments; and when 6 weeks have passed since that release with fewer than 5 explored specs or no lower mean of revised assumptions for explored specs, then it reports "kill rule met: retire /component:explore and /system:explore as tombstones (your decision)" and changes nothing itself.
- **AC-188.9** Given a request the product-manager finds too ambiguous to build, when `/component:spec` (or `/system:spec`) asks that open question, then the recommended answer is `/component:explore <topic>` (or `/system:explore <topic>`).
- **AC-188.10** Given an issue in `/issue:triage`, when it is classified, then "needs exploring" is offered as a route next to spec, fix and reply; choosing it shows `/component:explore #<n>` (`/system:explore` in a gitops-app repo) as the next step and leaves the issue in the triage queue.
- **AC-188.11** Given an unattended run (ship, build, dispatcher, journey, headless), when its run allowlist and prompts are checked, then neither explore command nor `cplat explore` appears in them, and the explore commands state that they are started by a person only.
- **AC-188.12** Given the new explore prompts and the changed product-manager, spec and triage prompts, when `cplat platform rules check` runs, then it passes: every new rule has a register entry with its reason, and any raise of the recorded prompt size was made with `cplat platform rules rebaseline --reason`.

## Non-goals

- Explore writing code, specs, plans, design documents or any other file, or committing.
- A persisted decisions file or resuming a past session from disk (the printed list is the handoff).
- Explore choosing libraries or the build approach; hints stay non-binding for the architect.
- Starting explore from unattended runs, ship, the dispatcher or journeys.
- Retiring the commands automatically; the retro only reports the kill rule.

## Assumptions

- **A1** (decided by the user) Explore is strictly read-only: no Write/Edit tools, Bash only `cplat explore *` and read-only git, diagrams in chat, nothing committed (other option: a scratch notes file; affects AC-188.1).
- **A2** (decided by the user) Decisions are handed over inline as a `DECIDED:` block to the spec command, no persisted file (other option: a decisions file in the spec folder; affects AC-188.4).
- **A3** (decided by the user) `/system:explore` is in this spec with the same handoff; only the context (system, components, resources, APIs) differs (other option: a later spec; affects AC-188.1, AC-188.2, AC-188.4).
- **A4** (decided by the user) A thin `cplat explore context "<topic>" [--json]` gathers specs, open issues, ADRs, project map and shape (plus components, resources, APIs in a system repo); the commands run it and relay its output (other option: the model searches by hand; affects AC-188.2).
- **A5** (decided by the user) Decisions are sorted into behaviour (criterion), constraint (binding assumption) and hint (non-binding "Notes for the architect", overridable with a reason in the design); a contradiction with an existing spec or ADR becomes an open question (other option: all decisions as assumptions; affects AC-188.5, AC-188.6).
- **A6** (decided by the user) Only three ways out (spec it / keep exploring / stop); explore never implements, plans, writes the design or picks libraries; the running decisions list is printed regularly (other option: free-form ending; affects AC-188.3).
- **A7** (decided by the user) Discovery through `/component:spec` / `/system:spec` (recommended answer to an ambiguity question) and a fourth triage route "needs exploring" (other option: docs only; affects AC-188.9, AC-188.10).
- **A8** (decided by the user) Explored specs are marked and the weekly retro compares revised assumptions and amendments; kill rule at 6 weeks after the release with fewer than 5 explored specs or no drop, decided by the person (other option: no measurement; affects AC-188.7, AC-188.8).
- **A9** (decided by the user) Started by a person only, never by unattended runs, ship, dispatcher or journeys; works in the platform repo like any component repo (other option: none; affects AC-188.11).
- **A10** (decided by the user) The prompt changes follow spec 168's rule register and size baseline (other option: none; affects AC-188.12).
- **A11** The explored marker is the front matter field `explored: true`, set when the spec command receives a `DECIDED:` block, because `cplat spec` already reads front matter (other option: a word in the Changelog `created` line; affects AC-188.7, AC-188.8).
- **A12** The running decisions list is printed after every turn that changed it and at least every 3rd turn (other option: every 5th turn, or only on request; affects AC-188.3).
- **A13** A constraint assumption ends with `(decided in explore)` so it can be told apart from the product-manager's own defaults (other option: a separate "Decided" section; affects AC-188.5).
- **A14** "Notes for the architect" bullets are not acceptance criteria: `cplat spec check` does not count them, and they do not enter the spec's criteria hash, so editing a note needs no new plan (other option: notes inside the hash; affects AC-188.5).
- **A15** `cplat explore context` matches the topic case-insensitively on words in spec titles and criteria, issue titles and ADR titles, and lists at most 10 of each kind (other option: no limit; affects AC-188.2).
- **A16** An empty topic is a usage error (exit 2); a topic with no match returns empty lists with exit 0 (other option: list everything; affects AC-188.2).
- **A17** The "needs exploring" triage route adds no new label and keeps the `triage` label, so the issue stays in the queue until it is explored and specced (other option: a new `needs-exploring` label, which needs `setup-labels`; affects AC-188.10).
- **A18** An amendment, for the retro, is a Changelog line other than `created`, `approved` and status moves; revised assumptions are the struck-through ones (other option: count spec_hash changes; affects AC-188.8).
- **A19** The retro compares specs in the repos it already covers, created since the release that ships the explore commands (other option: all specs ever; affects AC-188.8).

## Open questions

## Changelog

- 2026-11-12 created
- 2026-11-12 approved
- 2026-11-12 building
