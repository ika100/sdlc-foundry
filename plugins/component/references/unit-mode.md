# Unit mode

`cplat headless` runs a long ship or build as short sessions, one **unit** each, (`--unit <unit>` of `/component:ship` or `/component:build`). This file is the only place the per-unit rules are written. Follow your unit's rules and nothing else.

**Permissions:** the session is granted the run allowlist: the feature branch, `commit -s`, `git rm` of tracked files (never forced), push without force and the PR; force pushes, default-branch pushes and merges outside `cplat component ship land` are refused (ADR-076).

## Units

| Unit | What you do |
|---|---|
| `plan` | Follow `plan.md` unattended and commit it. In a ship, then run `cplat component ship phase build`. |
| `red-tests` | Build Phases 0 and 1: pre-flight and the failing acceptance tests, the test review and `cplat component build reviewed`. |
| `batch:<id>,<id>…` | Build Phase 2 for exactly these tasks as one parallel batch: the worktree probe, one coder per task at once (one message, `isolation: "worktree"`), each merged with `cplat component build merge` in the listed order; a refused merge follows Phase 2's re-plan rule. Then `cplat spec task-done <spec> <id>` per merged task and the commit of Phase 2. A failed probe → one task after another (`build-worktree-fallback.md`). |
| `task:<id>` | Build Phase 2 for that one task, sequential: no probe, no batch. Then `cplat spec task-done <spec> <id>` and Phase 2's commit. |
| `verification` | Build Phases 2.5 to 6. In a ship, then run `cplat component ship phase pr`. |
| `land` | In a ship, the ship phases `pr`, `land` and `deploy`, without `cplat component ship finish`. In a build, Phase 7. |

## Rules for every unit

- Check with `cplat component ship unit` where the run stands, then stop at once when your unit is done.
- Never start another unit, because a unit is one short session.
- Commit what is done before every stop, so the next session starts clean.
- Escalate as the command says (`cplat component ship escalate` in a ship, `cplat platform runs end --outcome escalated` in a build).