---
description: "Run the component's smoke tests against one of its instances. Usage: /instance:verify [<env>] [--base-url URL] [--json]"
---

Run the smoke tests of the current component repo. **Request:** $ARGUMENTS

```bash
cplat instance verify <ARGS>
```

The environment defaults to `dev`. Without `--base-url` the URL comes from the linked system's model for any environment the component has an instance in. Show the output verbatim; the exit code is the result (0 passed). On a failure report the failing check and do not fix it unless the user asks; it is retried once unless `--no-retry` is given.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
