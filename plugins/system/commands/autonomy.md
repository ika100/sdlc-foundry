---
description: "Show and change autonomy per environment, pause or resume it, undo or approve what an engine did. Usage: /system:autonomy show | set <env> <level> [flags] | pause | resume | undo <event> | approve <repo>#<n>"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled; one call per Bash invocation, from the repo root:

```bash
cplat system autonomy <ARGS>
```

1. `show`: run it as is and report the output verbatim.
2. `set`, `pause`, `resume`: **preview** with `--dry-run` and show the plan verbatim. Errors name the key and the allowed values: show them and stop. Then **run** with `--pr`; opening the pull request (and, to lower autonomy or pause, signalling the engines) is what the user asked for, so do not ask again. **Pause is urgent:** run it right after the preview.
3. `undo <event>` and `approve <owner/repo>#<n>`: show the `--dry-run` plan, then run it without `--dry-run`.
4. **Report** the output verbatim, including every environment that was `not confirmed`.

`set <env> <level>` takes the flags `--routes`, `--max-criticality`, `--max-files`, `--max-lines`, `--regression-test`, `--second-review`, `--runs-per-day`, `--merges-per-day`, `--per-run KEY=VALUE`, `--days`, `--from`, `--to`, `--timezone`, `--undo-window` and `--engine`. Only `environments.<env>.autonomy` changes. A higher level takes effect after the merge; a lower level or a tighter guardrail takes effect at once by a signal, and the pull request records it.

Rules: only `applications/` and `bootstrap/` change; never `kubectl apply`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
