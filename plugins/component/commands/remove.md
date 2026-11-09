---
description: "Remove components from the system.yaml of a gitops-app repo; the rendered manifests go in one PR. Usage: /component:remove <component...>"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

One `cplat` call per Bash invocation, from the repo root:

```bash
cplat component remove <ARGS>
```

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

1. **Preview** with `--dry-run`; show it verbatim. Errors carry a `fix:` line; show them and stop.
2. **Run** with `--pr` (one PR for all); do not ask again, because removing the entry and opening the PR is what the user asked for.
3. **Report** the script's output, including what the render deletes.

The script changes `applications/` and `bootstrap/` alone. **Hard rule:** never `kubectl apply`, because the gitops repo and Argo CD own the cluster. Removal deletes the component's manifests, so the cluster prunes it after merge: if the user did not name the component, ask once before running.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
