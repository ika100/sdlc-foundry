---
description: "Remove a system from this cluster repo in one PR; nothing is deleted in the cluster. Usage: /cluster:remove <system>"
---

Remove a system from the cluster repo you are in, with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

```bash
cplat cluster remove <ARGS>
```

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. An unknown name fails and lists the registered systems; show that and stop.
2. **Run.** The user's request is the confirmation. Run the same command without `--dry-run`.
3. **Report.** Relay the PR URL and the "kept in the cluster" line verbatim. Say it plainly: nothing is deleted in the cluster. The system's namespaces, resources and data stay until a human deletes them; merging the PR removes only the Argo CD application that syncs the system.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
