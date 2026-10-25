# Build: resume an interrupted build

Read from `/svc:build` Phase 0, step 1, when the tree is dirty on a `building` spec (spec 047).

- Staged entries that differ from both `HEAD` and the working tree are stale (left by the interrupted coder): `git restore --staged <files>` and name them.
- The first task in `plan.md` that is not `done` is the interrupted one. Ask, then commit the remaining changes as `wip(<task-id>): interrupted` (in an unattended run, commit without asking and say so).
- That task runs again in Phase 2 with `git show HEAD` (the WIP diff) in its coder prompt, so the coder finishes or redoes it.
