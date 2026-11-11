---
description: "Change a component of the system in a gitops-app repo (one PR). Usage: /component:set <component> [--env K=V] [--expose [HOST]] [--uses postgres] [--replicas N] [--resources K=V] [--provides NAME[:TYPE]] [--consumes NAME] [--instance <env> --replicas N]"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

One `cplat` call per Bash invocation, from the repo root:

```bash
cplat component set <ARGS>
```

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

1. **Preview** with `--dry-run`; show it verbatim. Errors carry a `fix:` line; show them and stop.
2. **Run** with `--pr`; do not ask again, because the branch and PR are what the user asked for.
3. **Merge an exposure** (spec 142): `--expose` asks for the component to be reachable, which needs the merge; run `cplat pr wait <pr-url> --merge` and do not ask again, because that request already says so. When the user said not to merge, leave the PR open, so that the user keeps the last word on merging. Other changes: leave the PR for review, and merge it when the user asked to.
4. **Wait** once the PR is merged (spec 143): `cplat system wait --env <env> <component> --refresh` for each environment the change touches, `--refresh` right after a merge you made (without it when the user merged). It ends `READY:` (exit 0), `RED:` (exit 1: a sync error, failed sync or `Degraded` at the new revision; show its lines and stop, nothing is retried) or `TIMEOUT:` (exit 2: run the same wait again, the command it prints, at most twice; then escalate with cause `environment`: `cplat component ship escalate '<the TIMEOUT line>' --cause environment` inside a ship run, otherwise report the `TIMEOUT:` lines to the user as an environment problem). Never write a polling loop on `kubectl`, `gh` or `cplat`, because the wait already ends on the synced revision.
5. **Report** the script's output, and for an exposure the URL once the wait is `READY:`.

`set <component>` with `--env K=V`, `--expose [HOST]`, `--uses postgres`, `--replicas N` or `--resources requests.cpu=100m` merges into the component's existing entry and re-renders. One component per `set`. `--instance <env> --replicas N` changes just that instance and writes `instances.<env>.replicas`; the component needs an instance in `<env>` already, and `--instance` takes nothing but `--replicas`. `--replicas` is refused where a `scale` exists: the error names the key to remove. Edit `scale` in `system.yaml`. `--uses postgres` needs `/resource:add postgres` first.

The script changes `applications/` and `bootstrap/` alone. **Hard rule:** never `kubectl apply`, because the gitops repo and Argo CD own the cluster.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
