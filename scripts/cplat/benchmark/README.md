# Benchmarks

The fixed tasks behind `cplat platform runs benchmark` (spec 099, ADR-035), listed in `tasks.json`.

| Workflow | Sample | Ends at | Release gate |
|---|---|---|---|
| `quick-task`, `build`, `ship`, `fix-rounds` | one repo, `ika100/todo-api` | a new open (or merged) PR | `quick-task` and `build` when a prompt changed (spec 151) |
| `system-ship` | a system: `ika100/bench-files-gitops` with `bench-files-api` (Python), `bench-files-worker` (Go) and `bench-files-web` (Next.js) | every component PR merged, before `land` (`/system:ship --until repos`) | none: report-only, about an hour per run (spec 156) |

## system-ship

`cplat platform runs benchmark system-ship [--plugins plugins] [--reset-first] [--repeat N]` ships the system spec `system/spec.md` with its pinned plan `system/plan.md` (one repo first, then two that do not depend on each other). Each run is its own `benchmark` record with, per repo, wall clock, agent time, tokens, sessions, criteria and the most subagents at work at once, and for the run the overlap (the components' wall clocks summed over the run's; 1.0 means one after another). `--report` runs nothing and prints the stored runs per plugins tree with median and spread, and compares the newest two trees: a difference of medians inside the larger spread is no gain, and fewer than two runs per side is no result.

The sample system (`ika100-demo/bench-files-*`, private; that organization's `GITOPS_TOKEN` secret lets the component ships pin) was created once from `system/manifest.yml` with `cplat system new … --dir <folder>`. The benchmark reuses the four clones in that folder (`--dir`, or `CPLAT_BENCH_SYSTEM_DIR`; default `<state dir>/benchmark/system-ship/`) and puts every repo back to its pinned revision after a run. When a template changes what a fresh repo needs (a toolchain out of support, a new `.gitignore` entry), commit the same change on each sample repo's `main` on top of its pin and pin the new revision in `tasks.json`, so the sample stays a repo the platform would generate today. Claude Code must trust each clone once (open it interactively and accept the dialog): a trusted parent folder does not count, and an untrusted folder ignores the repo's permission rules.

**Judge a change on the benchmarks, not on a journey.** The sample differs from the journey's system on purpose (domain, component shapes, plan order), so that a change is not fitted to one scenario: judge a round with `--repeat 3` before and after on `system-ship` and with the single-repo benchmarks; a journey only confirms the result end to end. Run `system-ship` before a release that changes the system ship (CONTRIBUTING.md, Releases).

## ux-plan

`cplat platform runs benchmark ux-plan --plugins plugins [--dir <system-ship folder>] [--reset-first]` (spec 222) plans the fixed website spec `spec-902.md` (a status page) with `/component:plan 902`, so the UX step of spec 219 runs: `web:ux-designer` writes `ux.md`, then the architect plans. It ends at the local plan commit; nothing is built or pushed. The sample is the `bench-files-web` component of the system-ship sample at that sample's pinned revision, and the run reuses its clone `bench-files-web` in the system-ship folder (`--dir`, else `$CPLAT_BENCH_SYSTEM_DIR`, else `<state dir>/benchmark/system-ship`), so no second sample needs its own Claude Code trust or upkeep; a missing or untrusted clone is refused. The run is `done` only when the plan branch `feature/902-…` holds a `ux.md` that `cplat spec ux` answers `done` for, the spec passes `cplat spec check`, and `design.md` or `plan.md` names `ux.md`. Its record carries the ux-designer's and the architect's tokens and time like every other run.

It is opt-in: `cplat platform eval-gate` (and so `cplat platform release`) asks for it only when a prompt under `plugins/web/` or the UX step's decision `scripts/cplat/spec_ux.py` changed since the last release; a change to `spec_ux.py` alone asks for `ux-plan` only. `cplat platform rules rebaseline` keeps asking for `quick-task` and `build`.
