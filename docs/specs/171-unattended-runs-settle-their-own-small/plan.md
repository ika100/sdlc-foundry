---
spec_id: 171-unattended-runs-settle-their-own-small
shape: platform
spec_hash: 56b185949ad4
summary: The preflight's minimum allowlist and the platform repo's own allowlist, one landing module (merge GitHub accepted = merged, head guard, push ahead, generated-file regeneration), running waits visible to the Stop hook, pr-check body files, test-helper tightening and repeatable --tracks
tasks:
  - id: t1
    title: Preflight - the minimum repo allowlist
    files: [scripts/cplat/preflight.py, tests/cplat/units131_support.py, tests/cplat/test_appship_131.py, tests/cplat/test_headless.py]
    covers: [AC-171.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: The platform repo's committed allowlist
    files: [.claude/settings.json]
    covers: [AC-171.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: check-settings.py in validate, ci-local and CI
    files: [scripts/check-settings.py, devbox.json, .github/workflows/ci.yml, scripts/ci-local.sh]
    covers: [AC-171.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: land_merge - merge, cleanup, head guard, regeneration, settle loop
    files: [scripts/cplat/land_merge.py, scripts/cplat/merge_lock.py]
    covers: [AC-171.3, AC-171.4, AC-171.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: Running waits - marks, stopgate and the system ship gate
    files: [scripts/cplat/waits.py, scripts/cplat/stopgate.py, scripts/cplat/appship_state.py]
    covers: [AC-171.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: pr-check reads the body file like the other PR commands
    files: [scripts/cplat/house_rules.py]
    covers: [AC-171.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: spec - repeatable --tracks and test-diff names test helpers
    files: [scripts/cplat/spec.py]
    covers: [AC-171.7, AC-171.10]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t11
    title: Docs and changelog fragment
    files: [docs/unattended-delivery.md, docs/changelog.d/171-unattended-runs-settle-small-problems.fixed.md]
    covers: [AC-171.3, AC-171.6, AC-171.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: ship land through land_merge, push ahead, gate with running waits
    files: [scripts/cplat/ship.py, tests/cplat/test_ship.py, tests/cplat/test_platform_shape_123.py]
    covers: [AC-171.3, AC-171.4, AC-171.5, AC-171.6, AC-171.8]
    parallel_safe: true
    depends_on: [t4, t5]
    done: true
  - id: t9
    title: pr wait --merge through land_merge, the wait marks itself running
    files: [scripts/cplat/pr.py, tests/cplat/test_tags_and_wait.py]
    covers: [AC-171.3, AC-171.4, AC-171.6, AC-171.8]
    parallel_safe: true
    depends_on: [t4, t5]
    done: true
  - id: t10
    title: Build prompt - a test helper is tightened without asking
    files: [plugins/component/commands/build.md, plugins/component/references/build-tighten.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/build-tighten.yml, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-171.7]
    parallel_safe: true
    depends_on: [t7]
    done: true
human_steps:
  - "Before the next platform release (ADR-085): t10 changes component prompts, so in a Claude session on the release candidate run `cplat platform runs benchmark quick-task --plugins plugins --reset-first` and `cplat platform runs benchmark build --plugins plugins --reset-first`; the eval gate of `cplat platform release` needs both."
---

# Plan — 171 Unattended runs settle their own small problems

Contract: [design.md](design.md); decisions outliving the spec: [ADR-092](../../adr/092-a-land-settles-what-has-an-obvious-answer.md)
(landing) and [ADR-093](../../adr/093-running-cplat-waits-are-visible-to-the-stop-hook.md) (running waits).
Levels: t1, t2, t3, t4, t5, t6, t7, t11 → t8, t9, t10. `ship.py` imports `land_merge` only inside functions (as it does
`merge_lock` today), because `land_merge` imports `ship` and `merge_lock` at module level.

## t1 — Preflight - the minimum repo allowlist

**Files:** scripts/cplat/preflight.py, tests/cplat/units131_support.py, tests/cplat/test_appship_131.py, tests/cplat/test_headless.py
**Covers:** AC-171.1
**Goal:** a committed settings file that allows neither `cplat` nor reading the installed plugins fails the preflight
before any session, naming the missing rule (design.md *Preflight*).

**Implementation notes:**
- `MINIMUM = ("Bash(cplat *)", "Read(~/.claude/plugins/**)")`; `_no_allowlist` keeps the missing-file message verbatim
  (AC-131.11 `test_no_repo_allowlist` pins it) and adds the present-file check of the design.
- A `read_matches(rule, path)` helper next to `matches`: `Read`, `Read(**)`, `Read(<glob>)` with `**` → any, `*` → no
  `/`, a leading `~` and the expanded home both accepted.
- Only the project layer counts (the committed file); user and local layers never satisfy the minimum.
- The failure detail starts with the missing rules joined by ` and `, `Bash(cplat *)` first.
- Fixtures: the "clean" repos of `units131_support.make_repo`, `test_appship_131` clones and the `test_headless` repo
  fixture commit settings without these rules; add the two rules there so their existing tests keep passing (no
  assertion changes).

**Done when:** the AC-171.1 acceptance tests pass, `test_preflight_131.py`, `test_headless*.py` and `test_appship_131.py`
still pass.

## t2 — The platform repo's committed allowlist

**Files:** .claude/settings.json
**Covers:** AC-171.2
**Goal:** the platform repo can ship headless: its committed settings hold every allow and ask rule of
`templates/library-python/.claude/settings.json`.

**Implementation notes:**
- Keep `$schema` and `worktree`; add `permissions.allow` and `permissions.ask` with the template's strings in its
  order; no `defaultMode`, `extraKnownMarketplaces`, `enabledPlugins` (A1).
- No platform-only rules beyond the template's (keep the diff reviewable).

**Done when:** the file is valid JSON, `python3 scripts/check-settings.py` passes once t3 is in, and the AC-171.2 test
that runs the preflight of `cplat headless "/component:ship <spec>"` in the platform repo with a fake session prints no
`preflight failed` line (with t1).

## t3 — check-settings.py in validate, ci-local and CI

**Files:** scripts/check-settings.py, devbox.json, .github/workflows/ci.yml, scripts/ci-local.sh
**Covers:** AC-171.2
**Goal:** the repository checks fail naming each library-template rule the platform's settings lack (design.md
*Platform allowlist*).

**Implementation notes:**
- Standard library only, `--root` (default: the repo root above `scripts/`), output and exit codes exactly as designed;
  a module docstring in the style of `scripts/check-pins.py`.
- `devbox.json` `validate`: append `&& python3 scripts/check-settings.py`.
- `ci.yml` job `validate-shapes`: a step `the platform's allowlist holds the library template's rules (spec 171)` running
  `python3 scripts/check-settings.py` (next to the link check). `ci-local.sh`: the same as a `step`.
- Keep the pinned-action and actionlint checks green (no new `uses:`).

**Done when:** the AC-171.2 tests of the check pass (a temporary root lacking a rule fails naming it, the real repo
passes with t2), `bash scripts/ci-local.sh` runs the step.

## t4 — land_merge - merge, cleanup, head guard, regeneration, settle loop

**Files:** scripts/cplat/land_merge.py, scripts/cplat/merge_lock.py
**Covers:** AC-171.3, AC-171.4, AC-171.6
**Goal:** the shared landing module of design.md *Landing* (`GENERATED`, `Unresolvable`, `MergeFailed`, `Rounds`,
`Settled`, `await_head`, `wait_green`, `merge`, `cleanup`, `regenerate`, `settle`), verbatim to the contract.

**Implementation notes:**
- Every function takes the caller's `run`; `gh` through `ship.gh` (looked up at call time); `say`/`sleep` through `ship`.
- `merge`: never `--delete-branch`; the post-failure `gh pr view` decides merged / head-moved / conflicting / `MergeFailed`.
- `cleanup`: each step in its own `try` (catch `Exception`: a cleanup error never fails a merge); the "base checked out in
  another worktree" test from `git worktree list --porcelain` against `git rev-parse --show-toplevel`; the local steps
  only when `dispatch_state.slug_of(repo)` equals `merge_lock.slug_of(repo, url)`.
- `regenerate`: steps 1–5 exactly; `git merge --no-ff --no-commit`, `git merge-file -p` on the three stages with the
  generated region replaced by a placeholder, `spec.write_index` as the generator of `docs/backlog.md`, commit
  `-s --no-edit` with `core.git_identity`, push without force, `git merge --abort` on every refusal so no half-merged
  state stays, `git reset -q --hard <pre>` only after a refused push of its own commit.
- `settle` / `wait_green`: the loop of the design; `wait_green` absorbs `pr._watch`'s "a push during the last poll" loop.
- `merge_lock._known`: `if watch.head is None and head: watch.head = head`; update the module docstring (the callers now
  merge through `land_merge`).

**Done when:** the AC-171.3, AC-171.4 and AC-171.6 acceptance tests that drive `land_merge` and `merge_lock` directly
pass; the ones through `ship land` / `pr wait` pass with t8 and t9; `test_merge_lock*.py` still pass.

## t5 — Running waits - marks, stopgate and the system ship gate

**Files:** scripts/cplat/waits.py, scripts/cplat/stopgate.py, scripts/cplat/appship_state.py
**Covers:** AC-171.8
**Goal:** waits mark themselves running per checkout and the stop gate holds the count while one runs (design.md *Stop
hook*).

**Implementation notes:**
- `waits.running(command, cwd)` and `waits.live(repo)` as designed (mark file under `core.git_dir`, pid liveness,
  dead marks removed, no git dir → no-op); `record()` wraps `body` in `running(f"cplat {name}", Path.cwd())`, so
  `system ship next --wait`, `dispatch wait`, `component ship wait`, `component release wait` and the env waits are
  covered without touching their modules.
- `stopgate.Verdict` gains `waiting: str | None = None` (existing equality checks keep working); `check(..., waiting=None)`
  and `wait_line(v)` as designed; agents first, then waits, then the no-progress count.
- `appship_state.gate`: pass `waits.live(repo)`; a block with `verdict.waiting` uses the design's three lines (`The
  product ship of …`), then the keep-going sentence.
- `ship.gate` is wired in t8 (it owns `ship.py`).

**Done when:** the AC-171.8 acceptance tests on `stopgate`, `waits` and the system gate pass; `test_*126*.py` and the
existing stopgate and waits tests still pass.

## t6 — pr-check reads the body file like the other PR commands

**Files:** scripts/cplat/house_rules.py
**Covers:** AC-171.9
**Goal:** `--body-file .git/PR_BODY.md` works in a linked worktree; an unreadable body file is one `ERROR:` line and exit 1
(design.md *pr-check*).

**Implementation notes:**
- `core.git_path(repo, ns.body_file)`, never `core.stage_pr_body` (pr-check must not move the file).
- Catch `OSError` and `UnicodeDecodeError` around the read; print `ERROR: body file <F>: <reason>` with `F` as given;
  return 1 before any rule runs.

**Done when:** the AC-171.9 acceptance tests pass and `test_150_pr_check.py` still passes.

## t7 — spec - repeatable --tracks and test-diff names test helpers

**Files:** scripts/cplat/spec.py
**Covers:** AC-171.7, AC-171.10
**Goal:** every `--tracks` value is kept once in order and claimed; a changed test helper is named as such by `test-diff`
(design.md *--tracks* and *Test helpers*).

**Implementation notes:**
- `--tracks`: `type=int, nargs="*", action="extend", default=None`; de-duplicate with `dict.fromkeys` before `new()` and
  before the claims (`claim.claim` gets the stored list).
- `test_diff`: after the formatting / suppression / approval decisions, a refused file with no test definitions in old
  and new (`_test_names`) gets `why = "test helper (defines no test): " + why`.
- `--reason` help: "with --tighten: the reviewer's finding, or why a test helper changed".
- `tightening` and the `--tighten` recording stay as they are (they already refuse a lost assertion, test or criterion id
  and record `kind: tightened` for the PR block).

**Done when:** the AC-171.10 tests and the AC-171.7 tests on `test-diff` / `--tighten` pass; `test_spec*.py`,
`test_165_*.py` and `test_169_*.py` still pass.

## t11 — Docs and changelog fragment

**Files:** docs/unattended-delivery.md, docs/changelog.d/171-unattended-runs-settle-small-problems.fixed.md
**Covers:** AC-171.3, AC-171.6, AC-171.8
**Goal:** the user-facing description of what a land and the Stop hook now settle by themselves.

**Implementation notes:**
- `docs/unattended-delivery.md`: a short section "What a land settles by itself" (merged-is-merged with `WARNING:`
  cleanup lines, the head guard, local commits pushed first, generated-file conflicts regenerated at most 3 times,
  everything else a person's decision; link ADR-092) and one paragraph at the Stop hook text (a running `cplat` wait
  blocks the stop without counting it; link ADR-093). Relative links only.
- Fragment per `docs/changelog.d/README.md`: bold summary ending `(spec 171).`; the eight fixes in one or two short
  paragraphs naming the issues (#613, #621–#626, #633); "Update the plugins (`/plugin marketplace update`)".

**Done when:** `python3 scripts/check-links.py` passes and the fragment parses (`cplat platform pr-check` reports no
fragment problem).

## t8 — ship land through land_merge, push ahead, gate with running waits

**Files:** scripts/cplat/ship.py, tests/cplat/test_ship.py, tests/cplat/test_platform_shape_123.py
**Covers:** AC-171.3, AC-171.4, AC-171.5, AC-171.6, AC-171.8
**Goal:** `cplat component ship land` pushes local commits first, lands through `land_merge`, records a merge GitHub
accepted as merged, and the ship Stop gate knows running waits (design.md *Landing*, *Push ahead*, *Stop hook*).

**Implementation notes:**
- `push_ahead(repo, st, pr, watch)` exactly as designed, called at the top of `_land` (under the whole-phase lock when
  there is one); no check is read when it raises.
- `_land`: the first wait through `land_merge.wait_green` with one `land_merge.Rounds()` for the whole land; the red
  handling (fix rounds, budget, metrics) unchanged.
- `_merge_locked` → `land_merge.settle(..., before_merge=...)` where `before_merge` runs `merge_gitops(..., "before-merge", ...)`
  and `_ready_if_draft`; `Settled.updated` → the existing local `git pull --ff-only origin <branch>`; red → fix round +
  `red(...)` as today.
- `_merged(repo, st, sha, lines)`: state `merge_sha` and phase `deploy` first (the merge is recorded even if every local
  step fails), the joint marker, then `lines + land_merge.cleanup(...)`; no unconditional `git switch main`. The
  "already merged" path goes through it too.
- Hints: `land_merge.MergeFailed` → the design's non-conflict hint (draft keeps its hint); `land_merge.Unresolvable` /
  `merge_lock.Conflict` → `merge conflicts with main: rebase is a human decision; cplat component ship escalate 'merge failed'`.
- `gate`: pass `waits.live(repo)` to `stopgate.check`; a block with `verdict.waiting` gets the design's three lines, then
  the keep-going sentence. `main`'s `land` subcommand runs inside `waits.running("cplat component ship land", Path.cwd())`.
- Existing tests that pin `gh pr merge … --squash --delete-branch` (`test_ship.py`, `test_platform_shape_123.py`): drop
  `--delete-branch` from the expected argv and let their fakes answer the cleanup calls; change no other assertion.

**Done when:** the AC-171.3–AC-171.6 and AC-171.8 acceptance tests through `ship land` and `ship gate` pass;
`test_ship*.py`, `test_platform_shape_123.py`, `test_headless_126.py` and the joint/system ship tests still pass.

## t9 — pr wait --merge through land_merge, the wait marks itself running

**Files:** scripts/cplat/pr.py, tests/cplat/test_tags_and_wait.py
**Covers:** AC-171.3, AC-171.4, AC-171.6, AC-171.8
**Goal:** `cplat pr wait --merge` (and `cplat dispatch land`, which calls it) lands through `land_merge`; the CLI wait
marks itself running (design.md *Landing*, *Stop hook*).

**Implementation notes:**
- `_watch`: the check wait through `land_merge.wait_green` (one `Rounds()` per call of `wait`); with `--merge`,
  `land_merge.settle(...)` inside the lock as today; red → `_red(...)`.
- `MergeFailed = land_merge.MergeFailed` (so `dispatch_units.land` and `_failure_section` keep working); `_merge` goes away.
- The merged result: `merged <url> (squash)` followed by the cleanup `WARNING:` lines; the #371 line
  `(squash); the local cleanup failed: …` is gone.
- `main`: the `wait` subcommand runs inside `waits.running(f"cplat pr wait {ns.pr}{' --merge' if ns.merge else ''}", Path.cwd())`;
  `wait()` itself marks nothing (the dispatcher calls it in-process).
- `test_tags_and_wait.py`: `test_a_merge_that_landed_but_failed_locally_counts_as_merged` asserts the new contract
  (`merged … (squash)` and a `WARNING:` line, no "local cleanup failed"); its fake `run` answers the cleanup calls; no
  other assertion changes.

**Done when:** the AC-171.3, AC-171.4, AC-171.6 and AC-171.8 acceptance tests through `pr wait` pass;
`test_tags_and_wait.py`, `test_dispatch*.py` and `test_merge_lock*.py` still pass.

## t10 — Build prompt - a test helper is tightened without asking

**Files:** plugins/component/commands/build.md, plugins/component/references/build-tighten.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/build-tighten.yml, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-171.7
**Goal:** when `cplat spec test-diff` names a `test helper`, the build records it with `--tighten` and goes on; the user
is asked only when that is refused.

**Implementation notes:**
- `build-tighten.md`: a short second section "A test helper changed" (the `test helper (defines no test)` line from
  `test-diff` → `cplat spec test-diff $RED --tighten <file> --task <task> --reason '<why the helper changed>'` without
  asking, because the check refuses a helper change that drops an assertion, a test or a criterion id; exit 1 → stop as a
  changed test, `build-test-approval.md`). The `TIGHTENED` list to the reviewer includes it.
- `build.md` Phase 2.4 step 2: one clause before "stop and show the user": a `test helper` line → read
  `build-tighten.md` first. Keep the hard rule sentence and every phrase pinned by `test_lean_prompts`,
  `test_165_test_problems` and `test_476` verbatim.
- Byte budget (docs/rules/README.md rule 5): the changed prompts together may not grow; shorten other sentences of these
  two files by at least the bytes added. `build.md` stays below the `test_lean_prompts` limit.
- Register entries for each new or changed rule sentence (next free `R<n>`, class `practice`, `source: spec 171`, the
  reason in the sentence); `cplat platform rules check --only <each file>` passes.
- Patch bump of the component plugin in its `plugin.json` and the marketplace entry.

**Done when:** `cplat platform rules check` passes on the repo, `devbox run validate` passes, the AC-171.7 acceptance
tests that read the prompts pass, and `cplat quiet test-fast` shows no newly failing prompt test.
