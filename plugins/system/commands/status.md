---
description: "One-table overview of a system (run in its gitops-app repo): per component and environment the pinned version, CI state on main and Argo sync/health. Usage: /system:status [--context <kube-context>]"
---

Show the system status. One Bash call from the gitops-app repo root:

```bash
cplat system status <ARGS>
```

Pass `--context k3d-<system>-local` (or the user's cluster context) when they want the Argo column. The table has one row per component and one column per environment, in the order of `environments:` in `system.yaml`. Show it verbatim (with the Backups section below it: last backup, archiving and restore points per database and environment), then add at most three lines: anything not `ok`/`Synced/Healthy`, whether staging/prod lag behind dev, and the one command that would fix the most obvious problem. Read-only: never change anything.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
