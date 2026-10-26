---
description: "Remove components from the system.yaml of a gitops-app repo; the rendered manifests go in one PR. Usage: /component:remove <component...>"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from; one call per Bash invocation, from the repo root:

```bash
cplat component remove <ARGS>
```

1. **Preview** with `--dry-run`; show it verbatim. Errors carry a `fix:` line (typical: component not found, another component still uses it, dirty tree) — show them and stop.
2. **Run** with `--pr` (one PR per invocation, however many components). Removing the entry and opening the PR is what the user asked for; do not ask again.
3. **Report** the script's output, including what the render deletes.

Rules: only `applications/` and `bootstrap/` change; never `kubectl apply`. Removal deletes the component's manifests, so the cluster prunes it after merge: if the user did not name the component, ask once before running.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
