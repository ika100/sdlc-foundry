---
description: "Remove a resource from system.yaml; refused while a component uses it. Usage: /resource:remove <name> (for example postgres)"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

```bash
cplat resource remove <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line. While a component still lists the resource under `uses`, the command refuses and names every component that does: remove it there first with `/component:set`. A broker is also refused while an events API is bound to it (the command names the APIs): unbind or remove those events APIs first. An unknown name lists the resources of the system.
2. **Run** with `--pr` (one PR); do not ask again, because the user asked for it.
3. **Say** that removing the resource leaves the data that already exists in place (the running database or bucket store, its volumes and Secret, or an external store and its Secret). A removed in-cluster cache keeps its StatefulSet, volume and Secret until deleted by hand; a removed broker keeps its server, volumes, streams and Secrets (streams and consumers stay with their messages).

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
