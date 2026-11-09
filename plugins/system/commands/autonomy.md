---
description: "Show or change autonomy per environment, pause, undo, approve. Usage: /system:autonomy show | set <env> <level> [flags] | pause | resume | undo <event> | approve <repo>#<n>"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

Run `cplat` from the repo root, one call per Bash invocation. Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

```bash
cplat system autonomy <ARGS>
```

1. `show`: run it as is and report the output verbatim.
2. `set`, `pause`, `resume`: **preview** with `--dry-run` and show the plan verbatim. Show errors and stop. Then **run** with `--pr`; opening the pull request (and, to lower autonomy or pause, signalling the engines) is what the user asked for, so ask nothing more. **Pause is urgent:** run it right after the preview.
3. `undo <event>` and `approve <owner/repo>#<n>`: show the `--dry-run` plan, then run it without `--dry-run`.
4. **Report** the output verbatim, including every environment that was `not confirmed`.

`set <env> <level>` takes guardrail flags such as `--routes`, `--max-criticality`, `--max-files`, `--max-lines`, `--runs-per-day`, `--days`, `--undo-window` and `--engine`; `--help` lists them all. Only `environments.<env>.autonomy` changes.

Only `applications/` and `bootstrap/` change, because Argo CD reads the cluster state from there. **Hard rule:** never `kubectl apply`, because a manual apply drifts the cluster from git.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
