---
spec_id: 193-building-and-releasing-run-on-their-own
shape: platform
spec_hash: d9c138ace9e4
summary: cplat next shows the build start, progress, stops, end of build, staging-release-prod, and last screens from records; cplat dispatch gains build, start --detach, budget (today only), setup and answer, so the person builds, answers and releases by choosing
tasks:
  - id: t1
    title: Dispatcher state - today's budget raise, the build record and the read-only queue preview
    files: [scripts/cplat/dispatch_state.py, scripts/cplat/dispatch_budget.py, scripts/cplat/dispatch_view.py, scripts/cplat/dispatch_cycle.py]
    covers: [AC-193.1, AC-193.5, AC-193.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Policy set-up through a pull request that merges on green CI
    files: [scripts/cplat/dispatch_setup.py]
    covers: [AC-193.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Answers written into the spec (or the issue) and the criteria-hash rule
    files: [scripts/cplat/dispatch_answer.py, scripts/cplat/ship.py]
    covers: [AC-193.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t10
    title: Plugin version, ADR and changelog fragment
    files: [plugins/platform/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/adr/README.md, docs/changelog.d/193-building-and-releasing-run-on-their-own.added.md]
    covers: [AC-193.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: cplat dispatch verbs build, start --detach, budget, setup, answer and resume with the label
    files: [scripts/cplat/dispatch.py, docs/dispatch.md]
    covers: [AC-193.1, AC-193.2, AC-193.4, AC-193.5]
    parallel_safe: true
    depends_on: [t1, t2, t3]
  - id: t5
    title: nextbuild - the read-only build state, release sections, deploy steps and the build group
    files: [scripts/cplat/nextbuild.py, scripts/cplat/nextstate.py]
    covers: [AC-193.1, AC-193.2, AC-193.3, AC-193.4, AC-193.5, AC-193.6, AC-193.7, AC-193.8]
    parallel_safe: true
    depends_on: [t1, t2]
  - id: t6
    title: nextbuildscreen - the text of the build, stop, release, promote and last screens
    files: [scripts/cplat/nextbuildscreen.py, scripts/cplat/nextscreen.py]
    covers: [AC-193.1, AC-193.2, AC-193.3, AC-193.4, AC-193.5, AC-193.6, AC-193.7, AC-193.8]
    parallel_safe: true
    depends_on: [t5]
  - id: t7
    title: nextbuildquestions - options, input, other, actions and undo of those screens
    files: [scripts/cplat/nextbuildquestions.py, scripts/cplat/nextquestions.py]
    covers: [AC-193.1, AC-193.2, AC-193.3, AC-193.4, AC-193.5, AC-193.6, AC-193.7]
    parallel_safe: true
    depends_on: [t5]
  - id: t8
    title: cplat next --watch, the new --show values, judge_items, the build key and the how additions
    files: [scripts/cplat/nextcmd.py]
    covers: [AC-193.1, AC-193.3, AC-193.4, AC-193.5]
    parallel_safe: true
    depends_on: [t6, t7]
  - id: t9
    title: /platform:next writes the judgement for the build and the stops
    files: [plugins/platform/commands/next.md, docs/rules/plugins/platform/commands/next.yml]
    covers: [AC-193.1, AC-193.3, AC-193.4]
    parallel_safe: true
    depends_on: [t8]
human_steps:
  - "Before the PR merges: t9 lengthens /platform:next, so the prompts may pass `baseline.prompt_bytes`. In a Claude session on the branch run `cplat platform runs benchmark quick-task --plugins plugins --reset-first`, then `cplat platform rules rebaseline --reason \"/platform:next judges the build and the stops (spec 193)\"` and commit docs/rules/register.yml."
---

# Plan — 193 Building and releasing run on their own and interrupt only to ask

Contract: [design.md](design.md). Levels: t1, t2, t3, t10 → t4, t5 → t6, t7 → t8 → t9.

This plan replaces [plan.v1.md](plan.v1.md) after the 2026-11-15 amendment of AC-193.7: a deployable repo with manual
staging offers Promote to Staging before the Release step and Promote to Prod after it. The task split is unchanged;
t5, t6 and t7 carry the staging-release-prod order (design.md, `deploy` and Groups).

Every new module follows the `cplat` conventions of spec 192: standard library plus what `cplat` already imports, a
module docstring with its public API, the clock through `dispatch_state.now` / `runs.utcnow` / `notify.now`, `gh` and
`git` through the existing replaceable seams (`dispatch_units.gh`, `spec_pr.git`/`gh`, `nextstate.git`) or a
module-level `git(repo, *args)` the tests replace. The `next*` modules write nothing (AC-192.1 holds for every new
screen); the existing read-only tests of `cplat next` must stay green.

## t1 — Dispatcher state - today's budget raise, the build record and the read-only queue preview

**Files:** scripts/cplat/dispatch_state.py, scripts/cplat/dispatch_budget.py, scripts/cplat/dispatch_view.py, scripts/cplat/dispatch_cycle.py
**Covers:** AC-193.1, AC-193.5, AC-193.6
**Goal:** the state the new verbs write and the screens read: a raise that holds for today only, the build record, and
the queue in `plan`'s order without any write.

**Implementation notes:**
- `dispatch_state`: `empty()` steering gains `budget_today: None`; `raise_today(slug, tokens)`, `reset_today(slug)`,
  `budget_today(slug) -> int | None` (None unless its `day == today()`); `open_build(slug, slots)` writes
  `build = {"started_at": stamp(), "slots": slots}`; `build_of(slug) -> dict | None`. `_complete` keeps old files valid.
- `dispatch_budget.limit_of(policy, slug=None)`: the raise of today when `slug` is given and it applies, else the
  policy's; `reached(usage, policy, slug=None)`; `budget_need` passes its slug, so a raise resolves today's need.
- `dispatch_view.tokens_doc`: `limit` through the raise, new key `raised`; `starts_doc` and `render_status`/
  `render_plan` use the effective limit (` (raised for today)` after it in text).
- `dispatch_cycle`: `_why_not` and `_reached` pass the slug; `preview(repo, policy)` as design.md (same `_judge`, the
  ship-busy rule of `_schedule` without its agent calls, `snapshot(..., max_age=300, fetch=False)`, no `book`).
- Update the module docstrings.

**Done when:** the AC-193.5 tests on the raise (today only, never the policy file, the need resolved) and the AC-193.1
preview-order tests (same order as `evaluate`'s candidates, `after` on a waiting ship, no state write) pass;
`test_dispatch*.py` pass.

## t2 — Policy set-up through a pull request that merges on green CI

**Files:** scripts/cplat/dispatch_setup.py
**Covers:** AC-193.2
**Goal:** `suggest(slug) -> int | None`, `text(tokens) -> str` and `apply(repo, tokens) -> list[str]` as design.md
(`setup`), so the set-up writes the exact file and lands it like every other change (A5).

**Implementation notes:**
- `suggest`: highest known day of `dispatch_budget.history_hint(slug)` rounded up to the next 1,000,000; None without
  a known day above 0 (A4).
- `text`: the fixed file of design.md; `None` renders `<your number>` (for `--show` only).
- `apply`: refuse when `.platform/dispatch.yml` exists; branch `chore/dispatch-setup` from `origin/main`, write, commit
  `-s`, push and open the PR through `pr_open.open_pr`; wait and merge through `pr.wait(..., merge=True, ...)` with the
  timeouts `cplat pr wait --merge` uses; fast-forward the local `main` when checked out and clean.
- Return the output lines; raise `PlatformError` with the `pr wait` lines on red CI (the PR stays open).

**Done when:** the AC-193.2 tests on the file text (both hint cases), the refusal, and the fake-`gh` landing pass.

## t3 — Answers written into the spec (or the issue) and the criteria-hash rule

**Files:** scripts/cplat/dispatch_answer.py, scripts/cplat/ship.py
**Covers:** AC-193.4
**Goal:** `answer(repo, slug, key, text, question=None) -> list[str]` as design.md (`answer`): the answer is an
assumption the person decided; equal criteria hash → approved in the Changelog and the item goes on; changed → back to
draft with its PR.

**Implementation notes:**
- Find the unit file in `dispatch_state.worktree_path(slug, key)`; refuse (`dispatch_state.ItemRefused`) unless it
  ended `escalated`.
- Questions: the live ship state of the worktree or the newest archive (the glob `ship.revive_escalated` uses).
- Spec: Assumptions bullet, `answers` in the unit file (`dispatch_units.update_unit`), hash against
  `git show origin/main:<spec path>`; equal → `spec.add_changelog`, commit `-s`, and once all questions are answered
  `dispatch_state.resume_item` plus label removal on open tracked issues; changed → `spec.set_status(..., "draft", ...)`,
  Changelog, commit, `spec_pr.publish`, `resume_item`.
- Issue: comment with the marker, label removal, `resume_item`.
- Output lines and the `Undo:` line exactly as design.md.
- `ship.escalate`: store `{"text", "suggested", "options"}` per question (options from `spec._question`, suggested
  first); readers of `suggested` stay as they are.
- Check with a test that a resumed escalated ship unit restarts in the kept worktree and continues from its stopped
  phase (`dispatch_units._worktree` reuse, `ship.revive_escalated`); fix the path in this task if it does not.

**Done when:** the AC-193.4 tests (assumption text, approval Changelog line, resume after the last answer, back to
draft on a changed criterion, the issue comment) pass; `test_ship*.py` and `test_dispatch*.py` pass.

## t10 — Plugin version, ADR and changelog fragment

**Files:** plugins/platform/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/adr/README.md, docs/changelog.d/193-building-and-releasing-run-on-their-own.added.md
**Covers:** AC-193.5
**Goal:** the version, the decision record and the release note.

**Implementation notes:**
- Minor bump of `platform` in its `plugin.json` and the marketplace entry (and any other plugin
  `cplat platform pr-check` names for this branch).
- ADR: `cplat adr add a-days-budget-raise-lives-in-local-state --decision "<the line in design.md>"` (it writes the
  file and its `docs/adr/README.md` row); fill Status (Accepted), Context (spec 193 AC-193.5, the user decision of
  2026-11-12), Decision (`steering.budget_today`, local day, every limit reader through `limit_of`), Consequences
  (nothing committed changes; a raise ends at midnight; `--reset-today` takes it back). The new `docs/adr/<NNN>-…md`
  is not in `files` because its number is known only when `cplat adr add` runs; no other task touches `docs/adr/`.
- Fragment per `docs/changelog.d/README.md`: bold summary ending `(spec 193).`, then what the person now does
  (`/platform:next` builds, answers stops, releases and promotes by choosing); "Update the plugins (`/plugin marketplace update`)".

**Done when:** `devbox run validate`, `python3 scripts/check-links.py` and `python3 scripts/check-docs.py` pass, and
`cplat platform pr-check` reports no fragment or version problem.

## t4 — cplat dispatch verbs build, start --detach, budget, setup, answer and resume with the label

**Files:** scripts/cplat/dispatch.py, docs/dispatch.md
**Covers:** AC-193.1, AC-193.2, AC-193.4, AC-193.5
**Goal:** the command line of design.md (`cplat dispatch` verbs) on top of t1–t3.

**Implementation notes:**
- Parser: `build --slots N`, `start --detach`, `budget [--today N | --reset-today]`, `setup (--show [--json] |
  --tokens-per-day N)`, `answer <item> --answer TEXT [--question K]`; module docstring lines.
- `build`: policy with budget required, `set_slots`, `resume` when paused or draining, `open_build`, then the detach.
- `start --detach`: `loop_alive` → the adopted line; else spawn in a new session with output to
  `<state base>/logs/loop.log` (a replaceable `spawn_loop` seam), wait up to 5 s for the lock.
- `budget`: validation and texts of design.md through t1's functions.
- `setup` and `answer`: call t2 and t3 and print their lines; `ItemRefused` → exit 2 as today.
- `resume <item>`: after `resume_item`, remove `needs-decision` from the item's open issues through
  `dispatch_units.gh` and print `label removed: #<n>` per issue.
- `docs/dispatch.md`: the new verbs in Verbs; one paragraph in Budget on the raise for today; one in "Turn it on" that
  `/platform:next` sets the policy up and starts the build.

**Done when:** the AC-193.1/.2/.4/.5 verb tests (texts, exit codes, the detached spawn seam, the label removal) pass;
`test_dispatch*.py` pass.

## t5 — nextbuild - the read-only build state, release sections, deploy steps and the build group

**Files:** scripts/cplat/nextbuild.py, scripts/cplat/nextstate.py
**Covers:** AC-193.1, AC-193.2, AC-193.3, AC-193.4, AC-193.5, AC-193.6, AC-193.7, AC-193.8
**Goal:** `nextbuild.collect(repo_dir, slug, shape, local, items, src) -> dict | None` (the `build` object of
design.md) and `stop_of(item, ...)`, plus the state changes in `nextstate`, all read-only.

**Implementation notes:**
- Policy (`dispatch_policy.load`; no file → the set-up values and `setup` from `dispatch_setup.suggest`/`text`);
  `queue` from `dispatch_cycle.preview`; estimates from `state.json` history (A3); `tokens` from
  `dispatch_budget.usage_today` and `limit_of(policy, slug)`.
- `current` from `build_of`; `events`, `last_seq`, `running` (steps as spec 192's `_STEP`), `ended`, `totals`, `flow`
  as design.md; person lines read as `runs_report.aggregate_person` reads them (store and buffer); closed issues by one
  `gh issue list --state closed` read; tags by `git for-each-ref`.
- Stops: map an `escalation`/`stuck` item to its unit (`worktree_path` of its spec or issue key), fill `stop`
  (kind, tried, questions with options — only `suggested` for an older ship state, answered, branch, log, phase, spec
  path, `asked_minutes`); budget items get `kind: budget`.
- `deploy` (deployable shapes of `shapes.yml`): the component through `staging._find` (`ship.gitops_apps`,
  `ship.service_name`), `staging` from its `staging_promotion`; `step` = first of staging (manual and the staging
  instance does not resolve to `origin/main`'s head, `staging.resolve`), release, prod (newest `v*` tag not in prod);
  `after-dev-smoke` never yields staging (A10). An unreadable gitops-app gives `deploy: null` and a `src` failure.
- `nextstate`: `GROUPS` gains `build` before `release`; the `build:<repo>` item; `_release_items` for every component
  shape but `gitops-app` with `consequence.sections` (platform fragments through `platrelease_changelog.read_fragments`;
  first-parent subjects otherwise); in a deployable repo only the item of `deploy.step` (staging promote, release or
  prod promote, ids as design.md, a `needs.json` promote item with the same id kept once); `state["build"]`.
- Each source in its own `try` (a failure is `unavailable`, never raised); nothing writes.

**Done when:** the state-level tests of AC-193.1–.8 (fixtures of `state.json`, unit files, ship states, fragments,
tags, a gitops-app with manual and with `after-dev-smoke` staging) and the AC-192.1 read-only tests pass;
`test_next*.py` pass.

## t6 — nextbuildscreen - the text of the build, stop, release, promote and last screens

**Files:** scripts/cplat/nextbuildscreen.py, scripts/cplat/nextscreen.py
**Covers:** AC-193.1, AC-193.2, AC-193.3, AC-193.4, AC-193.5, AC-193.6, AC-193.7, AC-193.8
**Goal:** the part-2 lines and `Your part:` of every screen in design.md (Groups and screens), pure functions of the
state and the judgement.

**Implementation notes:**
- `nextbuildscreen`: `build_lines`, `setup_lines`, `progress_lines`, `stop_lines`, `raise_lines`, `log_lines`,
  `release_lines` (with the end-of-build head), `promote_lines` (staging and prod), `last_lines`, `your_part(...)`;
  the age, tokens and wall-time formats; the newest-5 event cut.
- `nextscreen`: dispatch these cases (build group, progress when dispatcher units run, stops with `stop`, release and
  promote, the end-of-build head before a staging step, the last screen when `flow.done`, the `log:`/`raise-budget:`
  sub-screens and the set-up details file); `Also waiting` words for build and release; `_KIND_STAGE` of a staging
  promote is `Staging`; wrap, ASCII and `plain` over every new line as for spec 192's lines.
- No I/O; the judgement comes in as data.

**Done when:** the AC-193.1–.8 screen tests (fixtures of `state` dicts) and spec 192's screen tests pass.

## t7 — nextbuildquestions - options, input, other, actions and undo of those screens

**Files:** scripts/cplat/nextbuildquestions.py, scripts/cplat/nextquestions.py
**Covers:** AC-193.1, AC-193.2, AC-193.3, AC-193.4, AC-193.5, AC-193.6, AC-193.7
**Goal:** the questions table and actions of design.md (Questions), within spec 192's rules (≤ 4 options, recommended
first, `header` ≤ 12, `description`, `record`).

**Implementation notes:**
- `nextbuildquestions`: one builder per screen of the table; actions, `cannot_undo` and `undo` lines; `input` on the
  set-up (no suggestion), budget and invalid-raise options; `other` on decision stops; `then` argv through spec 192's
  `_Ctx.call` (it repeats `--later`, `--ascii`, `--judgement`).
- Promote: "Promote to Staging" or "Promote to Prod" by `consequence.env` (header `Staging`/`Prod`), then "Show
  details", "Not now"; replaces spec 192's single "Promote" label for promote items.
- `nextquestions`: `_all` hands `build`, stops with `stop`, release and promote items to it; `build` handles
  `show="raise-budget:<N>"` and `show="log:<key>"`; `action_map` includes the new actions; `record` refs as design.md.
- Shell-safe quoting of `<answer>` and reasons in the step strings (`shlex.quote`).

**Done when:** the AC-193.1–.7 question tests (labels, order, steps, undo, input, other, record refs) and spec 192's
question tests pass.

## t8 — cplat next --watch, the new --show values, judge_items, the build key and the how additions

**Files:** scripts/cplat/nextcmd.py
**Covers:** AC-193.1, AC-193.3, AC-193.4, AC-193.5
**Goal:** the CLI additions of design.md (`cplat next` additions, the `how` additions).

**Implementation notes:**
- `--watch S --after SEQ`: read-only polling of `dispatch_state.load` and the mtime of `needs_path` every 2 s
  (replaceable `sleep`/`clock` seams); then render as usual.
- `--show log:<key>`, `--show raise-budget:<N>` passed to render and build.
- `--judgement`: the `items` key next to `specs`; `judge_items` built from the state; `judgement_wanted` as design.md.
- JSON keys `build` and `judge_items`; `input`/`other` pass through from the questions.
- `HOW`: spec 192's text unchanged, the additions appended; update the module docstring.

**Done when:** the end-to-end tests of `cplat next [--json]` for the build, progress (`--watch` with a fake clock),
stop, raise and log screens pass; the same state prints the same screen twice; `test_cplat*.py` and `test_next*.py` pass.

## t9 — /platform:next writes the judgement for the build and the stops

**Files:** plugins/platform/commands/next.md, docs/rules/plugins/platform/commands/next.yml
**Covers:** AC-193.1, AC-193.3, AC-193.4
**Goal:** the session supplies only judgement text (A6): `you_get` for queue and running items, `what_happened` and
`why_ask` for stops.

**Implementation notes:**
- Extend the judgement sentence: also for each entry of `judge_items` the fields its `wants` names, one plain sentence
  each from its `title` and `text`, under `items` keyed by its `key`, "so that the screen says in plain words what each
  item brings and why it stopped". Keep R1–R3 verbatim.
- Register entry for the changed rule (next free `R<n>`, `source: spec 193`, its reason) per `docs/rules/README.md`
  (A12); keep the file as short as the change allows.

**Done when:** `cplat platform rules check --only plugins/platform/commands/next.md` passes and the structure tests that
read the command pass.
