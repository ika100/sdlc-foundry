---
description: "Set or list values of remote (store-backed) secrets in the local cluster. Usage: /instance:secret set <component>/<env> <secret> <KEY> | list [--env dev]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat instance secret <ARGS>
```

- `cplat instance secret list` shows every declared secret and which remote keys are still missing; `generate` secrets need nothing.
- `cplat instance secret set <component>/<env> <secret> <KEY>` prompts for the value without echo, which only works in a terminal: never ask the user to paste a secret into this chat and never pass it as an argument. Tell them to run it themselves with `! <the command>` (use `--value-stdin` only for piped input).
- Real clusters have their own store (Vault, AWS, GCP): values are managed there, not with this command.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
