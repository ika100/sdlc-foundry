# Design — 093 Green dev smoke promotes to staging

Builds on 091's interfaces (`smoke.run_smoke`, `smoke.dev_url(env=…)`, `smoke.file_issue`, the `smoke` record
section) and on 062/065/077's pin-dev mechanism. ADR: [041](../../adr/041-staging-follows-green-dev-smoke.md)
(amends ADR-027 decision 4).

## Decisions

- **The staging pin is a gitops-app workflow, `pin-staging.yml`, a twin of `pin-dev.yml`.** `cplat ship deploy` sends it a
  `repository_dispatch` (event `pin-staging`) after a green dev smoke. The workflow pins, opens the PR, closes older
  automatic staging PRs, runs `ci.yml` as a reusable workflow and merges on green, or comments the failed run and leaves
  the PR open. This is the mechanism dev already uses (no branch protection on GitHub Free, ADR-028). It is the
  "self-merging" PR of AC-093.1: nobody in the ship session merges it. The workflow can only pin `staging`, and nothing
  in the platform pins `prod` without `/gitops:promote` (AC-093.13).
- **The decision is made in ship, the pin in the gitops-app.** Ship reads `services.yaml`, `app.yaml` and the staging
  overlay through `gh api`, as `smoke.dev_url` does. It decides on/off, "not in staging yet" and "staging already newer".
  It dispatches only when the decision is "promote". The workflow re-checks only what it can see locally: the service
  runs in staging and the tag is immutable.
- **Setting:** `promotion: {staging: auto | manual}` in `app.yaml` (app-wide), and the same key on a `services.yaml`
  entry (per service; it wins). Unset at both levels means `manual`. `app.yaml.jinja` sets `staging: auto`, so new apps
  have it on. `app.yaml` is in `_skip_if_exists`, so `/shared:update-service` never switches an existing app on
  (AC-093.15). `render.py` validates the key. `prod` is accepted only as `manual`. Every other value is rejected
  (AC-093.13).
- **Only the first linked gitops-app that lists the service is promoted.** This is the app `smoke.dev_url` already
  picks. A service in two products is promoted in the first one only. Ship prints that it skipped the others.
- **Time limit:** pin merge plus Argo `<svc>-staging` Synced/Healthy on the tag within `STAGING_WINDOW_S = 900`, counted
  from the green dev smoke result (AC-093.1). After that, the run escalates as `environment`.
- **Staging smoke reuses 091 unchanged:** `smoke.run_smoke(env="staging")`, the same 600 s limit and one retry, and
  `smoke.file_issue` (its signature already includes `result.env`). Red is escalated by deploy, cause `code`, as in dev.
  No rollback.
- **Evidence for prod comes from the run store**, not from GitHub statuses. `cplat promote … staging prod` reads the
  last 30 days of records (`runs_store.Store.read`) and matches the image by the new `image` field of the smoke section.
- **The evidence commit of a release.** `/svc:release` tags the merge commit of a release PR, and no `cplat ship` run
  ever smoke-tests that commit. When the tag's commit is a merge commit whose diff to its first parent touches only
  release files (`CHANGELOG.md`, `pyproject.toml`, `uv.lock`, `package.json`, `pom.xml`), the evidence is looked up for
  the first parent, and the summary says so. Otherwise it is looked up for the tag's commit. Without this rule, every
  prod summary would warn, and the warning would mean nothing (AC-093.11, AC-093.12).

## Modules

| Module / file | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` | `validate_promotion(services, cfg)` | changed |
| `templates/gitops-app/applications/{{ app_name }}/app.yaml.jinja`, `services.yaml.jinja` | the `promotion` key (on in app.yaml) and its comments | changed |
| `templates/gitops-app/.github/workflows/pin-staging.yml` | pin, PR, supersede, CI, merge or comment | new |
| `templates/gitops-app/scripts/pin.py` | docstring only (staging is pinned by pin-staging too) | changed |
| `scripts/cplat/staging.py` | settings, current staging tag, `decide()`, PR text helpers, record URL | new |
| `scripts/cplat/staging_deploy.py` | dispatch, wait for the PR and the run, Argo health, staging smoke, issue, record, escalation | new |
| `scripts/cplat/ship.py` | calls staging after a green dev smoke, resumes staging, adds `image`/`at` to the smoke section, `describe()` | changed |
| `scripts/cplat/evidence.py` | the prod evidence summary | new |
| `scripts/cplat/promote.py` | shows the summary for `→ prod`, puts it in the PR body and in `--json` | changed |

## Contract

### Setting (AC-093.13, AC-093.15)

```yaml
# app.yaml
promotion:
  staging: auto        # auto | manual; unset = manual
# services.yaml entry
  - name: shop-api
    promotion: {staging: manual}   # overrides app.yaml for this service
```

`render.py` `validate_promotion` runs in `render_app` next to `validate_policies`. It raises `RenderError` with:
- `<file>: promotion must be a mapping, e.g. {staging: auto}`, where `<file>` is `app.yaml` or `services.yaml (<name>)`
- `<file>: promotion.staging must be auto or manual, got '<v>'`
- `<file>: promotion.prod: prod is promoted only by /gitops:promote, never automatically (spec 093); remove the key or set it to manual`
  This message is for any `prod` value other than `manual`, including `true` and `auto`.
- `<file>: promotion.<k> is not a setting (only staging; dev always follows main)`, for any other key

`staging.effective(app_cfg: dict, entry: dict) -> bool`: the entry's `promotion.staging` if set, else app.yaml's, else
`manual`. True only for `auto`.

### Decision (AC-093.1, AC-093.3, AC-093.4, AC-093.5, AC-093.15)

```python
@dataclass
class Decision:
    action: str                 # "promote" | "skip"
    reason: str | None          # the skip reason, printed verbatim
    app: str | None             # gitops-app slug
    app_dir: str | None         # applications/<a>
    service: str                # services.yaml name
    tag: str                    # sha-<40> that dev runs (st["deployed"])
    previous: str | None        # staging's newTag before
    workflow: bool              # the app has .github/workflows/pin-staging.yml

def decide(repo: Path, st: dict, apps: list[str], svc: str, dev: smoke.SmokeResult) -> Decision
```

Checks, in this order (the first match wins; `<svc>` is the services.yaml name):

| check | reason |
|---|---|
| dev outcome red / timed-out | `dev smoke red` |
| dev outcome not-run | `dev smoke not run: <dev.reason>` |
| no linked app lists the service | `<svc> is not in the linked gitops-app` |
| effective setting off | `automatic promotion to staging is off for <svc>` |
| `staging` not in `environments` | `<svc> is not in staging yet: the first promotion is manual: /gitops:promote <svc> dev staging` |
| staging's tag resolves to the build's commit | `staging already runs <tag>: nothing pinned` |
| `compare/<build>...<staging commit>` is `ahead` | `staging already runs a newer build of <svc> (<staging short>): nothing pinned` |
| no `pin-staging.yml` in the app | `the gitops-app <slug> has no pin-staging workflow (update it with /shared:update-service)` |

Then `action = "promote"`.

- The staging tag is read from `applications/<a>/overlays/staging/<svc>/kustomization.yaml` (`images[0].newTag`).
- `sha-<40>` and `sha-<7>` resolve to that sha.
- `X.Y.Z` resolves to `repos/<service slug>/commits/vX.Y.Z` `.sha`.
- An unresolvable tag, or a compare status other than `ahead`/`identical`, means "promote".
- A skip is never escalated.
- `gh` goes through `staging.gh` (seam).

### Dispatch and the workflow (AC-093.1, AC-093.5, AC-093.6, AC-093.7)

Ship sends:

```
gh api repos/<app>/dispatches -f event_type=pin-staging \
  -f client_payload[service]=<svc> -f client_payload[tag]=sha-<40> \
  -f client_payload[spec]=<spec_id> -f client_payload[smoke]=<dev row> -f client_payload[record]=<record url or "">
```

`pin-staging.yml`:
- `run-name: pin-staging <service> <tag>`
- concurrency `pin-staging-<service>`, no cancel
- the same permissions, pinned action SHAs and job layout (`pin` → `ci` → `merge`) as `pin-dev.yml`

The pin job:
1. Validates `service` (`^[a-z0-9][a-z0-9-]*$`) and `tag` (`^sha-[0-9a-f]{40}$`). `record` must be empty or start with
   `https://github.com/`. `smoke` and `spec` are passed only through `env:` and a body file, never interpolated into
   the script.
2. `uv run scripts/pin.py staging <service> <tag>`, then parses `<old>` from `<name> in staging: <old> -> <tag>`.
   `uv run scripts/render.py --check`. No diff → notice `staging already runs <service>:<tag>`, and the run ends.
3. Branch `pin/staging-<service>-<sha7>`, commit `chore(staging): promote <service> to <tag>` (signed off).
4. PR title: `chore(staging): promote <service> to <tag> (automatic, spec 093)`. Body (AC-093.7):

```
Opened automatically under spec 093: a build of `<service>` passed its smoke tests in dev, so staging follows it.

- service: `<service>`
- new tag: `<tag>`
- staging ran before: `<old>`
- dev smoke: <smoke> (spec <spec>), run record: <record | "not stored">

Merges itself when the gitops-app CI passes. If CI fails, the PR stays open and staging keeps `<old>`.
Revert this PR to put staging back on `<old>`.
```

5. Every other open PR whose head starts with `pin/staging-<service>-` is closed with `--delete-branch` and the
   comment `Superseded by <new url> (a newer build of <service> passed dev smoke).` (AC-093.5).

The merge job is the same as in pin-dev, with "dev" replaced by "staging". On red, the comment is:
`CI on this promotion ended with **<result>** (<run url>), so it was not merged and staging keeps \`<old>\`.`
Then it exits 1.

### Ship deploy (AC-093.1, AC-093.6, AC-093.8–AC-093.10)

`staging_deploy.promote(repo, st, apps, svc, dev, context, interval, *, window=STAGING_WINDOW_S) -> tuple[bool, list[str]]`
is called by `ship._smoke_finish` after it has recorded the dev outcome, for every outcome (the decision reports
red/not-run). `ship` then calls `_done` when it returns True. A dev red still escalates as in 091 first, and its lines
end with `Promotion (staging): not promoted: dev smoke red`.

Lines and steps:

```
Promotion (staging): not promoted: <reason>                        (skip; returns True)
staging: dispatched pin-staging <svc> sha-<40> to <app>
staging: pinned <svc> to sha-<40> (<pr url>), was <previous>
Argo CD <svc>-staging: Synced/Healthy
smoke (staging) against <url>: …                                    (SmokeResult.lines())
Promotion (staging): sha-<40> (<pr url>)
Smoke (staging): <row>                                              (091's row format)
```

1. Dispatch (`staging.gh`). An error escalates (cause `environment`):
   `could not start the staging promotion: <error>`.
2. Wait. Every `interval`, find the run by name (`pin-staging <svc> sha-<40>`, as `ship.pin_run` does) and watch it with
   `ship.RunWatch`. Find the PR by head `pin/staging-<svc>-<sha7>` (state all).
   - PR MERGED → step 3.
   - Run red, or PR CLOSED → escalate (cause `environment`):
     `staging pin failed for <svc>: gitops-app CI <conclusion> (<run url>); staging keeps <previous>`. For a closed PR:
     `staging pin failed for <svc>: <pr url> was closed without merging; staging keeps <previous>`.
   - The run concluded with no PR (no diff) → `Promotion (staging): staging already runs sha-<40>`, return True.
3. With `context`, `ship.argo_health(context, f"{svc}-staging", …, images={tag, sha-<7>})`. Not `Synced/Healthy` →
   escalate (cause `environment`): `<svc>-staging is <health> on sha-<40>`. Without `context` → staging smoke is
   not run: `no kube context, so Argo health was not checked (pass --context <kube-context>)`.
4. Steps 2 and 3 together stay within `window` from the call. Past it → escalate (cause `environment`):
   `staging did not run sha-<40> within 15 minutes of the green dev smoke (<last state>)`.
5. Staging smoke:
   - URL: `smoke.dev_url(repo, [app], svc, env="staging")`. None → not-run `no staging URL for <svc>` (AC-093.10).
   - Otherwise `smoke.run_smoke(repo, url, env="staging", spec=…, probe=smoke.liveness_probe(repo))`.
   - Not-run or green → return True (no escalation).
   - Red / timed-out → `smoke.file_issue(result, service_slug, spec_id, image=tag, run_id, shape)` (AC-093.9: 091's draft
     with `env="staging"` gives `[auto] Smoke red in staging: …`, `triage`, `auto-filed`, `smoke-failure`,
     `Signature: smoke:<16 hex>` over slug + `staging` + sorted failing ids, redacted). Then
     `ship.escalate(repo, f"smoke red in staging: {n} failing ({spec_id})", "code", report=lines)`, then
     `ship <spec>: escalated (<reason>); staging keeps running sha-<40> (no automatic rollback: revert <pr url> to go back to <previous>). Resume with /svc:ship <spec>`.
     Return False.

Escalations go through `ship.escalate` with `report=lines`, and the state is saved first.

### State and resume (ship.py)

`st["staging"] = {"state": "skipped"|"dispatched"|"merged"|"pin-failed"|"smoked", "reason", "app", "tag", "previous", "pr", "smoke": {"outcome", "row", "signature", "url"}}`.

On `cplat ship deploy` with `st["deployed"]` set:
- dev smoke red/timed-out → 091's resume (dev smoke only, then staging as above).
- else `staging.state == "pin-failed"`:
  - PR MERGED → continue at step 3.
  - OPEN → escalate again with the stored reason, plus `; fix the gitops-app CI and merge <pr>, or close it`.
  - CLOSED → `Promotion (staging): <pr> closed without merging; staging keeps <previous>`, then done.
- else `staging.smoke.outcome` red/timed-out → `resuming: staging smoke only, against what staging runs now`, then step 5.

`describe()` adds `  staging: <Promotion row>; smoke <row>`.

### Run record (AC-093.8)

- The dev `smoke` section of 091 gains `"image": "sha-<40>"` and `"at": "<UTC ISO>"` (written by ship).
- The staging outcome is the same dict shape (`env: "staging"`, plus `image`, `at`), stored as `smoke.staging` through
  `runs.mutate`. A record without staging has no key.
- Section `promotion`: `{"staging": {"result": "promoted"|"skipped"|"failed", "reason", "app", "tag", "previous", "pr"}}`.
- Recording never raises.

`staging.record_url(run_id) -> str | None`: `https://github.com/<CPLAT_RUNS_REPO>/blob/HEAD/runs/<UTC today Y/m/d>/<run_id>.json`,
or None when no store is configured. The day is predicted (the record path uses `ended_at`). A run that ends on a
later day breaks the link in the staging PR only. The prod evidence uses real paths.

### Prod evidence (AC-093.11, AC-093.12)

```python
def summary(svc: dict, version: str, staging_tag: str | None, *, days: int = 30) -> Evidence  # never raises
@dataclass
class Evidence:
    service: str; version: str; commit: str | None; evidence_commit: str | None; note: str | None
    staging_commit: str | None; dev: dict; staging: dict; issues: list[dict]; warning: str | None
    def lines(self) -> list[str]
    def data(self) -> dict
```

`staging_tag` is the newTag of the gitops-app's local `overlays/staging/<svc>/kustomization.yaml`. Seams:
`evidence.gh`, `evidence.open_store` (default `runs.open_store`), and `evidence.today`.

- **Records:** kind `ship`, `repo == svc["repo"]`, and `smoke.image` (dev) or `smoke.staging.image` in
  `{sha-<E>, sha-<E7>}` for the evidence commit E. The newest record wins (by `at`, else `ended_at`).
- **Link:** `https://github.com/<store>/blob/HEAD/<path>`.
- **No store** (`CPLAT_RUNS_REPO` unset) or an unreachable store → both outcomes are `no record (<why>)`.
- **Issues:** `gh issue list -R <repo> --state open --label <l> --json number,title,url --limit 50`, for `smoke-failure`
  and for `alert`, de-duplicated by URL.

`lines()`:

```
WARNING: v1.4.0 of shop-api has no green staging smoke: <why>          (only when warning)
evidence for shop-api v1.4.0 (commit abc1234):
- evidence commit: def5678 (the release commit only changes CHANGELOG.md, pyproject.toml)   (only when E != commit)
- staging runs: commit def5678 (sha-<40>)          | staging runs: no pinned build
- smoke (dev): passed 3/3, 2026-10-24 14:02 UTC, <link>
- smoke (staging): red (1 failing), 2026-10-24 14:20 UTC, <link>
- open issues (smoke-failure, alert): 2: <url>, <url>        | open issues (smoke-failure, alert): none
```

- Outcome words: `passed <p>/<total>`, `passed on retry`, `red (<n> failing)`, `red (timed out after 600s)`,
  `not run: <reason>`, `no record`.
- `<why>`, the first one that applies:
  1. `staging runs <s7>, not <E7>`
  2. `staging smoke red`
  3. `staging smoke not run: <reason>`
  4. `no staging smoke record`
- An unreadable issue list gives `open issues: unknown (<error>)`. That alone causes no warning.

`promote.py`, for `to == "prod"`, per service:
- after `pick_tag`, it prints `lines()` before the Report, in `--dry-run` too (`--json`: `data["evidence"][<svc>]`)
- `--pr` appends `\n\n## Evidence\n\n` and every service's lines to the PR body
- it never blocks

## Risks

- **Predicted record URL** in the staging PR: see above. The run id is in the URL, so the record can still be found.
- **Two products linking one service:** only the first is promoted (documented). Spec 097 owns multi-app shipping.
- **`repository_dispatch` needs the user's token to have write access on the gitops-app.** Ship already merges gitops
  PRs with it. A 403 escalates as `environment` with gh's message.
- **Tests:** no test reaches GitHub or a cluster. The seams are `staging.gh`, `ship.gh`, `ship.argo_health`/`kubectl`
  through `ship.run`, `smoke.run_recipe`, `smoke.reachable`, `smoke.sleep`, `ship.sleep`/`ship.now`, the autoissue fake
  tracker, `evidence.gh`, `evidence.open_store` and `runs.open_store`. The workflow is checked statically (YAML,
  pinned actions, branch and title strings). `render.py` is run on fixtures.
