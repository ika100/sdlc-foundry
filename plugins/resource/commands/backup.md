---
description: "Take an on-demand backup of a database now. Usage: /resource:backup <db> --env <env>"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource backup <ARGS>
```

1. **Run** it and relay the output verbatim; errors carry a `fix:` line. It reads the cluster of `<env>` and creates one backup of the database; it changes nothing in git.
2. **Say** that the scheduled backups and the continuous archiving come from `backup:` on the database instance in `system.yaml`; this command only adds one backup now. Check it with `/system:status`, which shows the Backups section.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
