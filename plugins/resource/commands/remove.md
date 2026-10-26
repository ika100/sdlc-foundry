---
description: "Remove the postgres resource from system.yaml; refused while a component uses it. Usage: /resource:remove postgres"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource remove <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line. While a component still lists `postgres` under `uses`, the command refuses: remove it there first with `/component:set`.
2. **Run** with `--pr` (one PR; the user asked for it, do not ask again).
3. **Say** that removing the resource never deletes the database that already runs.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
