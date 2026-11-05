---
description: "Install a system in this cluster repo: reads its name from the system's gitops repo, renders, opens one PR. Usage: /cluster:add <owner>/<repo> [--name <system>]"
---

Register a system in the cluster repo you are in, with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

The system name comes from `applications/<system>/system.yaml` on `main` of the given repo; `--name` picks one when the repo holds several.

```bash
cplat cluster add <ARGS>
```

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. The preview already runs this cluster's check (`scripts/check.py`) against the system. If it exits non-zero (not a cluster repo, dirty tree, repo without `system.yaml`, unreadable, already listed, or the check names problems such as `set environments.<env>.operators: owner in <repo>` or a missing operator), show the error and its `fix:` line and stop; nothing changed.
2. **Run.** The user's request is the confirmation. Run the same command without `--dry-run`.
3. **Report.** Relay the PR URL and the next step; add nothing else. Merging the PR makes Argo CD sync the system.
4. **Wait** once the PR is merged (merge it with `cplat pr wait <pr> --merge` only when the user asked): `cplat cluster wait --refresh` waits until the cluster's root applications run the head of `main`, `--refresh` right after a merge you made (without it when the user merged). It prints a line each time a root application's state changes and ends `READY:` (exit 0), `RED:` (exit 1: a sync error, a failed sync or `Degraded` at the new revision; show its lines and stop, nothing is retried or rolled back) or `TIMEOUT:` (exit 2: run the same wait again, the command it prints when Argo CD is behind on the revision, at most twice; after the third timeout escalate with cause `environment`: `cplat component ship escalate '<the TIMEOUT line>' --cause environment` inside a ship run, otherwise report the `TIMEOUT:` lines to the user as an environment problem). Never write a polling loop on `kubectl`, `gh` or `cplat`: the wait is the only way to wait.

Read `cplat`'s output whole: never pipe it into `grep`, `head` or `tail` (its last lines carry the decisions, next steps and fixes); use `--json` where the command offers it.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK (only a `platform` escalation is filed by the platform itself, ADR-033).
