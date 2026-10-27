---
description: "Remove a resource from system.yaml; refused while a component uses it. Usage: /resource:remove <name> (for example postgres)"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource remove <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line. While a component still lists the resource under `uses`, the command refuses and names every component that does: remove it there first with `/component:set`. An unknown name lists the resources of the system.
2. **Run** with `--pr` (one PR; the user asked for it, do not ask again).
3. **Say** that removing the resource never deletes the data that already exists (the running database or bucket store, its volumes and its Secret, or an external database or bucket and its Secret).

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
