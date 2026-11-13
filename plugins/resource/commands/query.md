---
description: "Run one read-only SQL statement on a database: its active instance or a restored copy. Usage: /resource:query <db> --env <env> [--copy g<N>] \"<sql>\" [--json]"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource query <ARGS>
```

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

It reads, so there is no dry run: run it and relay the table whole; errors carry a `fix:` line.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
