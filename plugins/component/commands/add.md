---
description: "Add components to the system.yaml of a gitops-app. Usage: /component:add <component...> [--env K=V] [--expose [HOST]] [--uses postgres] [--replicas N] [--generate|--secret NAME=KEY,KEY] [--provides NAME[:TYPE]] [--consumes NAME] [--from-k8s]"
---

Run in the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

One `cplat` call per Bash invocation, from the repo root:

```bash
cplat component add <ARGS>
```

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

1. **Preview** with `--dry-run`; show it verbatim. Errors carry a `fix:` line; show them and stop.
2. **Run** with `--pr` (one PR for all); do not ask again, because the branch and PR are what the user asked for.
3. **Merge an exposure** (spec 142): `--expose` asks for the component to be reachable, which needs the merge; run `cplat pr wait <pr-url> --merge` and do not ask again, because that request already says so. If the user said not to merge, leave the PR open. Without an exposure leave the PR for review, and merge it when the user asked to.
4. **Wait** once the PR is merged (spec 143): `cplat system wait --env dev <component…> --refresh` (new components start in `dev`), `--refresh` right after a merge you made (without it when the user merged). It ends `READY:` (exit 0), `RED:` (exit 1: a sync error, failed sync or `Degraded` at the new revision; show its lines and stop, nothing is retried) or `TIMEOUT:` (exit 2: run the same wait again, the command it prints, at most twice; then escalate with cause `environment`: `cplat component ship escalate '<the TIMEOUT line>' --cause environment` inside a ship run, otherwise report the `TIMEOUT:` lines to the user as an environment problem). Never write a polling loop on `kubectl`, `gh` or `cplat`, because the wait already ends on the synced revision.
5. **Report** the script's output, for an exposure the URL once the wait is `READY:`. Remind the user: wire the new entry if the component needs it (`/component:set <component> --env … --expose …`), and that new components start in `dev` (`instances: {dev: {}}`) — `/instance:promote` moves them on.

`add` writes `components.<name>` with `type`, `lang` and the `dev` instance; `--type`/`--lang` are needed when the component's repo has no `.copier-answers.yml`. It refuses a component that is already there (use `/component:set`).

A component that still has `k8s/base` (platform v1): add `--from-k8s` to seed port, probes, env, replicas and resources from it; afterwards `/platform:update --migrate` removes its `k8s/` directory.

Secrets: `--generate NAME=KEY,KEY` has the platform's credentials Job create random values in the cluster once per environment; `--secret NAME=KEY` declares values read from the secret store. **Hard rule:** values never go to git, because a committed secret stays in the history for good.

The script changes `applications/` and `bootstrap/` alone. **Hard rule:** never `kubectl apply`, because the gitops repo and Argo CD own the cluster. Never add GitHub topics, because that changes the repo's settings outside this PR; report the missing one instead.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
