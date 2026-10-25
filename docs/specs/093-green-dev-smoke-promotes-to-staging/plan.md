---
spec_id: 093-green-dev-smoke-promotes-to-staging
spec_hash: 2ecb47006b1c
summary: After a green dev smoke, cplat ship dispatches a self-merging pin-staging PR in the gitops-app (setting
  promotion.staging auto|manual, app-wide with per-service override, prod never), waits for Argo, runs staging smoke and
  records it; /gitops:promote … staging prod shows an evidence summary from the run store
tasks:
- id: t1
  title: promotion setting in app.yaml/services.yaml, validated by render.py (prod rejected)
  files: [templates/gitops-app/scripts/render.py, 'templates/gitops-app/applications/{{ app_name }}/app.yaml.jinja',
    'templates/gitops-app/applications/{{ app_name }}/services.yaml.jinja']
  covers: [AC-093.13, AC-093.15]
  parallel_safe: true
  depends_on: []
- id: t2
  title: pin-staging workflow in the gitops-app template
  files: [templates/gitops-app/.github/workflows/pin-staging.yml, templates/gitops-app/scripts/pin.py]
  covers: [AC-093.1, AC-093.5, AC-093.6, AC-093.7]
  parallel_safe: true
  depends_on: []
- id: t3
  title: staging.py decides whether a build is promoted
  files: [scripts/cplat/staging.py]
  covers: [AC-093.1, AC-093.3, AC-093.4, AC-093.5, AC-093.7, AC-093.15]
  parallel_safe: true
  depends_on: []
- id: t4
  title: evidence.py builds the prod evidence summary from the run store
  files: [scripts/cplat/evidence.py]
  covers: [AC-093.11, AC-093.12]
  parallel_safe: true
  depends_on: []
- id: t5
  title: staging_deploy.py dispatches, waits, checks Argo, runs staging smoke, files and escalates
  files: [scripts/cplat/staging_deploy.py]
  covers: [AC-093.1, AC-093.6, AC-093.8, AC-093.9, AC-093.10]
  parallel_safe: true
  depends_on: [t3]
- id: t6
  title: ship deploy promotes after a green dev smoke, resumes staging, records image and time
  files: [scripts/cplat/ship.py]
  covers: [AC-093.1, AC-093.3, AC-093.6, AC-093.8, AC-093.9]
  parallel_safe: true
  depends_on: [t5]
- id: t7
  title: promote to prod shows the evidence summary and puts it in the PR body
  files: [scripts/cplat/promote.py, plugins/gitops/commands/promote.md]
  covers: [AC-093.11, AC-093.12, AC-093.13, AC-093.14]
  parallel_safe: true
  depends_on: [t4]
- id: t8
  title: docs, agents and ship command describe automatic staging and manual prod
  files: [docs/USER-JOURNEY.md, docs/HOW-IT-WORKS.md, templates/gitops-app/CLAUDE.md.jinja, plugins/gitops/agents/deployment.md,
    plugins/svc/commands/ship.md, docs/ARCHITECTURE.md, docs/unattended-delivery.md, site/src/content/docs/scenarios/promote-safely.md,
    docs/CHANGELOG.md]
  covers: [AC-093.14]
  parallel_safe: true
  depends_on: []
- id: t9
  title: ADR-041 listed in the index, ADR-027 links to it
  files: [docs/adr/README.md, docs/adr/027-dev-follows-main-through-pin-prs.md, docs/adr/041-staging-follows-green-dev-smoke.md]
  covers: [AC-093.16]
  parallel_safe: true
  depends_on: []
---

The contract for every task is [design.md](design.md). ADR: [041](../../adr/041-staging-follows-green-dev-smoke.md).
The strings in design.md (reasons, rows, branch, run name, PR title and body, record keys) are binding: the acceptance
tests match them byte for byte. No test may reach GitHub, a cluster or a real devbox. The seams are `staging.gh`,
`ship.gh`, `ship.run`, `ship.sleep`, `ship.now`, `smoke.run_recipe`, `smoke.reachable`, `smoke.sleep`, the autoissue
fake tracker, `evidence.gh`, `evidence.open_store`, `evidence.today` and `runs.open_store`. No plugin or marketplace
version bumps (the release does them).

## t1 — promotion setting in app.yaml/services.yaml, validated by render.py

**Files:** templates/gitops-app/scripts/render.py, templates/gitops-app/applications/{{ app_name }}/app.yaml.jinja, templates/gitops-app/applications/{{ app_name }}/services.yaml.jinja
**Covers:** AC-093.13, AC-093.15
**Goal:** a gitops-app can switch automatic staging promotion on app-wide and per service. New apps have it on, and no
value can make prod automatic. See design.md "Setting".

**Implementation notes:**
- `validate_promotion(services, cfg)` checks `cfg.get("promotion")` (file `app.yaml`) and each service's `promotion`
  (file `services.yaml (<name>)`). Use the four messages of the design exactly.
- Call it in `render_app` right after `validate_policies(cfg)`, so `devbox run validate` / `render.py --check` fail on it.
- `app.yaml.jinja`: add a commented block that explains `promotion` (spec 093: `auto` = a green dev smoke in
  `cplat ship` promotes staging through `pin-staging.yml`; `manual` = only `/gitops:promote`; unset = manual; prod is
  always manual). Then add the active lines `promotion:` / `  staging: auto`.
- `services.yaml.jinja`: one commented example line `#    promotion: {staging: manual}   # overrides app.yaml (spec 093)`.
- Do not change `copier.yml`: `app.yaml` stays in `_skip_if_exists` (existing apps stay off).

**Done when:** the acceptance tests for AC-093.13 and AC-093.15 pass (render on fixtures, rendered template has
`staging: auto`), and `devbox run smoke-*` for gitops-app still renders.

## t2 — pin-staging workflow in the gitops-app template

**Files:** templates/gitops-app/.github/workflows/pin-staging.yml, templates/gitops-app/scripts/pin.py
**Covers:** AC-093.1, AC-093.5, AC-093.6, AC-093.7
**Goal:** a `repository_dispatch` `pin-staging` pins staging, opens a self-merging PR with the AC-093.7 text,
supersedes older automatic staging PRs, and leaves a red PR open with a comment. See design.md "Dispatch and the
workflow".

**Implementation notes:**
- Copy `pin-dev.yml`'s structure: the same pinned action SHAs (the repo's pinned-actions check must pass), permissions,
  and `pin` → `ci` (reusable `ci.yml` with `ref`) → `merge`. Replace dev with staging.
- `run-name: pin-staging ${{ github.event.client_payload.service }} ${{ github.event.client_payload.tag }}`, concurrency
  `pin-staging-<service>`.
- The tag regex is `^sha-[0-9a-f]{40}$` only. Validate `record` (empty or `https://github.com/` prefix). Pass `spec`,
  `smoke` and `record` only via `env:`.
- Capture pin.py's stdout and parse `<old>` from `in staging: <old> -> `.
- Write the PR body with `printf` to a temp file and use `--body-file`. The title, body, branch and supersede comment
  are exactly as in the design.
- Merge job: the same as pin-dev, with the staging comment text of the design.
- `pin.py` docstring: staging is pinned by `pin-staging.yml` after a green dev smoke (spec 093). Prod only by
  `/gitops:promote`. No code change.

**Done when:** the AC-093.1/5/6/7 static workflow tests pass, and `scripts/` pinned-action and YAML checks pass.

## t3 — staging.py decides whether a build is promoted

**Files:** scripts/cplat/staging.py
**Covers:** AC-093.1, AC-093.3, AC-093.4, AC-093.5, AC-093.7, AC-093.15
**Goal:** a pure decision module. Given the ship state, the linked apps, the service name and the dev `SmokeResult`, it
returns a `Decision` with the design's skip reasons in the design's order.

**Implementation notes:**
- `gh(args, *, cwd)` seam, like `smoke.gh` (`check=False`).
- Reading files: reuse `smoke._read`, `smoke._app_dirs` and `smoke._slug` (import them). Pick the entry like
  `smoke.dev_url`: repo slug first, then name, in the first app that lists the service.
- `effective(app_cfg, entry) -> bool`, as in the design.
- `staging_tag(slug, app_dir, svc) -> str | None` from the staging overlay kustomization.
- `resolve(service_slug, tag) -> str | None` (sha-40, sha-7, X.Y.Z → `commits/v<tag>`). `newer(service_slug, build,
  staging) -> str` returns the compare status, via `repos/<slug>/compare/<build>...<staging> --jq .status`.
- `has_workflow(slug)` checks that `contents/.github/workflows/pin-staging.yml` answers.
- `decide(...)`: the order and reasons are exactly those of the design table. It never raises (gh errors count as
  unreadable: "not in the linked gitops-app", or "promote" for the compare step).
- `record_url(run_id)`, and `pr_branch(svc, tag) -> "pin/staging-<svc>-<sha7>"`, `run_name(svc, tag)`.

**Done when:** the AC-093.3/4/5/15 decision tests pass.

## t4 — evidence.py builds the prod evidence summary

**Files:** scripts/cplat/evidence.py
**Covers:** AC-093.11, AC-093.12
**Goal:** `summary(svc, version, staging_tag)` returns an `Evidence` whose `lines()` and `data()` match the design's
"Prod evidence". It never raises.

**Implementation notes:**
- Seams: `gh(args) -> str` (raises `PlatformError` like `promote.gh`), `open_store = runs.open_store`, `today()`.
- Release commit: `repos/<repo>/commits/v<version>`. Read `.sha`, `.parents[].sha` and `.files[].filename`. The
  evidence-commit rule: two parents, every file in the release-file set → first parent, with the note.
- Staging commit: resolve `staging_tag` (sha-40, sha-7 via `commits/<7>`, X.Y.Z via `commits/v<tag>`). `None`/`latest`
  → `staging runs: no pinned build`.
- Records: `runs.configured_repo()`, then `open_store(slug).read(<last 30 days>)`. Parse JSON, skip what is unreadable,
  filter as in the design, newest wins. A `StoreUnreachable` or no store gives `no record (<why>)`.
- Issues: two `gh issue list` calls (labels are ANDed in gh), de-duplicated.
- The warning `<why>` follows the design's order. Timed-out counts as red.

**Done when:** the AC-093.11/12 evidence tests pass (fake store records and fake gh).

## t5 — staging_deploy.py: dispatch, wait, Argo, staging smoke, issue, escalation

**Files:** scripts/cplat/staging_deploy.py
**Covers:** AC-093.1, AC-093.6, AC-093.8, AC-093.9, AC-093.10
**Goal:** `promote(repo, st, apps, svc, dev, context, interval, *, window=900)` and `resume(repo, st, apps, svc,
context, interval)` implement design.md "Ship deploy" and "State and resume". They return `(ok, lines)`.

**Implementation notes:**
- Import `ship` lazily inside the functions (ship imports this module). Use `ship.save_state`, `ship.escalate`,
  `ship.RunWatch`, `ship.argo_health`, `ship.now`, `ship.sleep` and `ship.service_slug`.
- `staging.decide(...)` first. On skip, set `st["staging"]` = `{"state": "skipped", "reason"}`, record
  `promotion.staging`, append `Promotion (staging): not promoted: <reason>`, and return True.
- Dispatch with `staging.gh(["api", f"repos/{app}/dispatches", "-f", "event_type=pin-staging", "-f", …])`. The payload
  `smoke` is `dev.row()`, `record` is `staging.record_url(run_id) or ""`, and `spec` is the spec id.
- Wait loop until `window`: run by name (list the `pin-staging` workflow runs, as `ship.pin_run` does), the PR by head
  branch. Use the design's escalation reasons, all with cause `environment`.
- Staging smoke: `smoke.dev_url(repo, [app], svc, env="staging")`. A None URL → `smoke.not_run("staging", f"no staging
  URL for {svc}", acs)`.
- Record: `runs.mutate(run_id, …)` sets `smoke.staging` = `{**result.section(filed), "image": tag, "at": utc iso}`,
  and the `promotion` section. Both are wrapped so they never raise.
- Red: file the issue, then escalate `code`, in this order (`escalate` ends the record). The lines are the design's
  escalation line, then `Promotion (staging): …` and `Smoke (staging): <row>`.
- `st["staging"]` keeps the design's keys, and every state change is saved.

**Done when:** the AC-093.1/6/8/9/10 deploy tests pass through the seams (fake gh, RunWatch polls, argo, smoke recipe).

## t6 — ship deploy promotes after a green dev smoke

**Files:** scripts/cplat/ship.py
**Covers:** AC-093.1, AC-093.3, AC-093.6, AC-093.8, AC-093.9
**Goal:** wire `staging_deploy` into `deploy`, `_smoke_finish` and `describe()`, and add `image`/`at` to the dev smoke
section.

**Implementation notes:**
- `_smoke_state`: the section becomes `{**result.section(filed), "image": st.get("deployed"), "at": <UTC ISO now>}`.
- `_smoke_finish`, green or not-run path: after `_smoke_state` and the `Smoke (dev)` line, call
  `staging_deploy.promote(repo, st, apps, svc, result, context, interval)`. `apps`, `svc`, `context` and `interval`
  are threaded through `_smoke_step` / `_smoke_not_run`. Default `None`/`[]` keeps the library and not-linked paths
  working, and the decision skips them. `_done` only when it returns True.
- `_smoke_finish`, red path: append `Promotion (staging): not promoted: dev smoke red` before the final `Smoke (dev)`
  line. Do not call staging.
- `deploy` resume: after the existing dev-red resume check, `st.get("staging", {}).get("state") == "pin-failed"` or a
  staging smoke red/timed-out → `return staging_deploy.resume(...)`, then `_done` when ok.
- `describe()`: add `  staging: <row>` when `st["staging"]` is set.
- `main` passes `interval` and `context` (already parsed for deploy) through.

**Done when:** the AC-093.1/3/8/9 ship-level tests pass, and the existing 091 deploy tests still pass.

## t7 — promote to prod shows the evidence summary

**Files:** scripts/cplat/promote.py, plugins/gitops/commands/promote.md
**Covers:** AC-093.11, AC-093.12, AC-093.13, AC-093.14
**Goal:** `cplat promote <svc...> staging prod` (and `--dry-run`) prints each service's evidence summary before the
report. It puts the summary in the PR body and in `--json`, and never blocks.

**Implementation notes:**
- When `to == "prod"`, after `pick_tag`: read the local `app_dir/overlays/staging/<n>/kustomization.yaml` newTag (it
  may be missing), then `evidence.summary(svc, tag, staging_tag)`.
- Text mode: print every service's `lines()` (blank line between services) before `r.emit`. JSON: `r.data["evidence"]
  = {n: ev.data()}`.
- `--pr` body: append `\n\n## Evidence\n\n` + the lines joined by `\n`, after the existing production line.
- Nothing changes for `dev → staging`.
- `promote.md`:
  - step 1 shows the evidence verbatim, warning included. The production gate repeats any WARNING line.
  - The rules line: staging also moves automatically after a green dev smoke in `/svc:ship` when
    `promotion.staging: auto` (spec 093). Switch it off in `app.yaml` or per service in `services.yaml`. `prod` only
    moves through this command, and its PR is never auto-merged.

**Done when:** the AC-093.11/12 promote tests pass (fake `promote.gh`, fake evidence seams), and the existing promote
tests pass.

## t8 — docs, agents and ship command

**Files:** docs/USER-JOURNEY.md, docs/HOW-IT-WORKS.md, templates/gitops-app/CLAUDE.md.jinja, plugins/gitops/agents/deployment.md, plugins/svc/commands/ship.md, docs/ARCHITECTURE.md, docs/unattended-delivery.md, site/src/content/docs/scenarios/promote-safely.md, docs/CHANGELOG.md
**Covers:** AC-093.14
**Goal:** every place that says how staging and prod move describes spec 093. That covers the green dev smoke, the
self-merging `pin-staging` PR, staging smoke, the setting and how to turn it off (`promotion: {staging: manual}` in
`app.yaml` or on a service), and prod as a manual promotion with an evidence summary. None of them still says staging is
never auto-merged.

**Implementation notes:**
- Grep each file for `promot`, `staging`, `auto-merge` and rewrite only those passages.
- `ship.md`: the report gains `Promotion (staging)` and `Smoke (staging)` rows. The escalation reasons are
  `staging pin failed …` and `smoke red in staging …`. The "Next:" line for unchecked criteria no longer tells the user
  to promote staging by hand when promotion is on.
- `ARCHITECTURE.md` line on "the one explicit, human-approved step": now only staging → prod.
- `CHANGELOG.md`: an Unreleased entry for spec 093. Existing gitops-apps are off. To opt in, add
  `promotion: {staging: auto}` to `app.yaml` after `/shared:update-service` has delivered `pin-staging.yml`.

**Done when:** the AC-093.14 docs test passes: each file names the mechanism and the off switch, and no file matches
"staging … never auto-merged".

## t9 — ADR-041 in the index, ADR-027 links to it

**Files:** docs/adr/README.md, docs/adr/027-dev-follows-main-through-pin-prs.md, docs/adr/041-staging-follows-green-dev-smoke.md
**Covers:** AC-093.16
**Goal:** ADR-041 (already written by the architect) is listed in the index. ADR-027 decision 4 says it is amended by
ADR-041 for staging.

**Implementation notes:**
- README: add a row after 040, in the same style: `[041](041-staging-follows-green-dev-smoke.md) | Staging follows a
  green dev smoke through a self-merging pin-staging PR (app-wide setting, per-service override); prod stays a manual
  /gitops:promote with an evidence summary`.
- ADR-027: add `**Amended by:** [ADR-041](041-staging-follows-green-dev-smoke.md) (decision 4, for staging)` under
  the header. Append to decision 4: `Amended by ADR-041: staging now follows a green dev smoke; prod is unchanged.`
- ADR-041: fix only what the index check or the link check reports.

**Done when:** the AC-093.16 test passes, and `scripts/` Markdown link check is green.
