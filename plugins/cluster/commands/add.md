---
description: "Install a system in this cluster repo: reads its name from the system's gitops repo, renders, opens one PR. Usage: /cluster:add <owner>/<repo> [--name <system>]"
---

Register a system in the cluster repo you are in, with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

The system name comes from `applications/<system>/system.yaml` on `main` of the given repo; `--name` picks one when the repo holds several.

```bash
cplat cluster add <ARGS>
```

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. If it exits non-zero (not a cluster repo, dirty tree, repo without `system.yaml`, unreadable or already listed), show the error and its `fix:` line and stop; nothing changed.
2. **Run.** The user's request is the confirmation. Run the same command without `--dry-run`.
3. **Report.** Relay the PR URL and the next step; add nothing else. Merging the PR makes Argo CD sync the system; the CI check names any operator the system still needs.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
