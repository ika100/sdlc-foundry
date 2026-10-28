---
description: "List the APIs the system declares, with type, provider and consumers. Usage: /api:list [--json]"
---

Show the APIs of the system. **Request:** $ARGUMENTS

Run from the gitops-app repo (or a component repo linked to it by `.platform-app.yml`; then clone the listed repo with `gh repo clone <org>/<repo>` and run there):

```bash
cplat api list <ARGS>
```

Show the output verbatim: one line per API, `<api>  type <type>  provider <component or ->  consumers <c1,c2 or ->`; an events API bound to a broker ends with `  broker <b>` (`--json` adds `broker`, null when no broker carries it). With no APIs it says `no APIs declared`. A repo still on 4.x fails with `NOT_MIGRATED`; tell the user to run `/platform:update --migrate`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
