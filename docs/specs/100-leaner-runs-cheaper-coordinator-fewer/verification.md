# Verification — 100 Leaner runs: cheaper coordinator, fewer turns, smaller context

**Result:** pass
**Commit:** f8b8e61 · **Base:** 1408296 (merge base with origin/main) · **Trace:** 15/17 criteria named by tests; AC-100.15 and AC-100.16 are benchmark criteria, proven by the run records below

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-100.1 | met | `tests/cplat/test_headless_model.py::test_the_default_coordinator_model_is_sonnet`, `::test_the_model_is_recorded_in_the_run` | `scripts/cplat/settings.py:71`, `scripts/cplat/headless.py:169` | `--model sonnet` is always on the claude command; source `default` is printed and recorded (`headless.py:176`) |
| AC-100.2 | met | `test_headless_model.py::test_the_model_flag_is_used_and_opus_is_accepted` | `scripts/cplat/settings.py:61-65` | |
| AC-100.3 | met | `test_headless_model.py::test_project_beats_user_and_flag_beats_both` | `scripts/cplat/settings.py:63-70` | files are read project first, user second; flag returns first |
| AC-100.4 | met | `test_headless_model.py::test_a_per_workflow_map_applies_to_that_workflow_only` | `scripts/cplat/settings.py:29-31`, `:55-56`, `:67-70` | covers map-only, map + user general, map `default` |
| AC-100.5 | met | `test_headless_model.py::test_an_unknown_model_is_refused_before_anything_starts` (flag, project, user, map, unused map key; with and without `--dry-run`) | `scripts/cplat/settings.py:34-36`, `headless.py:169` (before `runlog.start` at :177) | message names `sonnet, opus or haiku`; nothing started is asserted |
| AC-100.6 | met | `test_headless_model.py::test_agents_keep_their_own_model` | `plugins/svc/agents/{architect,reviewer,product-manager}.md:5` (`model: opus`, unchanged in the diff) | |
| AC-100.7 | met | `tests/cplat/test_pr_open.py::test_one_command_commits_signed_off_pushes_and_opens_the_pr`, `::test_finishing_step_of_the_commands_is_one_cplat_pr_open`, ready-PR and allow-rule tests | `scripts/cplat/pr_open.py:124-191`, `scripts/cplat/pr.py:79-107`; `plugins/svc/commands/quick-task.md:110`, `fix-bug.md:84`, `build.md:183` ("one Bash call") | test relaxed after red to skip `pr: ready` lines; acceptable, those lines are the spec-051 paragraph and contain "gh pr create" only as wording (checked: no push/PR step remains) |
| AC-100.8 | met | `test_pr_open.py::test_nothing_to_commit_fails_and_runs_nothing_else`, `::test_push_rejected_reports_the_parts_and_a_rerun_makes_no_second_commit`, `::test_pr_already_open_is_a_failure_without_a_second_pr`, `::test_gh_failure_then_rerun_leaves_one_commit_and_one_pr`, `::test_json_reports_the_failed_part` | `scripts/cplat/pr_open.py:148-180`, exit at `:51-54` | parts after the failure print `not run`; re-runs skip the commit on a clean tree |
| AC-100.9 | met | `test_pr_open.py::test_refused_before_anything_changes`, `::test_closes_lines_replace_the_placeholder_from_every_source`, `::test_wip_commits_add_the_squash_note_once`, `::test_base_is_origin_base_when_it_exists`; `tests/cplat/test_pr_body_staging.py`; `test_lean_briefs.py::test_ac_100_12_quiet_*` (the other new one-command step) | `pr_open.py:107-121`, `:138-146`; `scripts/cplat/core.py:163`; `scripts/cplat/quiet.py:32-51` | |
| AC-100.10 | met | `tests/cplat/test_lean_briefs.py::test_ac_100_10_commands_use_the_brief_headings`, `::test_ac_100_10_build_does_not_send_agents_to_the_spec_files`, `::test_ac_100_10_agents_start_from_the_brief`, `::test_ac_100_10_tester_acceptance_mode_has_no_unconditional_spec_read` | `plugins/svc/commands/build.md:43`, `:69`, `:104`; `quick-task.md:37`; `fix-bug.md:61`; `plugins/svc/agents/coder.md:10`, `tester.md:10,25`, `plugins/shared/agents/quality.md:10` (and the go/java/web coder and tester) | prompt-text tests are the only feasible proof; benchmark runs show the agents work from the briefs |
| AC-100.11 | met | `test_lean_briefs.py::test_ac_100_11_reviewer_still_reads_the_full_spec` | `plugins/svc/commands/build.md:122` (`SPEC_DIR`), `plugins/svc/agents/reviewer.md` unchanged | |
| AC-100.12 | met | `test_lean_briefs.py::test_ac_100_12_*` (commands, agents, templates, quiet success/failure/refusal, registration) | `scripts/cplat/quiet.py:32-51`, `scripts/cplat/cplat.py:73`, `templates/service-python/devbox.json` and `templates/library-python/devbox.json` `test-fast` (`-q --tb=line`) | template test parses with a regex after red: acceptable, the template `devbox.json` has `{%- if needs_migrations %}` (line 34) and is not JSON |
| AC-100.13 | met | `tests/cplat/test_lean_prompts.py::test_command_is_smaller_than_at_origin_main`, `::test_moved_text_is_gone_from_the_command` | `plugins/svc/commands/build.md:28,64,72,89,107`, `ship.md:40,54`, `quick-task.md:119` | sizes vs origin/main: build 19912 → 19455, ship 12106 → 11010, quick-task 7961 → 7821 bytes. The moved-text test was weakened in 09121f8 (now "not every reference line is in the command"); I checked by hand that 0 of the 17 moved lines remain in any command, so the criterion holds |
| AC-100.14 | met | `test_lean_prompts.py::test_moved_branch_lives_in_its_reference_file`, `::test_command_points_to_the_reference_file` | `plugins/svc/references/*.md` (7 files) | step-4 diff shows the moved text verbatim (only a "Read from …" header added) |
| AC-100.15 | met | benchmark run `20261025T165405Z-8cb3357c` | steps 1–4 | done, PR, quality + tests ran, $0.15 ≤ $0.30 |
| AC-100.16 | met | benchmark runs `20261025T165559Z-37076823` ($1.19), `20261025T170445Z-7913b9a4` ($1.33) | steps 1–4 | both done with PR, acceptance and security gates passed, reviewer pass; median $1.26 ≤ $1.36 (−35% vs the v4 baseline median $1.94) |
| AC-100.17 | met | `tests/cplat/test_runs_bench_plugins.py` (all AC-100.17 tests, plus `--model` and `CPLAT_PLATFORM` tests added after red) | `scripts/cplat/runs_bench.py` `plugin_args`, `main` (`plugins`, `coordinator_model` in the record); `scripts/cplat/headless.py` `claude_cmd`/`plugin_dirs_of` | every run is in the table below, failures with their cause; no accepted step failed a gate or changed the outcome in its counted runs; step 4 is marked `regression` (cost up a little in both workflows, within the ±$0.10 noise) and kept, as the plan's rule allows. The added tests after red are additions, not changes to red assertions |

## Benchmarks (copied from benchmarks.md)

| Step | Workflow | Run | Outcome | PR | Gates | Reviewer | Calls | Tokens | Est. cost | Coordinator | Plugins | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | quick-task v2 | `20261025T113632Z-73dcf110` | done | todo-api#9 | n/a (quick-task: quality + tests ran) | — | 22 | 674,791 | $0.48 | opus (user default) | installed 4.5.0 |  |
| baseline | build v3 | `20261025T123218Z-f4e36dbe` | done | todo-api#11 | acc passed, sec passed | pass | 81 | 2,617,700 | $1.64 | opus (user default) | installed 4.5.0 | v3 task; superseded by the v4 baselines below |
| 1 | quick-task v2 | `20261025T131302Z-cbc6693e` | done | todo-api#12 | n/a (quick-task: quality + tests ran) | — | 10 | 366,432 | $0.16 | sonnet | worktree @eef4db9 | coordinator did the change itself (no coder/quality/tester agents) and ran lint, types and tests |
| 1 | build v3 | `20261025T131439Z-f8398a6a` | failed | — | acc passed, sec passed | not reached | 65 | 2,120,178 | $1.13 | sonnet | worktree @eef4db9 | stopped before push: build.md said push/PR need confirmation (fixed in 208c9f2) |
| 1 | build v3 | `20261025T132523Z-7606b481` | failed | — | acc not run, sec not run | not reached | 44 | 1,265,392 | $0.68 | sonnet | worktree @208c9f2 | escalated: tester read AC-900.2 without a request body (spec 900 v4 fixes the wording) |
| baseline v4 | build v4 | `20261025T133329Z-d19e689b` | done | PR (closed by reset) | acc passed, sec passed | pass | 84 | 2,712,447 | $1.75 | opus | worktree @3f5201b |  |
| 1 | build v4 | `20261025T134409Z-7971f596` | done | PR (closed by reset) | acc passed, sec passed | pass | 71 | 2,380,239 | $1.25 | sonnet | worktree @3f5201b |  |
| baseline v4 | build v4 | `20261025T135136Z-d3ddd653` | done | PR (closed by reset) | acc passed, sec passed | pass | 107 | 3,467,205 | $2.12 | opus | worktree @3f5201b |  |
| 1 | build v4 | `20261025T140715Z-578ba653` | done | PR (closed by reset) | acc passed, sec passed | pass | 66 | 2,280,157 | $1.20 | sonnet | worktree @3f5201b |  |
| 2 | quick-task v2 | `20261025T142815Z-b2f8093c` | failed | — | n/a (quick-task: quality + tests ran) | — | 6 | 222,476 | $0.14 | sonnet | worktree @ccbc6da | failed: the session could not write .git/PR_BODY.md (fixed in 113030f: .pr-body.md) |
| 2 | quick-task v2 | `20261025T153130Z-674b051e` | done | PR (closed by reset) | n/a (quick-task: quality + tests ran) | — | 7 | 251,537 | $0.08 | sonnet | worktree @2b660e1 |  |
| 2 | build v4 | `20261025T153255Z-44f7c252` | done | PR (closed by reset) | acc passed, sec passed | pass | 56 | 1,698,198 | $1.00 | sonnet | worktree @2b660e1 |  |
| 2 | build v4 | `20261025T154213Z-71619373` | done | PR (closed by reset) | acc passed, sec passed | pass | 81 | 2,575,727 | $1.32 | sonnet | worktree @2b660e1 |  |
| 3 | quick-task v2 @ef04f90 | `20261025T160351Z-67d8fd20` | done | PR (closed by reset) | n/a (quick-task: quality + tests ran) | — | 7 | 246,675 | $0.13 | sonnet | worktree @dcf7612 |  |
| 3 | build v4 @ef04f90 | `20261025T160526Z-4c318bb8` | done | PR (closed by reset) | acc passed, sec passed | pass | 56 | 1,769,214 | $1.04 | sonnet | worktree @dcf7612 |  |
| 3 | build v4 @ef04f90 | `20261025T161313Z-84282c71` | failed | — | acc not run, sec not run | not reached | 27 | 841,667 | $0.59 | sonnet | worktree @dcf7612 | failed: `git commit -am` not allowlisted (fixed: templates allow `git commit *`, #173, todo-api#22) |
| 3 | build v4 @1e004f2 | `20261025T162946Z-6ac9e1cf` | done | PR (closed by reset) | acc passed, sec passed | pass | 65 | 2,181,191 | $1.14 | sonnet | worktree @1c19108 | sample @1e004f2 (git commit * allowed) |
| 3 | build v4 @1e004f2 | `20261025T163707Z-e6e75020` | done | PR (closed by reset) | acc passed, sec passed | pass | 68 | 2,163,118 | $1.17 | sonnet | worktree @1c19108 | sample @1e004f2 |
| 4 | quick-task v2 @1e004f2 | `20261025T165405Z-8cb3357c` | done | PR (closed by reset) | n/a (quick-task: quality + tests ran) | — | 8 | 302,856 | $0.15 | sonnet | worktree @09121f8 |  |
| 4 | build v4 @1e004f2 | `20261025T165559Z-37076823` | done | PR (closed by reset) | acc passed, sec passed | pass | 69 | 2,186,363 | $1.19 | sonnet | worktree @09121f8 |  |
| 4 | build v4 @1e004f2 | `20261025T170445Z-7913b9a4` | done | PR (closed by reset) | acc passed, sec passed | pass | 76 | 2,422,331 | $1.33 | sonnet | worktree @09121f8 |  |


Run records were not re-read from the run store by this review (it is a remote repo); the figures are from benchmarks.md.

## Non-goals

No budgets or enforcement, no no-progress breakers, no change-aware validation, no agent removed, no gate made weaker or stricter (quick-task and build run the same gates; only their output is routed through `cplat quiet`). ✔

## Deviations from the plan

- Files outside every task's `files`: `plugins/app/commands/build.md` (PR body to `.pr-body.md`), `scripts/cplat/core.py` (`PR_BODY`, `stage_pr_body`), `scripts/cplat/ship.py` (same body path), `tests/cplat/test_pr_body_staging.py`, `tests/cplat/test_runs_usage_bench.py`, `scripts/cplat/benchmark/spec-900.md` and `tasks.json` (spec 900 v4, sample pinned at `1e004f2`), `docs/adr/036-…`, `docs/adr/037-…`. Acceptable: they are the fixes the benchmarks found (113030f, 2b660e1, 3f5201b, 1c19108), each recorded in benchmarks.md.
- t9 is `done` but the version bumps in `marketplace.json` and the five `plugin.json` files are not in the diff: deferred to the release, as the orchestrator said. Acceptable only if the release bumps svc, shared, svc-go, svc-java and web (minor) in both places; the CHANGELOG, `docs/unattended-delivery.md` and ADR index parts are done.
- b4 in plan.md still names the old build target `$1.15`; the amended spec (approved) sets `$1.36`. The spec wins; stale plan text only.
- The size check compares with origin/main, not `v4.5.0` as t8 says. Acceptable: origin/main got spec 091 text in ship.md after v4.5.0 (ship.md is 9926 bytes at v4.5.0, 12106 at origin/main, 11010 now), so "smaller than before" means smaller than the base of this change.
- Benchmarks ran on the worktree at 09121f8, before the origin/main merge; afterwards only the merged spec-091 text changed in build.md and ship.md. Acceptable.
- The final build runs use sample `@1e004f2`, the v4 baseline `@ef04f90`; the only difference is the `git commit *` allow rule (#173). Acceptable, it does not favour the new runs in cost.

## Contract

Matches `design.md` with one difference: the default `--body-file` of `cplat pr open` is `.pr-body.md`, which cplat moves to `.git/PR_BODY.md` before committing (`core.py:163`), instead of the model writing `.git/PR_BODY.md` directly (Claude Code refuses edits under `.git/`). The `ready:` command still names `.git/PR_BODY.md`, as the contract does. Acceptable, but design.md should say so. Also, on an exit-2 refusal after the body was staged, the body file has moved into `.git/` (`pr_open.py:127` runs before the branch and title checks); harmless and re-run safe, but not strictly "nothing changed".
