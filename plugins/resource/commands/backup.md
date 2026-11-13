---
description: "Set a database's scheduled backup or take one now. Usage: /resource:backup <db> --env <env> [--to <bucket>] [--schedule <cron>] [--retention <n>d|<n>w] [--off]"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

```bash
cplat resource backup <ARGS>
```

1. **Setting option** (`--to`, `--schedule`, `--retention` or `--off`): preview with `--dry-run` and show it verbatim, then run with `--pr` (one PR); do not ask again, because the user asked for it.
2. **No option**: run it and relay the output verbatim. It creates one backup now from the cluster of `<env>` and changes nothing in git. Check backups with `/system:status`.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
