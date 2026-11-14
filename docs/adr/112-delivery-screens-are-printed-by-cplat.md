# ADR-112: Delivery screens are printed by cplat

**Status:** Accepted (2026-11-14)

## Context

The person who delivers with the platform had to know which command comes next: triage, approval, build, ship and
release each ended with its own "Next step" line, and nothing showed where an item stood in the whole process or what
waited for them. A screen written by the session differs from run to run, costs tokens and cannot be tested.

## Decision

Delivery screens and their choices are printed by cplat; the session adds only judgement text and follows the procedure the screen carries.

- The screen (process bar, what is happening, the person's part) and the choices are code: `nextstate` reads every
  source read-only, `nextscreen` renders, `nextquestions` builds the options, `nextcmd` is `cplat next`.
- The session adds only judgement text (what the person gets from a draft, its most important assumption), passed in
  with `--judgement`.
- The procedure (print the screen, ask the questions, run the chosen option) travels in the `how` paragraph of
  `cplat next --json`; `/platform:next` and the hand-over at the end of triage, approval, build, ship and release say
  only "run `cplat next --json` and follow its `how`".
- The person's answers are recorded by `cplat next answer` as run-store follow-ups (`"followup": "person"`), never as
  run records, so they show in the report's person time and never look like a finished run.

## Consequences

- One tested screen replaces eight differently worded "next step" lines; a change to the procedure is a code change,
  not eight prompt edits.
- Each prompt grows by one sentence; the prompt size baseline is raised once, after the benchmark.
- Later screens (spec 193's build screens) build on `nextstate` and `nextquestions` and must stay read-only.
