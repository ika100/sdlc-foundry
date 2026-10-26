# Verification — 111 Unattended runs spend turns only on judgement

**Result:** fail (pending b1 only: every criterion t1–t3 cover is met; AC-111.10 is not run yet, so the result cannot be pass)
**Cycle:** 2 · **Commit:** e56f3a8 · **Base:** 2fdf430 (merge base with origin/main) · **Trace:** 9/10 criteria named by tests; AC-111.10 is the benchmark criterion (task b1, not run yet)

## Cycle 2 (e56f3a8)

The cycle-1 findings are fixed. Checked with `git show e56f3a8`: it touches 7 files, and in `tests/` it only adds tests (6 new ones, no `-` lines), so no existing assertion changed. I re-ran the gaming cases on the real `quicktask.check` in temp repos:

| Case | Cycle 1 | Cycle 2 |
|---|---|---|
| `git mv pyproject.toml src/conf.toml` (committed or staged) | allowed, 0 lines | refused: manifest |
| `git mv .github/workflows/ci.yml src/ci.yml` | allowed | refused: ci-workflow |
| `git mv docs/specs/…/spec.md docs/old.md` | allowed | refused: protected (spec) |
| `git rm docs/specs/…/spec.md` | allowed | refused: protected (spec) |
| `git rm pyproject.toml` / Dockerfile rename | refused | refused |
| src → tests rename | allowed | allowed, 2 files, both sides counted (fine) |
| binary modified / untracked binary | allowed, 0 / 1 lines | same: one file, the file limits hold (acceptable) |
| untracked symlink to a directory / committed symlink | allowed | same: the path is the link (acceptable) |
| `tests/helpers.py` + one source | allowed (tests/** is a test glob) | same, per design |

The fixes:

- `quicktask.py:18-19,27`: `--no-renames`, and `docs/specs/**` is in `PROTECTED`.
- `quick-task.md:39`: the check runs on the change once it is made; the inline path skips Step 2's agents but runs both gates; on failure the change is undone and the agent path is used.
- `quick-task.md:41-44`: the `TOUCHED_FILES` capture is restored.
- `quick-task.md:39`: "no worktrees" is restored.
- `ship.md:52`: the resume uses `cplat ship continue`, and "from the green smoke" is restored at `:56`.
- `ship.py:154,156`: `next_step` names `continue`.
- `headless.py:87-101`: new `mcp_flags`, also used by `retro.py:141`.

In retro, `d` is the retro report directory, not a repo, so the restriction there means strict MCP with no servers and connectors off. That is correct for a Read/Write-only proposal session.

The cycle-1 rows below are updated where the verdict changed.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-111.1 | met | `tests/cplat/test_spec_111.py::test_continue_runs_land_then_deploy_in_one_command`, `::test_continue_stops_at_a_red_land_without_deploy`, `::test_continue_exits_2_when_the_run_is_escalated_in_land`, `::test_continue_exits_2_when_deploy_escalates`, `::test_continue_exits_1_when_deploy_is_red_but_not_escalated`, `::test_continue_skips_a_phase_that_is_already_past` | `scripts/cplat/ship.py:1290-1304`, wired at `:1342-1347` and `:1405-1406` | Prints the same line lists as the single steps. Escalation is checked before `ok` (`:1300`), so a smoke escalation in deploy (`_smoke_finish` returns False after `escalate`) is exit 2. A `PlatformError` from land or deploy (merge refused, no checks, closed PR) is exit 1 through `cplat.py:107-111`, which matches ship.md's "1 = red or an error". An argparse usage error is also exit 2. That is harmless, because the output is a usage message |
| AC-111.2 | met | `::test_continue_passes_its_options_to_both_steps`, `::test_the_single_steps_still_work_unchanged`, `::test_continue_keeps_the_rules_of_the_steps_through_the_real_land`, `::test_continue_is_a_ship_subcommand_with_the_documented_options` | `scripts/cplat/ship.py:1290-1304` calls the module's `land` (`:648`) and `deploy` (`:985`) and nothing else | Checked against the real code, not only the fakes. `land` returns True only after a merge (`_merged`, `:703-711`), on an already merged PR (`:658`), or with `--no-merge`. With `--no-merge`, land sets phase `done` (`:686`) and `deploy` then returns `already done` (`:997`), so deploy only follows a merge. After a red round the phase stays `land`, so the next `continue` runs land again. The CI rerun rules and budget safe points (`allow_rerun` `:521,568,589,1153`; `refused` `:641`; `budget.attempt` `:679`) live inside the steps. There was no `cplat ship phase` safe point between land and deploy before, and none was added. The single steps are unchanged (`:1397-1404`) |
| AC-111.3 | met | `::test_ship_md_uses_continue_after_the_pr`, `::test_ship_md_calls_land_or_deploy_alone_only_to_resume`, `::test_ship_md_stays_under_the_size_cap`, `::test_the_red_round_reference_resumes_with_land` | `plugins/svc/commands/ship.md:52`, `plugins/svc/references/ship-land-red.md:3` | ship.md is 11367 → 11227 bytes. The exit codes match the code. Gaps: ship.md does not say "after the resumed land is green, run `cplat ship continue` (or deploy)", and `next_step` (`ship.py:155`), the hint the Stop hook prints, still says `cplat ship land`. Both cost turns but break no rule. "→ exit 2" at `:52` presumably means "stop", so the wording could be clearer |
| AC-111.4 | met | `::test_claude_cmd_is_strict_with_no_mcp_when_the_repo_has_none`, `::test_claude_cmd_loads_the_repos_mcp_json_only`, `::test_claude_cmd_turns_the_claude_ai_connectors_off_in_one_settings_json`, `::test_claude_cmd_keeps_the_plugin_read_rules_in_the_same_settings`, `::test_dry_run_shows_the_restriction`, `::test_benchmark_sessions_go_through_claude_cmd`; `tests/cplat/test_runs_bench_plugins.py::test_headless_adds_plugin_dir_and_a_read_rule_per_path` | `scripts/cplat/headless.py:79-97`, `:188`; `scripts/cplat/runs_bench.py:213-223` (via `headless.main`) | Checked on the installed `claude` 2.1.308. `--help` lists `--strict-mcp-config` ("Only use MCP servers from --mcp-config") and the variadic `--mcp-config <configs...>`. Repeated use accumulates, and the `--settings` that follows ends the variadic list. `--session-id` is appended after `--settings` (`headless.py:268`). Per code.claude.com/docs/en/settings-reference, `disableClaudeAiConnectors: true` "in any settings file applies" and makes Claude Code "neither fetch nor connect" those connectors. Servers passed with `--mcp-config` are unaffected, which is the intent. The mcp docs say a strict session skips the approval prompt for unloaded project servers from v2.1.246, which this version has. The benchmark test only greps the source, but the real path goes through `headless.main` → `claude_cmd` |
| AC-111.5 | met | `::test_the_extra_mcp_config_of_the_settings_file_is_loaded_too`, `::test_the_extra_mcp_config_works_without_a_mcp_json`, `::test_a_missing_extra_mcp_file_is_refused_naming_the_setting` | `scripts/cplat/settings.py:128-148`, `headless.py:92-93` | |
| AC-111.6 | met | `::test_only_claude_cmd_adds_the_mcp_flags`, `::test_retro_proposal_session_gets_the_mcp_restriction` | `scripts/cplat/headless.py:90` (`mcp_flags`), used by `:87` and `retro.py:141` | cycle 2: retro's `claude -p` now gets the restriction too |
| AC-111.7 | met (cycle 2; cycle 1: not met) | `::test_one_source_and_one_test_file_are_allowed` … `::test_inline_check_is_a_cplat_command` (14 tests), `::test_quick_task_goes_inline_only_after_the_check_passes` | `scripts/cplat/quicktask.py:21-61`, `plugins/svc/commands/quick-task.md:39` | **(1) Order in the command text.** quick-task.md:39 says "if `cplat quick-task inline-check --base main` exits 0, make the change yourself". The check runs before the change, so the diff is empty and the check always passes with `0 files, 0 lines`. The AC says the check decides *after* the coordinator has made the change. The test only checks that the string is present. **(2) Renames bypass the forbidden list.** `quicktask.py:26` runs `git diff --numstat` without `--no-renames`, so a rename reaches `:31` as a single path `"old => new"` or `"{a => b}/c"`, which the globs do not match. Reproduced in temp repos: `git mv pyproject.toml src/conf.toml` → `(True, '1 files, 0 lines')`; `git mv .github/workflows/ci.yml src/ci.yml` → allowed; `git mv docs/specs/001-x/spec.md docs/old.md` → allowed. Only `Dockerfile` renames are caught, because `Dockerfile*` happens to match the start of the string. **(3) Deleting a spec file is allowed** (`git rm docs/specs/001-x/spec.md` → allowed, 1 line). `validate.mandatory_categories` skips spec files that no longer exist (`validate.py:193`), and `PROTECTED` (`quicktask.py:18`) lacks the `docs/specs/**` the design lists. Checked and acceptable: deleting a manifest is refused; untracked and uncommitted files count; a binary file counts as a file with 0 lines (the one-file limit still holds); an untracked symlink to a directory counts 0 lines. The `secrets` category (`**/auth*`) also refuses, which is stricter than the AC. An acceptance test (`acceptance-test` category, skipped at `:51`) may be edited inline; quick-task.md:140 still forbids that in words |
| AC-111.8 | met | `::test_quick_task_runs_both_gates_inline_before_the_pr`, `::test_quick_task_pr_body_says_made_inline` | `plugins/svc/commands/quick-task.md:39` | The "<check line>" carries the reason (files, lines). Ambiguity: the text does not say whether Step 2 (quality and tester agents) is skipped on the inline path. Phase 3 still starts "After the tester passes" (`:71`), and "Testing done" asks for tester output (`:90`) |
| AC-111.9 | met (cycle 2; cycle 1: partial) | `::test_quick_task_never_retries_inline_after_a_refusal_or_red_gate` | `plugins/svc/commands/quick-task.md:39` | "never try inline again" is stated. But the agent path it falls back to lost its `TOUCHED_FILES=$(git diff --name-only $BASE_REF -- .)` capture (removed at the old line 41-44). `$TOUCHED_FILES` is still used at `:51` and `:63` ("refresh `$TOUCHED_FILES`"), so the quality and tester prompts get an undefined value. The text also does not say what happens to a change the coordinator made inline before the fallback (keep it for the coder, or discard it). This matters once (1) under AC-111.7 is fixed |
| AC-111.10 | pending | — | task b1 | Benchmarks not run yet (b1 `done: false`). Not counted as not met; the result must be re-checked after b1 |

## Command text, sentence by sentence

**ship.md** (old Phases `land` and `deploy` against the new `:50-56`). Every rule is kept: first red ends the wait (072), stuck/queued rerun once and then an error naming the runner set, transient rerun (079), `cplat pr wait` outside a ship and no polling loop, before-merge gitops PRs, squash and `--no-merge`, the red and security branches via ship-land-red.md, `--context`, pin PR (ADR-027), the image tag (077), main CI, pin-dev and the 5-min rule, after-release order, Synced/Healthy, smoke (091; `--base-url`, retry, 600 s, `(smoke)` criteria), escalation cause `code` and the `smoke-failure` issue, "never call `cplat ship escalate` for it", no rollback, resume reruns smoke only, staging (093, ADR-041), not-run smoke, the no-gitops-app note, and `human_steps`. Lost only as wording: "never on the old image" (implied by "only once … the merged build's tag"), "in the service repo" for the smoke-failure issue, "the gitops-app's" before `pin-staging`, and "from the green smoke" after "15 minutes". The last one changes what the timeout is measured from in the text. Acceptable, but restore "from the green smoke" if the text is touched again. ship-land-red.md changes only its header line.

**quick-task.md (cycle 2)**. 7928 bytes. The capture and "no worktrees" are back. Dropped as wording only: "without product or architectural review" (line 2 still says no PM, no architect), "Wall-clock is the longer leg, not the sum" (not a rule), and "The agent starts from the brief" (the rule "do not tell the agent to read the spec files" stays). The remaining gap is minor: Phase 3 still begins "After the tester passes" (`:76`), which on the inline path means the two gates. **Cycle 1:** Kept with equal meaning: lines 5, 9 and 35 (shortened). Lost:
- the `TOUCHED_FILES` capture (see AC-111.9). This one is a defect.
- "no worktrees" from "One coder, one pass — no worktrees, no fan-out" (`:39`).
- "first" from "read relevant files first" (`:35`). Minor.

The file grew 7821 → 7954 bytes. There is no cap in this spec, and it stays under spec 100's baseline of 7961.

## Non-goals

No per-agent model choice, no change to what coder, tester or reviewer do, no gate changed, and no restriction on interactive sessions. ✔ Shrinking command files is a non-goal; the ship.md shrink was needed to fit `continue` under the cap, so it is acceptable.

## Deviations from the plan

- `tests/cplat/test_runs_bench_plugins.py` is changed but is in no task's `files`. Acceptable: its exact `--settings` assertion now includes `disableClaudeAiConnectors`, which AC-111.4 requires, and nothing was weakened.
- b1 is not done (benchmarks, BASELINES.md, CHANGELOG). Pending, as expected.
- No version bumps for svc and shared are in the diff (`plugin.json`, `marketplace.json`). Deferred to the release, as in spec 100.

## Contract

Matches `design.md` for `cplat ship continue` (options, exit 0/1/2, skipping a phase that is already past), for `headless.mcp_config` (relative path, must exist, `PlatformError` naming the setting) and for the `claude -p` flags (one `--settings`). Differences:

- `inline-check` does not refuse `docs/specs/**` itself; it relies on validate's `spec` category, which ignores deleted files.
- `inline-check` reads `git diff --numstat <merge-base>` (working tree included) rather than `<base>...HEAD` plus the working tree. That is equivalent, apart from the rename problem above.
- `--base` defaults to `origin/main`, then `main` (`validate.default_base`), while quick-task.md passes `--base main`. Acceptable.

## Bug report for the coder (cycle 1, all fixed in e56f3a8)

1. `plugins/svc/commands/quick-task.md:39`: say that the coordinator makes the change first and then runs `cplat quick-task inline-check` (exit 1 → hand the change to the coder path). Restore the `TOUCHED_FILES=$(git diff --name-only $BASE_REF -- .)` capture before Step 2 and "no worktrees". Say that the inline path skips Step 2, and what "After the tester passes" and "Testing done" mean on it.
2. `scripts/cplat/quicktask.py:26`: use `--no-renames` (or `-z` and check both sides of a rename), so a rename is judged as a deletion plus an addition. Add tests for renaming a manifest, a CI workflow and a spec file.
3. `scripts/cplat/quicktask.py:18`: add `docs/specs/**` to `PROTECTED`, so deleting a spec is refused, and add a test for it.
