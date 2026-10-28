---
description: "Restore an environment from a Velero backup. Usage: /system:restore <env> [--backup <name|latest>] [--replace] [--confirm prod]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat system restore <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line.
2. **Run** it. In `prod` the command needs `--confirm prod`; ask the user first.
3. **Say** what it did: `--backup` picks the backup (default `latest`); `--replace` restores over existing objects. Relay the next steps `cplat` prints and check the result with `/system:status`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
