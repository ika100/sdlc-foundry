# Build: resume an interrupted build

Read from `/component:build` Phase 0, step 1, when the tree is dirty on a `building` spec (spec 047).

- Staged entries that differ from both `HEAD` and the working tree are stale (left by the interrupted coder): `git restore --staged <files>` and name them.
- The first task in `plan.md` that is not `done` is the interrupted one. Ask, then commit the remaining changes as `wip(<task-id>): interrupted` (in an unattended run, commit without asking and say so).
- That task runs again in Phase 2 with `git show HEAD` (the WIP diff) in its coder prompt, so the coder finishes or redoes it.
- Run `cplat budget resume` (spec 102): it prints the last recovery snapshot (stage and failure excerpt) and, per stage, `skip` only for a gate that passed on the current `HEAD` and inputs, otherwise `run` with the reason. Skip what it says to skip; run the rest, starting with the stage of the snapshot.
