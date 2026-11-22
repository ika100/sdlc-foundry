---
spec_id: 219-website-specs-get-a-ux-design-step
title: Website specs get a UX design step
status: done
priority: P1
shape: platform
tracks: [715]
---

# 219 — Website specs get a UX design step

## Problem

A website feature goes from the approved spec straight to the architect and the coders (#715). Nothing decides which
screens a user moves through, which states each screen has (empty, loading, error) or what keeps it accessible, so the
coder decides it while writing code and the reviewer has no design to check the built screens against. The comparison
with the BMAD method named this the clearest step the platform lacks: a UX design written before the architecture, for
the features that change what a user sees, and only for those, so that service and library specs pay nothing for it.

## Stories

- As a website owner, I want every approved spec that changes what a user sees to get a short UX design (flows, screens,
  states, accessibility) before it is planned, so that the screens are decided once, on purpose, and not by each coder.
- As the architect and the coders of a website, I want the UX design in the spec folder and in my brief, so that the
  plan and the code follow the same screens.
- As the reviewer, I want to check the built screens against the UX design, so that a missing screen or state shows up
  in verification instead of in production.
- As the owner of a service or library repo, I want no UX step in my runs, so that it costs me no time and no tokens.

## Acceptance criteria

- **AC-219.1** Given the shape registry, when a shape is read, then a shape may declare `ux_designer: true` only when
  its plugin has a `ux-designer` agent, `scripts/shapes.py check` fails a declaration without the agent naming the
  shape and the missing file, and `web-nextjs` is the only shape that declares it.
- **AC-219.2** Given `cplat shape` in a repo of a shape that declares `ux_designer`, when it routes, then its `agents`
  map holds `ux-designer` → `<plugin>:ux-designer` (for `web-nextjs`: `web:ux-designer`); in a repo of any other shape
  the map has no `ux-designer` key.
- **AC-219.3** Given a website spec without a `ux` field, when `cplat spec ux <id> --json` runs, then it answers
  `needed` when an active criterion or a story names something a user sees or does on screen (for example a page,
  screen, form, button, link, dialog, message shown, click), naming the matched word in its `reason`, and `none` with a
  reason saying no criterion names a visible element otherwise.
- **AC-219.4** Given a website spec whose front matter sets `ux: needed` or `ux: none`, when `cplat spec ux` runs, then
  that value decides over the derived one and the reason says it came from the spec; any other value of `ux` fails
  `cplat spec check` with an error naming the allowed values.
- **AC-219.5** Given a repo whose shape does not declare `ux_designer` (or no shape), when `cplat spec ux` runs on any
  spec, then it answers `none` with a reason naming the shape, whatever the spec's front matter says.
- **AC-219.6** Given a website spec whose folder holds a `ux.md` with a `spec_hash` equal to the spec's current
  criteria hash, when `cplat spec ux` runs, then it answers `done`; a `ux.md` written for earlier criteria answers
  `needed` with a reason saying it is stale, so that a re-plan redesigns it.
- **AC-219.7** Given a spec folder with a `ux.md`, when `cplat spec check` runs, then it fails, naming `ux.md` and the
  problem, when the front matter lacks `spec_id` equal to the folder or lacks `spec_hash`, when one of the sections
  `Flows`, `Screens`, `States` or `Accessibility` is missing, or when it names a criterion id that is not an active
  criterion of the spec; a `ux.md` with all of them passes.
- **AC-219.8** Given the `web` plugin, when it is read, then it holds a `ux-designer` agent whose tools can read the repo
  and write files but cannot run commands or edit code by command (no Bash), whose prompt passes `cplat platform rules
  check`, and which names the `ux.md` sections of AC-219.7.
- **AC-219.9** Given `/component:plan` (and `/component:ship`, which follows it), when the routing has a `ux-designer`,
  then the command asks `cplat spec ux` before the architect step, runs the `ux-designer` agent once when the answer is
  `needed`, checks the result with `cplat spec check`, and passes `ux.md` to the architect; a routing without
  `ux-designer` reaches the architect with no UX step.
- **AC-219.10** Given `/component:build` on a spec with a `ux.md`, when it briefs a coder and the reviewer, then the
  coder brief carries a `UX` field (the screens and states of the task's criteria, or `none`) and the reviewer reads
  `ux.md` and reports a screen or state it names that the build lacks as a deviation.
- **AC-219.11** Given the platform's docs, when they are read, then the spec-format skill lists `ux.md` (written by the
  ux-designer, for website specs), its format reference documents the `ux` field of `spec.md`, the `web` plugin README
  lists the agent, and `docs/AGENTS.md` places the step between approval and the architect.

## Non-goals

- A design system or component library in the `web-nextjs` template.
- Images, wireframe files, visual design tools, Figma or image generation; `ux.md` is text with optional ASCII sketches.
- System specs: the website repo of a system gets the step when its own spec (`/component:spec --from-plan`) is planned.
- A user approval gate for `ux.md`: it is a design input like `design.md`, not a second spec approval.
- UX design for service, library or gitops shapes.

## Assumptions

- **A1** The step runs inside `/component:plan`, after approval and before the architect, so that every path that plans
  (attended, ship, headless) gets it without a new command (other option: a separate `/component:ux` command; affects
  AC-219.9).
- **A2** Whether a spec needs UX is decided by `cplat` from the criteria and stories, with an explicit `ux:` field in
  the spec to override it, so that the decision is deterministic and testable (other option: the product-manager always
  sets the field; affects AC-219.3, AC-219.4).
- **A3** The agent lives in the `web` plugin and the shape registry declares which shapes have it (`ux_designer: true`),
  so that a later website shape opts in by data (other option: a hard-coded shape check; affects AC-219.1, AC-219.2).
- **A4** The ux-designer runs on Opus like the product-manager and the architect, because it writes a spec-level input
  every later agent reads, once per spec (other option: Sonnet, cheaper; affects AC-219.8).
- **A5** A missing screen or state in the build is a deviation in verification, not a `not met` criterion, because the
  user approved the criteria, not `ux.md` (other option: fail the criterion; affects AC-219.10).
- **A6** `ux.md` records the criteria hash it was written for, so a re-plan after an amendment redesigns it (other
  option: keep it; affects AC-219.6).

## Notes for the architect

- Mirror the `migrations` agent routing in `cplat shape` and the `environments` field check in `cplat spec check`.
- The prompts may not grow past the recorded size without the benchmark and a recorded reason (spec 168).

## Open questions

- none

## Changelog

- 2026-11-22 created
- 2026-11-22 approved
- 2026-11-22 building
- 2026-11-22 done
