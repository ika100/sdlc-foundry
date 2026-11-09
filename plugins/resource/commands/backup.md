---
description: "Take an on-demand backup of a database now. Usage: /resource:backup <db> --env <env>"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

```bash
cplat resource backup <ARGS>
```

1. **Run** it and relay the output verbatim; errors carry a `fix:` line. It reads the cluster of `<env>` and creates one backup of the database; it changes nothing in git.
2. **Say** that the scheduled backups and the continuous archiving come from `backup:` on the database instance in `system.yaml`; this command adds one backup now. Check it with `/system:status`.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
