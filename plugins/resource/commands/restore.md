---
description: "Restore a database by generation: to a point in time, switch to the restored copy, or discard it. Usage: /resource:restore <db> --env <env> (--to <time|latest> | --switch | --discard) [--confirm prod]"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

```bash
cplat resource restore <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line.
2. **Run** it. `--to <time|latest>` recovers a new copy next to the running database, which keeps serving, and needs no confirmation in any environment; `--switch` makes the restored copy the active database; `--discard` removes it. **Hard rule:** in `prod`, never run `--switch` or `--discard` without `--confirm prod` and the user's explicit yes, because they change which database serves or delete a copy.
3. **Relay** the next steps `cplat` prints and check progress with `/system:status`.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
