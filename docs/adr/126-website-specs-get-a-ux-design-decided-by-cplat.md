# ADR-126: Website specs get a UX design step that cplat decides

**Status:** Accepted (2026-11-22, spec 219)

## Context

A website feature went from the approved spec straight to the architect and the coders (#715): nobody decided the screens,
their states or their accessibility, so each coder decided while coding and the reviewer had nothing to check the screens
against. A design step for every spec would cost service and library repos time and tokens for nothing, and leaving the
"does this spec need UX?" call to an agent's judgement makes it untestable and different from run to run.

## Decision

1. **A shape opts in by data.** `shapes.yml` declares `ux_designer: true` on a shape whose plugin has a `ux-designer`
   agent (today `web-nextjs`, agent `web:ux-designer`); `scripts/shapes.py check` refuses the flag without the agent.
   `cplat shape` routes `ux-designer` only for such a shape, and the orchestrators gate the step on that key.
2. **cplat decides per spec.** `cplat spec ux <id> [--json]` answers `needed`, `none` or `done`: `none` for a shape
   without the flag; `done` when `ux.md` records the spec's current criteria hash; else the spec's `ux: needed|none`; else
   `needed` when an active criterion or a story names something a user sees or does on screen (a fixed word list).
   A `ux.md` written for earlier criteria is stale and designed again.
3. **The step runs inside `/component:plan`, before the architect, once.** Every path that plans (attended, ship,
   headless) gets it. The agent (opus, no Bash) writes `docs/specs/<id>/ux.md`: front matter `spec_id`, `spec_hash`, and
   the sections Flows, Screens, States, Accessibility; `cplat spec check` validates it. The architect plans from it, the
   coder brief carries a `UX` field and the reviewer lists a screen or state the build lacks as a deviation.
4. **`ux.md` is not a second approval.** The user approves the criteria; `ux.md` is a design input like `design.md`, so a
   gap against it is a deviation in verification, never a `not met` criterion.

## Consequences

- Service, library and gitops repos route no ux-designer and run no extra agent.
- One more opus call per UI-changing website spec, and a larger prompt set (the new agent and a few clauses).
- A later website shape opts in with the flag and its own agent; the word list may need tuning, and a spec can always
  override it with `ux:`.
