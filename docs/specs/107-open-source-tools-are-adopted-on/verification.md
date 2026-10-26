# Verification — 107-open-source-tools-are-adopted-on Open-source tools are adopted on measured value

**Result:** pass            <!-- code (t1, t2) only, cycle 2; t3–t6 pending -->
**Commit:** bb31187 · **Base:** ae17cab (merge-base with origin/main) · **Scope:** plan tasks t1, t2 · **Suite:** not run by the reviewer (the coder's run: full suite 2415 passed)

## Code (t1, t2)

The criteria below are judged only for the part t1 and t2 deliver (the arm machinery, the record and report fields, `--recall`).
AC-107.1, .4–.8 and .11, and the trial halves of .2, .3, .9 and .10, are **pending**: t3–t6 (index, baseline, trials, ADRs) have not run.

Cycle 2 re-reviews fixes 1e831c1 and bb31187 for the two `partial` verdicts of cycle 1 (0a75294).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-107.9 | met (code part) | `tests/cplat/test_bench_arms.py::test_the_arm_is_applied_committed_and_pushed_before_the_session_and_the_reset_still_runs`, `::test_the_reset_also_runs_when_a_session_with_an_arm_fails`, `::test_a_refused_arm_exits_non_zero_before_any_session_and_writes_no_record`, `::test_the_failing_arm_command_is_named`, `::test_a_refused_plugins_value_leaves_no_arm_on_main` | `scripts/cplat/runs_bench.py:179` (stage_arm, local only), `:184` (files only inside the clone), `:347–349` (staged during prepare), `:368–371` (push_arm inside the `try`), `:425–428` (reset in `finally`) | Fixed: the arm is committed locally during prepare and pushed only inside the `try` whose `finally` resets. That is after `plugin_args`, `coordinator_model` and `runs.start`, so every refusal leaves `main` untouched. The new test proves this for `--plugins` (no non-forced push, no session). An unknown arm, an unlisted workflow or a failing command still refuses before any session and writes no record. A failed push happens inside the `try`, so it resets and writes a failed record. That is acceptable: it is not a refusal, and the record is truthful. |
| AC-107.2 | met (code part) | `::test_the_report_row_key_carries_the_arm`, `::test_a_record_without_arm_counts_as_baseline_in_the_report`, `::test_the_text_report_shows_the_arm`, `::test_an_arm_build_pushes_only_the_arm_and_keeps_the_spec_commit_local`, `::test_the_devbox_arms_keep_the_pinned_test_fast_flags`, `::test_compare_validation_applies_the_arm_and_recall_in_both_passes`; `tests/cplat/test_runs_usage_bench.py` (keys updated) | `scripts/cplat/runs_usage_report.py:123,132`; `scripts/cplat/runs_bench.py:137,153` (`_prepare(spec=…)`, `commit_spec`), `:371–372`, `:398–402` | Fixed: (1) with an arm, the spec commit follows the pushed arm commit and stays local, as in a baseline run (the test checks the order arm commit < push < spec commit). (2) I diffed each arm's devbox.json against `ika100/todo-api@9cba320`. Testmon and pytest-impact add only their flag to `test-fast` (`-q --tb=line` kept). Semgrep and trivy change only `security`. (3) The `--compare-validation` second pass stages and pushes the arm again and commits the spec after it, and `--recall` runs in both passes (test counts 2 arm commits, 2 pushes, 2 suite runs). |
| AC-107.10 | met (code part) | `::test_the_record_names_the_arm_and_a_run_without_arm_is_baseline` | `scripts/cplat/runs_bench.py:440` | `benchmark.arm` is the arm name, `baseline` without `--arm`. Older records count as baseline (`runs_usage_report.py:123`). Citing run ids in records is t4–t6. |
| AC-107.3 | met (code part: recall) | `::test_a_deselected_failing_test_fails_the_record_with_a_named_reason`, `::test_recall_runs_the_full_suite_after_the_session_and_before_the_reset`, `::test_without_recall_the_full_suite_is_not_run`, `::test_the_codebase_memory_arm_approves_the_server_and_uses_an_absolute_command`, `::test_stage_arm_resolves_home_in_files` | `scripts/cplat/runs_bench.py:204` (recall_check), `:388` (in every pass, after the result check) | A failure in the full suite after a green session fails the record and names the `FAILED` test ids. The check cannot tell "deselected" from "selected but ignored" failures; both count against the candidate, which is acceptable. Hypothesis and decisive measure per record: t4–t6. |

### Arm files against the sample at the pinned rev (9cba320)

- `testmon`: `--testmon` is appended to `test-fast`. `uv add --dev pytest-testmon` adds a dependency group, which `uv sync --all-extras` (init_hook) installs by default. Every run starts cold (`git clean -ffdx` removes `.testmondata`). For t4: the session's `git add -A` may commit `.testmondata`, because the sample's `.gitignore` does not list it.
- `pytest-impact`: `--impact --impact-base=origin/main` matches the upstream README (az-pz/pytest-impact 0.1.0). For t4: the push goes to the URL, so the clone's `origin/main` stays at the pinned rev until the session fetches. Until then the merge-base diff also contains the arm commit (pyproject, uv.lock, devbox.json). Check in the first trial run that the selection is not "everything" for that reason.
- `semgrep`: `uv run semgrep scan --config p/python --error` is appended to `security`, and the three existing gates are unchanged (AC-107.4). `--error` makes it block on findings, as the design says. It needs network (the note says so).
- `trivy`: `trivy fs … --exit-code 0` is appended (non-blocking). trivy 0.74.0 is already in the sample's packages. Its DB cache goes to `~/.cache/trivy`, which the note does not say (minor, a cache rather than an install).
- `codebase-memory`: the install is the upstream README one-liner with the documented `--skip-config`, and it runs non-interactively (`install.sh` passes `-y --force`). The note now names `~/.local/bin` and `~/.cache/codebase-memory-mcp`. `enabledMcpjsonServers: ["codebase-memory-mcp"]` approves the project server, a setting the settings reference allows in any settings file. The command is `$HOME/.local/bin/codebase-memory-mcp`, resolved at apply time (`runs_bench.py:187`). Minor: the resolved path, which contains the local user name, is committed and pushed to the public sample's `main` until the reset, and stays reachable from that run's PR. The install is unpinned (`main`). Neither blocks.

## Non-goals

No template, plugin or default `cplat` behaviour changed. The arms live under `scripts/cplat/benchmark/arms/` and only act with `--arm`. ✔ No benchmark task or price table changed. ✔

## Deviations from the plan

- `tests/cplat/test_bench_arms.py` and `tests/cplat/test_runs_usage_bench.py` are in no task's `files`. They are the plan's red tests and the review-fix tests, so this is acceptable. The setup line `arms.delivered_pr = None` in `test_bench_arms.py` is approved by the user.
- `apply_arm` from the design became `stage_arm` + `push_arm` + `commit_spec`. The behaviour still matches the design (the arm commit reaches `main`, the reset removes it), so this is acceptable.
- t3–t6 are not done (expected at this point).

## Contract

`cplat runs benchmark <wf> [--arm NAME] [--recall]`, the arm file keys `{name, candidate, workflows, files, commands, note}`, `benchmark.arm` and the report key `{<arm>}` match `design.md`. ✔ Arm files may now use `$HOME`, which is resolved at apply time; `design.md` does not mention it (worth one line there). `docs/evaluations.md` and the ADRs are pending (t3–t6).
