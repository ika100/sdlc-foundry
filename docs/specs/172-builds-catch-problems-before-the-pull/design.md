# Design — 172 Builds catch problems before the pull request

## Decisions

- **The frozen set comes from git history, not from a new state file.** The red-tests step's commits are found by their
  subject ("acceptance tests for" naming the spec), so a resumed build, a unit-mode run and a manual build all read the
  same set without anything new to write or lose (AC-172.1, AC-172.2). The selection lives in a new module
  `testdiff_select.py`; `spec.py` only calls it, so the change there stays inside `test_diff` and the `test-diff` branch of
  `main` (spec 171 edits other parts of `spec.py` in parallel).
- **`test-fast` alone takes arguments, after `--`; `--repeat` lives in a module of its own** (`quiet_repeat.py`), so that
  `quiet.py` keeps its single-run path and the argument parsing; the two are joined by one function (AC-172.3, AC-172.5).
- **The platform repo's `test-fast` becomes `scripts/test-fast.sh`**: no arguments or only options → `tests/cplat` plus
  them; any argument naming an existing path (a `::` node id counts by its file part) → only the arguments (A4). The
  templates' recipes already end in `"$@"` and stay unchanged.
- **One deterministic helper computes the tests a coder and the load run use**, `cplat component build tests`, so the
  orchestrator copies one printed line instead of deriving files from the trace, and the shape's runner form (paths,
  Go `-run`, Surefire `-Dtest`) is decided in code (AC-172.4, AC-172.6). The per-shape table lives in `buildtests.py`, not
  in `shapes.yml`, because a `shapes.yml` change puts every pull request into the full e2e scope (`scripts/e2e-scope.py`).
- **The sign-off check is a refusal before `git merge` runs**, in a module of its own (`signoff.py`) reusing
  `house_rules.SIGNED`, so `build merge` and `cplat platform pr-check` agree on what a sign-off is (AC-172.7).
- **"Reads as an instruction" is a pure function in `promptrules.py`** with a fixed verb list; `rulescheck.py` adds one
  failure kind (AC-172.8).
- The durable part (coders run their own tests, new tests run under load before the PR, flaky under load exits 3) is
  [ADR-094](../../adr/094-a-build-runs-each-coder-on-its-own-tests-and-new-tests-under-load.md).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/testdiff_select.py` | red-tests commits of a spec, the frozen test files | new |
| `scripts/cplat/spec.py` | `test_diff` uses the frozen set; `main` prints the fallback line | changed |
| `scripts/cplat/quiet.py` | argument parsing (`--`, `--repeat`), args passed to `devbox run test-fast` | changed |
| `scripts/cplat/quiet_repeat.py` | n runs at once, attribution, alone reruns, exit 0/1/3 | new |
| `scripts/cplat/flaky.py` | `failed_tests(..., limit=)` | changed |
| `scripts/test-fast.sh`, `devbox.json` | platform `test-fast` with arguments | new / changed |
| `scripts/cplat/buildtests.py` | `cplat component build tests` | new |
| `scripts/cplat/signoff.py` | unsigned commits of a branch, the worktree that has it checked out | new |
| `scripts/cplat/buildcmd.py` | `merge` refuses unsigned commits in the platform repo; dispatches `tests` | changed |
| `scripts/cplat/promptrules.py` | `IMPERATIVES`, `instruction(sentence)` | changed |
| `scripts/cplat/rulescheck.py` | failure kind `hidden-rule` | changed |
| `plugins/component/commands/build.md` (+ `references/build-load-run.md`) | coder `Commands`, sign-off rebase, step 2.6 | changed / new |

## Contract

### 1. `cplat spec test-diff <base>` file selection (AC-172.1, AC-172.2)

Unchanged: the CLI, `--approve`, `--tighten`, `--task`, `--by`, explicit file arguments (they are checked as given), the
per-file verdicts and their texts, the exit codes (0 / 1), the spec 169 line `base: <sha7>, where the red-tests unit
ended (spec 169), not <sha7>`.

Definitions, for every spec whose status is `building`:

- **Red-tests commit of spec S:** a non-merge commit reachable from `HEAD` whose subject contains `acceptance tests for`
  and names S: `AC-<NNN>.` or the word `<NNN>` (S's number, `(?<![\w.])<NNN>(?![\w])`) or S's full id. This matches
  `test(<slug>): acceptance tests for AC-172.1–AC-172.8`, `test: acceptance tests for 172` and
  `test(<slug>): lint-fix acceptance tests for 172-…`.
- **Given base:** the `<base>` argument as typed, before the spec 169 adjustment. **Frozen commit:** the base after it
  (`spec.frozen_base`, which is the given base when no red-tests unit is recorded).
- **Frozen mode** applies when at least one red-tests commit of a `building` spec is the given base or a descendant of
  it (and an ancestor of `HEAD`). Otherwise **fallback**.
- **Frozen test files (frozen mode):** for each `building` spec with a red-tests commit, `first` = its oldest red-tests
  commit; the paths changed by the non-merge commits from `first` (inclusive) to the frozen commit (inclusive), i.e.
  `git log --no-merges --format= --name-only <frozen> ^<first>^` (without the `^<first>^` part when `first` has no
  parent); kept when the path matches the shape's `test_globs`, is not under `docs/`, does not end in `.md`, is not
  `_ignored`, exists in the frozen commit and its content there names a criterion id of a `building` spec (A1). The union
  over the specs.

`test_diff(root, base, files, *, red=None, notes=None)` (`red` defaults to `base`; `notes`, when a list, receives the
lines `main` prints first):

- No file arguments, frozen mode: the checked files are the frozen test files that `git diff --name-only <frozen>` lists
  (a deleted one included: it is reported `changed — new or deleted file`). A file outside the frozen set is never
  reported, whatever criterion id it names; `created_by_plan` is not consulted.
- No file arguments, fallback: the selection of today (changed test files naming a criterion of a `building` spec, minus
  the plan's new files) and exactly one note line:
  `fallback: no 'acceptance tests for' commit of a building spec between <given base sha7> and HEAD; checking every changed test file that names a criterion of a building spec (as before spec 172)`
- `main` prints the note lines before the per-file lines; nothing else in the output changes.

`testdiff_select.py`: `red_commits(root, spec) -> list[str]` (oldest first), `in_range(root, given, sha) -> bool`,
`frozen_files(root, given, frozen, building) -> set[str] | None` (None = fallback). Git through `subprocess` with
`git -C <root>`, as `spec.py` does.

### 2. `cplat quiet` (AC-172.3, AC-172.5)

```
cplat quiet [--raw] <devbox-script>
cplat quiet [--raw] test-fast [--repeat N] -- <test args>...
```

Usage line (stderr, exit 2), replacing today's:
`usage: cplat quiet [--raw] <devbox-script> | cplat quiet [--raw] test-fast [--repeat N] -- <test args>   (a key of shell.scripts in ./devbox.json; only test-fast takes arguments, after --)`

Refused with the usage line and exit 2: an unknown script; any argument after a script other than `test-fast`;
arguments after `test-fast` that do not start with `--` or `--repeat N` (e.g. `cplat quiet test-fast tests/x.py`);
`--repeat` with N not an integer from 2 to 5; `--repeat` without `--` or with nothing after `--`.

`cplat quiet test-fast -- <args>` (no `--repeat`): runs `devbox run test-fast -- <args>` (args unchanged, as separate
argv items) into the same log file name as today (`<stamp>-test-fast.log`); the success line, the failure summary and
the sidecar are exactly as for `cplat quiet test-fast`; the failsum `command` field is `devbox run test-fast -- <args>`;
the spec 165 flake rerun (`_flaky`) applies unchanged, exit 0 when it clears. `cplat quiet test-fast --` with nothing
after it is the same as no arguments.

`cplat quiet test-fast --repeat N -- <args>` → `quiet_repeat.run(cwd, n, args, raw=<bool>, on=<failsum enabled>) -> int`:

1. Starts N processes `devbox run test-fast -- <args>` at the same time (`subprocess.Popen`, cwd, each with the extra
   environment variable `CPLAT_REPEAT_RUN=<i>`, i = 1..N, and its own log `<stamp>-test-fast-repeat-<i>.log`), then waits
   for all.
2. All exit 0 → prints `ok: <N> runs at once of devbox run test-fast passed (logs: <log 1> … <log N>)`, exit 0.
3. Otherwise each failed run is summarised with `failsum.summarize`; `flaky.failed_tests(summary, limit=MAX_LOAD_TESTS)`
   (20) must name its tests and all failed runs must report the same tool, else the failure is **not attributable**: the
   first failed run's summary (or the raw tail with `--raw` / summaries off) is printed with
   `FAILED under load: a failure not attributable to named tests`, exit 1.
4. Each distinct failed test `t` (sorted), `k` = the number of runs it failed in, is run once more alone, one after
   another: `devbox run test-fast -- <flaky.rerun_args(tool, [t])>` into `<stamp>-test-fast-alone-<j>.log`, without
   `CPLAT_REPEAT_RUN`.
   - Passes → prints `flaky under load: <t> (failed in <k> of <N> runs)` and `  failed in: <log>, …` (the logs of the
     runs it failed in); adds `{"test": t, "script": "test-fast", "repeat": N, "failed_runs": k}` to the run record's
     `flaky_tests` (`runs.add_to(runs.current_run(cwd), ...)`; recording never changes the result).
   - Fails → its summary is printed (title `FAILED (exit <rc>): devbox run test-fast -- <rerun args> (log: <log>)`).
5. Exit 1 when any test failed alone too; else exit 3 with the last line
   `FLAKY: <m> test(s) failed under load and passed alone; fix the harness before the pull request`. Never 0 once a run
   failed.

`flaky.failed_tests(summary, limit=MAX_TESTS)`: `limit=None` means no cap; the default keeps spec 165's behaviour.

### 3. Platform `test-fast` (AC-172.3, A4)

`devbox.json`: `"test-fast": "bash scripts/test-fast.sh \"$@\""`. `scripts/test-fast.sh` runs
`uv run --with-requirements requirements-test.txt pytest -q -n auto <targets>`: no arguments → `tests/cplat`; arguments
of which none names an existing path (after cutting `::…`) → `tests/cplat <args>`; otherwise `<args>` alone. So
`-- tests/cplat/test_x.py` runs that file only, `-- -k expr` runs the matching tests of `tests/cplat`, no arguments runs
what it runs today. `devbox run test` is unchanged.

### 4. `cplat component build tests` (AC-172.4, AC-172.6)

```
cplat component build tests <spec> <task> [--json] [--repo DIR]
cplat component build tests <spec> --load [--base REF] [--json] [--repo DIR]
```

Exit 0 with exactly one line on stdout; an unknown spec or task, a gitops task, or a task and `--load` together →
`ERROR:` (exit 1, `PlatformError`).

Per-shape table `TEST_FAST` in `buildtests.py` (files `test-fast` runs; how a runner selects them):

| Shape | Files (globs, `validate.matches`) | Selection args |
|---|---|---|
| `platform` | `tests/cplat/**/test_*.py` | the paths |
| `service-python`, `library-python` | `tests/**/test_*.py`, `tests/**/*_test.py` | the paths |
| `web-nextjs` | `tests/**/*.test.ts`, `tests/**/*.test.tsx` | the paths |
| `service-go` | `**/*_test.go` | `-run ^(<TestA>\|<TestB>)$` from `^func (Test\w+)\(` in the existing files |
| `service-java` | `src/test/**/*Test.java`, `src/test/**/Test*.java`, `src/test/**/*Tests.java`, `src/test/**/*TestCase.java` | `-Dtest=<Class>,<Class> -Dsurefire.failIfNoSpecifiedTests=false` (file stems) |
| others (gitops) | none | none |

- **Task mode:** files = (the trace files, `spec.trace` with the spec's shape's `test_globs`, of every criterion in the
  task's `covers`) ∪ (the task's `files` entries that are paths, existing or not, plus existing files a directory or glob
  entry matches), kept when they match the table's globs; sorted. Prints `cplat quiet test-fast -- <shlex.join(args)>`;
  with no entry for the shape or no files (or no Go test names): `cplat quiet test-fast`.
- **Load mode:** files = (the trace files of every active criterion) ∪ (files existing at HEAD that
  `git diff --name-only <base>..HEAD` lists), kept when they match the table's globs; `base` defaults to
  `git merge-base main HEAD`. Prints `cplat quiet test-fast --repeat 3 -- <shlex.join(args)>`; else one line
  `none: <reason>` with reason `<shape> runs no test runner in test-fast`, `no test files to repeat`, or
  `service-java runs share target/, so they cannot run at once (ADR-094)`.
- `--json`: `{"spec": id, "task": id|null, "load": bool, "files": [...], "args": [...], "command": str|null, "reason": str|null}`.

`buildcmd.main` hands `argv[1:]` to `buildtests.main` when `argv[0] == "tests"` (before its own argparse), so the
subcommand needs no parser in `buildcmd.py`.

### 5. `cplat component build merge` refuses unsigned commits (AC-172.7)

In the platform repo (`spec.repo_shape(repo) == "platform"`), after today's checks (branch exists, no merge in progress,
clean tree, the #501 red-commit check) and before `git merge`: the commits `git rev-list HEAD..<branch>` (merge commits
included) whose message has no line matching `house_rules.SIGNED`. When there is at least one: nothing is merged (HEAD
and the tree untouched), no `replan.set_pending`, no conflict event, no run-record change, and `PlatformError` (exit 1):

```
ERROR: branch '<branch>' brings in <n> commit(s) without a Signed-off-by line: <sha7> <subject>; <sha7> <subject>
  fix: rebase it with sign-off onto its merge base in the task's worktree: `git -C <worktree> rebase --signoff <merge-base sha7>`, then run `cplat component build merge <spec> <task> <branch>` again
```

`<worktree>` is the path `git worktree list --porcelain` shows for `refs/heads/<branch>`; without one the hint reads
`in the worktree of <branch>: \`git rebase --signoff <merge-base sha7>\``. Other repos: unchanged (no check).

`signoff.py`: `unsigned(repo, rev_range) -> list[tuple[str, str]]` (sha7, subject), `worktree_of(repo, branch) -> Path | None`.

### 6. `cplat platform rules check`: instructions classed `not a rule` (AC-172.8)

For a rule sentence whose single matching entry has class `not a rule`: when `promptrules.condition(sentence)` finds a
condition clause and `promptrules.instruction(sentence)` is true, a failure

- kind `hidden-rule`, file = the prompt path, line = the sentence's line, text = the sentence,
- message: ``` `<condition>` in an instruction classed `not a rule` (<entry id>): class it `practice` and state its purpose ```,
- text output `FAIL hidden-rule <file>:<line>: <message>: "<sentence>"`; in `--json` `failures[]` like every kind; it
  fails the check (exit 1) and so the `rules` rule of `cplat platform pr-check`. No override exists.

`instruction(sentence) -> bool`, on the sentence with inline code masked (`_mask`):

1. A word `you` or `your` (case-insensitive) → true.
2. Otherwise strip, repeatedly while something changes: leading whitespace, `|`, `>`, list markers (`-`, `*`, `+`,
   `1.`), quote and bracket characters (`"“'(`), emphasis (`*`, `_`); one leading label of at most 8 words ending in `:`
   (e.g. `**Note:**`, `Default:`); one leading clause `If …,` or `When …,` (up to its first comma).
3. True when the first word, lowercased, is in `IMPERATIVES`:
   `add aim apply ask avoid build bump call change check choose commit compare confirm copy create decide delegate delete
   depart describe do don't edit end escalate explain file fill find fix follow give go hand include keep leave let list
   load look make mark merge move name note offer open pass pick prefer prepend print pull push put read rebase record
   refuse remove rename replace reply report re-run rerun reset resolve restart resume return review rewrite run say scan
   send set show skip spawn split stage start state stop switch take tell treat try update use verify wait write`.

So "Read the design only when the brief lacks a fact." and "Merge the pull request, unless the user said not to merge."
fail; "The check runs only when a spec is building." passes as `not a rule`. On `main` today the one entry this flags is
`plugins/system/agents/planner.md` R3 ("Aim for 8 or fewer, …; above 12 `plan-check` refuses the slice unless …"),
re-classed by the plan's t7 (A13).

### 7. Build prompt (`plugins/component/commands/build.md`)

Phrases the acceptance tests may pin (keep them verbatim):

- 2.3 `Commands`: `cplat quiet test-fast -- <the task's test files>` (the line `cplat component build tests <id> <task>`
  prints) and `cplat quiet quality`; **Done when** runs that command, not the whole suite.
- 2.4 step 1: merge exit 1 naming commits without `Signed-off-by` → run the printed `git -C <worktree> rebase --signoff
  <sha>` and merge again without asking.
- 2.5 keeps `cplat quiet test-fast` (the whole suite) and Phase 3 keeps `cplat quiet ci`.
- New `### 2.6 Under load`, between 2.5 and Phase 3: run the line `cplat component build tests <id> --load` prints
  (`cplat quiet test-fast --repeat 3 -- …`; `none: …` → skip, name it in the report). Exit 1 → the failing tests to a
  coder of a covering task as in 2.5; exit 3 → read `references/build-load-run.md`: the **tester** in **Harness mode**
  gets each flaky test and the logs `cplat quiet` printed, fixes only the harness (fixtures, helpers, fakes, process
  clean-up) in files that are not frozen, changes no assertion, then `cplat spec test-diff $RED` (exit 1: the person
  approves as today) and the repeated run again; still flaky after 2 rounds → escalate naming each test.

## Risks

- **A 3× parallel `pytest -n auto` is heavy** on the platform repo; it runs only the named tests, once per build.
- **`git rebase --signoff` in the orchestrator** needs the session's permission for `git -C <path> rebase`; in an
  unattended run without it the build escalates at that step, which is still earlier than the PR.
- **The imperative-verb list is a heuristic**: a not-a-rule sentence starting with a listed word used as a noun
  ("Report lines …") would fail; the remedy is rewording, by design (no override).
- **Fallback detection is by commit subject**: a red-tests commit with another subject falls back to today's selection,
  which errs on the side of reporting more, never less.
