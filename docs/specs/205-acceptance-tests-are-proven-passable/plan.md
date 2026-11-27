---
spec_id: 205-acceptance-tests-are-proven-passable
shape: platform
spec_hash: a1e42f143da1
summary: AC-205.8 delta - the red check of an amended spec judges only the tests of criteria new or changed since its last done commit; every other test must pass, and a failing one is a regression the build escalates with cause code
tasks:
  - id: t1
    title: Red check scoped to the new or changed criteria of an amended spec (red_scope, quiet --red --spec)
    files: [scripts/cplat/red_scope.py, scripts/cplat/quiet_red.py, scripts/cplat/quiet.py]
    covers: [AC-205.8, AC-205.5]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: build tests --red adds --spec for an amended spec
    files: [scripts/cplat/buildtests.py]
    covers: [AC-205.8, AC-205.6]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: Build and tester prompts - a regression escalates with cause code, unjudged passes stay as they are
    files: [plugins/component/commands/build.md, docs/rules/plugins/component/commands/build.yml, plugins/svc/agents/tester.md, docs/rules/plugins/svc/agents/tester.yml]
    covers: [AC-205.8, AC-205.6, AC-205.7]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: ADR, plugin versions and changelog fragment
    files: [docs/adr/, docs/adr/README.md, plugins/component/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/1094-amended-spec-red-check.changed.md]
    covers: [AC-205.1, AC-205.2, AC-205.3, AC-205.4]
    parallel_safe: true
    depends_on: []
---

# Plan — 205 Acceptance tests are proven passable before they freeze (AC-205.8 delta)

AC-205.1 to AC-205.7 are built ([plan.v1.md](plan.v1.md)); this plan covers only the amendment of 2026-11-27
(AC-205.8, A6, A10, A11). The contract is [design.md](design.md), "Decisions — AC-205.8" and Contracts 3, 6 and 7.
Level 0 runs t1 (the scoped red check), t3 (the prompts) and t4 (bookkeeping) with disjoint files. Level 1 is t2,
which imports `red_scope.amended` from t1. `testreview.py` (the freeze gate) does not change: a scoped run writes the
same record, and a regression makes its exit 1.

The earlier criteria in `covers` are those whose code or prompt a task touches (AC-205.5 in `quiet_red.py`, AC-205.6 in
`buildtests.py` and Phase 1, AC-205.7 in tester step 3), so that their tests run with the task. AC-205.1 to AC-205.4
(test-diff) are on t4 only because `cplat spec check` requires every active criterion in some task: t4 changes none
of their code, and their tests, which pass on `main`, run with it as a guard.

## t1 — Red check scoped to the new or changed criteria of an amended spec (red_scope, quiet --red --spec)

**Files:** scripts/cplat/red_scope.py, scripts/cplat/quiet_red.py, scripts/cplat/quiet.py
**Covers:** AC-205.8, AC-205.5
**Goal:** `cplat quiet test-fast --red --spec <spec> -- <files>` judges only the tests that trace to a criterion new or
changed since the spec's last `done` commit. The others must pass and print `passes (not judged: <ids> unchanged)`;
one that does not is a `regression`. A spec that is not amended after a build is checked as today, and a run without
`--spec` is unchanged (AC-205.5).

**Implementation notes:**
- New `red_scope.py` with the functions of design Contract 6. `amended(spec)` reads the Changelog bullets only
  (`spec.sections(body)["changelog"]`): a `done` bullet, then a later `amended` bullet.
- `done_commit(root, spec)`: `git log --format=%H -- <spec.md rel path>` from HEAD, newest first; per sha, `git show
  <sha>:<path>`, take its Changelog's last bullet and compare it with the current last `done` bullet, whitespace
  collapsed. First hit wins. None → `PlatformError` with the message of Contract 6.
- Criteria text: per `AC_LINE` line of the `acceptance criteria` section (after `spec_replace.hash_text`), the line
  plus indented continuation lines, whitespace collapsed. `changed` = active now and (not active at the done commit or
  text differs). Parse the old text with `spec.sections` on the shown file, not with `spec.read`, which needs a
  directory.
- `test_criteria`: the three steps of the design with `ast` (decorator to `end_lineno` source lines plus the name slug
  `ac_(\d{3,})_(\d+)`; then the class; then the file's ids). Only `AC-<number>.<k>` ids in `active` count. Strip a
  `[…]` suffix from the node id. Cache the parse per file.
- `apply(rows, scope, root)`: relabel `classify()`'s rows as the design says and compute the exit code (at least one
  row, every judged `missing behaviour`, every unjudged `passes (not judged …)` or `skipped (not judged)`, at least one
  judged test when `changed` is not empty).
- `quiet_red.run(..., spec_ref=None)`: when set, resolve the spec and its scope **before** starting pytest (exit 2
  lines of Contract 6, nothing run), print the scope line first, use `apply` for the rows and the exit code, and the
  summary order of Contract 6. Without `spec_ref` nothing changes.
- `quiet.py` `_parse`: accept `--red --spec <ref> -- <args>`; refuse `--spec` without a value or without `--red` with
  the existing usage line. Keep `USAGE` byte for byte (pinned by `test_172_quiet.py` and `test_205_red_check.py`);
  document `--spec` in the module docstring.

**Done when:** the AC-205.8 tests of the red check pass (scope line, `passes (not judged: …)`, `regression`, exit
codes, first-build behaviour, missing done commit), and `test_205_red_check.py`, `test_172_quiet.py`, `test_185_*`
and `test_quiet*.py` still pass.

## t2 — build tests --red adds --spec for an amended spec

**Files:** scripts/cplat/buildtests.py
**Covers:** AC-205.8, AC-205.6
**Goal:** for an amended spec, `cplat component build tests <id> --red` prints `cplat quiet test-fast --red --spec
<spec id> -- <files>`, so Phase 1 and the freeze gate run the scoped check; a first build prints today's line.

**Implementation notes:**
- In the `red` branch of `build_tests`, `import red_scope` and use `red_scope.amended(sp)` to put `--spec <sp.id>`
  between `--red` and `--`. `doc["args"]` stays the file list; add `doc["amended"]`.
- Update the module docstring's `--red` line. Nothing else changes: `testreview._red_gate` keys on `doc["command"]`
  and `doc["files"]`, both unchanged in meaning.

**Done when:** the AC-205.8 tests of the command line pass, and `test_205_build_red_check.py` and
`test_172_build_tests.py` still pass.

## t3 — Build and tester prompts: a regression escalates with cause code, unjudged passes stay as they are

**Files:** plugins/component/commands/build.md, docs/rules/plugins/component/commands/build.yml,
plugins/svc/agents/tester.md, docs/rules/plugins/svc/agents/tester.yml
**Covers:** AC-205.8, AC-205.6, AC-205.7
**Goal:** the orchestrator escalates a `regression` line at once with `--cause code`, before any coder and without a
tester round or a `--wrong-failure` record; the tester leaves `passes (not judged …)` lines alone.

**Implementation notes:**
- build.md Phase 1, the red-check bullet (line 35): add that a `regression` line → escalate `--cause code` at once:
  `regression of built criteria: <node id> (<exception line>); …`, because criteria already built broke. Keep "Each
  `test error` or `passes` line goes back" as it is (the judged lines).
- svc tester.md step 3: "every judged line must be `missing behaviour`"; `passes (not judged …)` lines are built
  criteria and stay untouched; on a `regression` line, undo its own edit to that test's file or helper, else report
  it, so that a built test is never weakened (design Contract 7).
- **Bytes:** the four files together must not grow (docs/rules/README.md rule 6). Pay for the new words by tightening
  the bullet and step they extend (for example the parenthesised examples in tester step 3, or the "lines left →"
  phrasing in build.md). Do not rebaseline in this build.
- Register: update the `text` of tester.yml R4 to the new sentence; a new rule sentence in build.md gets a `practice`
  entry with its reason clause and `source: spec 205`. No new hard rule. Keep `--wrong-failure` and `--untraced` in
  build.md (pinned by `test_runs_agents.py`).

**Done when:** `cplat platform rules check` passes (no size growth, every target resolves), the AC-205.8
prompt-structure tests pass, and `test_205_build_red_check.py` and `tests/cplat/test_runs_agents.py` still pass.

## t4 — ADR, plugin versions and changelog fragment

**Files:** docs/adr/, docs/adr/README.md, plugins/component/.claude-plugin/plugin.json,
plugins/svc/.claude-plugin/plugin.json, .claude-plugin/marketplace.json,
docs/changelog.d/1094-amended-spec-red-check.changed.md
**Covers:** AC-205.1, AC-205.2, AC-205.3, AC-205.4 (as a guard only, see above; release bookkeeping)
**Goal:** the decision is recorded as an ADR, the changed plugins carry new minor versions in both places, and the
changelog names the change.

**Implementation notes:**
- Run the `cplat adr add …` command of design.md's AC-205.8 ADR decision (never hand-number the file) and fill in
  Status (Accepted, spec 205 AC-205.8), Context (#1094: an amended spec's built tests pass, so the red check sent them
  back as `passes`), Decision (judged by criterion text since the last done commit, per-test trace, regression gate)
  and Consequences (a regression escalates before any coder; a spec whose amendment was built without a `done` line
  judges that amendment's criteria again; a shallow clone gets exit 2). Builds on ADR-121.
- Minor bumps: component 1.28.1 → 1.29.0 and svc 4.15.2 → 4.16.0, each in `plugin.json` and `marketplace.json`. If
  `main` has moved, bump the minor of whatever is current.
- Fragment per `docs/changelog.d/README.md`, ending its bold summary in `(#1094).`.

**Done when:** `devbox run validate` passes, `cplat platform pr-check` reports no version or fragment finding, and
the AC-205.1 to AC-205.4 tests (`test_205_no_assertion_changed.py`) still pass.
