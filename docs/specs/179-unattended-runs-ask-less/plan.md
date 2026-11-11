---
spec_id: 179-unattended-runs-ask-less
shape: platform
spec_hash: d99ec382df25
summary: Instance settings as system-plan gitops operations with a plan check, git rm in the run allowlist, type-only test changes recorded without asking, one acceptance-test review before the freeze, smoke findings fixed by the build, and platform-repo escalations on the desktop instead of GitHub
tasks:
  - id: t1
    title: Preflight - git rm allowed, forced git rm refused
    files: [scripts/cplat/preflight.py, tests/cplat/test_preflight_131.py]
    covers: [AC-179.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: spec.py - type-only test-diff line and provided-by-system settings
    files: [scripts/cplat/spec.py]
    covers: [AC-179.4, AC-179.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: testreview - the reviewed marker commit and cplat component build reviewed
    files: [scripts/cplat/testreview.py, scripts/cplat/buildcmd.py]
    covers: [AC-179.5, AC-179.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: gitops-app plan.py - replicas and resources operations, entry order, instance-setting check
    files: [templates/gitops-app/scripts/plan.py]
    covers: [AC-179.1, AC-179.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: component set --resources
    files: [scripts/cplat/compose.py, plugins/component/commands/set.md, docs/rules/plugins/component/commands/set.yml]
    covers: [AC-179.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: System ship entry applies the replicas and resources operations
    files: [scripts/cplat/appship.py]
    covers: [AC-179.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: Run records, run rows and escalation items carry the repo shape
    files: [scripts/cplat/runs.py, scripts/cplat/runlist.py, scripts/cplat/needs.py]
    covers: [AC-179.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t10
    title: Notifier - explicit cells and the platform escalation preset per event
    files: [scripts/cplat/notify_config.py, scripts/cplat/notify.py]
    covers: [AC-179.7, AC-179.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t11
    title: Build prompts - test review before the freeze, type-only and smoke findings, git rm
    files: [plugins/component/commands/build.md, plugins/component/references/unit-mode.md, plugins/component/references/build-tighten.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/unit-mode.yml, docs/rules/plugins/component/references/build-tighten.yml]
    covers: [AC-179.3, AC-179.4, AC-179.5, AC-179.6, AC-179.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t12
    title: Reviewer - test-review mode, SMOKE line, TEST REVIEW input
    files: [plugins/svc/agents/reviewer.md, docs/rules/plugins/svc/agents/reviewer.yml]
    covers: [AC-179.5, AC-179.6, AC-179.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t13
    title: System planner and ship-entry - instance settings become entry operations
    files: [plugins/system/agents/planner.md, plugins/system/references/ship-entry.md, docs/rules/plugins/system/agents/planner.yml, docs/rules/plugins/system/references/ship-entry.yml]
    covers: [AC-179.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t14
    title: Plugin versions, docs, ADR index and changelog fragment
    files: [plugins/component/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/console.md, docs/unattended-delivery.md, docs/adr/README.md, docs/changelog.d/179-unattended-runs-ask-less.changed.md]
    covers: [AC-179.1, AC-179.3, AC-179.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: units - the red-tests unit needs the reviewed commit
    files: [scripts/cplat/units.py, tests/cplat/units131_support.py, tests/cplat/test_units_131.py]
    covers: [AC-179.5, AC-179.6]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t5
    title: PR block - unresolved test-review findings and tightened smoke tests
    files: [scripts/cplat/runs_built.py, scripts/cplat/runs_agents.py]
    covers: [AC-179.6, AC-179.9]
    parallel_safe: true
    depends_on: [t3]
    done: true
human_steps:
  - "Before the next platform release (ADR-085): t11 and t12 change component and svc prompts, so in a Claude session on the release candidate run `cplat platform runs benchmark quick-task --plugins plugins --reset-first` and `cplat platform runs benchmark build --plugins plugins --reset-first`; the eval gate of `cplat platform release` needs both."
---

# Plan — 179 Unattended runs ask less

Contract: [design.md](design.md); the decision that outlives the spec:
[ADR-101](../../adr/101-acceptance-tests-are-reviewed-once-before-they-freeze.md) (review before the freeze).
Levels: t1, t2, t3, t6, t7, t8, t9, t10, t11, t12, t13, t14 → t4, t5 (both import `testreview`).

Every prompt task keeps the total bytes of the prompt files it changes at or below what they had before (docs/rules
README, rule 6: shorten other sentences of the same files by the bytes added), keeps every phrase existing tests pin
verbatim, gives each new or changed rule sentence its reason and a register entry (next free `R<n>`, `source: spec
179`), and passes `cplat platform rules check --only <file>`.

## t1 — Preflight - git rm allowed, forced git rm refused

**Files:** scripts/cplat/preflight.py, tests/cplat/test_preflight_131.py
**Covers:** AC-179.3
**Goal:** every unattended run of a covered command may `git rm` tracked files; forced removal stays refused
(design.md section 2).

**Implementation notes:**
- `run_allowlist`: `"Bash(git rm *)"` right after `"Bash(git commit -s *)"`, for every command.
- `refused_rules`: the eight `git rm` force rules of the design, after the push rules and before `gh pr merge*`.
- `_self_check` must keep passing (no allow sample matches a refused rule).
- `_representative` / `_blocked` stay as they are: the preflight does not start refusing repos whose settings ask for
  `git rm`.
- `test_preflight_131.py::test_the_run_allowlist_of_a_ship_names_the_branch_commit_push_pr_and_land` pins the whole
  list: add `"Bash(git rm *)"` to its expected list at the new position; change nothing else in that file.

**Done when:** the AC-179.3 acceptance tests pass; `test_preflight_131.py`, `test_headless_131.py`,
`test_appship_131.py` and `test_156_system_benchmark.py` pass.

## t2 — spec.py - type-only test-diff line and provided-by-system settings

**Files:** scripts/cplat/spec.py
**Covers:** AC-179.4, AC-179.1
**Goal:** `cplat spec test-diff` names a type-only change of a frozen test (design.md section 3); a repo spec written
from a system plan lists the new replicas and resources operations under "Provided by the system" (section 1).

**Implementation notes:**
- `type_only(old, new, name)` next to `tightening`, the five rules of the design in order, using `AC_ANY`,
  `_TEST_DEFS` (full match text, trimmed), `_SKIPS` and `_ASSERTS`; `collections.Counter` for the multisets.
- Assertion lines: a line matching `_ASSERTS` starts a statement; following lines belong to it while the running count
  of `([{` minus `)]}` from its start is above 0. Brackets inside string literals are not special-cased (A4, Non-goals).
- `test_diff`: in the loop that names test helpers, a refused file with texts, with test definitions, for which
  `type_only` holds gets `(False, "type-only (test definitions, assertion lines and criterion ids unchanged)")`.
  Approved and tightened files are decided before, as today.
- `tightening` and the `--tighten` recording stay as they are (a type-only change passes `tightening`).
- `provided_by_system`: `replicas` → `` - replicas `N` `` plus `` in `E` `` with an instance; `resources` →
  `` - resources `requests.cpu=A, limits.memory=D` `` (mapping order), for ops whose `component` is the repo.

**Done when:** the AC-179.4 tests on `test-diff` / `--tighten` and the AC-179.1 test on the slice's "Provided by the
system" pass; `test_165_*.py`, `test_169_*.py`, `test_171_test_helpers.py`, `test_172_test_diff.py`,
`test_160_lint_suppressions.py` and `test_spec*.py` pass.

## t3 — testreview - the reviewed marker commit and cplat component build reviewed

**Files:** scripts/cplat/testreview.py, scripts/cplat/buildcmd.py
**Covers:** AC-179.5, AC-179.6
**Goal:** the freeze point of the acceptance tests is a marker commit written by `cplat`, which records the review's
unresolved findings (design.md section 4).

**Implementation notes:**
- `testreview.py`: `REVIEWED_MSG`, `reviewed_commit`, `unresolved`, `commit` and a `main(argv)` for
  `reviewed <spec> [--repo R] [--findings N] [--unresolved V]...`, exactly as designed (messages, exit codes, the
  "already reviewed" case).
- Range: `merge-base` with `main`, else `origin/main`, else the whole history, as `units._acceptance_commit` does.
- The spec is found with `specmod.find`; active ids from `spec.active_acs()`.
- The commit: `git commit -s --allow-empty -m <subject> -m <body>` with `core.git_identity(repo)`; body lines exactly
  `findings: N` and `unresolved: <test> | <AC> | <what>` (parts trimmed, joined with ` | `).
- `buildcmd.main`: `if argv and argv[0] == "reviewed": return testreview.main(argv[1:])`, next to the `tests`
  dispatch; add the line to the module docstring.

**Done when:** the AC-179.5 / AC-179.6 acceptance tests of `cplat component build reviewed` and of
`testreview.unresolved` pass; `test_build*.py` pass.

## t6 — gitops-app plan.py - replicas and resources operations, entry order, instance-setting check

**Files:** templates/gitops-app/scripts/plan.py
**Covers:** AC-179.1, AC-179.2
**Goal:** a system plan can state replicas and resources in its gitops entry, and `devbox run plan-check` refuses a
plan that leaves a criterion naming an instance setting without a gitops entry (design.md section 1).

**Implementation notes:**
- `GITOPS_OPS` gains `replicas` and `resources`; `check_gitops` validates them with the design's messages; the target
  component is `op["component"]` (or `service`) for both.
- Entry `order`: checked in `check_all` for `shape: gitops-app` entries.
- `spec_criteria` returns the criterion text too (e.g. `(active: dict[id, text], withdrawn: set)`); update its one
  caller.
- `check_settings(meta, repos, active)`: the word regex of the design, keys in order of first appearance; errors go to
  `late`, so finished plans get a warning. The `missing` summary for finished plans falls back to the joined messages.
- Keep the stdlib + pyyaml dependency set; the module docstring's usage stays.

**Done when:** the AC-179.1 / AC-179.2 acceptance tests on `plan.py validate` pass; `test_plan.py`,
`test_appship_097.py`, `test_154_journey_6_findings.py` and `test_units_131.py` pass.

## t7 — component set --resources

**Files:** scripts/cplat/compose.py, plugins/component/commands/set.md, docs/rules/plugins/component/commands/set.yml
**Covers:** AC-179.1
**Goal:** `cplat component set <c> --resources KEY=VALUE` writes the component's `resources:` mapping and re-renders
(design.md section 1).

**Implementation notes:**
- `--resources`, `action="append"`, `metavar="KEY=VALUE"`; keys and the quantity regex of the design; merge into
  `entry.setdefault("resources", {}).setdefault(a, {})[b]`.
- Refused with `--instance` by the existing "`--instance` takes nothing but `--replicas`" rule (extend its check).
- Refused on `add` like the other set-only options, if `add` refuses them today; otherwise follow what `--replicas`
  does on `add`.
- The dry-run preview names the change (`resources requests.cpu=100m`), like the other options.
- `set.md`: `[--resources K=V]` in the description and one clause in the options paragraph; byte-neutral (shorten the
  paragraph); register entry only if a rule sentence changes.

**Done when:** the AC-179.1 acceptance test of `component set --resources` (system.yaml and the rendered Deployment's
container `resources`) passes; `test_compose*.py` and `test_component*.py` pass.

## t8 — System ship entry applies the replicas and resources operations

**Files:** scripts/cplat/appship.py
**Covers:** AC-179.1
**Goal:** `cplat system ship entry apply` runs the two new operations with `cplat component set`, one commit each
(design.md section 1, `entry_ops`).

**Implementation notes:**
- `entry_ops`: `replicas` (with optional `instance`) and `resources` (flattened in mapping order) exactly as the design's
  table; check `replicas` before the `expose` branch so an operation never matches two kinds.
- `entry_body` lists them like the other operations (no change needed beyond `entry_ops`, verify).
- Nothing else in the entry flow changes: no extra PR, no new phase.

**Done when:** the AC-179.1 acceptance tests on `entry_ops` pass, and the `entry apply` test with a `resources`
operation passes once t7 is merged; `test_appship*.py` pass.

## t9 — Run records, run rows and escalation items carry the repo shape

**Files:** scripts/cplat/runs.py, scripts/cplat/runlist.py, scripts/cplat/needs.py
**Covers:** AC-179.7
**Goal:** an escalation item knows the shape of the repo its run ran in (design.md section 6).

**Implementation notes:**
- `runs.start(..., shape: str | None = None)`: the key only when known; the derivation inside the existing
  `try` (recording never changes a run). `git rev-parse --show-toplevel` of `Path.cwd()`, then `spec.repo_shape`;
  import `spec` inside the function (avoid an import cycle).
- `runlist.row`: `**({"shape": s} if s else {})`, the record's value first, else `spec.repo_shape(Path(repo_dir))`
  when `repo_dir` is a directory, errors swallowed.
- `needs._escalations`: `_obj(..., **({"shape": r["shape"]} if r.get("shape") else {}))`.
- Keys are added only when known, so the existing fixtures that compare whole rows or items stay equal.

**Done when:** the AC-179.7 acceptance tests on the record, row and item pass; `test_runs*.py`, `test_runlist*.py`,
`test_needs*.py` and `test_dispatch*.py` pass.

## t10 — Notifier - explicit cells and the platform escalation preset per event

**Files:** scripts/cplat/notify_config.py, scripts/cplat/notify.py
**Covers:** AC-179.7, AC-179.8
**Goal:** escalations of platform-repo runs go to the desktop, never to GitHub, unless the user's file says otherwise
(design.md section 6).

**Implementation notes:**
- `Config.explicit` filled in `_apply_events` (`f"{event}.{channel}"`); `PLATFORM_ESCALATION` and `cells_for` as
  designed; `recommended()` unchanged (other shapes keep their preset).
- `notify.events_of`: escalation events (the generic needs branch) get `"shape": obj.get("shape")`; other events
  `None`.
- `notify.process`: iterate `notify_config.cells_for(cfg, ev["event"], ev.get("shape")).items()`; quiet hours, held
  sends, signatures and resolution unchanged.
- `autoissue` is not touched; AC-179.8's filing half is proven by tests against the unchanged path.
- Update the `notify_config` module docstring with one line on the platform preset.

**Done when:** the AC-179.7 / AC-179.8 acceptance tests pass (no `gh issue create` for a platform escalation, a desktop
send instead; `escalation: {github: instant}` in the file restores the issue; other shapes unchanged); `test_notify*.py`,
`test_122*.py` and `test_dispatch_notify*.py` pass.

## t11 — Build prompts - test review before the freeze, type-only and smoke findings, git rm

**Files:** plugins/component/commands/build.md, plugins/component/references/unit-mode.md, plugins/component/references/build-tighten.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/unit-mode.yml, docs/rules/plugins/component/references/build-tighten.yml
**Covers:** AC-179.3, AC-179.4, AC-179.5, AC-179.6, AC-179.9
**Goal:** the build runs the flow of design.md sections 3–5 without asking the person.

**Implementation notes:**
- Phase 1: the skip rule (reviewed commit → skip; trace only → start at the review); after `TRACE`, the reviewer in
  test-review mode (brief: criteria, contract, `TRACE`; `cplat platform runs agent spawned reviewer`); findings → the
  tester round of the design once (trace must pass, else revert and count all as unresolved); then lint-fix commit,
  `cplat component build reviewed <id> --findings <n> [--unresolved '<test> | <AC> | <what>']...`, then `RED=`.
- Coder prompt (2.3): after the suppression sentence, allow a type-only change the type check needs (annotation, cast,
  import; no assertion line touched). Keep the hard-rule sentence verbatim.
- Phase 2 step 2 and Phase 3 step 4: a `type-only` line, like a `test helper` line → `build-tighten.md`.
- Phase 4: the reviewer gets `TEST REVIEW` (the `unresolved:` lines of the reviewed commit, or `none`); step 3:
  `SMOKE` items → tester in the same round, `cplat platform runs agent smoke <file> --finding '<finding>'`, run the test,
  never ask the user.
- `build-tighten.md`: merge the test-helper paragraph into "A test helper or type-only line" (`--tighten` without
  asking, exit 1 → `build-test-approval.md`).
- `unit-mode.md`: the permissions line names `git rm` of tracked files (never forced); the `red-tests` row ends with
  "the test review and `cplat component build reviewed`".
- Keep the phrases pinned by `test_165_test_problems.py`, `test_171_test_helpers.py`, `test_runs_built_133.py`,
  `test_smoke_091_spec.py`, `test_152_mutation.py` and the lean-prompt tests verbatim.

**Done when:** `cplat platform rules check` passes on the repo, the acceptance tests that read these prompts pass, and
`cplat quiet test-fast` shows no newly failing prompt test.

## t12 — Reviewer - test-review mode, SMOKE line, TEST REVIEW input

**Files:** plugins/svc/agents/reviewer.md, docs/rules/plugins/svc/agents/reviewer.yml
**Covers:** AC-179.5, AC-179.6, AC-179.9
**Goal:** the reviewer can review acceptance tests before the freeze, reports loose smoke tests, and lists unresolved
test-review findings in `verification.md` (design.md sections 4 and 5).

**Implementation notes:**
- A short section "Test-review mode": inputs, the three contradiction kinds, read-only (no `verification.md`), the
  `TEST FINDINGS:` reply exactly as designed.
- Inputs: `TEST REVIEW` (or `none`); workflow step 6 adds the `## Unresolved test-review findings` table.
- Workflow: a test outside the trace that can pass without the feature → `SMOKE:` line, not a verdict; a traced test
  stays `TEST LOOSER`.
- Reply block: the `SMOKE:` line after `DEVIATIONS:`.
- Byte-neutral within the file; register entries for the new rule sentences.

**Done when:** `cplat platform rules check --only plugins/svc/agents/reviewer.md` passes and the acceptance tests that
read the reviewer prompt pass.

## t13 — System planner and ship-entry - instance settings become entry operations

**Files:** plugins/system/agents/planner.md, plugins/system/references/ship-entry.md, docs/rules/plugins/system/agents/planner.yml, docs/rules/plugins/system/references/ship-entry.yml
**Covers:** AC-179.1
**Goal:** the planner turns every criterion that states an instance setting into a gitops entry operation with the
criterion in the entry's `acs` and `order: before-merge`, never a separate PR or question (design.md section 1).

**Implementation notes:**
- planner.md step 4: the YAML example gains `{replicas: 2, component: todo-api, instance: staging}` and a `resources`
  line; the sentence listing the operations names all six; one rule sentence with its reason (the approved spec
  decided the value, so it ships in the one entry PR); the plan template's gitops entry shows `order: before-merge`.
- ship-entry.md step 1: the two new operations in the mapping list (`→ cplat component set … --replicas` /
  `--resources`).
- Byte-neutral across the two prompts (shorten the step 4 prose).

**Done when:** `cplat platform rules check` passes for both files and the acceptance tests that read them pass.

## t14 — Plugin versions, docs, ADR index and changelog fragment

**Files:** plugins/component/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/console.md, docs/unattended-delivery.md, docs/adr/README.md, docs/changelog.d/179-unattended-runs-ask-less.changed.md
**Covers:** AC-179.1, AC-179.3, AC-179.7
**Goal:** versions, user docs and the release note for the change.

**Implementation notes:**
- Minor bump of `component`, `svc` and `system` in each `plugin.json` and the matching marketplace entries.
- `docs/console.md` (Notifications): one paragraph: escalations of runs in the platform repo (`shape: platform`) go to
  the desktop, never to GitHub, unless `events.escalation.github` is set; auto-filed platform issues are unaffected.
- `docs/unattended-delivery.md`: a short section "What a run no longer asks": instance settings from the system plan,
  `git rm` of tracked files, type-only test changes, the one test review before the freeze (link ADR-101),
  smoke-test findings. Relative links only.
- `docs/adr/README.md`: the ADR-101 row in the style of the 093–095 rows.
- Fragment per `docs/changelog.d/README.md`: bold summary ending `(spec 179).`; name #616, #653, #654, #655, #642,
  #643; note that gitops-app repos get the new plan check with `/platform:update` and that plugins update with
  `/plugin marketplace update`.

**Done when:** `devbox run validate` and `python3 scripts/check-links.py` pass, and `cplat platform pr-check` reports
no fragment or version problem.

## t4 — units - the red-tests unit needs the reviewed commit

**Files:** scripts/cplat/units.py, tests/cplat/units131_support.py, tests/cplat/test_units_131.py
**Covers:** AC-179.5, AC-179.6
**Goal:** a red-tests unit is done only after the test review, so the tests freeze at the reviewed commit
(design.md section 4, Units).

**Implementation notes:**
- `_evaluate` for `red-tests`: trace, then `testreview.reviewed_commit(repo, spec_id, head)`; the design's reason text.
- `next_step("red-tests", …)`: name the review and `cplat component build reviewed <spec>`.
- `_acceptance_commit` and `only_verification_left` unchanged.
- Fixtures: `units131_support.py` (the helper that commits `acceptance tests for …`) and the two places in
  `test_units_131.py` that commit acceptance tests to make red-tests done also commit
  `test(007): reviewed acceptance tests for <spec id>` (empty, `--allow-empty`); change no assertion.

**Done when:** the AC-179.5 / AC-179.6 acceptance tests on the red-tests unit (not done without the reviewed commit,
checkpoint at it, `test-diff` compares against it) pass; `test_units_131.py`, `test_headless*.py`,
`test_169_*.py` and `test_build_parallel_501.py` pass.

## t5 — PR block - unresolved test-review findings and tightened smoke tests

**Files:** scripts/cplat/runs_built.py, scripts/cplat/runs_agents.py
**Covers:** AC-179.6, AC-179.9
**Goal:** the "How this was built" block lists every unresolved test-review finding and every tightened smoke test
(design.md sections 4 and 5).

**Implementation notes:**
- `runs_agents`: subcommand `smoke <file> --finding <text>`; `smoke(run_id, repo, file, finding)` adds the design's
  event to the tester entry through `_change(..., "tester_events")`; malformed input → the usual warning, exit 0.
- `runs_built.collect`: event kind `smoke` → `smoke test tightened <file>: <finding>`; then, with the run's spec dir
  known, `testreview.unresolved(repo, spec_id)` → `test review left open: <test> (<AC>): <what>`, both in `handbacks`;
  any error reading git adds nothing (the block never fails a PR).
- Update the module docstring's list of sources (the reviewed commit).

**Done when:** the AC-179.6 / AC-179.9 acceptance tests on the block pass; `test_runs_built_133.py` and
`test_runs_agents*.py` pass.
