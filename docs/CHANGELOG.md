# CHANGELOG

All notable changes to the `ika100/claude-platform` marketplace and templates.

Format: each section lists changes for a tagged release. Plugin and template versions are independent — a release may bump only one channel.

## [Unreleased]

- Fix (085): a broken spec names its file, line and fix and no longer blocks other specs (#129)
- **Feature (098): gitops CI checks Components against the service branch's CRDs.** (#110)
  - `cplat ship gitops pr` adds one `Service-ref: <owner>/<repo>@<branch>` line to every gitops PR it opens or reuses.
  - On pull requests the gitops-app CI reads the CRDs of that branch and validates the Components under `applications/` against them, instead of the public catalog. Without a marker nothing changes.
  - `cplat doctor` warns when a gitops-app lacks the `SERVICE_REPOS_READ_TOKEN` secret.
  - **Action:** add the secret `SERVICE_REPOS_READ_TOKEN` (fine-grained, Contents: read on the service repos) to every gitops-app, then run `/shared:update-service` there.

## [4.4.0] — 2026-10-22

**Deploys report what really runs, every PR wait is one tested command, and builds and CI do each thing once.**
- **`cplat ship deploy`** fails at once on a red main CI, a failed pin-dev run or a missing `GITOPS_TOKEN`. It counts Argo only once dev runs the merged image.
- **Image tags are the full commit sha** (ADR-030); `sha-<7>` still works for one release.
- **`cplat pr wait`** waits for any PR and reruns stuck or transiently failed jobs once.
- **Leaner flow:** `/svc:build` runs the CI gate once, and `cplat headless` stops after two idle sessions.
- **Real gates:** gate tools are pinned, `cplat doctor` checks the gates, and sessions claim the issues they work on.
- **Visible drift:** `/shared:status` shows each repo's platform version.
- **Faster platform CI:** platform tests run in about 30 s.

**Action for existing repos:**
1. Run `/plugin marketplace update` (svc 3.3.0, shared 0.13.0, gitops 1.4.2, svc-go/svc-java/web 0.2.6).
2. Run `/shared:update-service` in every repo. Service repos then dispatch `sha-<40>`. Update gitops-apps first, so their pin-dev accepts the full sha and names its run.
3. Run `cplat doctor` once per repo: the new gates section names anything to fix.

- **Fix (077): `cplat ship deploy` reports what really runs.** (#113, #114, #115)
  - It watches the service's CI on main and the gitops-app's pin-dev run, found by its new run name `pin-dev <service> <tag>`.
  - A red main CI or a failed pin-dev run fails it at once, with the log tail. A stuck pin-dev run is rerun once.
  - No pin-dev run 5 min after main's CI passed is an error that names `GITOPS_TOKEN`.
  - Pin PRs carry no checks, so spec 072's AC-072.5 could never fire; it is withdrawn.
  - Argo counts only once `<service>-dev` runs the merged image (`status.summary.images`). The apps named by gitops tasks count once they reached the merged gitops commit.
  - `cplat ship start` and `cplat doctor` refuse a linked repo without `GITOPS_TOKEN`, and the template's pin-dev job now warns instead of a notice.
- **Change (078): image tags are the full commit sha** ([ADR-030](adr/030-image-tags-are-the-full-commit-sha.md)). (#116)
  - The template CI pushes `sha-<40>`, plus `sha-<7>` for one more release, and asks pin-dev for `sha-<40>`.
  - `pin-dev.yml` and `pin.py` accept both formats; the pin branch keeps the short sha.
  - `/gitops:promote` pins `sha-<40>`, or `sha-<7>` for images built before.
- **Feat (079): `cplat pr wait <pr> [-R owner/repo] [--merge]`** waits for any PR with the ship watch, merges on green, and replaces hand-written polling loops. A job that failed on a transient error (artifact download, resolve failure, HTTP 502/503/504, connection reset, TLS timeout) is rerun once before it counts; `ship land` does the same. (#117)
- **Feat (080): leaner builds and unattended runs.** (#118, #119)
  - `/svc:build` Phase 3 runs `devbox run lint-fix` and `devbox run ci` once and spawns only the agent that owns a red gate: the tester only for internals without unit tests, security only for a changed Dockerfile.
  - `cplat headless` stops after two sessions in a row that change nothing, and escalates the run.
- **Feat (081): gates that can fail.** (#120, #123, #126)
  - The templates pin every gate tool: kustomize, kubeconform, ruff, mypy, pip-audit, golangci-lint, govulncheck, maven. `bump_template_pins.py` bumps them (minor/patch) in its weekly PR.
  - `cplat doctor` gets a gates section: the secrets baseline has its filters, scanners are pinned, `ci` and `secrets-baseline` exist, `ci` chains the CI workflow's gates, and CI jobs run the template gates.
  - `cplat adopt` lists the template gates the repo's CI lacks.
- **Feat (082): sessions do not collide.** (#121, #122)
  - `cplat spec new --tracks` and `cplat ship start` claim each tracked issue: an `in-progress` label, the user as assignee, and a comment naming the branch. An issue claimed for another branch stops them (`--take-over` moves the claim); an escalation releases it.
  - The platform CI requires a spec (or the `no-spec` label) for a PR that closes an issue and changes `scripts/`, `plugins/` or `templates/`.
- **Feat (083): `/shared:status` shows each service repo's platform version**, marked `(behind)` when it is older than the installed platform. (#125)
- **CI (084): the platform's own CI takes minutes.** (#124, #127)
  - `pytest tests/cplat` runs in parallel (`-n auto`): 163 s → 29 s locally.
  - The smoke-test matrices no longer cancel healthy siblings (`fail-fast: false`).
  - The Java smoke jobs retry downloads.

## [4.3.0] — 2026-10-22

**Ship runs lose minutes, not an hour, to CI, and they carry their gitops changes.**
- **`cplat ship land`** stops at the first red check and reruns a stale or stuck run once.
- **`devbox run ci`** runs CI's gates locally, and `ship pr` refuses to push while it is red.
- **CI runs once per change** (push only on `main` and tags).
- **The secrets scan answers the same everywhere**: pinned scanners, the standard filters, no gibberish filter.
- **Plans carry gitops tasks**, which ship opens and merges around the deploy.
- **The templates ask for fewer permissions** on the routine steps.

**Action for existing repos:**
1. Run `/plugin marketplace update` (svc 3.2.0, shared 0.12.1).
2. Run `/shared:update-service` in every repo.
3. Run `devbox run secrets-baseline`, audit what it adds, and commit the baseline. It is project-owned, so the update does not replace it.
4. Repos with extra CI jobs add them to their `ci` script.

- **Templates: fewer permission prompts.** The generated `.claude/settings.json` allows the routine, reversible steps the SDLC flows take: `cplat` (it guards its own outward steps: it pushes feature branches only and merges only on green CI), signed-off commits (`git commit -s -m`, which the DCO requires and the old `git commit -m *` rule never matched), `git pull --ff-only`, removing agent worktree branches, `gh pr create/checks/diff/comment`, `gh run rerun/cancel/watch`, `gh workflow run`, `gh issue comment`, CI log and check-run reads, `kubectl --context <ctx> get/describe/logs`, and local `docker build/run --rm/rm/rmi`. Still asked: force push, push to main, reset/clean/rebase/amend, deleting other branches, `kubectl delete`/rollout, manual merges, releases, `docker push`, closing issues. **Action:** `/shared:update-service`.
- **`devbox run ci`: the CI gate locally (#105), svc 3.2.0.** Every template has a `ci` script with the gates its CI workflow runs (`quality` + `test` + `security`; gitops-apps: `validate` + `security`), and `shapes.py` requires it. `/svc:build` Phase 3 ends with one `devbox run ci` on the staged tree, and `/svc:ship` runs it before `ship pr` and after every CI fix. A red check is then found before the push, not after a CI round on the runners. **Action:** `/shared:update-service`; repos with extra CI jobs (e.g. `chart-lint`) add them to their `ci` script.
- **Templates: CI runs once per change (#104).** `ci.yml` in every template triggers `push` only on `main` (and `v*.*.*` tags). Feature, fix and other branches run CI through `pull_request` alone; before, every commit on an open PR ran each job twice, which queued PR jobs behind the duplicates on small self-hosted runner sets. In gitops-apps, pin-dev keeps running CI through `workflow_call`. **Action:** `/shared:update-service`.
- **CI: template pin bumps no longer get stranded.** `bump-template-pins` opens its pull request with a GitHub App token (repository variable `BUMP_APP_CLIENT_ID`, secret `BUMP_APP_PRIVATE_KEY`; `BUMP_TOKEN` still works), so CI runs on it, and the job now fails when it cannot open the pull request instead of passing with a warning. Two weekly bumps had been pushed without a pull request.
- **Docs: the kro spike is kept.** [`docs/spikes/kro.md`](spikes/kro.md) is now on main and linked from ADR-020; rendered manifests stay the only addon backend.
- **Feat (072): `cplat ship land` reports a red check at once and heals stuck checks.**
  - It stops waiting at the first failed check and prints its log.
  - It prints one line per check as each one concludes.
  - A stale check (still in progress after its run completed) is rerun once. So is a run with only queued jobs for `--queue-timeout` (300 s) while nothing else of the PR runs. A second time is an error that names the runner set.
  - `ship deploy` applies the same rules to the open pin PR. (#102)
- **Fix (073): the secrets scan gives the same answer locally and in CI.**
  - The templates pin `detect-secrets@1.5.0` and `trivy@0.74.0`.
  - The template baselines list the standard filters. Before, `filters_used: []` turned them all off, so `# pragma: allowlist secret` had no effect. They no longer carry the gibberish filter, which only some machines can apply.
  - New recipe `devbox run secrets-baseline` refreshes the baseline with fixed flags, keeping audits. It regenerates a baseline without the standard filters (or a missing one) from scratch first.
  - `secrets-scan` passes the same `--disable-filter`, so a hook that rewrites the baseline (line numbers moved) does not add the gibberish filter back.
  - The Python templates call the devbox binary instead of `uv run`.
  - **Action:** run `/shared:update-service`, then `devbox run secrets-baseline`. The baseline is project-owned. Audit what it adds: hits the gibberish filter used to hide on some machines show up once. Then commit it. (#103)
- **Docs (074): a persistent Docker volume is the build cache on self-hosted runners.** `docs/self-hosted-runners.md` recommends one dind `/var/lib/docker` volume per runner set and explains why there is no registry cache (it uploads every layer on each main build). The trigger change is #107 above; spec 074 records both. (#104)
- **Feat (075): `cplat ship pr` enforces `devbox run ci`.** It runs the recipe before pushing and refuses while it is red, printing the tail; spec 075 records this together with #108. (#105)
- **Feat (076): ship carries a spec's gitops changes.**
  - Plans can have gitops tasks (`repo:`, `order: before-merge | after-release`, `files`, `apps`) and `human_steps`; `cplat spec check` validates them.
  - `cplat ship gitops prepare|pr <task>` opens each task as a draft PR during the build.
  - `ship land` merges the `before-merge` PRs before the service PR.
  - `ship deploy` merges the `after-release` PRs once dev runs the pin, then waits for every app they name. A SyncError stops the deploy.
  - The run ends with the human steps as a checklist.
  - The architect plans CRD field removals as expand/contract.
  - Validating Components against the service branch's CRD in gitops CI is the follow-up #110. (#106)

## [4.2.1] — 2026-10-22

**External Helm charts keep their release name.** Taking over a chart that already ran no longer fails with `spec.selector: field is immutable`. **Action:** `/shared:update-service` in gitops-apps with a `helm` external entry. No plugin changes.

- **Fix (069): external Helm charts keep their release name.** The chart Application sets `helm.releaseName` to the service name (`external.helm.releaseName` overrides it). Before, Argo named the release after the Application (`<svc>-<env>-chart`), which changes the chart's selector labels, so taking over a chart that already ran failed with `spec.selector: field is immutable`. **Action:** `/shared:update-service` in gitops-apps with a `helm` external entry, then `uv run scripts/render.py`.

## [4.2.0] — 2026-10-22

**From an approved spec to `dev`, unattended, on GitHub Free.** Approving a spec is the only step left for you:
- **`/svc:ship <NNN>`** plans, builds test-first, opens the PR, merges it once CI is green, and waits until `dev` runs it.
- **`cplat headless`** keeps starting fresh sessions until the run is done.
- **CI gates every merge in code**, so branch protection and auto-merge are not needed.
- **Also new:**
  - an `external` entry type for services the generator cannot express (CronJobs, volumes, Helm charts);
  - `cplat adopt` for repos that were not created from a template;
  - self-hosted CI runners set through repository variables.

**Action for existing products:**
1. Run `/plugin marketplace update`.
2. Run `/shared:update-service` in the gitops-app (pin-dev merge job, external entries) and in every service (CI runner variables).
3. Make sure Actions may open PRs in the gitops-app: `gh api -X PUT repos/<org>/<gitops>/actions/permissions/workflow -F can_approve_pull_request_reviews=true -f default_workflow_permissions=write`.
4. Open each repo interactively once before its first `cplat headless` run.

**Plugins:** svc 3.1.0, shared 0.12.0.

**Unattended delivery on GitHub Free** ([ADR-028](adr/028-unattended-delivery-without-branch-protection.md), [guide](unattended-delivery.md), from a [review of three lan repos](e2e/2026-10-22-review-unattended-delivery.md)). Approve a spec, then `/svc:ship <NNN>` plans, builds, opens the PR, merges it after green CI and waits until `dev` runs it, without branch protection or auto-merge. **Plugins:** svc 3.1.0, shared 0.12.0.

- **065 — merges wait for green CI without branch protection.** The gitops-app's `pin-dev` runs `ci.yml` (now also a reusable workflow with a `ref` input) on the pin branch and merges the pin PR only when it passed; a red CI comments the run and leaves the PR open. Where protection refuses the direct merge it falls back to auto-merge. `/shared:new-service` says what still guards merges on the free plan. **Action:** `/shared:update-service` in each gitops-app.
- **066 — unattended runs stop only when done.** A `Stop` hook in the shared plugin keeps an unfinished `/svc:ship` run going (next step, untraced criteria, red tests) until it is done, escalated (`cplat ship escalate`) or blocked 8 times.
- **067 — `/svc:ship <spec> [--no-merge]`.** Plan → build → `cplat ship pr` → `cplat ship land` (merge only when every reported check passed; red → log tails → fix loop, at most 3 rounds) → `cplat ship deploy` (the merged pin PR of the merge commit, optionally Argo `Synced/Healthy`). Resumable from the state in the git directory.
- **068 — done means verified.** `cplat spec set-status <id> done` needs `verification.md` with `**Result:** pass` (product specs excepted); `--unverified --reason` records an exception; `/svc:specs` shows `/svc:verify` for done specs without evidence.
- **069 — external services** ([ADR-029](adr/029-external-services.md)). A services.yaml entry with `external: {kustomize: <path>}` or `external: {helm: {repoURL, path, revision, imageTag}}` is wired into the environments and pinned like any service, so pin-dev, `/gitops:promote` and `/shared:status` cover services with CronJobs, volumes or charts. **Action:** `/shared:update-service` in each gitops-app (render.py, pin.py).
- **070 — `cplat headless "<prompt>"`.** Fresh `claude -p --permission-mode dontAsk` sessions until a ship run is done or escalated, `--quiet HH:MM-HH:MM`, a log, `summary.log` and a desktop notification.
- **071 — `cplat adopt --type <shape>`.** Brings a repo that was not created from a template onto the platform in one commit without overwriting its files.
- **Fix:** `/shared:update-service` works in a git worktree (it refused a `.git` file).

- **064 — self-hosted CI runners without editing workflows** ([guide](self-hosted-runners.md)). Every template job runs on `${{ vars.CI_RUNNER || 'ubuntu-latest' }}`, the devbox install step runs only on GitHub-hosted runners (self-hosted images ship devbox), and service `docker` jobs take their architecture matrix from `vars.CI_DOCKER_MATRIX` when it is set. Nothing changes for repositories without the variables. **To move a repository to self-hosted runners:** `/shared:update-service`, then `gh variable set CI_RUNNER --body <runner label>` (and `CI_DOCKER_MATRIX` for service shapes). On self-hosted runners the `docker` job no longer reads or writes the GitHub Actions cache (AC-064.5): exporting every layer over a home uplink cost 4–6 min per build.

## [4.1.0] — 2026-10-09

**Second end-to-end run, fixed.** A second feature on the existing todo product with v4.0.0 ([run log](e2e/2026-10-09-todo-second-feature.md)) found four high issues; this release fixes them (specs 060–063):
- **Updates keep your project's content.** The README and your own `devbox.json` recipes are no longer dropped.
- **Plans finished before v4 pass the checks again.**
- **`dev` follows `main`.** Every merge opens a pin PR to `sha-<7>` in the gitops-app, and it merges itself after CI ([ADR-027](adr/027-dev-follows-main-through-pin-prs.md)).
- **No more false alarms from `cplat spec test-diff`** on plan files.

**Action for existing products:** after `/plugin marketplace update`, run `/shared:update-service` in the gitops-app and in every service, then set the `GITOPS_TOKEN` secret in each service repo, using the command the update prints. Until then `dev` stays on its last pin, and the service's CI prints a notice saying why.

**Plugins:** svc 3.0.1, app 1.0.1, gitops 1.4.1, shared 0.11.1, web / svc-java / svc-go 0.2.5.

- **Fixes from end-to-end run 2** ([run log](e2e/2026-10-09-todo-second-feature.md), specs 060–063):
  - **060 — updates keep project content.** `README.md` is project-owned in every template (`_skip_if_exists`, checked by `shapes.py`); new repos still get it. `/shared:update-service` merges `devbox.json` instead of overwriting it: the template's recipes, packages and env vars win, the project's own are kept without reformatting, and the report lists kept entries and every replaced recipe with its old line.
  - **061 — completed plans pass.** The gitops-list and contract rules of specs 045 and 053 apply to `draft` and `in_progress` plans; `completed` and `abandoned` ones get one warning line. Errors name the exact heading line to add.
  - **062 — dev follows main** ([ADR-027](adr/027-dev-follows-main-through-pin-prs.md)). Service CI gets a `pin-dev` job that asks the gitops-app (`repository_dispatch`, secret `GITOPS_TOKEN`) to pin `dev` to `sha-<7>`. The gitops-app's new `pin-dev` workflow and `scripts/pin.py` open a pin PR that merges itself after CI. New gitops repos get auto-merge, new services print the token step, `/shared:update-service` names it for existing ones, and `/shared:status` shows open pin PRs. **Action for existing products:** update the gitops-app and every service, then set `GITOPS_TOKEN` in each service repo; until then `dev` stays on its last pin and CI prints a notice.
  - **063 — `cplat spec test-diff` only looks at test files** (the shape's `test_globs`, never `docs/` or `*.md`), so `plan.md` changes from `task-done` no longer fail it; `/svc:build` forbids treating a failure as a false alarm.

- **Field report: end-to-end run 2** ([run log](e2e/2026-10-09-todo-second-feature.md)): a second feature ("update a notice" → edit a todo's title) on the existing todo product with the released v4.0.0 — spec ambiguity caught as a question, both repos built test-first and verified, deployed and checked live; ~68 min active, $12.10. 17 findings, 4 high: v4's `plan.py` rejects completed pre-v4 plans, skeleton updates drop project `devbox.json` recipes (like the README, spec 060), `dev` never deploys new `latest` images, and `cplat spec test-diff` flags `plan.md`.

## [4.0.0] — 2026-10-08

**Spec-driven development.** A feature is now built from an approved spec ([ADR-026](adr/026-feature-specs.md)): `/svc:spec` writes `docs/specs/<NNN>-<slug>/spec.md` with numbered acceptance criteria and asks *you* its open questions; `/svc:plan` plans the approved spec; `/svc:build` writes failing tests from the criteria first, builds until they pass, has a reviewer verify every criterion and opens the PR. Products work the same way across repos with `/app:spec`, `/app:plan` and `/app:build`. Every check is the tested `cplat spec`; every generated repo checks its specs in CI.

**Breaking:** `/svc:plan-feature`, `/svc:build-feature`, `/app:build-feature`, `/app:run-plan` and `/app:plans` are replaced — the migration table is in the *svc 3.0.0 and app 1.0.0* entry below. After `/plugin marketplace update`, run `/shared:update-service` in each repo, and `/svc:specs migrate` where `docs/backlog.md` still holds `STORY-NNN` stories.

**Plugins:** svc 3.0.0, app 1.0.0, shared 0.11.0, gitops 1.4.0, web / svc-java / svc-go 0.2.4.

**Verified end to end:** a todo product (gitops-app, Python API with Postgres, Next.js web; public repos) went from an empty folder to a verified deployment in 60.5 min; the 17 issues that run found are fixed in this release ([run log](e2e/2026-10-08-todo-spec-driven.md)). Also in this release: `/shared:new-app`, `/shared:triage`, the `cplat` launcher, branch protection for new repos, and secret scans that actually scan in every template.

- **Docs for the release; `/gitops:compose set`** (gitops 1.4.0): the slash command now offers `set <service> [--env K=V] [--expose [HOST]] [--uses ADDON] [--replicas N]` (until now only `/app:build` could call `cplat compose set`). README, HOW-IT-WORKS, ADOPTING, USER-JOURNEY and AGENTS.md describe branch protection of new repos, the `specs` CI check, `cplat spec test-diff` and resume, `worktree.baseRef: "head"`, the gitops operations of product plans and the free local port; the AGENTS.md plan example shows the current format. The website's *Ship a product* scenario starts with `/shared:new-app` and the spec-first product flow, and the [end-to-end run log](e2e/2026-10-08-todo-spec-driven.md) is published under Reference. Leftover "prefix" wording from the `cplat` launcher change removed from three commands.

- **Fixes from the todo end-to-end run, waves 4–5** (specs 051, 052): when `gh pr create` is not allowed (headless, untrusted workspace, declined), `/svc:build`, `/svc:quick-task`, `/svc:fix-bug` and `/app:build` push the branch, write `.git/PR_BODY.md` and end with the exact `gh pr create` command, one per repo for `/app:build` (051). A repo spec sliced from a product plan lists under *Provided by the product* the env variables, addons (with their env names from the addon contract) and exposure the gitops entry wires for it, and `/svc:build` asks only for wiring that is missing (052). All 17 issues of the run are fixed (specs 043–059 `done`).

- **Fixes from the todo end-to-end run, wave 3** (specs 048, 050): new `cplat spec test-diff <red-commit> [files]` tells formatting from real changes in acceptance tests (Python by AST with sorted imports, other languages by whitespace-free text, criterion ids must stay); `/svc:build` runs it after every `lint-fix` and stops only on a real change, so lint no longer blocks a build and tests are never quietly weakened (048). `/app:plan` pushes the spec branch and opens its PR, and `/app:build` warns when the plan on `origin/main` differs from the local one (050).

- **Fixes from the todo end-to-end run, wave 2** (specs 046, 047, 053, 054): `/app:build` runs its repo agents as foreground calls, so headless runs no longer lose them after 600 s, and `docs/ADOPTING.md` has an *Unattended runs* section (046). `/svc:build` resumes an interrupted build: stale staged files are unstaged, the leftover work is committed as `wip(<task>): interrupted` and redone, and the PR asks for a squash merge (047). `plan-check` requires `### Errors` and `### Timeouts` in the contract of every multi-repo plan, so repo specs stop asking the same questions (053). `/shared:new-service` and `/shared:new-app` protect `main` with the shape's CI checks (new `ci_checks` per shape in `shapes.yml`, validated against the workflow job names; no review requirement; a warning with the manual command where the plan does not allow protection) (054).

- **Fixes from the todo end-to-end run, wave 1** (specs 043–045, 049, 055–059; [run log](e2e/2026-10-08-todo-spec-driven.md)):
  - **Templates:** service-python's `tracing.py`/`test_tracing.py` pass the template's own ruff rules (generated repos were red on `main`); platform CI now lints, type-checks and tests the rendered Python templates (043). Python templates exclude `docs/` from ruff, so spec code examples never fail CI (049). Every template sets `worktree.baseRef: "head"` so parallel coders start from the feature branch; `shapes.py check` requires it (044). Template workflows use the platform's action pins, enforced by `pin-actions.py --check`, and one Dependabot group updates all of them (055). `cluster-up` moves to the next free port when 8088 is taken (056). `spec-check` says exactly what happened (057).
  - **Security:** the secrets baselines of gitops-app, service-go, service-java and web-nextjs enabled **no** detect-secrets plugins (the scan checked nothing), library-python only 4; all templates now use the full default set (059). The security agent groups unfixable base-image CVEs into one line (059).
  - **Multi-repo:** new `cplat compose set <service> [--env K=V] [--expose [HOST]] [--uses ADDON] [--replicas N]` changes a composed service; the gitops-app entry of a product plan carries structured `gitops:` operations validated by `plan-check`, and `/app:build` runs them itself and marks the PR *merge first* (045, ADR-011 amended).
  - **Specs:** criteria stay environment-neutral (056); the `spec-format` skill is hidden from the `/` menu (058); `cplat spec trace` no longer counts `__pycache__` files as tests (found while verifying).

- **End-to-end run of the spec-driven platform** ([run log](e2e/2026-10-08-todo-spec-driven.md)): a todo product (gitops-app, Python API, Next.js web; public repos) went from an empty folder to a verified deployment on a local cluster in 60.5 min with PRs #77–#81: product spec with answered questions, per-repo spec slices, failing acceptance tests first, 18/18 and 25/25 criteria verified (the reviewer caught one real gap), resume after interruptions, Postgres persistence checked live. 17 issues logged with workarounds; the blocking ones: the service-python template fails its own lint (platform CI does not lint Python templates), parallel worktrees start from `main` instead of the feature branch, and `/app:build` has no route for the gitops-app repo entry the planner adds.

- **`cplat` on the PATH; the platform runs its own spec workflow** ([ADR-026](adr/026-feature-specs.md), spec 042; shared 0.11.0, gitops 1.3.4): the shared plugin ships `bin/cplat`, so the ~300-character fetch-and-clone line is gone from all 24 commands. `cplat` runs the platform script from the installed marketplace checkout, i.e. the version your plugins came from, **without network**; `CPLAT_PLATFORM` (local checkout) and `CPLAT_REF` (a tag, used by `--ref`) override it, and only a missing checkout falls back to fetching `main`. `/shared:doctor` reports which copy ran. claude.ai and Cowork do not install plugins with `bin/`; the platform targets the CLI and desktop app. This repo's backlog was migrated with `cplat spec migrate` into `docs/specs/001…042` (numbers kept, links rewritten, `STORY-036` superseded); platform changes now start with `/svc:spec`. `migrate` maps free-text legacy statuses (`done (superseded …)`, `partial`, `planned`).

- **Spec contract in every template** ([ADR-026](adr/026-feature-specs.md), [STORY-041](backlog.md)): every template seeds `docs/specs/README.md` (formats, lifecycle, rules) and lists `docs/specs/**` as project-owned. A new warn-only `specs` workflow and `devbox run spec-check` run `scripts/spec-check.sh`, which fetches the platform at the repo's own version (`ref:` in `.platform-version`, a release tag is cached) and runs the new `cplat spec ci`: every spec and plan valid, every criterion of a building or done spec named by a test, as GitHub annotations; `SPEC_CHECK_STRICT=1` turns warnings into a failure (planned default in the next major). `shapes.py check` requires the files, the recipe and the `/svc:spec` (gitops-app: `/app:spec`) rule. Existing repos get the workflow, script and recipe with `/shared:update-service`; `docs/specs/` appears with their first spec.

- **BREAKING — svc 3.0.0 and app 1.0.0: spec → plan → build → verify** ([ADR-026](adr/026-feature-specs.md), [STORY-038](backlog.md), [STORY-039](backlog.md), [STORY-040](backlog.md); app 1.0.0, shared 0.10.0, web/svc-java/svc-go 0.2.4). A feature is a folder `docs/specs/<NNN>-<slug>/` and is built only from an approved spec:
  - `/svc:spec <desc>` — the product-manager writes `spec.md` (acceptance criteria `AC-<NNN>.<n>`, non-goals, open questions); the command asks **you** each open question, folds the answers in and asks for approval. `/svc:spec approve <id>`, `/svc:spec --amend <id> <change>`, `/svc:spec --from-plan <plan> <repo-id>` (multi-repo).
  - `/svc:plan <id>` — the architect writes `design.md` (contract) and `plan.md` (tasks that `cover` criteria); refused for unapproved specs; `cplat spec check` validates coverage, cycles, parallel file overlap and spec drift.
  - `/svc:build <id>` — the tester writes failing, criterion-tagged acceptance tests first; coders (parallel worktrees) work until they pass and never weaken them; quality ‖ tester ‖ security; the new read-only **reviewer** checks every criterion and writes `verification.md`; image; PR listing every criterion. Tasks are marked done as they merge, so a re-run resumes.
  - `/svc:verify [<id>]` (reviewer only, no code changes) and `/svc:specs [--all|index|migrate]` (status with the next command, backlog table, legacy migration).
  - New `svc:spec-format` skill holds every format; product-manager (opus, shape-agnostic) returns open questions instead of guessing; architect, testers (acceptance mode) and coders updated in all four code plugins. `/svc:quick-task` and `/svc:fix-bug` stop when a change would contradict a criterion.
  - **app 1.0.0**: `/app:spec` writes the product spec in the gitops-app repo; `/app:plan` has the planner assign every product criterion to a repo (`acs:` per repo, `spec:` in the plan, ADR-011 amended; `plan-check` refuses an unassigned criterion) with the contract between them; `/app:build` builds every ready repo in parallel, each through its own spec slice; `/app:specs` tracks progress. `cplat spec new --from-plan <plan> <repo>` writes that slice deterministically (product problem, assigned criteria verbatim, contract, `parent:`). `/shared:triage` folds features into specs (`Tracked as spec <id>`). Bootstrap next steps, templates' `CLAUDE.md` and the seeded `docs/backlog.md` (now a generated spec index) follow.
  - `docs/AGENTS.md` fixed (product-manager model, gitops commands that have no agent) and tested against the agent files.

  **Migration**

  | Before (svc 2.x) | Now (svc 3.0) |
  |---|---|
  | `/svc:plan-feature <desc>` | `/svc:spec <desc>` → answer, approve → `/svc:plan <id>` |
  | `/svc:build-feature --plan docs/plan/<slug>.md` | `/svc:build <id>` |
  | `/svc:build-feature <desc>` (one step) | `/svc:spec` → `/svc:plan` → `/svc:build` (no one-step path: a build needs an approved spec) |
  | `/svc:build-feature --no-pm <precise request>` | `/svc:spec <precise request>` (few or no questions), approve, plan, build |
  | `/svc:build-feature --from-plan <plan> <repo>` | `/svc:spec --from-plan <plan> <repo>` → `/svc:plan` → `/svc:build` |
  | `/app:build-feature <desc>` | `/app:spec <desc>` → answer, approve → `/app:plan <id>` |
  | `/app:run-plan <slug>` | `/app:build <id>` |
  | `/app:plans list\|show\|start\|done\|abandon` | `/app:specs [--all\|show\|done\|abandon]` (`start` happens in `/app:build`) |
  | multi-repo plan with free-text `arguments` per repo | `spec:` + `acs:` per repo (old plans stay valid) |
  | `STORY-NNN` in `docs/backlog.md`, plans in `docs/plan/` | `docs/specs/<NNN>-<slug>/`; `/svc:specs migrate` converts existing stories (numbers kept) |

  Update the plugins (`/plugin marketplace update`), then in each repo run `/shared:update-service` for the new `CLAUDE.md` rule. Repos with stories in `docs/backlog.md` run `/svc:specs migrate`; the project-owned backlog is never overwritten by the update.

- **`cplat spec`** ([ADR-026](adr/026-feature-specs.md), [STORY-037](backlog.md)): the deterministic core for spec-driven development. Feature specs live in `docs/specs/<NNN>-<slug>/` (`spec.md`, `plan.md`, …) with acceptance criteria `AC-<NNN>.<n>`. `new`, `check [--require STATUS]` (criteria ids, shape, plan coverage, cycles, parallel file overlap, drift via `spec_hash`), `approve` (refused with open questions), `set-status`, `task-done`, `hash`, `trace` (every criterion named by a test, via the new `test_globs` per shape in `shapes.yml`), `index` (table in `docs/backlog.md`), `list`, `migrate` (legacy `STORY-NNN` stories → spec folders, dry run by default). No command uses it yet; the renamed `/svc:spec|plan|build|verify` commands follow in svc 3.0 (STORY-038 to STORY-042).

- **`/shared:triage`** ([ADR-025](adr/025-issue-triage.md), [STORY-035](backlog.md); shared 0.9.0, svc 2.2.1, `cplat triage`): reads new GitHub issues, proposes a class for each (`bug`, `small-change`, `feature`, `question`, `duplicate`, `wontfix`, `needs-info`), asks you at most three questions per issue and, with your OK, the reporter, then routes: features become `STORY-NNN` with `Tracks: #N` (and a `Tracked as STORY-NNN` comment), bugs go to `/svc:fix-bug`, small changes to `/svc:quick-task`. Labels and comments only after confirmation; issues are never closed; issue text is redacted, fenced and treated as untrusted. Every template ships issue forms (`triage` label, required fields); `shapes.py check` requires them. Existing repos pick the forms up only by copying them; the command works without. The product-manager agent's triage section now points to the command.

- **Spec-driven bootstrap** ([ADR-024](adr/024-spec-driven-bootstrap.md), [STORY-034](backlog.md); svc 2.2.0, shared 0.8.1): creating a service, library, web app or product now leads into planning. The *Next* steps of `/shared:new-service` and `/shared:new-app` start with `/svc:plan-feature "<description>"` (gitops-app and products: `/app:build-feature`). New `/svc:build-feature --plan <path>` builds a reviewed plan without planning again (validates the YAML block, the shape and the story ids). Stories are `STORY-NNN`, plans list `stories:`, the PR names them. Every template seeds `docs/backlog.md` and `docs/plan/` (project-owned) and a `### Spec first` section in `CLAUDE.md`; `shapes.py check` requires both. Existing repos get the `CLAUDE.md` rule with `/shared:update-service`.

- **`/shared:new-app <app.yml>`** (shared plugin 0.8.0, `cplat new-app`, [STORY-033](backlog.md)): creates the gitops-app repo and every component repo of a product from a manifest (`app`, optional `org`/`visibility`, `components` with `name`, `description`, `shape`, optional `data`), then opens one `compose add` pull request for the deployable ones. Each repo goes through the same code as `/shared:new-service`. Creation order is computed (gitops-app, libraries, services, web), validation and `gh repo view` checks run before anything is created (also in `--dry-run`), a failure midway lists the repos that exist and `--resume` continues; nothing is rolled back. Replaces the 6 `new-service` + 4 `compose` commands of the end-to-end scenario.

## [3.2.0] — 2026-10-07

Addresses issue #56 ("Improve performance") and the leftovers of the project-management sample.

- **Work starts right away.** `new-service` next steps, `/shared:new-service`, `/svc:build-feature` and the user journey now say that development starts on a feature branch immediately; nothing waits for the bootstrap CI on `main` (#56, idea 3).
- **Parallel multi-repo execution.** New `/app:run-plan <slug>` (app plugin 0.2.0, [ADR-023](adr/023-parallel-plan-execution.md)): builds every repo whose dependencies are done in parallel, one agent per repo, ends at open PRs, merges only on your word, never pins images. `plan.py ready` computes the wave; the planner writes a `## Contract` section so a backend and its UI can start together (#56, idea 1).
- **Template pins stay current.** Weekly `bump-template-pins` workflow and `scripts/bump_template_pins.py`: renders `service-java`, `web-nextjs` and `service-go`, bumps the rendered manifest (minor/patch), copies literal unique line changes back into the Jinja source and re-renders to verify. Needs a `BUMP_TOKEN` secret for CI to start on the bot's PR (#56, idea 2).
- **k9s in the gitops project**: `k9s` in the devbox and `devbox run cluster-ui` (clear error with the fix when the cluster is not running).
- **Java services wait for their database** at startup (Hikari `initialization-fail-timeout`) instead of crash-looping while PostgreSQL initialises.

- **k9s in the gitops project**: `k9s` is part of the gitops-app devbox and `devbox run cluster-ui` opens it on the local cluster in the `<app>-dev` namespace (clear error with the fix when the cluster is not running). `cluster-up` mentions it when it finishes. Existing projects get it with `/shared:update-service`.

## [3.1.0] — 2026-10-07

Found and fixed while building the project-management sample (`pm-gitops`, `pm-backend`, `pm-web-ui`) end to end. New options and flags only; nothing breaking.

- **CI re-checks a pull request when its title is edited** (all templates and the platform itself): the `pr-title` check ran only on open/push/reopen, so correcting a rejected title never turned it green; a title edit now re-runs CI in its own concurrency group, so it cannot cancel a running build.

- **Worked example** "project management app" on the docs site: Spring Boot + Next.js + PostgreSQL built and run end to end with the platform's commands (also a findings list).

### Database support in the Java template (found while building the project-management sample)

- **service-java `needs_database`** (default false; `/shared:new-service ... --type service-java --data needs_database=true`): Spring Data JPA, Bean Validation, Flyway and the PostgreSQL driver; `application.yml` reads the platform's **`PG*` variables** (the postgres addon injects them; defaults match `devbox run db-up`) and the password never travels inside a URL; Hibernate only validates (`ddl-auto: validate`), the schema belongs to Flyway (`src/main/resources/db/migration`); readiness includes the database; Testcontainers PostgreSQL for the generated tests (Docker needed); `db-up` recipe, env-var docs and CLAUDE.md section. The CI smoke job has a database variant that starts a real PostgreSQL next to the image. Before, a Java service could not use the postgres addon without hand-written wiring.

### UX fixes found while building the project-management sample

- **`/shared:new-service --public`** (or `--visibility public`): create the GitHub repository public instead of the hard-coded private one; the preview says PUBLIC or PRIVATE before anything is created.
- **`/shared:new-service --data KEY=VALUE`**: set template options at creation (for example `needs_observability=false`); the keys are validated against the template's own `copier.yml` and an unknown one lists the valid options. Before, options could only be changed afterwards with `update-service --data`.
- **`/gitops:compose add <svc> --secret-ref NAME`**: expose an existing Secret (for example the one generated for another service) to a service. `secretRefs` was previously impossible to set from the CLI.
- **`devbox run cluster-up` checks the host ports first**: a busy `LOCAL_HTTP_PORT` (or `REGISTRY_PORT`) stops the script before anything is created, names the program that holds the port and suggests a free one; `LOCAL_HTTP_PORT=auto` picks the first free port from 8088.
- Plugins: shared 0.7.3, gitops 1.3.3.

## [3.0.3] — 2026-10-07

### Fixed

- **The image publish failed on arm64 in every generated service and web repo that has the scan step (since 2.1.0).** The per-architecture jobs scan the digest they just pushed with Trivy, which resolves a digest to the host platform (linux/amd64) by default. On the arm64 job it found no matching image ("no child with platform linux/amd64 in index"), failed, and the multi-arch manifest and the `latest` / `sha-*` / version tags were never published. Both Trivy steps now set `TRIVY_PLATFORM: linux/${{ matrix.arch }}`. Pull-request runs never reach this step (it only runs when publishing), so it was invisible to the smoke tests; it surfaced when the platform's todo test application was migrated. A static test now asserts the setting in all four templates. **Existing repos: run `/shared:update-service` and merge**, then check that the next `main` build publishes the manifest.

## [3.0.2] — 2026-10-07

### Fixed

- **web-nextjs: `package.json` is now project-owned** (`_skip_if_exists`), like `pom.xml`, `go.mod` and `pyproject.toml` in the other templates. Until now `/shared:update-service` overwrote it: it silently **reverted dependency versions** (for example a Dependabot bump of TypeScript, which then failed CI with a frozen-lockfile mismatch) and **removed dependencies the project had added**. If you updated a web repo with an earlier release, check `git diff HEAD~1 -- package.json` on the update branch before merging and restore your dependencies (`git checkout HEAD~1 -- package.json pnpm-lock.yaml`). A test now asserts that every template protects its dependency manifest. Found while migrating the platform's own todo web app.

## [3.0.1] — 2026-10-07

### Fixed

- **`/shared:update-service` no longer adds starter files to project-owned paths.** The templates mark `app/**`, `tests/**`, `e2e/**`, `docs/adr/**`, `public/**` and a few docs as `_skip_if_exists` (never overwritten), but copier still *creates* files that are missing there. Since 2.2.0 an update of an existing web app therefore added the new starter UI (`app/globals.css`, `app/_components/*`, `app/not-found.tsx`, `app/error.tsx`, `app/icon.svg`) and a `tests/layout.test.tsx` that asserts a layout the app does not have, which would fail its CI. Updates now remove new files in those paths and say so in the report. **If you already ran an update on a web repo with 2.2.0 or 3.0.0**, delete those files if you do not use the starter UI (`git rm -r app/_components app/globals.css app/not-found.tsx app/error.tsx app/icon.svg tests/layout.test.tsx`). Found while migrating the platform's own test application to the new marketplace.

## [3.0.0] — 2026-10-07

**The project is now `sdlc-foundry`** (formerly *claude-platform*), an agentic SDLC platform. This is a breaking release because the plugin marketplace id changed; nothing else in how you work changes (slash commands keep their names).

### Breaking changes and migration

| What | Before | Now |
|---|---|---|
| Repository | `ika100/claude-platform` (GitHub redirects it) | `ika100/sdlc-foundry` |
| Plugin marketplace id | `ika100-claude` | `sdlc-foundry`, so plugins install as `shared@sdlc-foundry` |
| Documentation site | `ika100.github.io/claude-platform` (gone) | <https://ika100.github.io/sdlc-foundry/> |
| Commits | no sign-off | DCO: `git commit -s` (see CONTRIBUTING) |

**To migrate** (once per machine, in Claude Code):

```text
/plugin marketplace remove ika100-claude
/plugin marketplace add ika100/sdlc-foundry
/plugin install shared@sdlc-foundry        # and svc, gitops, web, svc-java, svc-go, app as you use them
```

then **restart Claude Code**, and in every repository generated from the templates run `/shared:update-service` (it rewrites `.claude/settings.json` and `_src_path` in `.copier-answers.yml`; review the branch it creates). `/shared:doctor` detects plugins still installed under the old marketplace and prints these steps.

### Renamed to sdlc-foundry (breaking), DCO sign-off

- **The project is now `sdlc-foundry`** (formerly *claude-platform*): repository `ika100/sdlc-foundry`, documentation at <https://ika100.github.io/sdlc-foundry/>, and the plugin marketplace id `sdlc-foundry` (was `ika100-claude`), so plugins install as `shared@sdlc-foundry`. The old name contained a third-party trademark and described only part of the scope: this is an agentic SDLC platform. GitHub redirects the old repository URL; the old Pages URL is gone. **Slash commands do not change** (`/svc`, `/gitops`, `/shared`, `/app`, `/web`, `/svc-java`, `/svc-go`).
- **Migration**: `/plugin marketplace remove ika100-claude`, `/plugin marketplace add ika100/sdlc-foundry`, `/plugin install <name>@sdlc-foundry` for each plugin, restart Claude Code; in every generated repo run `/shared:update-service` (the template-owned `.claude/settings.json` and the `_src_path` in `.copier-answers.yml` are rewritten; a regression test covers a repository generated before the rename). `/shared:doctor` detects plugins still installed under the old marketplace and prints these steps.
- **DCO**: every commit of a pull request needs a `Signed-off-by` trailer (`git commit -s`), enforced by the `DCO sign-off` CI job (`scripts/check-dco.py`, bots exempt). See CONTRIBUTING.
- Dependabot's grouped PR titles exceed the title limit, so the `pr-title` check skips Dependabot PRs. A naming guard test keeps the old names out of the tree. Plugins: shared 0.7.2, svc 2.1.2, gitops 1.3.2, web, svc-java and svc-go 0.2.3, app 0.1.4.

## [2.2.0] — 2026-10-07

The platform is now an **open-source project with a documentation site**: <https://ika100.github.io/claude-platform/> (vision, problem statement, client value, usage scenarios, user documentation). It also gets a feedback loop for problems found in the field, a designed starter UI for new web services, and a leaner CI. No breaking changes.

### Upgrading from 2.1.x

- **Plugins**: `claude plugin marketplace update ika100-claude`, then `claude plugin update <name>@ika100-claude` for each installed plugin, then **restart Claude Code** (a running session keeps the old prompts). You get `/shared:report-issue` and the escalation line in every agent and command (shared 0.7.1, svc 2.1.1, gitops 1.3.1, web, svc-java and svc-go 0.2.2, app 0.1.3).
- **Generated repos**: run `/shared:update-service` for pull requests with the new skeleton: `concurrency` that cancels superseded PR runs, monthly grouped Dependabot, the `org.opencontainers.image.source` label in Dockerfiles (links the GHCR package to the repository), `git init -b main` for new repos, and for web repos the test-setup cleanup. **Existing web apps keep their own UI** (`app/**` is project-owned); new web services get the designed starter UI.
- **Forks and contributors**: `main` is protected and the single required status is `ci-success`; see `CONTRIBUTING.md` (new) and run `scripts/ci-local.sh` for the cheap checks.

### Web template: a designed starter UI

- **web-nextjs** now ships a real design instead of a bare heading: plain-CSS design tokens (`app/globals.css`), automatic light/dark themes, fluid typography, a sticky header with brand mark, a hero with gradient headline and actions, a responsive "what's included" card grid, numbered getting-started steps, a branded 404 and error boundary, a favicon, `themeColor`/`viewport` metadata, a skip link, visible focus styles and reduced-motion support. No new dependencies, no network fonts (Docker builds stay reproducible).
- Components live in `app/_components/`; tests cover every component (15 tests, 100% line coverage) and the Playwright smoke test now checks landmarks, the 404 page and a 375px viewport without horizontal scroll. `vitest.setup.ts` cleans up after each test (without it, repeated `render()` calls accumulate).
- Existing services are unaffected (`app/**` is project-owned); new web services get the design.
- e2e: log checks no longer fail intermittently under `pipefail` (`kubectl logs | grep -q` could die of SIGPIPE).

### Documentation site

- **GitHub Pages site** at <https://ika100.github.io/claude-platform/> (Astro Starlight, no analytics, no third-party requests, full-text search): vision, problem statement, client value by role with measured evidence and honest limits, seven usage scenarios, get started, concepts, and the user documentation. Guides, ADRs, the changelog and community pages are synced from the repository's Markdown; the command, shape, configuration and CLI reference pages are generated from the code, so they cannot drift. Built and link-checked in CI (`site` job, part of `ci-success`), published by `pages.yml`; Dependabot covers its npm dependencies.
- `docs/USER-JOURNEY.md` refreshed: a chapter for secrets, Postgres, observability and guard rails, `doctor`/`status`/`report-issue`, and honest limits that match the tested-script design.

### Open source

- **Public repository** under the Apache License 2.0 (`LICENSE`, `NOTICE`), with a contributing guide, Code of Conduct (Contributor Covenant 2.1), security policy (private vulnerability reporting), support guide, CODEOWNERS and a PR template. The three todo test repositories are public too.
- **Legal hygiene**: `THIRD_PARTY_NOTICES.md` and `LICENSES/` (Apache-2.0, CC-BY-4.0, ISC); the web template's icon paths are adapted from Lucide, so `icons.tsx` now carries Lucide's ISC notice (which travels into every generated web app); trademark/affiliation and no-warranty disclaimers, a privacy and no-telemetry statement and an AI-assistance disclosure in the README; the repository is **REUSE 3.3 compliant** (`REUSE.toml`, `reuse lint` in CI) so every file has machine-readable license and copyright data.
- **Repository protection**: `main` requires a pull request and the `ci-success` status, linear history, no force-push or deletion; `v*` tags are immutable; secret scanning with push protection, Dependabot alerts and security updates, CodeQL, and read-only Actions tokens with approval for outside contributors' workflows.
- A pre-publication secret scan (gitleaks over the full history of all four repositories, detect-secrets, issue/PR text and run logs) found no credentials.
- The `/shared:report-issue` command now warns that issues on this repository are public (shared 0.7.1).

### CI usage cut, link check, local CI

- **Platform CI** only runs what a change needs: a `changes` job (plain `git diff`, no third-party action) gates the template smoke jobs and the cplat tests; docs-only pull requests run the validation jobs only (about 2 minutes instead of about 25). Superseded runs of the same PR are cancelled. A final `ci-success` job aggregates everything and is the single required status for branch protection (skipped jobs count as passed; matrix jobs would otherwise block merges forever). The e2e workflow is path-filtered, nightly and cancels superseded PR runs.
- **Dependabot** is monthly and grouped (Actions together; minor and patch together per language ecosystem) in the platform repository and in every template, so a month of updates is a handful of PRs instead of 16; security updates still arrive immediately.
- **Generated repos** cancel superseded PR runs (`concurrency` in every `ci.yml`).
- `scripts/check-links.py` (relative Markdown links, in CI) and `scripts/ci-local.sh` / `devbox run ci-local` (the cheap CI checks locally; `--render` also renders every template).

### Feedback loop and fixes for the old issues

- **`/shared:report-issue`** (`cplat feedback`): when a step fails because a platform template, script or command misbehaves, every agent and command now tells Claude to stop, summarize and offer to file an issue. The draft carries platform/plugin versions, shape, OS and tool availability plus the error tail, with tokens, passwords, e-mail addresses and home-directory names removed; it is shown to you and filed through `gh` only after your OK (a prefilled browser link without `gh`). An unexpected `cplat` crash prints the same pointer. Issue templates (`bug_report`, `feedback`) and labels added; README documents it.
- **Old issues triaged**: #3 (invalid `team: "@org"` label), #7 (`commonLabels`) and #6 (GHCR pull path for local k3d) are obsolete since v2 (no service-level manifests; `cluster-up` creates the pull secret, `doctor` checks `read:packages`). #4: copier tasks now `git init -b main` (the CLI already renamed to `main`). #5: generated Dockerfiles carry `org.opencontainers.image.source` (links the GHCR package to the repo, so CI can push) and ADOPTING has a Troubleshooting section. #8: `/svc:quick-task` PR body no longer lists an unchecked security box; it says what was not run.
- web-nextjs `dependabot.yml` ignores major bumps of the `node` Docker image and `@types/node` (ADR-005: the Node LTS major is bumped deliberately; the bot proposed Node 25 and `@types/node` 26 against a Node 24 image).
- Plugins: shared 0.7.0 (new command), svc 2.1.1, gitops 1.3.1, web/svc-java/svc-go 0.2.2, app 0.1.3 (escalation line in every agent and command).

## [2.1.0] — 2026-10-07

Everything the GitOps repo needs around your services, still declared in one place and rendered by `render.py`: secrets, a Postgres addon, OpenTelemetry observability, Kyverno guard rails, and a hardened CI supply chain. No breaking changes.

### Upgrading from 2.0.x

- **Generated repos**: run `/shared:update-service` (gitops-app: new `render.py`, `local-cluster.sh`, `check-policies.sh`; Python services: standard OpenTelemetry variables; all service/web repos: SHA-pinned actions, scan + SBOM, Dependabot). Nothing changes behaviour until you use a feature.
- **New plugin commands** (restart Claude Code after `claude plugin update`): `/gitops:secret`, `/gitops:addon`; `/gitops:compose` gains `--generate`, `--secret`, `--uses`.
- **Cluster prerequisites only for features you turn on**: External Secrets Operator (`secrets:`), CloudNativePG (`addons.postgres`), Kyverno (`policies:`); `devbox run cluster-up` installs them locally, real clusters need them installed by their owner. OpenTelemetry needs no operator.
- Local credentials: `cluster-up` accepts `REPO_TOKEN` and `PULL_TOKEN` for least-privilege cluster credentials.

### Kyverno guard rails (Phase G, slice 6, ADR-022)

- **`policies:` in `app.yaml`** (opt-in) renders a namespaced CEL `NamespacedValidatingPolicy` per environment with the platform's conventions (numeric non-root, read-only filesystem, no escalation, dropped capabilities, no privileged/host access, requests + memory limit, `part-of` label, allowed registries, no `:latest` outside dev). Audit in dev/staging and Enforce in prod by default; per environment `Audit | Enforce | Off`.
- **Checked before merge**: `devbox run validate` / CI evaluate the rendered overlays and addons offline with the Kyverno CLI (`scripts/check-policies.sh`); the CI downloads the CLI with a pinned checksum.
- `cluster-up` installs Kyverno when `policies:` is declared (`WITH_KYVERNO` overrides); `doctor` checks it. e2e runs the whole stack under `Enforce` and proves a violating Deployment is denied.

### Observability: OpenTelemetry base, optional UI stack (Phase G, slice 5, ADR-021)

- **`addons.observability`** renders an OpenTelemetry Collector per environment (OTLP in, a Prometheus scrape job per service with a `metrics:` path, optional OTLP/HTTP export via `exportTo` + `headersSecret`) and injects the standard `OTEL_*` variables into every service. No operator, no CRDs; works with any OTLP backend.
- **`ui: lgtm`** (optional): `cluster-up` installs Grafana, Tempo, Loki and Prometheus as a shared dev stack at `http://grafana.localhost:8088`. Dev/demo only.
- `shapes.yml` runtime gains `metrics`; `compose add` writes it into `services.yaml`. **service-python** now configures tracing from the standard OTel variables (legacy `OTLP_ENDPOINT` still works) and ships tracing tests; run `/shared:update-service` in Python services.
- `/gitops:addon add observability [--ui lgtm | --export-to URL]`; `doctor` and `status` know the addon. Config addons are pruned, databases never (separate ApplicationSets).

### Addons: Postgres (Phase G, slice 4, ADR-020)

- **`addons:` in `app.yaml` + `uses: [postgres]` on a service**: a CloudNativePG `Cluster` per environment (sizing as scalars or per-env maps) and `DATABASE_URL` / `PG*` injected from the operator's Secret (never in git). The contract, not the implementation, is what services see.
- **`/gitops:addon add|remove|list`** (`cplat addon`), **`compose add --uses postgres`**; `doctor` checks the operator, `status` shows the addon's Argo health. Removing an addon never deletes the data (`prune: false`).
- **`cluster-up` installs CloudNativePG** when `addons.postgres` is declared (`WITH_CNPG=0/1` overrides). e2e proves a real connection with the generated credentials.
- gitops plugin 1.2.0.

### Supply chain (Phase G, slice 3, ADR-019)

- **All GitHub Actions pinned by commit SHA** (91 references, platform and templates) with `scripts/pin-actions.py`; `--check` runs in platform CI. Every generated repo (incl. gitops-app and library-python) gets Dependabot for Actions, which keeps the pins current.
- **Least-privilege workflows**: top-level `permissions: contents: read` everywhere; `packages: write` only on the image jobs.
- **Image scan + SBOM** in the service/web CI: Trivy scans each pushed architecture (fixable HIGH/CRITICAL; blocks `v*.*.*` releases, reports on main) and a CycloneDX SBOM is kept for 90 days.
- **`cluster-up` credential split**: `REPO_TOKEN` (Contents: read) for ArgoCD and `PULL_TOKEN` (read:packages) for GHCR instead of one broad token.

### Secrets with External Secrets Operator (Phase G, slice 2, ADR-018)

- **`secrets:` in `services.yaml`**: `generate: [KEY…]` has ESO create random values in the cluster once per environment (DB passwords, signing keys); `remote: {keys: […]}` reads from a SecretStore (`app.yaml` `secretStore`). Rendered as `ExternalSecret` (+ `Password` generator) and wired into the pod via `envFrom`. Secret values never enter git; secret-looking keys with a value in `env:` are rejected.
- **`devbox run cluster-up` installs ESO** (k3s `HelmChart`, chart 2.12.0) and a `platform-secrets` store over the `secrets-store` namespace; `WITH_ESO=0` skips it.
- **`cplat compose add … --generate NAME=KEY,KEY --secret NAME=KEY`** and **`/gitops:secret set|list`** (`cplat secret`); values come from a hidden prompt or stdin. e2e test covers generated, stable and remote secrets.
- gitops plugin 1.1.0.

### Token efficiency and consistency (Phase G, slice 1)

- **Always-on cost −28%**: the 41 agent/command descriptions (loaded into every session) are tightened from 10.8 KB to 6.3 KB, ≈ **−1.1k tokens** of the ≈ 3.95k always-on total, keeping what routing needs (what it does, when to use it, usage line). `shapes.py check` now enforces valid front matter and a 260-character cap, and fixes seven descriptions that were not valid YAML (unquoted `: `).
- **Model tiering**: `product-manager` runs on sonnet (structured story writing); `architect` and the `app` planner stay on opus (decomposition and design decisions).
- **`/svc:build-feature --no-pm`** skips the product-manager phase for precise requests.

## [2.0.0] — 2026-10-07

**v2: the GitOps repo owns every Kubernetes manifest; services ship an image.** Driven by the end-to-end todo-app test (see [ADR-017](adr/017-gitops-owns-manifests.md) and [BASELINES](BASELINES.md)). Plugin versions: svc 2.0.0, shared 0.6.0, gitops 1.0.0, web 0.2.0, svc-java 0.2.0, svc-go 0.2.0, app 0.1.1, shapes unchanged.

### Breaking changes — migration: [ADOPTING → Migrating from v1 to v2](ADOPTING.md#migrating-from-platform-v1-to-v2-services-no-longer-ship-kubernetes-manifests)

- **Service templates ship no `k8s/`**, no `k3d`/`kubectl`/`k9s`, no `deploy`/`deploy-check`, no `owner_label`. `shapes.py check` forbids `k8s/` in them.
- **gitops-app generates manifests** (`deployment.yaml`, `service.yaml`, `httproute.yaml`, `kustomization.yaml`) from a richer `services.yaml` entry (port, probes, user, volumes, env, secretRefs, replicas, resources, expose, environments) — no remote Kustomize bases. v1 entries (`path:`) are rejected with a pointer to the migration.
- **New services start in `dev` only**; `/gitops:promote` adds `staging`, then `prod`. Promotion pins an **image tag only** (staging `sha-<7>`, prod `X.Y.Z`), verified in GHCR.
- `/gitops:compose` / `/gitops:promote` are thin wrappers over tested scripts; their agents are removed. The v1 platform-wide promote mode is gone (it needed service-owned overlays).
- The per-shape `deployment` agents own the **image** only; `/svc:build-feature` Phase 5 is "Container image".

### Added

- **Gateway API exposure**: `expose:` → `HTTPRoute`; `app.yaml` holds gateway and per-env hostname templates (dev default `{service}.{app}-dev.localhost`). `cluster-up` installs the Traefik Gateway provider (the Gateway API CRDs come with k3s' Traefik chart) and enables Traefik's Gateway provider on k3s, and prints the URLs. Spike-verified on k3s v1.32.5/Traefik 3.3.6; `*.localhost` resolves everywhere (localtest.me / nip.io / lvh.me do not behind rebind-protecting DNS).
- **`cplat compose` / `cplat promote`** with 21 more tests (fake `gh`, real renders); `compose add --from-k8s` seeds an entry from a v1 service; `update-service --migrate` removes `k8s/`.
- `shapes.yml` `runtime:` defaults per deployable shape (validated by `shapes.py check`).
- `docs/adr/017-gitops-owns-manifests.md`; CI renders a fixture product and runs the label check, `kubectl kustomize` and kubeconform on the generated manifests; offline `validate` in generated gitops repos.

### End-to-end test and UX

- **`tests/e2e/run.sh` + `.github/workflows/e2e.yml`** (nightly, on relevant PRs, manual): renders a gitops-app, a Java service and a web app from the real templates, builds the images, starts the platform's own `local-cluster.sh` (Gateway only, local registry), applies the generated manifests and probes the services through the Gateway; asserts non-root numeric users and read-only filesystems. **Its first run caught a regression before release**: on a fresh cluster the Gateway API CRDs applied by `cluster-up` raced with k3s' own `traefik-crd` Helm chart (which installs them) — `cluster-up` now only enables the provider.
- `local-cluster.sh`: `WITH_ARGO=0` (Gateway + namespaces only) and `REGISTRY_PORT` (local registry) modes.
- **`/shared:status`** (`cplat status`): one table per product — pinned tag per environment, CI state of each service's `main`, ArgoCD sync/health (`--context`).
- `docs/HOW-IT-WORKS.md`: diagrams of bootstrap, build, compose/render, promote and exposure, and which test guards what.

### Faster / more stable CI

- **Native multi-arch image builds**: the `docker` job is a matrix (amd64 on `ubuntu-latest`, arm64 on `ubuntu-24.04-arm`, verified available for private repos) that pushes by digest; `docker-publish` merges the digests into one manifest with the usual tags. PRs build amd64 only. Measured: web ≈ 9 → ≈ 3 min, Java ≈ 3 → ≈ 2 min (`docs/BASELINES.md`).
- Docs-only pushes (`**.md`, `docs/**`, `.claude/**`) skip CI on branches (PRs and tags always run); `.github/dependabot.yml` in every service template (language ecosystem, Actions, Docker).
- **`actionlint`** runs over the platform's workflows and every generated repo's workflows in CI (it caught a corrupted expression on its first run). `update-service` picks a unique branch name when one with today's date exists.

### Removed

`SERVICE_REPOS_TOKEN` and Argo credentials for service repos (Argo reads only the gitops repo), `?ref=` handling, service-side `overlays/` and PrometheusRule files (alerting is a gitops-side follow-up).

### Added in the 2.0.0 cycle (phase A)

### Added (v2 work, phase A)

- **`scripts/cplat/cplat.py`** — deterministic, tested implementation of the commands: `new-service`, `update-service`, `doctor`, `shape`; each prints *what I will do* (`--dry-run`) and *what happened / next / how to undo*. 29 tests in `tests/cplat` (CI job `platform-tests`), including regression tests for defects found in the e2e run (module_name for non-Python shapes, stable `_src_path`, update keeps project files).
- **`/shared:doctor`** — preflight: tools, `gh` scopes, Docker, kube context (warns on non-local), plugin versions (with the "restart Claude Code" hint), repo platform version.
- **`.platform-version`** stamp in generated repos; `update-service` reports the changelog range and lists overwritten skeleton files.
- `docs/BASELINES.md`: the numbers v2 is measured against.

### Changed

- `/shared:new-service` (11 KB → 1.8 KB) and `/shared:update-service` (4.8 KB → 1.4 KB) are thin wrappers: preview with `--dry-run`, run, relay the report.
- **Fixed a latent defect:** eleven commands/agents referenced repo-relative fragment files (`plugins/svc/fragments/shape-dispatch.md`, …) that do not exist in a consumer repo (and cross-plugin paths are not reachable), so the model could not read them. They now call `cplat shape`, which prints the shape and the agent routing as JSON; the two fragment files are removed.

## [1.1.1] — 2026-10-06

Fixes found by running the platform end to end on a real todo app (Java API + Next.js UI + gitops-app on a local k3d/ArgoCD cluster): 12 defects, several of which made every generated deployable service undeployable. Plugin versions: shared 0.5.1, gitops 0.3.1. **Existing repos:** run `/shared:update-service` (skeleton fixes: CI, Dockerfiles, devbox), and see the migration notes in the entries below for project-owned files (`k8s/base/deployment.yaml` label value, `pom.xml` patched Tomcat/Jackson for Java).

### Added

- **gitops-app:** `devbox run cluster-up` / `cluster-down` (`scripts/local-cluster.sh`): a local k3d cluster with ArgoCD, repo credentials for private GitHub repos, pre-created `<app>-<env>` namespaces with a GHCR pull secret, and the root Application. Everything the e2e test had to do by hand.

### Changed

- **gitops-app:** `devbox run bootstrap` now requires `KUBE_CONTEXT=<context>` and prints it; before, it applied to whichever kube context was current.

### Fixed

- **web-nextjs:** bootstrap failed (`devbox run -- pnpm install` → `SyntaxError`) because `packageManager: pnpm@12.9.1` was newer than the pnpm devbox provides (11.x). Both pins are now `pnpm@11.22.0` and `shapes.py check` enforces that they match (ADR-003 amendment).
- **All deployable templates:** Dockerfiles ran as a *named* user (`nonroot`, `app`), and Kubernetes cannot verify `runAsNonRoot: true` for a name, so pods stayed in `CreateContainerConfigError` ("image has non-numeric user (nonroot)"). All images now use a numeric `USER`; `shapes.py check` enforces it. Existing repos get this through `/shared:update-service` (the Dockerfile is a skeleton file).
- **service-java:** the image never started: `ADD` created the OpenTelemetry agent jar as `-rw-------` root, so the non-root runtime user got "Error opening zip file or JAR" (`ADD --chmod=0644`). CI smoke jobs now build the Java, Go and web images and start them with a read-only root filesystem and probe them.
- **All deployable templates:** images were `linux/amd64` only, so Apple-silicon k3d/Docker nodes failed with "no match for platform in manifest". The `docker` job now publishes `linux/amd64,linux/arm64` (QEMU) on `main`/tags; PR builds stay amd64. The Go and Java builder stages run on the native platform (`--platform=$BUILDPLATFORM`; Go cross-compiles with `GOOS/GOARCH`, the jar is portable) so only web and Python pay for emulation.
- **gitops `promote` (app mode):** staging pins used `?ref=sha-<short>` which kustomize cannot fetch (only a full commit SHA is a valid ref), and prod pins used `newTag: vX.Y.Z` although CI publishes semver images as `X.Y.Z`. The agent and command now specify the ref and the image tag separately.
- **All deployable templates (since v1.0):** `team: "@owner"` in the Deployment/PrometheusRule labels is not a valid Kubernetes label value, so **no generated service could ever be applied** (Argo: `Deployment ... is invalid: metadata.labels: Invalid value: "@ika100"`). Labels now use the computed `owner_label` (`@my-org/team` → `my-org-team`); CI renders the templates and validates every label (`scripts/check-k8s-labels.py`). **Existing repos:** `k8s/base/deployment.yaml` and `k8s/monitoring/alerts.yaml` are project-owned — change `team: "@x"` to `team: "x"` by hand.
- **All templates:** the generated CI workflow did not trigger on pushes to `main`, so merged code was never built and no `latest`/`sha-*` image was pushed (the GitOps flow depends on them). `main` is now in the push triggers and `shapes.py check` enforces it.
- **All deployable templates:** `k8s/base/deployment.yaml` is now project-owned (`_skip_if_exists`). It is the file every app edits (env vars such as `API_URL`, resources), and `/shared:update-service` silently reverted those edits. `shapes.py check` enforces it. Existing repos: nothing to do, the next update simply stops touching the file.
- **gitops-app:** CI could not `kustomize build` overlays whose remote bases are private service repos (`GITHUB_TOKEN` is repo-scoped). The quality job now uses an optional `SERVICE_REPOS_TOKEN` secret for the full check and otherwise runs the new `validate-static` recipe with a warning.
- **service-java:** `devbox run audit` aborted in CI when `NVD_API_KEY` was unset (empty key → "Invalid API Key"); it now falls back to `trivy fs` (after `mvn dependency:resolve`, with `--offline-scan`, because trivy otherwise fetches poms from Maven Central and gets HTTP 429 on shared CI runners). A fresh project also failed that audit, so `pom.xml` overrides the vulnerable BOM-managed Tomcat/Jackson versions and `.trivyignore` records the one CVE with no fix in Spring 6.x (ADR-009 amendment).
- **gitops-app:** the bootstrap did not run `devbox install`, so `devbox.lock` was left untracked after the first `devbox run`.

## [1.1.0] — 2026-10-06

**Multi-shape platform.** Implements the platform vision ([PRD](requirements/platform-vision.md), ADR-001…016): six repo shapes, shape-aware orchestration, a multi-repo planner, and a documented add-a-shape contract. Existing Python repos are unaffected (their templates are unchanged apart from doc comments); no breaking changes. See [USER-JOURNEY](USER-JOURNEY.md) for the end-to-end walk-through.

Plugin versions: svc 1.1.0, shared 0.5.0, gitops 0.3.0, web 0.1.0, svc-java 0.1.0, svc-go 0.1.0, app 0.1.0.

### Added

- **`shapes.yml`** — machine-readable shape registry (all six shapes, all `status: stable`).
- **`scripts/detect-shape.sh`** — shape detection from `.copier-answers.yml` with sniffing fallback (ADR-008), plus `scripts/test-detect-shape.sh` fixtures.
- **`scripts/shapes.py`** — validates `shapes.yml` and checks it against templates, plugins and the PRD §4 table.
- **`plugins/shared/fragments/shape-detection.md`** — canonical detection procedure for commands and agents.
- **`scripts/shapes.py check` now enforces the add-a-shape contract** (PRD §4.1): canonical devbox recipes, CLAUDE.md, plugin enablement in the template settings, plugin agents, detection registration. Documented in the new `docs/templates.md`.
- CI job `validate-shapes`; `devbox run shapes-check` and `devbox run test-detect` (included in `devbox run smoke`).

### Plugins

- **shared 0.5.0** (docs/UX pass): new `/shared:update-service [--ref] [--data k=v]` — `copier update` cannot work on repos bootstrapped by `/shared:new-service` (the template has no git history of its own), so the command re-applies the template with the repo's recorded answers on a review branch and lists overwritten skeleton files. `/shared:new-service` now records a stable `_src_path`, no longer passes the Python-style `module_name` to non-Python templates (it had turned the Go module path into `my_saas`), and runs its clone+copier steps in one shell. All docs that pointed at `copier update` now point at `/shared:update-service`; ADOPTING has a shape table, an end-to-end product flow, and a corrected migration guide (`/shared:check-quality`, not `/svc:check-quality`).
- **shared 0.4.0**: `/shared:new-service` gains `--type <shape>` (aliases `--library`, `--web`, `--gitops`); template, topic and `--python` handling are read from `shapes.yml`. With no flag it still produces a `service-python` repo. Requesting a `planned` shape fails with a clear message.

- **svc 1.1.0** (phase 2): every orchestration command resolves `$SHAPE` and routes coder/tester/deployment/observability/release to `$SHAPE_PLUGIN:<role>` via the new `plugins/svc/fragments/shape-dispatch.md`. The architect plan metadata gains a required `shape:` field (missing → `service-python` with a deprecation notice). `/svc:build-feature` gains `--from-plan <path> [<repo-id>]` (ADR-011) and skips deployment for non-deployable shapes. `/svc:release` dispatches to the shape's release agent. `/shared:check-quality` and the quality/security agents are shape-neutral.

- **gitops 0.3.0** (phase 3): new `compose` agent and `/gitops:compose add|remove <service...>`; `/gitops:promote` works in `gitops-app` repos, from a service repo via `.platform-app.yml`, with batch/`--all` and one PR per invocation.

- **web 0.1.0** (new, phase 4): `coder`, `tester`, `deployment`, `observability`, `release` agents for Next.js repos, plus a SessionStart hook that runs `devbox run install`. The `svc` SessionStart hook now only runs `uv sync` when `pyproject.toml` exists.

- **app 0.1.0** (new, phase 5): `/app:build-feature <desc>` (PM stories per repo → `planner` agent → validated topo-sorted multi-repo plan; **plan-only**, ADR-007) and `/app:plans list|show|start|done|abandon` (ADR-011 lifecycle).
- svc: `/svc:build-feature --from-plan` no longer edits the plan file (it lives in the gitops-app repo); progress is recorded with `/app:plans`.

- **svc-go 0.1.0** and **svc-java 0.1.0** (new, phase 6): `coder`, `tester`, `deployment`, `observability`, `release` agents for Go and Spring Boot repos; releases follow ADR-012 (`pom.xml` via `versions:set`; Go has no version file — the git tag is the version).

### Templates

- **service-go** (new, phase 6): chi + slog, golangci-lint v2, `govulncheck`, optional Prometheus `/metrics`, distroless static image with ldflags version, pre-resolved `go.mod`/`go.sum`. Verified by running `devbox run test`/`quality`/`audit` on rendered projects (both observability variants).
- **service-java** (new, phase 6): Spring Boot 3.5 / JDK 21 / Maven, Spotless (google-java-format) + Checkstyle, JUnit 5 + JaCoCo 80% gate, Actuator probes, optional Micrometer Prometheus + OTel Java agent, distroless java21 image. Verified by running `devbox run lint`/`test`/`quality` on rendered projects and booting the jar.
- ADR-009 / ADR-010 amendments record where the implementation differs from the ADR text.
- **gitops-app** generates a root Argo Application (`bootstrap/<app>-root.yaml`, app-of-apps) and a human-only `devbox run bootstrap` recipe, so after one `kubectl apply` per cluster all changes deploy through merged PRs; `validate` also schema-checks it with kubeconform (ADR-014 amendment).
- **gitops-app** gains `scripts/plan.py` (plan validation + lifecycle), `devbox run plan-check` (part of `validate`), and enables the `app` plugin.
- **web-nextjs** (new, phase 4): Next.js 16 App Router, TypeScript strict, pnpm (`packageManager` pinned, `pnpm-workspace.yaml` with `allowBuilds`), Node 24 LTS pinned in `package.json`/`devbox.json`/Dockerfile, Vitest + Testing Library (80% gate), optional Playwright (`needs_e2e`), optional `/api/metrics` + OpenTelemetry (`needs_observability`), `/api/health` + `/api/ready`, standalone-output multi-stage non-root Dockerfile, Kustomize base/overlays, CI. The rendered project is verified in CI (`pnpm install`, lint, typecheck, test, build).
- **gitops-app** (new, phase 3): product-scoped GitOps repo — `applications/<app>/{services.yaml,applicationset.yaml,overlays/<env>/<service>/}` generated by `scripts/render.py`, devbox recipes (`render`, `validate` = render-check + kustomize + kubeconform, `security`), CI, CLAUDE.md. See the ADR-013/014 amendments.
- `/shared:new-service` gains `--app <org>/<repo>` (writes `.platform-app.yml`).

### Documentation

- `docs/templates.md` (new): template authoring guide with the pitfalls found while building the Go, Java and web shapes. README, ARCHITECTURE, ADOPTING (web and gitops-app migration sections), AGENTS updated; PRD marked implemented.

### Migration

- Run `/plugin marketplace update`. No `copier update` needed for existing Python repos (their templates are unchanged).
- New repos: `/shared:new-service <name> --web | --gitops | --type service-java | --type service-go`.

## [1.0.1] — 2026-05-22

CI-only patch. No plugin or template behavior changes.

### Fixed

- **CI smoke-test** no longer fails on `devbox: not found`. The copier templates' bootstrap `_tasks` (which invoke `devbox install`) are now skipped via `--skip-tasks` in `.github/workflows/ci.yml`; CI verifies template rendering only. The full render-and-bootstrap path remains covered by `devbox run smoke` locally. Broken since v0.2.1.

## [1.0.0] — 2026-05-19

Phase 3 of the agentic efficiency overhaul. **First stable major.** Orchestration commands restructured for parallelism and to skip wasted work; per-command preludes deduplicated.

### Breaking changes

- **`/svc:build-feature` phase numbering changed.** The old Phase 3a (intermediate quality gate), Phase 4 (tester), Phase 4a (security) are merged into a single **Phase 4 — parallel QA fan-out** that runs quality + tester + security in one orchestrator turn. Phase 5 stays "deployment"; old Phases 6/7 are unchanged. Any consumer scripts that grep transcripts for `Phase 4a complete` need updating.
- **`/svc:fix-bug` phase numbering changed.** Old "Phase 5 — Commit and open PR" is now "Phase 4 — Commit and open PR" after the redundant intermediate phase was dropped in v0.1.4.
- **`/svc:quick-task` phase numbering changed.** Old "Phase 4 — Commit and open PR" is now "Phase 3 — Commit and open PR".

### Plugins

- **svc 1.0.0**:
  - **Scope classifier** (`/svc:build-feature` Phase 0a): the orchestrator now classifies the request before running PM + Architect. Typos / docs / one-file tweaks are routed to `/svc:quick-task`; bug reports are routed to `/svc:fix-bug`; standard features get a "confirm full pipeline?" prompt. Saves PM + Architect on requests that don't need them.
  - **Parallel QA fan-out** (`/svc:build-feature` Phase 4, `/svc:quick-task` Step 2): quality + tester + security (build-feature) or quality + tester (quick-task) now spawn in a single orchestrator turn, mirroring `/shared:check-quality`. Wall-clock is the longest leg, not the sum.
  - **Pre-computed subagent context:** every orchestrator now computes `$PROJECT_MAP` (top-level dirs) and `$TOUCHED_FILES` (`git diff --name-only $BASE_REF..HEAD`) up-front and prepends them as `<project-map>` / `<touched-files>` blocks to every subagent prompt. Each agent saves 2–5 exploratory Glob/Grep calls.
  - **Phase prelude fragment**: new `plugins/svc/fragments/phase-prelude.md` documents the canonical pre-Phase-1 workflow (git status check, branch creation, base-ref capture, context pre-compute). The three orchestration commands now reference it instead of carrying drifted copies.

### Migration

- Run `/plugin marketplace update` to pull svc 1.0.0.
- Existing service repos do **not** need a `copier update` for this release — only plugin contracts changed, no template files.
- If you watch for specific phase headers in agent output (CI greps, dashboards), update them per the breaking changes above.

## [0.4.0] — 2026-05-19

Phase 2 of the agentic efficiency overhaul: boilerplate that the `svc` agents used to regenerate on every invocation is now part of the `service-python` Copier template. Agents become verify-and-extend instead of generate-from-scratch. Non-breaking for consumers — run `copier update` to pull the new template files.

### Templates

- **service-python**: new pre-rendered observability files under `src/{{ module_name }}/`:
  - `tracing.py` — OpenTelemetry OTLP exporter wired via `OTLP_ENDPOINT` env var.
  - `main.py` now exposes `/metrics` (Prometheus `generate_latest`) and conditionally calls `configure_tracing()`.
  - `k8s/monitoring/alerts.yaml` — default PrometheusRule with `HighErrorRate`, `HighLatencyP95`, `PodRestarting`.
  - `docs/env-vars.md` — documents `LOG_LEVEL`, `OTLP_ENDPOINT`, `METRICS_PORT`, and `DATABASE_URL` when applicable.
- **service-python**: new pre-rendered Alembic scaffolding (gated by `needs_migrations`):
  - `alembic.ini` with `script_location = migrations`.
  - `migrations/env.py` that requires `DATABASE_URL` from env and leaves a TODO for wiring `target_metadata`.
  - `migrations/script.py.mako` with typed `upgrade()` / `downgrade()` signatures.
- **service-python copier.yml**: new `_exclude` block skips `alembic.ini` and `migrations/` when `needs_migrations=false`. `_skip_if_exists` extended with `docs/env-vars.md` and `k8s/monitoring/**` so they're project-owned after bootstrap.

### Plugins

- **svc 0.2.0**: three agents slimmed against the template now owning the boilerplate:
  - `observability.md`: 158 → 45 lines. Verifies the templated logging/metrics/tracing files exist, then focuses on service-specific instrumentation and alert tuning.
  - `deployment.md`: 100 → 61 lines. References the template's `Dockerfile` + `.github/workflows/ci.yml` instead of restating the YAML; verifies CI integrity and the dry-run gate.
  - `migrations.md`: 139 → 77 lines. Skips the `alembic init` boilerplate (template handles it); focuses on wiring `target_metadata`, generating + verifying migrations, and maintaining the runbook.

## [0.3.0] — 2026-05-19

Devbox awareness extended to every plugin and the platform repo itself. No breaking changes — repos without `devbox.json` see the new hooks as a silent no-op.

### Plugins

- **shared 0.3.0**: new `hooks/hooks.json` with a `SessionStart` hook. Checks `devbox` is on `PATH` (prints install URL if missing, exits 0 — non-blocking) and runs `devbox install` if a `devbox.json` is present. Makes any consumer repo that uses the `shared` plugin (library repos, GitOps repos, the platform repo) devbox-aware out of the box.
- **gitops 0.2.0**: same new `hooks/hooks.json` as `shared`. GitOps repos that add a `devbox.json` (for `kubectl`, `argocd`, `kustomize`) get automatic sync; older GitOps repos see a no-op.
- **svc 0.1.3**: existing `SessionStart` hook hardened with the same `command -v devbox` host-check, plus a `[ -f devbox.json ]` guard so it no-ops cleanly in non-devbox directories.

### Platform repo

- New root `devbox.json`: pins `jq`, `python@3.13`, `uv`, `git`, `gh`, and `init_hook`-installs `copier` (invoked at runtime via `uv tool run --from copier copier ...` so it's reachable from inside the devbox PATH). New scripts: `validate` (jq-checks marketplace + plugin manifests + hook files), `smoke-service`, `smoke-library`, `smoke` (runs all three). Smoke recipes run individual `devbox run lint` + `devbox run typecheck` instead of the chained `devbox run quality` recipe — devbox 0.17.2 has a wrapper bug that mis-evaluates the chained recipe even though both children succeed; tracked separately.
- `CLAUDE.md` smoke-test section rewritten to use `devbox run validate` / `smoke-service` / `smoke-library` instead of host-installed `jq` + `copier`. Only host requirement is `devbox` itself.
- `docs/AGENTS.md` documents the new SessionStart hooks under the golden-rule section.

## [0.2.1] — 2026-05-19

Bugfix release. Resolves the two issues raised after the `/shared:new-service` UX overhaul ([#1](https://github.com/ika100/claude-platform/issues/1), [#2](https://github.com/ika100/claude-platform/issues/2)).

### Templates

- **service-python + library-python (#1)**: `_tasks` in `copier.yml` now runs `devbox install` and `devbox run -- uv sync --all-extras` to materialize `devbox.lock` and `uv.lock`, then makes an initial `chore: bootstrap` commit. A fresh `copier copy …` now leaves `git status` clean instead of two lockfiles untracked. Requires `devbox` on `PATH` at template-render time (already a prerequisite for all other recipes in the template).
- **service-python (#2)**: tightened the `docker` job's login and `build-push-action` conditions from `github.event_name != 'pull_request'` to `github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v'))`. Feature-branch pushes now build only, matching the policy documented in the template's `CLAUDE.md` (and avoiding the 403 from a brand-new repo's `GITHUB_TOKEN` lacking `packages: write`).

### Plugins

- **shared 0.2.1**: `/shared:new-service` Phase 3 rewritten for the new copier-side commit. Instead of `git add -A && git commit`, it now `git commit --amend --reset-author`s the bootstrap commit produced by `_tasks` so the user owns it with the richer `/shared:new-service` commit message. Falls back to the legacy `add && commit` path if `_tasks` didn't produce a commit (older templates).

## [0.2.0] — 2026-05-19

UX overhaul for `/shared:new-service` based on dogfooding feedback. Non-breaking — old flag form (`--description "..."`) still works.

### Plugins

- **shared 0.2.0**: `/shared:new-service` rewritten for fewer interactions:
  - **Natural-language args.** First token = project name, the rest = description. `/shared:new-service hello-world a simple rest api` now scaffolds end-to-end with zero further prompts. Old `--description "..."` flag still accepted.
  - **Auto-preflight.** Silently runs `uv tool install copier` if `copier` is missing. If `gh` is missing, automatically falls back to "skip GitHub steps" mode and emits the exact `gh repo create` / `gh repo edit` commands in the final report (instead of aborting).
  - **Auto-detect `GITHUB_ORG`.** Tries `gh api user -q .login`, falls back to the copier template's `ika100` default. No prompt.
  - **No confirmation table.** Resolved inputs go on one compact line; bootstrap proceeds immediately. The user can correct after the fact — everything is local and reversible until Phase 4.
  - **Empty/stub directory auto-clean.** If `./<name>` is empty or contains only `.claude/`, removes it with one warning line. Non-empty directories still abort.
  - **Single-round prompt when truly missing.** If both name and description are absent, asks once via plain text (`<name> <description>` on one line) — no `AskUserQuestion`, no batched dialog.
  - **Handles missing git identity.** Falls back to one-off `-c user.name=... -c user.email=...` on the bootstrap commit so fresh hosts without global git config don't error out.

### Templates

No template changes in this release.

## [0.1.1] — 2026-05-19

Bugfix release. All five issues found during the hello-world dogfood are resolved.

### Plugins

- **shared 0.1.1**: `/shared:new-service` now shallow-clones the platform repo before invoking Copier instead of using the unsupported `gh:<owner>/<repo>/<subdir>` URL form. Also passes `--trust` because the templates declare `_tasks`.

### Templates

- **service-python**:
  - **CI**: added `workflow_dispatch:` trigger so freshly-bootstrapped repos can run their first validation without needing a PR.
  - **devbox.json**: dropped `--frozen` from the init_hook so fresh repos can `uv sync` and generate `uv.lock` on first session.
  - **pyproject.toml**: added `ruff`, `mypy`, `pip-audit` to dev deps so `uv run <tool>` uses venv-installed versions (the devbox-Nix versions can't see project deps like pydantic). Excluded `tests/` from mypy and disabled `disallow_untyped_decorators` (FastAPI decorators lack stubs).
  - **Python source files**: pre-formatted to ruff style — added blank line between module docstring and first import. Generated trees now pass `ruff format --check` on first bootstrap.
  - **Dockerfile + .dockerignore**: README.md is now included in the docker build context (hatchling needs it to satisfy `readme = "README.md"` in pyproject.toml).

- **library-python**:
  - Same `workflow_dispatch:` trigger, dropped `--frozen`, and the same dev-dep + mypy additions as service-python.

### Validated by

- `ika100/hello-world` — green CI on all 6 jobs after applying these fixes locally. Bumping the platform to 0.1.1 means a fresh `/shared:new-service` invocation produces a green-on-first-PR repo.

## [0.1.0] — 2026-05-19

### Plugins
- **svc 0.1.0**: initial release. 8 agents (product-manager, architect, coder, tester, migrations, observability, release, deployment) + 5 commands (plan-feature, build-feature, quick-task, fix-bug, release).
- **gitops 0.1.0**: initial release. 2 agents (deployment, promote) + 1 command (promote). ArgoCD ApplicationSet conventions documented.
- **shared 0.1.0**: initial release. 2 agents (quality, security) + 2 commands (check-quality, new-service).

### Templates
- **service-python**: initial. Full Python service skeleton — devbox, CI (quality/test/security/pr-title/docker), Dockerfile, k8s base + overlays, FastAPI scaffolding, optional observability/migrations toggles.
- **library-python**: initial. Slim Python library skeleton — devbox, CI (quality/test/security/pr-title), no Docker, no k8s.

### Docs
- AGENTS.md lifted from money-maker; orchestration model documented.
- ADOPTING.md: green-field + existing-repo migration paths.
- ARCHITECTURE.md: design rationale.
