---
description: "Restore a database by generation: to a point in time, switch to the restored copy, or discard it. Usage: /resource:restore <db> --env <env> (--to <time|latest> | --switch | --discard) [--confirm prod]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource restore <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line.
2. **Run** it. In `prod` the command needs `--confirm prod`; ask the user first.
3. **Explain the action used.** `--to <time|latest>` recovers a new copy next to the running database, which keeps running. `--switch` makes the restored copy the active database. `--discard` removes the restored copy. Relay the next steps `cplat` prints and check progress with `/system:status`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
