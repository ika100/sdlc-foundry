---
description: "Install a system in this cluster repo: reads its name from the system's gitops repo, renders, opens one PR. Usage: /cluster:add <owner>/<repo> [--name <system>]"
---

Register a system in the cluster repo you are in, with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

The system name comes from `applications/<system>/system.yaml` on `main` of the given repo; `--name` picks one when the repo holds several.

```bash
cplat cluster add <ARGS>
```

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. If it exits non-zero (a failed check included), show the error and its `fix:` line and stop; nothing changed.
2. **Run.** The user's request is the confirmation. Run the same command without `--dry-run`.
3. **Report.** Relay the PR URL and the next step; add nothing else. Merging the PR makes Argo CD sync the system.
4. **Wait** once the PR is merged (merge it with `cplat pr wait <pr> --merge` when the user asked): `cplat cluster wait --refresh` waits until the cluster's root applications run the head of `main`, `--refresh` right after a merge you made (without it when the user merged). It ends `READY:` (exit 0), `RED:` (exit 1: a sync error, failed sync or `Degraded` at the new revision; show its lines and stop, nothing is retried) or `TIMEOUT:` (exit 2: run the same wait again, the command it prints, at most twice; then escalate with cause `environment`: `cplat component ship escalate '<the TIMEOUT line>' --cause environment` inside a ship run, otherwise report the `TIMEOUT:` lines to the user as an environment problem). Never write a polling loop on `kubectl`, `gh` or `cplat`, because the wait already ends on the synced revision.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
