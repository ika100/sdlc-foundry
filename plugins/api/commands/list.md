---
description: "List the APIs the system declares, with type, provider and consumers. Usage: /api:list [--json]"
---

Show the APIs of the system. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

Run from the gitops-app repo (or a component repo linked to it by `.platform-app.yml`; then clone the listed repo with `gh repo clone <org>/<repo>` and run there):

```bash
cplat api list <ARGS>
```

Show the output verbatim, one line per API; an events API bound to a broker ends with `  broker <b>` (`--json` adds `broker`, null when no broker carries it). With no APIs it says `no APIs declared`. A repo still on 4.x fails with `NOT_MIGRATED`; tell the user to run `/platform:update --migrate`.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
