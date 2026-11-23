# Design — 219 Website specs get a UX design step

## Decisions

- **Registry flag, not a shape check.** `shapes.yml` gets `ux_designer: true` on `web-nextjs`; `scripts/shapes.py check`
  refuses the flag on a shape whose plugin lacks `plugins/<plugin>/agents/ux-designer.md`. `cplat shape` (`shapecmd.route`)
  adds `agents["ux-designer"] = "<plugin>:ux-designer"` for a flagged shape, the way it adds `migrations` for
  `service-python`. Orchestrators only test for the key, so a non-website run never sees the step.
- **The decision is cplat's.** New module `scripts/cplat/spec_ux.py`, subcommand `cplat spec ux <id> [--json]`:
  1. the repo shape is not flagged (or there is none) → `none`, reason names the shape;
  2. `ux.md` exists and its `spec_hash` equals `Spec.ac_hash()` → `done`;
  3. front matter `ux: needed|none` → that value, reason `set in spec.md`; a stale `ux.md` with `ux: needed` → `needed`
     (stale);
  4. otherwise the active criteria and `## Stories` are matched against a fixed word list of things a user sees or does
     on screen (`VISIBLE`); a match → `needed` naming the word, none → `none`. A stale `ux.md` → `needed` (stale) also
     when the words match.
  Output: `{"spec": id, "ux": "needed"|"none"|"done", "reason": "..."}`; text mode prints `<id>: <ux> — <reason>`.
- **Check.** `spec.check` calls `spec_ux.field_errors(meta)` (`ux` ∈ {needed, none}) and `spec_ux.file_errors(spec)` when
  `ux.md` exists: front matter `spec_id` = folder and `spec_hash` present; sections `Flows`, `Screens`, `States`,
  `Accessibility`; every `AC-<NNN>.<n>` it names is active. A stale hash is no check error (the plan step redesigns it).
- **Agent.** `plugins/web/agents/ux-designer.md`, `model: opus`, tools `Read, Write, Glob, Grep`. It reads spec.md and the
  app's existing pages/components, writes only `SPEC_DIR/ux.md` with the format in its prompt, replies `UX: <path>` and
  `BLOCKERS: none|…`.
- **Plan command.** `plan.md` gets step 2 "UX design" before the architect: with `agents.ux-designer`, `cplat spec ux <id>
  --json`; `needed` → the agent (foreground) with `SPEC_DIR`, `SPEC_HASH`, `<project-map>`; `cplat spec check <id>` errors
  go back once; the architect prompt then names `UX: SPEC_DIR/ux.md`. The plan commit already holds the spec folder.
  `ship.md` records the spawn next to the architect's.
- **Build.** `build.md` 2.3 adds `UX` to the coder brief; the reviewer prompt reads `ux.md` with the plan and lists a
  missing screen or state with the deviations (A5).
- **Size.** The new agent and the few added clauses take the prompts past `baseline.prompt_bytes`; the raise goes
  through `cplat platform rules rebaseline` after both benchmarks (spec 168).

## Contract

`cplat spec ux <id> --json` → `{"spec": "<id>", "ux": "needed" | "none" | "done", "reason": "<one line>"}`, exit 0.

`ux.md`:

```markdown
---
spec_id: <NNN>-<slug>
spec_hash: <cplat spec hash>
---
# UX — <NNN> <title>
## Flows
## Screens
## States
## Accessibility
```
