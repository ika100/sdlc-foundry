---
description: "Open a PR that moves a later cluster to the platform release the cluster before it runs, once that one is ready. Usage: /cluster:promote <cluster> [--component-dir NAME=DIR]..."
---

Promote a cluster of the cluster repo you are in, with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

A promotion is a person's decision: run it for the user's request, never as a step of a ship, update or engine run, because the command refuses those runs.

```bash
cplat cluster promote <ARGS>
```

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. If it exits non-zero, show the error and its `fix:` line and stop; nothing changed.
2. **Run.** The user's request is the confirmation. Run the same command without `--dry-run`.
3. **Report.** Relay the PR URL, or the `NOT PROMOTED:` lines, verbatim, and stop. Never merge the PR yourself, because merging it changes what runs on the cluster.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; the platform posts only `platform` escalations and milestone comments itself.
