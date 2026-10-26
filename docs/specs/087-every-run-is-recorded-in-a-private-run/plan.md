---
spec_id: 087-every-run-is-recorded-in-a-private-run
spec_hash: 5f6f79b88c77
summary: runs.py record API with a local buffer, a private GitHub run store, cplat runs init/flush/report, recording in ship, pr wait, build, headless and doctor; amendment 2026-10-26 (#207) adds a pr_wait result section and red-ci counting in the report and the weekly retro
tasks:
- id: t1
  title: Record API, local buffer, flush and the cplat runs CLI
  files: [scripts/cplat/runs.py, scripts/cplat/cplat.py, tests/cplat/conftest.py]
  covers: [AC-087.5, AC-087.6, AC-087.7, AC-087.8, AC-087.9, AC-087.10, AC-087.15, AC-087.19, AC-087.20, AC-087.21, AC-087.22, AC-087.23]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: GitHub run store transport over gh api
  files: [scripts/cplat/runs_store.py]
  covers: [AC-087.8, AC-087.9, AC-087.20]
  parallel_safe: true
  depends_on: []
  done: true
- id: t3
  title: Report aggregation and rendering
  files: [scripts/cplat/runs_report.py]
  covers: [AC-087.14, AC-087.17, AC-087.18]
  parallel_safe: true
  depends_on: []
  done: true
- id: t4
  title: Ship and pr wait record their runs
  files: [scripts/cplat/ship.py, scripts/cplat/pr.py]
  covers: [AC-087.1, AC-087.3, AC-087.4, AC-087.5, AC-087.16]
  parallel_safe: true
  depends_on: [t1, t2]
  done: true
- id: t5
  title: Headless records; build and ship commands call cplat runs
  files: [scripts/cplat/headless.py, plugins/svc/commands/build.md, plugins/svc/commands/ship.md]
  covers: [AC-087.5, AC-087.6]
  parallel_safe: true
  depends_on: [t1, t2]
  done: true
- id: t6
  title: Doctor run store check
  files: [scripts/cplat/doctor.py]
  covers: [AC-087.11]
  parallel_safe: true
  depends_on: [t1, t2]
  done: true
- id: t7
  title: Docs for the run store
  files: [docs/CHANGELOG.md, docs/unattended-delivery.md, plugins/shared/README.md, plugins/svc/README.md]
  covers: []
  parallel_safe: true
  depends_on: []
  done: true
- id: t8
  title: pr wait records why it ended (pr_wait section)
  files: [scripts/cplat/pr.py, scripts/cplat/ship.py]
  covers: [AC-087.24]
  parallel_safe: true
  depends_on: [t4]
- id: t9
  title: Report counts pr-wait results, top red checks and red-ci
  files: [scripts/cplat/runs_report.py]
  covers: [AC-087.25, AC-087.26]
  parallel_safe: true
  depends_on: [t3]
- id: t10
  title: Weekly retro shows pr-wait results and red checks week over week
  files: [scripts/cplat/retro_report.py]
  covers: [AC-087.26, AC-087.27]
  parallel_safe: true
  depends_on: [t9]
- id: t11
  title: Docs for pr-wait results
  files: [docs/CHANGELOG.md, docs/unattended-delivery.md]
  covers: []
  parallel_safe: true
  depends_on: [t7]
---

The contract for every task is [design.md](design.md). ADR: [032](../../adr/032-private-run-store.md). Recording must
never change a run's outcome, exit code or stdout: every call into `runs` from other modules is either a mutator
(never raises) or `runs.finish` (never raises, at most one stderr line).

Tasks t1 to t7 are the original plan ([plan.v1.md](plan.v1.md)), built and merged. Tasks t8 to t11 implement the
amendment of 2026-10-26 (#207, AC-087.24 to AC-087.27); their contract is design.md "Amendment 2026-10-26". Each new
task depends on the done task whose module it extends (so no level holds two tasks on one file); since those are done,
t8, t9 and t11 can start at once, and t10 follows t9 (it imports `runs_report.count_outcome` and `aggregate_pr_wait`).

## t1 — Record API, local buffer, flush and the cplat runs CLI

**Files:** scripts/cplat/runs.py, scripts/cplat/cplat.py, tests/cplat/conftest.py
**Covers:** AC-087.5, AC-087.6, AC-087.7, AC-087.8, AC-087.9, AC-087.10, AC-087.15, AC-087.19, AC-087.20, AC-087.21, AC-087.22, AC-087.23
**Goal:** the `runs` module as in design.md "Python API". Done; see plan.v1.md for the implementation notes.

## t2 — GitHub run store transport over gh api

**Files:** scripts/cplat/runs_store.py
**Covers:** AC-087.8, AC-087.9, AC-087.20
**Goal:** the transport as in design.md "Transport". Done; see plan.v1.md.

## t3 — Report aggregation and rendering

**Files:** scripts/cplat/runs_report.py
**Covers:** AC-087.14, AC-087.17, AC-087.18
**Goal:** `parse`, `aggregate`, `render_text` as in design.md "Report". Done; see plan.v1.md.

## t4 — Ship and pr wait record their runs

**Files:** scripts/cplat/ship.py, scripts/cplat/pr.py
**Covers:** AC-087.1, AC-087.3, AC-087.4, AC-087.5, AC-087.16
**Goal:** ship and `pr wait` runs get their records, as in design.md "Integration points". Done; see plan.v1.md.

## t5 — Headless records; build and ship commands call cplat runs

**Files:** scripts/cplat/headless.py, plugins/svc/commands/build.md, plugins/svc/commands/ship.md
**Covers:** AC-087.5, AC-087.6
**Goal:** one `headless` record per invocation; `/svc:build` records or attaches. Done; see plan.v1.md.

## t6 — Doctor run store check

**Files:** scripts/cplat/doctor.py
**Covers:** AC-087.11
**Goal:** the `run store` doctor check. Done; see plan.v1.md.

## t7 — Docs for the run store

**Files:** docs/CHANGELOG.md, docs/unattended-delivery.md, plugins/shared/README.md, plugins/svc/README.md
**Covers:** none (documentation)
**Goal:** setup and reading of the run store documented. Done; see plan.v1.md.

## t8 — pr wait records why it ended (pr_wait section)

**Files:** scripts/cplat/pr.py, scripts/cplat/ship.py
**Covers:** AC-087.24
**Goal:** a `cplat pr wait` that records its own `pr-wait` run writes the section
`pr_wait: {result, checks?, message?}` exactly as in design.md "Record section `pr_wait`" and the table "Where it is
decided". An attached wait (inside a ship run) and the ship land, gitops and deploy paths record nothing new.

**Implementation notes:**
- `ship.py`: add `NoChecks(PlatformError)` and `ChecksPending(PlatformError)` (with `checks: list[str]`, the pending
  names) and raise them from `wait_checks` in place of the two plain `PlatformError`s, with the same message and hint.
  Nothing else in `ship.py` changes.
- `pr.py`: `Closed(PlatformError)` and `MergeFailed(PlatformError)` where `_wait` raises today, same message and hint.
- `_wait` returns `(ok, lines, section)`: `merged` (already merged, or `--merge` succeeded), `green`, `red` /
  `budget-refused` with the sorted unique names of the failed checks it got back from `wait_checks`.
- `wait`: on an exception, map it with the table (`ChecksPending` → `timeout` + `e.checks`, `NoChecks` → `no-checks`,
  `Closed` → `closed`, `MergeFailed` → `merge-failed`, anything else incl. `BaseException` → `error` with
  `message` = first non-empty line of `str(e)` cut to 200 chars, else the class name; `KeyboardInterrupt` →
  `interrupted`), `runs.finish(own, "failed", fields={"pr_wait": section})`, re-raise.
- On return: `runs.finish(own, "done" if ok else "failed", fields={"pr_wait": section})`. Only when `own`; an attached
  run never gets the section.
- Building the section must never raise into the wait: a bug there falls back to `{"result": "error", "message": ...}`.
- Exit codes, stdout lines and the `ERROR:` / `fix:` text of every path are unchanged.

**Acceptance tests (new file `tests/cplat/test_runs_pr_wait.py`, docstrings start with the AC id, fixtures from
`test_runs.py` like the existing AC-087.5 tests):**
- `test_a_green_wait_records_result_green` — AC-087.24
- `test_a_merged_wait_records_result_merged` — AC-087.24 (with `--merge`)
- `test_an_already_merged_pr_records_result_merged` — AC-087.24
- `test_a_red_wait_records_red_with_the_failing_check_names` — AC-087.24
- `test_a_rerun_refused_by_the_budget_records_budget_refused` — AC-087.24
- `test_a_timeout_records_the_pending_check_names` — AC-087.24
- `test_no_checks_within_the_grace_period_records_no_checks` — AC-087.24
- `test_a_closed_pr_records_closed` — AC-087.24
- `test_a_refused_merge_records_merge_failed` — AC-087.24
- `test_a_gh_or_api_failure_records_error_with_a_redacted_one_line_message` — AC-087.24, AC-087.10
- `test_the_outcome_stays_done_or_failed_and_the_exit_code_is_unchanged` — AC-087.24, AC-087.5
- `test_a_wait_inside_a_ship_run_writes_no_pr_wait_section` — AC-087.24, AC-087.5

**Done when:** those tests pass, and the existing `test_runs.py` (AC-087.5 part), `test_tags_and_wait.py`,
`test_ship.py`, `test_ship_checks.py` and `test_gitops.py` stay green.

## t9 — Report counts pr-wait results, top red checks and red-ci

**Files:** scripts/cplat/runs_report.py
**Covers:** AC-087.25, AC-087.26
**Goal:** `PR_WAIT_RESULTS`, `RED_RESULTS`, `RED_CI`, `pr_wait_result`, `count_outcome` and `aggregate_pr_wait`, and
their use in `aggregate` and `render_text`, exactly as in design.md "Report — AC-087.25, AC-087.26". Pure functions,
tolerant of records without the section and of malformed sections.

**Implementation notes:**
- `aggregate`: count `count_outcome(r)` in `runs`; add `"pr_wait": aggregate_pr_wait(kept)` after `usage` (before the
  conditional `validation`).
- `results`: all nine results plus `unrecorded`, always, then any other result seen; `red_checks`: top 5, each name
  once per record, by count descending then name.
- `render_text`: the two lines `pr-wait results: …` / `Red checks: …` right after the runs-per-kind block; `none` as
  in the design.
- `count_outcome` and `pr_wait_result` are public: t10 imports them. `runs_usage_report` is not touched.

**Acceptance tests (new file `tests/cplat/test_runs_report_pr_wait.py`, built on `rec`/`put`/`store` from
`test_runs_report.py`):**
- `test_the_report_counts_pr_wait_results_and_unrecorded_records` — AC-087.25
- `test_the_report_lists_the_five_most_frequent_red_checks` — AC-087.25 (red and budget-refused, ties by name)
- `test_the_json_report_has_pr_wait_results_and_red_checks` — AC-087.25, AC-087.18
- `test_the_text_report_prints_pr_wait_results_and_red_checks` — AC-087.25
- `test_red_and_budget_refused_count_as_red_ci_not_failed` — AC-087.26
- `test_failed_pr_wait_keeps_timeouts_errors_and_unrecorded_records` — AC-087.26
- `test_red_ci_is_a_readers_count_and_the_stored_record_keeps_failed` — AC-087.26
- Existing: `test_json_output_has_stable_keys_and_nothing_else_on_stdout` in `tests/cplat/test_runs_report.py` gains
  `pr_wait` after `usage` in its key list (tester change, AC-087.18 with AC-087.25).

**Done when:** those tests pass and the rest of `test_runs_report.py`, `test_runs_report_agents.py` and
`test_runs_usage_report.py` stay green.

## t10 — Weekly retro shows pr-wait results and red checks week over week

**Files:** scripts/cplat/retro_report.py
**Covers:** AC-087.26, AC-087.27
**Goal:** the retro counts `red-ci` apart from `failed` and shows a `## pr-wait` section with the results for the
covered week and the week before and the top 5 red checks, named in the private retro and `check <n>` in the public
issue, as in design.md "Retro — AC-087.26, AC-087.27".

**Implementation notes:**
- `_outcome` uses `runs_report.count_outcome` for `red-ci`; `_runs` adds the `red-ci` column (after `failed`) only when
  either week counted one.
- `build` adds `pr_wait: {results, red_checks}` from `runs_report.aggregate_pr_wait` over each week, as `_fig(cur, prev)`;
  `red_checks` ranked on the covered week, with `run_ids` (at most 5, sorted).
- `_index` adds the evidence refs `pr_wait.<result>` and `pr_wait.check<rank>` for both sides.
- `_render`: `## pr-wait` after `## CI`; public → `check <rank>`; `no data for this week` when the week has no runs.

**Acceptance tests (new file `tests/cplat/test_retro_pr_wait.py`, built like `test_retro_report.py`):**
- `test_the_retro_counts_red_ci_apart_from_failed` — AC-087.26
- `test_a_retro_without_red_ci_renders_the_runs_table_as_before` — AC-087.26
- `test_the_retro_shows_pr_wait_results_for_the_week_and_the_week_before` — AC-087.27
- `test_the_retro_lists_the_five_most_frequent_red_checks` — AC-087.27
- `test_the_private_retro_names_red_checks_and_the_public_issue_shows_check_n` — AC-087.27
- `test_pr_wait_figures_are_evidence_refs_for_proposals` — AC-087.27

**Done when:** those tests pass and `test_retro_report.py`, `test_retro_proposals.py` and `test_retro_cli.py` stay
green.

## t11 — Docs for pr-wait results

**Files:** docs/CHANGELOG.md, docs/unattended-delivery.md
**Covers:** none (documentation)
**Goal:** users learn what a `pr-wait` result means and where to read it.

**Implementation notes:**
- `docs/CHANGELOG.md`: one bullet under `[Unreleased]`: **Feature (087): a `pr-wait` record says why the wait ended.**
  The `pr_wait` section and its results; `cplat runs report` shows `pr-wait results:` and `Red checks:` (`--json`:
  `pr_wait`); red CI counts as `red-ci`, not `failed`, in the report and the weekly retro; older records count as
  `unrecorded`. Only this task edits the CHANGELOG.
- `docs/unattended-delivery.md`: in "Run records", one short paragraph on the results and `red-ci`; in "Weekly retro",
  one line on the `## pr-wait` section (check names only in the private retro).
- No plugin or marketplace version bumps.

**Done when:** `devbox run validate` and the Markdown link check pass.
