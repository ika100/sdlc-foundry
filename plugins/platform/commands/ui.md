---
description: "Start the local console: Inbox, Board and System in the browser. Usage: /platform:ui [--no-open] [--port N]"
---

Start the local console. **Arguments:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled. Run the server in the background (Bash `run_in_background`), because it serves until stopped:

```bash
cplat platform ui $ARGUMENTS
```

Read its first output lines and tell the user the URL (`http://127.0.0.1:<port>/`). Run it from a `gitops-app` clone; without `applications/<system>/system.yaml` it says so and exits. The console only reads the system and starts `cplat headless` runs the user confirms; stop it with the user menu or by stopping the background task. More: `docs/console.md`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
