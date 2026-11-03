# Unit mode (spec 131, ADR-075)

`cplat headless` runs a long ship or build as a series of short sessions, one **unit** each, and passes `--unit <unit>` to `/component:ship` or `/component:build`. This file is the only place the per-unit rules are written. Follow the rules of your unit and nothing else; the rest of the command stays unread.

**Permissions:** the session is granted the run allowlist: the feature branch, `commit -s`, push without force and the PR; force pushes, pushes to the default branch and merges outside `cplat component ship land` are refused (ADR-076).

## Units

| Unit | What you do |
|---|---|
| `plan` | Follow `plan.md` of the spec unattended (the plan phase of the command) and commit `plan.md`. In a ship, then run `cplat component ship phase build`. |
| `red-tests` | Build Phases 0 and 1: pre-flight and the failing acceptance tests. |
| `task:<id>` | Build Phase 2 for that one task, as a sequential task: no worktree probe and no parallel batch. Run `cplat spec task-done <spec> <id>` and commit the task as build Phase 2 says. |
| `verification` | Build Phases 2.5 to 6: QA, verification, image and closing the spec. In a ship, then run `cplat component ship phase pr`. |
| `land` | In a ship, the ship phases `pr`, `land` and `deploy`, without `cplat component ship finish`. In a build, Phase 7. |

## Rules for every unit

- Check where the run stands with `cplat component ship unit`, then stop at once when your unit is done. The next session picks up the next unit.
- Never start another unit, even when the time or the budget would allow it.
- Commit what is done before every stop, so the next session starts from a clean tree.
- Escalate as the command says (`cplat component ship escalate` in a ship, `cplat platform runs end --outcome escalated` in a build).
- The run allowlist applies: the feature branch, `commit -s`, push without force and `gh pr create`. Force pushes, pushes to the default branch and merges outside `cplat component ship land` are refused.
