---
description: "Restore an environment from a Velero backup. Usage: /system:restore <env> [--backup <name|latest>] [--replace] [--confirm prod]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

```bash
cplat system restore <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line.
2. **Run** it. **Hard rule:** run a prod restore only with `--confirm prod` after the user explicitly confirmed, because it replaces live data.
3. **Say** what it did, relay the next steps `cplat` prints and check the result with `/system:status`.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
