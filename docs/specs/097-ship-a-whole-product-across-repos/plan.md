---
spec_id: 097-ship-a-whole-product-across-repos
spec_hash: b6976632f869
summary: /app:ship coordinates one cplat ship per component repo (cplat app-ship); state in the gitops-app clone, per-repo
  gates (smoke, Argo, merged PR), gitops merges serialized through a merge slot in plan order, spec/plan published and
  completed through PRs merged on green, one product-ship run record, Stop hook
tasks:
- id: t1
  title: appship_state — state file, start checks, resume, escalate, finish, run record, Stop hook gate
  files: [scripts/cplat/appship_state.py]
  covers: [AC-097.1, AC-097.4, AC-097.12, AC-097.18]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: appship_merge — merge slot in plan order, conflict escalation, land a gitops-app PR on green
  files: [scripts/cplat/appship_merge.py]
  covers: [AC-097.3, AC-097.8, AC-097.9]
  parallel_safe: true
  depends_on: [t1]
  done: true
- id: t3
  title: appship_sched — ready/running/blocked, gate classes and gate evaluation, repo start/result/escalate
  files: [scripts/cplat/appship_sched.py]
  covers: [AC-097.6, AC-097.7, AC-097.10, AC-097.19]
  parallel_safe: true
  depends_on: [t1]
  done: true
- id: t4
  title: appship_report — repo state table and the final report
  files: [scripts/cplat/appship_report.py]
  covers: [AC-097.10, AC-097.20]
  parallel_safe: true
  depends_on: []
  done: true
- id: t5
  title: cplat ship start --product (parent run, default context, merges through the slot, smoke reason)
  files: [scripts/cplat/ship.py]
  covers: [AC-097.7, AC-097.9, AC-097.12]
  parallel_safe: true
  depends_on: [t2]
  done: true
- id: t6
  title: cplat app-ship CLI with publish, entry pr/land and complete
  files: [scripts/cplat/appship.py, scripts/cplat/cplat.py]
  covers: [AC-097.1, AC-097.2, AC-097.3, AC-097.4, AC-097.8, AC-097.10, AC-097.12, AC-097.18, AC-097.20]
  parallel_safe: true
  depends_on: [t1, t2, t3, t4]
  done: true
- id: t7
  title: Stop hook entry for the product ship
  files: [plugins/shared/hooks/hooks.json]
  covers: [AC-097.4]
  parallel_safe: true
  depends_on: []
  done: true
- id: t8
  title: /app:ship command (the coordinator prompt)
  files: [plugins/app/commands/ship.md]
  covers: [AC-097.2, AC-097.6, AC-097.7, AC-097.8, AC-097.10, AC-097.20]
  parallel_safe: true
  depends_on: []
  done: true
- id: t9
  title: Docs, svc ship note and version bumps
  files: [plugins/app/README.md, plugins/svc/commands/ship.md, docs/CHANGELOG.md, .claude-plugin/marketplace.json, plugins/app/.claude-plugin/plugin.json,
    plugins/shared/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json]
  covers: []
  parallel_safe: true
  depends_on: []
  done: true
---

# Plan — 097 Ship a whole product across repos

The contract (CLI, state file, merge slot, gates, report, record) is in [design.md](design.md); every task builds
against it. Decision record: [ADR-042](../../adr/042-product-ship-coordinates-repo-ships.md). Module layout and test
seams follow `scripts/cplat/ship.py`: module-level `gh`, `sleep`, `now`, `say` that tests replace, `PlatformError`
with a hint for every refusal, recording that never raises.

Two lock files sit next to the state in the gitops-app's git common dir: `cplat-app-ship.state.lock` guards every
read-modify-write of `cplat-app-ship.json` (t1), `cplat-app-ship.lock` is the merge slot (t2, design.md).

## t1 — appship_state — state file, start checks, resume, escalate, finish, run record, Stop hook gate

**Files:** scripts/cplat/appship_state.py
**Covers:** AC-097.1, AC-097.4, AC-097.12, AC-097.18
**Goal:** the product run's state machine without scheduling: everything that decides whether a run may start, where
it resumes, and what is recorded when it ends.

**Implementation notes:**
- `PHASES = ["plan", "publish", "repos", "complete", "done"]`; `STATE_FILE = "cplat-app-ship.json"` in the git common
  dir (same lookup as `ship.state_path`); `load_state`, `save_state` (sets `updated`; calls `_record`), `require_state`,
  `update(repo, fn)`: load, apply, save while holding `fcntl.flock` on `cplat-app-ship.state.lock` (t2, t3 and t5 write
  the same file from parallel repo ships).
- `start(repo, ref, max_, context)`: refusals in the order of design.md, before anything is written: shape via
  `shapecmd.route` (≠ `gitops-app` → hint `/svc:ship <spec>`), `specmod.find` status in {`approved`, `building`},
  `resolve_context(repo, context)` (given or `kubectl config current-context`; must list `<entry>-dev` of a
  `services.yaml` service in `kubectl --context C -n argocd get applications -o name`), another unfinished run of a
  different spec. Initial phase `plan` without `docs/plan/<spec>.md`, else `publish`.
- `refresh_repos(repo, st)`: `repos` from the plan's metadata (`docs/plan/<spec>.md`, read with `yaml`): `done: true` →
  `done-before`, else `ready`, existing entries kept; called at start and when the phase leaves `plan`.
- Resume: same spec → clear `escalated`/`cause`, `blocks = 0`, `escalated` repos → `ready`; an escalated run gets a new
  `run_id` from `runs.start("product-ship", …, resumes=old)` and `recorded = False`.
- `_record`: `runs.start("product-ship", repo=runs.repo_slug(repo), spec=…)` once (local active record only);
  `runs.finish` exactly once: `done` when phase `done`, `escalated` with `{reason, cause}`; `fields={"ships": st["ships"],
  "repos": {id: state}}`. `finish(repo)` archives to `cplat-app-ship-<spec>-<ts>.json`, recording `abandoned` first
  when not recorded.
- `escalate(repo, reason, cause)`: cause coerced like `ship._coerce_cause`; when `cause` is None and a repo is
  `escalated`, take that repo's cause and prefix the reason with its id.
- `describe(st)` (phase, escalation, `next:` line), `next_step(st)` per phase, and `gate(repo, hook_input, max_blocks)`
  mirroring `ship.gate` (blocks counter, give up after N with an escalation, `None` when done or escalated).

**Done when:** the acceptance tests for AC-097.1, AC-097.4 (state and gate part), AC-097.12 and AC-097.18 pass with
`gh`/`kubectl` faked; nothing is written on any refusal.

## t2 — appship_merge — merge slot in plan order, conflict escalation, land a gitops-app PR on green

**Files:** scripts/cplat/appship_merge.py
**Covers:** AC-097.3, AC-097.8, AC-097.9
**Goal:** the one place where the product run (and the repo ships it drives) merges into the gitops-app.

**Implementation notes:**
- `slot(gitops_dir, repo_id, plan_index, timeout, interval)`: register in `waiting` through `appship_state.update`;
  loop until no waiter has a lower `plan_index`, then hold an exclusive `flock` on `cplat-app-ship.lock` and yield;
  always deregister. Timeout → `PlatformError` naming the waiter ahead.
- `merge(gitops_dir, pr, repo_id, cwd)`: `gh pr view --json state,mergeable`; `CONFLICTING` → `Conflict(pr, after)`
  with the message of design.md (`after` = last `gitops_merged[].pr`); `UNKNOWN` is polled up to 3× (GitHub computes it
  lazily); merge with `gh pr merge --squash --delete-branch` only; append to `gitops_merged`. Never `--admin`, never push.
- `land(gitops_dir, pr, repo_id, timeout, interval)`: `gh pr ready` when draft, `ship.wait_checks(ship.CheckWatch(...))`,
  red → `(False, ship.red(...) lines)`, green → `slot` + `merge` → `(True, lines)`.
- `plan_index(gitops_dir, repo_id)`: the repo's position in the product plan's `repos` (gitops entry = 0).

**Done when:** AC-097.9 tests (two waiters merge in plan order; a conflicting PR raises naming both PRs, nothing merged)
and the merge part of AC-097.3 / AC-097.8 pass.

## t3 — appship_sched — ready/running/blocked, gate classes and gate evaluation, repo start/result/escalate

**Files:** scripts/cplat/appship_sched.py
**Covers:** AC-097.6, AC-097.7, AC-097.10, AC-097.19
**Goal:** decide which repos start, and turn a finished repo ship into `passed` or `escalated`.

**Implementation notes:**
- `next_action(gitops_dir, st) -> dict`: the `next --json` object of design.md; `--max` cap counts `running`; after any
  `escalated` repo nothing new starts (AC-097.10); dependencies count only when `passed` or `done-before`.
- `gate_class(gitops_dir, repo) -> "entry"|"library"|"exposed"|"internal"`: `gitops-app` shape → entry; `deployable`
  false in `core.registry.load()` → library; `services.yaml`/`app.yaml` read with `git show origin/main:<path>` after
  `git fetch -q origin` under `applications/*/`, same rule as `smoke.dev_url` → exposed, else internal.
- `start_repo(gitops_dir, id)`: clone path `<gitops parent>/<id>`; `gh repo clone <github_org>/<id>` when missing
  (`github_org` from `.copier-answers.yml`); dirty clone → `PlatformError("<abs> has uncommitted changes …")`; the
  entry gets the worktree of design.md. Sets `running`, `clone`, `gate`.
- `result(gitops_dir, id, context)`: the table of design.md; reads the clone through `ship.load_state`, checks
  `parent:` on the repo spec (`specmod.find(clone, st["spec"]).meta["parent"]`), internal gate through
  `ship.argo_health`; copies the fields, appends the repo `run_id` to `ships` (once), then `ship.finish(clone)`.
  Phase not `done` and not escalated → error, repo stays `running`.
- `escalate_repo(gitops_dir, id, reason, cause)`: for questions before a ship exists (AC-097.6): the reason is stored
  verbatim.

**Done when:** AC-097.19 tests (each gate class, `not run` never passes an exposed service, `--max`), AC-097.10 (no new
start after an escalation, running repos keep running), AC-097.7 (dirty clone refused with its path) and AC-097.6
(questions stored verbatim) pass.

## t4 — appship_report — repo state table and the final report

**Files:** scripts/cplat/appship_report.py
**Covers:** AC-097.10, AC-097.20
**Goal:** pure rendering from a state dict and the product spec's title; no I/O.

**Implementation notes:**
- `state_table(st) -> list[str]`: the escalation table of design.md (`State` column; entry first, then plan order).
- `final_report(st, title, product_steps) -> list[str]`: the `## Shipped:` report of design.md, `Smoke (dev)` words as
  spec 091 (`not run: not deployable (library)`, `not run: <svc> has no dev URL (not exposed in dev)`), human steps
  as `- [ ]` lines (repo plans in plan order, then the product plan's), one `/gitops:promote <svc> dev staging` per
  repo whose gate class is exposed or internal, and the line that this run promotes nothing beyond dev.

**Done when:** the AC-097.20 report tests and the AC-097.10 table test pass.

## t5 — cplat ship start --product (parent run, default context, merges through the slot, smoke reason)

**Files:** scripts/cplat/ship.py
**Covers:** AC-097.7, AC-097.9, AC-097.12
**Goal:** link a repo ship to its product run; no change without `--product`.

**Implementation notes:**
- `start(..., product: Path | None = None)` and `--product DIR` on `start`: read the product state there
  (`appship_state.load_state`; missing → `PlatformError`, hint `/app:ship <spec>`), store `product` on fresh start
  and resume, pass `parent=product.run_id` to `runs.start` (both the fresh and the resumed `runs.start` call).
- `deploy`: `context = context or (st.get("product") or {}).get("context")`; `--context` stays optional.
- `merge_gitops`: when `st.get("product")`, replace the `gh pr merge` call by `appship_merge.slot(...)` +
  `appship_merge.merge(...)` (repo id = `service_name(repo)`); a `Conflict` returns `(False, [message])` after
  `escalate(repo, message, "decision")`.
- `_smoke_state`: add `"reason": result.reason` to `st["smoke"]`.
- Import `appship_merge`/`appship_state` lazily inside the branches.

**Done when:** the AC-097.7/AC-097.9/AC-097.12 tests for `--product` pass and the existing `tests/cplat/test_ship*.py`
stay green.

## t6 — cplat app-ship CLI with publish, entry pr/land and complete

**Files:** scripts/cplat/appship.py, scripts/cplat/cplat.py
**Covers:** AC-097.1, AC-097.2, AC-097.3, AC-097.4, AC-097.8, AC-097.10, AC-097.12, AC-097.18, AC-097.20
**Goal:** the `cplat app-ship` command table of design.md, wiring t1–t4, plus the three gitops-app PR flows.

**Implementation notes:**
- `argparse` like `ship.main`; `--repo` default `.`; module docstring lists the commands (it is the `--help`).
  `cplat.py`: add `"app-ship": "appship"` to `COMMANDS` (and the line in its docstring).
- `start`/`status` print `appship_state.describe` plus `appship_report.state_table`; `next --json` prints
  `appship_sched.next_action`.
- `publish`: design.md steps; the PR body names the criteria count and repos; red → `appship_state.escalate(…, "code")`,
  exit 1, no phase change (AC-097.2's failing `plan-check` is escalated by the command prompt before `publish`).
- `entry pr`: push `compose/<spec>` from the entry worktree (refuse when no commit ahead of `origin/main`), open or
  reuse the PR (`gh pr create --base main`). `entry land`: `appship_merge.land`; green → repo `passed`, worktree
  removed; red → repo `escalated` with the failed checks (AC-097.8).
- `complete`: refuses unless every repo is `passed`/`done-before`; then design.md's branch, edits, PR and `land`;
  green → phase `done`, print `appship_report.final_report`.
- `escalate`, `finish`, `gate` delegate to t1 (`gate` reads stdin JSON like `ship.main`).

**Done when:** the CLI-level acceptance tests for every covered criterion pass and `cplat app-ship --help` lists every
command.

## t7 — Stop hook entry for the product ship

**Files:** plugins/shared/hooks/hooks.json
**Covers:** AC-097.4
**Goal:** the session cannot end while a product run is neither done nor escalated.

**Implementation notes:**
- Add a second hook object in the existing `Stop` entry's `hooks` array with the command of design.md, `timeout` 120,
  `statusMessage` `Checking the product ship run (spec 097)`. Keep the existing ship gate unchanged.

**Done when:** `devbox run validate` passes and the AC-097.4 hook test passes.

## t8 — /app:ship command (the coordinator prompt)

**Files:** plugins/app/commands/ship.md
**Covers:** AC-097.2, AC-097.6, AC-097.7, AC-097.8, AC-097.10, AC-097.20
**Goal:** the thin prompt that does the judgement; every deterministic step is a `cplat app-ship` call.

**Implementation notes:**
- Frontmatter `description` with usage `/app:ship <spec> [--max N] [--context C]`; structure like
  `plugins/svc/commands/ship.md` (cplat, unattended rules, phases, finish, escalate). Link ADR-042.
- First calls: `cplat shape`, `cplat app-ship start <spec> …`; print outputs verbatim; refusal → stop.
- Phase `plan`: follow `${CLAUDE_PLUGIN_ROOT}/commands/plan.md` sections 1–2 unattended (no questions, no push/PR:
  `publish` does that); planner blockers or a red `devbox run plan-check` → `cplat app-ship escalate '<reason>' --cause decision`.
  Then `cplat app-ship phase publish`, then `cplat app-ship publish`.
- Phase `repos`, loop: `cplat app-ship next --json`. `action: start` → `repo start <id>` for each; the entry is built
  as `/app:build` step 2 in the printed worktree, then `entry pr` and `entry land`. In **one message**, one foreground
  subagent per component repo (never `run_in_background`), prompt: work only in `<clone>` (`cd <clone> && …` in every
  Bash call); `/svc:spec --from-plan <abs plan> <id>` unattended (approve when no open questions; else report
  `QUESTIONS:` verbatim and stop, never answer); then follow `/svc:ship`'s command file with
  `cplat ship start <n> --product <abs gitops dir>`; skip its Finish (`cplat ship finish` is not called); report the
  repo spec id and the last `cplat ship status`. After the message: `repo result <id>` per repo; `QUESTIONS` →
  `repo escalate <id> '<questions verbatim>' --cause decision`.
- `action: wait` → next message of still-running repos; `escalate` → `cplat app-ship escalate` (cause from the repo),
  print the table and stop; `complete` → `cplat app-ship complete`, print the report verbatim, then `cplat app-ship finish`.
- Rules: never merge by hand, never push to a default branch, never force-push, never promote beyond dev.

**Done when:** the prompt names every `cplat app-ship` command it relies on and the command-file checks in
`tests/cplat/test_spec_agents.py` pass.

## t9 — Docs, svc ship note and version bumps

**Files:** plugins/app/README.md, plugins/svc/commands/ship.md, docs/CHANGELOG.md, .claude-plugin/marketplace.json, plugins/app/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json
**Covers:** none (supporting)
**Goal:** document the command and ship the change.

**Implementation notes:**
- `plugins/app/README.md`: `/app:ship` next to `/app:build` (unattended vs attended), one paragraph on gates.
- `plugins/svc/commands/ship.md`: one sentence under the first calls: `--product <dir>` is passed by `/app:ship`
  only; it links the run to a product ship (parent record, kube context, merge slot).
- `docs/CHANGELOG.md`: an entry for spec 097 under the unreleased section.
- Bumps, from the versions currently in the files: app and shared minor (new command, new cplat command and hook),
  svc patch (doc line), each in its `plugin.json` and in `marketplace.json`.

**Done when:** `devbox run validate` and the repository's Markdown link check pass.
