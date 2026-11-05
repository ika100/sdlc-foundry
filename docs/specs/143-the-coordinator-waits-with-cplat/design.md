# Design — 143 The coordinator waits with cplat, not hand-written loops

The waits are `cplat` commands built on what exists: the output style and exit codes of `cplat pr wait` (spec 079), the image
rule of `ship.argo_health` (spec 077: a tag in `status.summary.images`, else the pod templates through `ship.workload_images`),
and the run-record attachment of spec 087. `ship.deploy`, `cplat resource upgrade --wait` and `cplat pr wait` keep their
behaviour (non-goal).

## Decisions

1. **Modules.** `scripts/cplat/waits.py` holds what every wait shares: the clock (`now`, `sleep`; tests replace them), the exit
   codes (0 reached, 1 red or escalated, 2 timeout), the time format and the run record (decision 8). `scripts/cplat/envwait.py`
   is `cplat system wait` and `cplat cluster wait`; `scripts/cplat/shipwait.py` is `cplat component ship wait` and
   `cplat system ship next --wait`. `ship.py` and `appship.py` only route to them, so neither grows.
2. **One GitHub ask.** The wanted revision is the head of `main` on GitHub when the wait starts: one `git fetch -q origin main`,
   then `git rev-parse origin/main`. The same fetch brings the content, so the pins of that revision are read locally with
   `git show <rev>:applications/<system>/…` (`model.load_remote`), and "a later commit that contains it" is a local
   `git merge-base --is-ancestor`; nothing else asks GitHub (no `gh api …/compare` as in `ship._ahead`). A revision Argo CD
   reports that the clone does not know after the fetch is newer than the fetch, so it counts as containing the wanted one.
   `--revision <sha>` skips the fetch when the clone has the commit. A failed fetch exits non-zero at once (`ERROR:`).
3. **Which apps.** For `--env E`: `<component>-E` for every component instance in E, `addon-<resource>-E` for every in-cluster
   resource instance (an external one has no app; a backup-only bucket has one, spec 139), and the environment's observability
   app (`addon-observability-E`) when E has instances, as `/system:status` shows them. Named components limit it to their
   apps; a name without an instance in E is refused before waiting. The model is the one of the wanted revision.
4. **One app's state**, judged in this order on each poll (one `kubectl get applications -n argocd -o json` per poll):
   missing → behind (`missing`); revision not reached → behind (`waiting for revision <w7>, Argo CD is at <r7>`); at the
   revision with an `*Error` condition, a `Failed`/`Error` sync operation of that revision, or health `Degraded` → **red**;
   a component whose running images carry no tag (or digest) its pin names → behind (`waiting for image <tag…>, runs …`);
   not `Synced`/`Healthy` → behind (`<sync>/<health>`); else reached. A failed operation of an older revision is not red.
5. **Output** (the `pr wait` style): a progress line `<app>: <sync>/<health> at <r7>[, runs <tag…>]` each time that text
   changes (so every app once at the start), nothing while nothing changes; then one result block whose first line is
   `READY:` (exit 0), `RED:` (exit 1: app, revision, Argo CD's message) or `TIMEOUT:` (exit 2: one line per app behind; when
   one is behind on the revision and `--refresh` was not given, the last line is the same command with `--refresh` added).
6. **Context check (AC-143.6)** before any wait: the context is `--context`, else the configured one
   (`settings.kube_context`), else the current one. The first `kubectl get applications` must answer (else `ERROR: the
   cluster of context X does not answer`), and Argo CD must be there (`no Argo CD in context X`). Without `--context` at least
   one app of the system (any environment), or one root of the cluster repo, must exist there (`context X is not the cluster
   of <system>`). Each exits 1 at once, naming the context.
7. **`--refresh`** annotates `argocd.argoproj.io/refresh=hard` once, at the start, on each app that exists and is not at the
   wanted revision, and prints one line naming them.
8. **Run record (AC-143.10).** The wait attaches to the run its directory runs inside: `runs.current` (the repo's ship run, a
   `runs begin` pointer, `$CPLAT_RUN_PARENT`), else the unfinished system ship run of a gitops-app repo. There it adds its
   seconds to `waiting_s` and one entry `{wait, result, seconds}` to `waits`. Outside a run it records its own run of kind
   `wait` (`outcome` done when reached, else failed) with a `wait` section `{command, result, seconds}`, `result` one of
   `reached`, `red`, `timeout`, `escalated`.
9. **Cluster wait.** The roots are the two applications that sync the cluster repo itself, `platform-operators` and
   `platform-systems` (spec 125, `scripts/render.py`); the wanted revision is the head of the cluster repo's `main`. No image
   rule. The rest is the environment wait.
10. **Ship wait.** It reads `<git dir>/cplat-ship.json` of `--repo` every 5 s (a local file, no API). When the run is finished
    and archived meanwhile, the newest archive of the same spec decides (done or escalated). The phase's age in `TIMEOUT:`
    comes from the run record's open phase, else from the time the wait first saw it.
11. **`next --wait`.** The action of a system ship changes only when a running repo's result is recorded. So the wait watches
    each running repo's clone (a line per phase change, as decision 10), and when one's ship ended (done or escalated) it
    records that result exactly as `cplat system ship repo result <id>` does (the step the command takes next anyway), prints
    its line, and computes the action again; it ends when the action is not `wait`. With `--json` the progress lines go to
    stderr so stdout holds only the JSON.
12. **The release's CI wait.** `/component:release` waits for `main`'s `ci` run on the tagged commit, which is no pull
    request, so `cplat pr wait` cannot do it. `cplat component release wait --commit <sha> [--timeout S]` does it with the same
    exit codes, built on `ship.main_ci`: `GREEN:` 0; `RED:` 1 with the failed runs' log tails; `NO RUN:` 1 when no `ci` push run
    exists 120 s after the start (a Markdown-only commit builds no image); `TIMEOUT:` 2. `gh` goes through `core.run`, so a
    rate limit is waited out (spec 137).
13. **Defaults.** Timeout 540 s for every wait (one Bash call); interval 10 s (environment, cluster, next, release), 5 s
    (ship). `--interval` is a hidden test option.
14. **Command texts and the guard.** Each command named in AC-143.11 says which wait to run, passes `--refresh` right after a
    merge it made, says to run the same wait again on exit 2 at most twice and then to escalate with cause `environment`, and
    says never to write a polling loop. `tests/cplat/test_143_waits_docs.py` fails on a shell loop with `sleep` that polls
    `kubectl`, `gh` or `cplat` in any `plugins/**/commands/*.md` or `plugins/**/agents/*.md`. ADR-082 records the rule.

## Contract

```
cplat system wait --env <env> [<component>…] [--revision SHA] [--refresh] [--timeout 540] [--context C] [--repo-dir DIR] [--system S]
cplat cluster wait [--refresh] [--timeout 540] [--context C] [--repo-dir DIR]
cplat component ship wait [--repo DIR] [--phase plan|build|pr|land|deploy|done] [--timeout 540]
cplat system ship next --wait [--timeout 540] [--json]
cplat component release wait --commit SHA [--timeout 540] [--repo DIR]
```

Environment wait, reached at once:

```
todo-api-dev: Synced/Healthy at 4f2a91c, runs sha-4f2a91c…
addon-postgres-dev: Synced/Healthy at 4f2a91c
READY: 2 app(s) in dev run 4f2a91c
```

Red: `RED: todo-api-dev at 4f2a91c: SyncError: <Argo CD's message>` (exit 1). Timeout (exit 2):

```
TIMEOUT: 1 of 2 app(s) in dev not ready after 540s (wanted revision 4f2a91c)
  todo-api-dev: waiting for revision 4f2a91c, Argo CD is at 9b07c3e
  todo-web-dev: missing
Argo CD has not picked up the revision yet; run it again with a hard refresh:
cplat system wait --env dev --refresh
```

Ship wait: `10:02:11 ship 143-x: phase build` per change; `REACHED: ship 143-x is in phase deploy` (0);
`ESCALATED: ship 143-x: <reason> (cause <cause>)` (1); `TIMEOUT: ship 143-x is still in phase build after 540s of waiting (in it
for 23 min)` (2); no state → `ERROR: no ship run in <dir>` (1).

`next --wait`: progress `10:02:11 todo-api: phase land`; the result is what `next` prints; timeout:
`TIMEOUT: action still wait after 540s; running: todo-api (land), todo-web (build)` (2).

Run record: inside a run `waiting_s += seconds`, `waits += [{"wait": "system wait", "result": "reached", "seconds": 42}]`;
outside one a record `kind: wait`, `wait: {"command": "system wait", "result": "timeout", "seconds": 540}`.
