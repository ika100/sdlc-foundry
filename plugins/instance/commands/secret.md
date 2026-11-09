---
description: "Set or list values of remote (store-backed) secrets in the local cluster. Usage: /instance:secret set <component>/<env> <secret> <KEY> | list [--env dev]"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

```bash
cplat instance secret <ARGS>
```

- `cplat instance secret list` shows every declared secret and which remote keys are still missing; `generate` secrets need nothing.
- `cplat instance secret set <component>/<env> <secret> <KEY>` prompts for the value without echo, which works in a terminal: never ask the user to paste a secret into this chat and never pass it as an argument, because both leave the value in logs. Tell them to run it themselves with `! <the command>` (`--value-stdin` takes piped input).
- Real clusters have their own store: values are managed there, not with this command.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
