---
description: "Preflight check of the platform setup (tools, gh scopes, Docker, kube context, plugin versions, this repo's platform version) with a concrete fix per problem. Usage: /platform:doctor"
---

Run the platform doctor. One Bash call:

```bash
cplat platform doctor
```

Show the output verbatim. If it reports outdated plugins, say plainly that **Claude Code must be restarted** to load updated plugin prompts (a running session keeps the old ones). On a cluster with scaled instances it also lists the rows `operator keda` (queue-triggered instances), `operator metrics-server` and `resource metrics`. A `plugins (4.x)` or `system.yaml` warning means the repo is still on 4.x: its fix is `cplat platform update --migrate`. Offer to run the `fix:` commands that are safe (`gh auth refresh -s …`, `claude plugin update …`, `open -a Docker`); never run anything that touches a non-local kube context.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
