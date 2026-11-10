---
spec_id: 172-builds-catch-problems-before-the-pull
shape: platform
spec_hash: c7021d7b264b
summary: test-diff judges only the frozen red-tests files, coders run their own tests, new tests run under load before the PR, build merge refuses unsigned commits, the rules check catches hidden instructions
tasks:
  - id: t1
    title: test-diff selects only the test files the red-tests step committed
    files: [scripts/cplat/testdiff_select.py, scripts/cplat/spec.py]
    covers: [AC-172.1, AC-172.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cplat quiet passes arguments after -- to test-fast; platform test-fast runs only given tests
    files: [scripts/cplat/quiet.py, scripts/test-fast.sh, devbox.json, scripts/cplat/cplat.py]
    covers: [AC-172.3, AC-172.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: quiet --repeat runs the named tests at once and tells flaky from failing
    files: [scripts/cplat/quiet_repeat.py, scripts/cplat/flaky.py]
    covers: [AC-172.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: cplat component build tests prints a task's and the load run's test command
    files: [scripts/cplat/buildtests.py]
    covers: [AC-172.4, AC-172.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: build merge refuses unsigned commits in the platform repo; dispatch of build tests
    files: [scripts/cplat/signoff.py, scripts/cplat/buildcmd.py]
    covers: [AC-172.7, AC-172.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: Build prompt - coder runs its own tests, sign-off rebase, the load run 2.6
    files: [plugins/component/commands/build.md, docs/rules/plugins/component/commands/build.yml, plugins/component/references/build-load-run.md, docs/rules/plugins/component/references/build-load-run.yml]
    covers: [AC-172.4, AC-172.6, AC-172.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: Re-class the planner entry the hidden-rule finding flags on main
    files: [plugins/system/agents/planner.md, docs/rules/plugins/system/agents/planner.yml]
    covers: [AC-172.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: Plugin versions, changelog fragment, ADR index and AGENTS.md
    files: [plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/172-builds-catch-problems.added.md, docs/adr/README.md, docs/AGENTS.md]
    covers: []
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: rules check fails on an instruction with a condition classed not a rule
    files: [scripts/cplat/promptrules.py, scripts/cplat/rulescheck.py, docs/rules/README.md]
    covers: [AC-172.8]
    parallel_safe: true
    depends_on: [t7]
    done: true
---

# Plan — 172 Builds catch problems before the pull request

The contract is [design.md](design.md). Level 0 runs eight tasks with disjoint files in parallel: the test-diff
selection (t1), the two halves of `cplat quiet` joined by `quiet_repeat.run` (t2, t3), the test-command helper and its
CLI hook (t4, t5), the build prompt (t6), the re-class of the one register entry the new rules finding flags on `main`
(t7) and the release bookkeeping (t9). Level 1 adds the rules finding itself (t8) once t7 has made `main` pass it, so
the repo-wide `cplat platform rules check` stays green at every merge. Spec 171 is built in parallel: no task touches
`ship.py`, `pr.py`, `merge_lock.py`, `preflight.py`, `house_rules.py`, `appship*.py` or `stopgate.py`, and t1 changes
`spec.py` only inside `test_diff` and the `test-diff` branch of `main`.

## t1 — test-diff selects only the test files the red-tests step committed

**Files:** scripts/cplat/testdiff_select.py, scripts/cplat/spec.py
**Covers:** AC-172.1, AC-172.2
**Goal:** `cplat spec test-diff <red>` without file arguments checks the frozen test files (design 1) and nothing else,
so a coder's own test naming its criterion never stops a build; without a red-tests commit it falls back to today's
selection and says so in one line.

**Implementation notes:**
- New `testdiff_select.py`: `red_commits(root, spec)` (non-merge commits reachable from HEAD, oldest first, subject
  containing `acceptance tests for` and naming the spec as design 1 says), `in_range(root, given, sha)`,
  `frozen_files(root, given, frozen, building) -> set[str] | None`.
- The path filter reuses `spec.test_globs(spec.repo_shape(root))`, `spec._ignored`, `docs/` and `.md` exclusions; the
  criterion check reads the content at the frozen commit (`git show <frozen>:<path>`), so a file deleted later still
  counts as frozen.
- `spec.test_diff(root, base, files, *, red=None, notes=None)`: frozen mode intersects the frozen set with
  `git diff --name-only <base>` and keeps deleted frozen files (verdict `new or deleted file`); fallback keeps today's
  code path untouched (including `created_by_plan`) and appends the fallback line of design 1 to `notes`.
- `main`: remember the typed base before the spec 169 adjustment, pass it as `red=`, print the notes before the
  per-file lines. No other change in `spec.py` (spec 171 edits `spec new --tracks` in the same file).
- Existing callers `spec.test_diff(root, "HEAD", [])` keep working (keyword arguments only).

**Done when:** the AC-172.1 and AC-172.2 tests pass, and the existing test-diff tests (`test_spec.py`,
`test_160_lint_suppressions.py`, `test_165_test_problems.py`, `test_169_red_freeze.py`, `test_spec_324.py`) still pass.

## t2 — cplat quiet passes arguments after -- to test-fast; platform test-fast runs only given tests

**Files:** scripts/cplat/quiet.py, scripts/test-fast.sh, devbox.json, scripts/cplat/cplat.py
**Covers:** AC-172.3, AC-172.5
**Goal:** `cplat quiet test-fast -- <args>` hands the arguments unchanged to the test runner with today's output, log
and flake handling; every other argument form is refused with the new usage line and exit 2; `--repeat N` is parsed,
validated and handed to `quiet_repeat.run`.

**Implementation notes:**
- Parse `[--raw] <script> [--repeat N] [-- <args>...]` exactly as design 2; the usage line is the design's, on stderr.
- Refusals (exit 2, usage line): unknown script, any argument after a script other than `test-fast`, arguments not
  starting with `--`/`--repeat`, N not an integer 2..5, `--repeat` without `--` or without arguments after it.
- Single run with arguments: `["devbox", "run", "test-fast", "--", *args]`, same log name, same success/failure output;
  failsum `command=` includes the arguments; `_flaky` unchanged.
- `--repeat`: `import quiet_repeat` lazily and `return quiet_repeat.run(cwd, n, args, raw=raw, on=on)` (t3 writes it;
  signature in design 2), after `failsum.enabled` is read as today.
- `scripts/test-fast.sh` and the `devbox.json` recipe exactly as design 3 (bash, `set -euo pipefail`, header comment
  naming spec 172); `devbox run test-fast` without arguments still runs `tests/cplat` with `-q -n auto`.
- `cplat.py` docstring: the `cplat quiet` line shows `[--repeat N] -- <test args>` for test-fast, and the
  `cplat component build …` line lists `tests` (t5 wires it).

**Done when:** the AC-172.3 tests pass (argument pass-through, refusals with exit 2, platform `test-fast` with a file
and with `-k`), the refusal cases of AC-172.5 pass, and the existing quiet and flaky tests still pass.

## t3 — quiet --repeat runs the named tests at once and tells flaky from failing

**Files:** scripts/cplat/quiet_repeat.py, scripts/cplat/flaky.py
**Covers:** AC-172.5
**Goal:** `quiet_repeat.run` starts N runs of the named tests at once, reruns each failed test alone, and exits 0 (all
pass), 3 (flaky under load only, recorded in `flaky_tests`) or 1 (a test fails alone too, or the failure names no tests).

**Implementation notes:**
- `run(cwd, n, args, *, raw, on) -> int` exactly as design 2, steps 1 to 5; logs via `quiet._log_path`-style names
  (`<stamp>-test-fast-repeat-<i>.log`, `<stamp>-test-fast-alone-<j>.log`) in the same log directory.
- N `subprocess.Popen` started before any is waited for; each gets `CPLAT_REPEAT_RUN=<i>` on top of `os.environ`.
- Attribution: `failsum.summarize` per failed run, `flaky.failed_tests(summary, limit=MAX_LOAD_TESTS)` with
  `MAX_LOAD_TESTS = 20`; differing tools across runs or None → not attributable (exit 1, design's line).
- Alone reruns one after another with `flaky.rerun_args(tool, [t])`; output lines `flaky under load: <t> (failed in <k>
  of <N> runs)` plus `  failed in: <logs>`, the `FLAKY: …` last line on exit 3.
- Record each flaky test with `runs.add_to(runs.current_run(cwd), "flaky_tests", {...})` inside `try/except`, never
  changing the result.
- `flaky.failed_tests(summary, limit=MAX_TESTS)`: `limit=None` removes the cap; spec 165 callers unchanged.
- Printing honours `raw` / `on` like `quiet.main` (summary or raw tail).

**Done when:** the AC-172.5 tests for all-pass (0), flaky (3, line and `flaky_tests` entry), failing alone (1) and not
attributable (1) pass, with a fake `devbox` on PATH; spec 165's flaky tests still pass.

## t4 — cplat component build tests prints a task's and the load run's test command

**Files:** scripts/cplat/buildtests.py
**Covers:** AC-172.4, AC-172.6
**Goal:** one printed line gives a coder its test command (its covered criteria's acceptance test files plus the test
files in its `files`) and the build its load-run command, in the form the shape's runner selects tests.

**Implementation notes:**
- `main(argv) -> int` with its own argparse (`<spec> [<task>] [--load] [--base REF] [--json] [--repo DIR]`), contract
  as design 4; `PlatformError` for an unknown spec or task, a gitops task (`repo:`), or a task with `--load`.
- `TEST_FAST` table exactly as design 4, keyed by `spec.repo_shape(root)`; glob matching via `validate.matches`.
- Task mode: `spec.trace(root, spec, spec.test_globs(spec.spec_shape(spec, shape)))` for the task's `covers`, plus the
  task's `files` (literal paths whether or not they exist; directory and glob entries expanded against existing files).
- Load mode: every active criterion's trace files plus `git diff --name-only <base>..HEAD` files that exist; `base`
  defaults to `git merge-base main HEAD`; `none: <reason>` lines of design 4 (no runner, no files, service-java).
- Selection args: paths; Go `-run ^(A|B)$` from `^func (Test\w+)\(`; Surefire `-Dtest=…` plus
  `-Dsurefire.failIfNoSpecifiedTests=false`; the command line built with `shlex.join`.
- `--json` document as design 4.

**Done when:** the AC-172.4 and AC-172.6 tests for the helper pass when called as `buildtests.main([...])`; the
`cplat component build tests` CLI form passes once t5 is merged.

## t5 — build merge refuses unsigned commits in the platform repo; dispatch of build tests

**Files:** scripts/cplat/signoff.py, scripts/cplat/buildcmd.py
**Covers:** AC-172.7, AC-172.4
**Goal:** in the platform repo `cplat component build merge` refuses a branch that brings in a commit without a
`Signed-off-by` line before merging anything, naming each commit and the rebase command; `cplat component build tests`
reaches `buildtests.main`.

**Implementation notes:**
- New `signoff.py`: `unsigned(repo, rev_range)` with `house_rules.SIGNED` (import only, no edit of `house_rules.py`)
  over `git log --format=%h%x00%s%x00%B%x1e <range>` (merge commits included); `worktree_of(repo, branch)` from
  `git worktree list --porcelain`.
- `buildcmd.merge`: after the #501 check and before `git merge`, when `spec.repo_shape(repo) == "platform"`, run
  `signoff.unsigned(repo, f"HEAD..{branch}")`; any → `PlatformError` with the message and hint of design 5 (merge base
  via `git merge-base HEAD <branch>`). No `replan.set_pending`, no `runs_agents.conflict`, no record.
- Other shapes: no check, merge unchanged.
- `buildcmd.main`: `if argv and argv[0] == "tests": import buildtests; return buildtests.main(argv[1:])` before argparse;
  module docstring gains the `tests` line.

**Done when:** the AC-172.7 tests pass (refusal leaves HEAD and tree, no pending re-plan, exit not 0/3/4, each commit
named, worktree hint; a non-platform repo merges as before) and the existing `build merge` tests
(`test_build_parallel_501.py` and the spec 094 tests) still pass.

## t6 — Build prompt: coder runs its own tests, sign-off rebase, the load run 2.6

**Files:** plugins/component/commands/build.md, docs/rules/plugins/component/commands/build.yml, plugins/component/references/build-load-run.md, docs/rules/plugins/component/references/build-load-run.yml
**Covers:** AC-172.4, AC-172.6, AC-172.7
**Goal:** the build prompt gives each coder only its own test command, rebases an unsigned task branch without asking,
and runs the new tests under load between 2.5 and Phase 3 with the tester fixing a flaky harness (design 7).

**Implementation notes:**
- 2.3 `Commands`: `cplat quiet test-fast -- <the task's test files>` (the line `cplat component build tests <id>
  <task>` prints) and `cplat quiet quality`; **Done when** runs that command, not the whole suite.
- 2.4 step 1: exit 1 naming commits without `Signed-off-by` → run the printed `git -C <worktree> rebase --signoff
  <sha>`, then the merge again, without asking.
- 2.5 unchanged in substance (`cplat quiet test-fast`, the whole suite once); Phase 3 keeps `cplat quiet ci`.
- New `### 2.6 Under load`: the line `cplat component build tests <id> --load` prints; `none: …` → skip and name it in
  the report; exit 1 → coder of a covering task as in 2.5; exit 3 → read `${CLAUDE_PLUGIN_ROOT}/references/build-load-run.md`.
- `build-load-run.md`: the tester's **Harness mode** brief (each flaky test, the logs `cplat quiet` printed; fix only
  fixtures, helpers, fakes, process clean-up in files that are not frozen; never an assertion), then `cplat spec
  test-diff $RED` (exit 1 → the person approves as in `build-test-approval.md`), the repeated run again, at most 2
  rounds, then `cplat platform runs end --outcome escalated --reason 'flaky under load: <tests>'`.
- Every rule sentence added or changed gets its register entry with a reason clause (docs/rules/README.md); never class
  an instruction with a condition clause `not a rule` (design 6).
- Keep the prompts within the byte baseline: pay for the added text by tightening other sentences of `build.md`.

**Done when:** the AC-172.4, AC-172.6 and AC-172.7 prompt tests pass; `cplat platform rules check` passes (also with
`--only plugins/component`); existing build-prompt tests (e.g. `test_runs_agents.py::test_the_prompt_passes_task_and_quality_to_test_diff`) still pass.

## t7 — Re-class the planner entry the hidden-rule finding flags on main

**Files:** plugins/system/agents/planner.md, docs/rules/plugins/system/agents/planner.yml
**Covers:** AC-172.8
**Goal:** the one register entry on `main` that the new `hidden-rule` finding flags (planner R3, "Aim for 8 or fewer, …;
above 12 `plan-check` refuses the slice unless it has `criteria_why:` …") is re-classed, so AC-168.6 keeps holding
when t8 lands (A13).

**Implementation notes:**
- Split the sentence: "Aim for 8 or fewer, because a small slice stays checkable." (its existing purpose; a `practice`
  entry, no condition clause) and a separate statement about `plan-check` refusing above 12 without `criteria_why:`
  (spec 154), classed `not a rule`, starting with no listed verb and without "you"; merge advice kept.
- Update R3's text and class, add the new entry with the next free `R<n>`; keep `source: spec 154`.
- Before handing back, apply design 6's algorithm by hand to every `not a rule` entry of the register (28 today) and
  report any other sentence it would flag; none is expected.
- Bytes: the reworded sentence must not grow the prompt.

**Done when:** `cplat platform rules check` passes, and the planner prompt tests (if any pin the sentence) still pass.

## t9 — Plugin versions, changelog fragment, ADR index and AGENTS.md

**Files:** plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/172-builds-catch-problems.added.md, docs/adr/README.md, docs/AGENTS.md
**Covers:** none (release bookkeeping and documentation)
**Goal:** the PR passes `cplat platform pr-check`: changed plugins bumped in both places, one changelog fragment, the
ADR index row, and the orchestration model describing the new build steps.

**Implementation notes:**
- Component plugin 1.15.0 → 1.16.0 (build prompt and new reference); system plugin patch bump (planner wording); the
  matching `marketplace.json` entries.
- Fragment per `docs/changelog.d/README.md`: test-diff judges only the frozen red-tests files, `cplat quiet test-fast --
  <args>` and `--repeat`, `cplat component build tests`, the build's load run, `build merge` refusing unsigned commits in
  the platform repo, the rules check's `hidden-rule` finding.
- `docs/adr/README.md`: the row for ADR-094 (spec 171 adds 092 and 093 in parallel: keep the table sorted).
- `docs/AGENTS.md` (the parallel-merge paragraph): coders run `cplat quiet test-fast -- <their tests>`, unsigned commits
  are refused at the merge in the platform repo, and the load run before Phase 3.

**Done when:** `devbox run validate`, `devbox run quality` (version loop, links) pass.

## t8 — rules check fails on an instruction with a condition classed not a rule

**Files:** scripts/cplat/promptrules.py, scripts/cplat/rulescheck.py, docs/rules/README.md
**Covers:** AC-172.8
**Goal:** `cplat platform rules check` fails with kind `hidden-rule` (file, line, text, hint) on a `not a rule` entry
whose sentence has a condition clause and reads as an instruction, as design 6 defines it.

**Implementation notes:**
- `promptrules.IMPERATIVES` (the design's list, a frozenset) and `instruction(sentence) -> bool` on the masked sentence:
  `you`/`your` word, else strip leading markers, emphasis, one label ending in `:` of at most 8 words, one leading
  `If …,`/`When …,` clause, then the first word in the list.
- `rulescheck._check_prompt`: after the single entry is resolved, `entry.cls == "not a rule"` and
  `pr.condition(s.text)` and `pr.instruction(s.text)` → `Failure("hidden-rule", rel, s.line, s.text, <design message>)`.
- `docs/rules/README.md`: "Rewriting rules" gains the rule that an instruction with a condition clause is never `not a
  rule`; the class description of `not a rule` says how the check decides it.
- The module docstring of `rulescheck.py` names the new finding.

**Done when:** the AC-172.8 tests pass (the two failing examples, the passing one, file/line/text/hint in text and
`--json`), `cplat platform rules check` passes on the repo (t7 merged), and the existing spec 168 rules tests still pass.
