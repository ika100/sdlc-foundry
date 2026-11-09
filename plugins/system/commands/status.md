---
description: "One-table overview of a system: per component and environment the pinned version, CI state and Argo health. Usage: /system:status [--context <kube-context>]"
---

Show the system status. One Bash call from the gitops-app repo root.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

```bash
cplat system status <ARGS>
```

Pass `--context k3d-<system>-local` (or the user's cluster context) when they want the Argo column. A scaled instance's cell shows `replicas <n> (<min>–<max>)`, or `?` when the cluster cannot be read. Show it verbatim (with its Resource versions and Backups sections), then add at most three lines: anything not `ok`/`Synced/Healthy`, whether staging/prod lag behind dev, and the one command that fixes the worst problem. Read-only: never change anything, so that a status call is always safe.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
