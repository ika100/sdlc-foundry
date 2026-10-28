# Build: re-planned tasks and re-plan after a conflict

Read from `/component:build` 2.3 for a re-planned task, and after a batch in which `cplat component build merge` exits 3.

## Coder prompt for a re-planned task (2.3)

- A task that was re-planned after a merge conflict (`cplat component build state <id> --json`: a `replans[].tasks[]` entry that is not merged) also gets: "This task was re-planned after a merge conflict on `<paths>` with `<with>`. Start from the feature branch, which already contains every merged task. Your earlier attempt is a reference only. Do not merge or cherry-pick it:" followed by the output of `git diff HEAD...<branch>`, with `<branch>` from that state output.

## Re-plan after a conflict (2.4a)

After a batch in which `cplat component build merge` set a task aside (exit 3), re-plan **without asking the user**, in an attended build as well as an unattended one:

1. Spawn the **architect** (`agents.architect`) with the prompt `**Re-plan mode.**` + `<project-map>` + `SPEC_DIR` + the output of `cplat component build state <id>` (the pending conflicts: task, the task it collided with, the paths) + "Change only `files`, `depends_on` and `parallel_safe` of tasks that are not done; anything else is a BLOCKER." Then `cplat platform runs agent spawned architect`.
2. `cplat component build replan-commit <id>`. On exit 1, send its errors to the architect once and call it again.
3. The architect reports a BLOCKER, or the second call also exits 1 → `cplat component build replan-abort <id> --reason '<the blockers or errors>'`, then `cplat platform runs end --outcome escalated --reason '<its ESCALATE line>'` and stop.
4. Exit 0 → continue from the schedule it printed. The set-aside task runs again on top of the merged work (coder prompt in 2.3).
