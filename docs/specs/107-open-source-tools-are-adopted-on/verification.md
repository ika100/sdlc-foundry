# Verification — 107-open-source-tools-are-adopted-on Open-source tools are adopted on measured value

**Result:** fail            <!-- code (t1, t2) only; t3–t6 pending -->
**Commit:** ca9a684 · **Base:** ae17cab (merge-base with origin/main) · **Scope:** plan tasks t1, t2 · **Suite:** not run by the reviewer (the tester's run: `tests/cplat/test_bench_arms.py` 19 green)

## Code (t1, t2)

The criteria below are judged only for the part t1 and t2 deliver (the arm machinery, the record and report fields, `--recall`).
AC-107.1, .4–.8 and .11, and the trial halves of .2, .3, .9 and .10, are **pending**: t3–t6 (index, baseline, trials, ADRs) have not run.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-107.9 | partial | `tests/cplat/test_bench_arms.py::test_the_arm_is_applied_committed_and_pushed_before_the_session_and_the_reset_still_runs`, `::test_the_reset_also_runs_when_a_session_with_an_arm_fails`, `::test_a_refused_arm_exits_non_zero_before_any_session_and_writes_no_record`, `::test_the_failing_arm_command_is_named` | `scripts/cplat/runs_bench.py:157` (load_arm, before any git call at :323), `:173–188` (apply_arm), `:405` (reset in `finally`) | What works: files can only go inside the clone (`:178`); commands run with cwd = clone; a failing command stops before commit/push (`:185` comes before `:188`); a failing session still resets (reset is in `finally`, test proves it); the reset force-pushes `rev` to main (`:132`), so the arm commit goes. **Gap:** the arm is pushed at `:345`, but `plugin_args` (`:349`, raises PlatformError for `--plugins` with a missing plugin), `settings.coordinator_model` (`:351`) and `runs.start` (`:353`) run after the push and before the `try/finally` at `:358`. A refusal there exits with the arm commit still on the sample's `main` and no reset. That breaks "refusals before any push" and "reset removes the arm". Fix: apply the arm after these calls (or inside the `try`). No test covers `--arm` with `--plugins`. The refusal test also does not assert "no push" for the `broken` arm. The code is right there, but the test does not prove it. |
| AC-107.2 | partial | `::test_the_report_row_key_carries_the_arm`, `::test_a_record_without_arm_counts_as_baseline_in_the_report`, `::test_the_text_report_shows_the_arm`; `tests/cplat/test_runs_usage_bench.py` (keys updated) | `scripts/cplat/runs_usage_report.py:123,132` | The row key `<version> [<plugins>] (<model>) {<arm>}` works as designed. **But arm runs are not the same task as baseline runs:** (1) for `build`/`ship`, `_prepare` commits the spec locally (`runs_bench.py:149–154`). `apply_arm` then pushes `HEAD` (`:188`), so the spec commit lands on the sample's `main` too. Baseline PRs contain the spec, arm PRs do not, and spec-check, change-aware validation and pytest-impact's diff all see a different change. Apply the arm on `rev` before the spec commit. (2) All four devbox-based arms change `test-fast` from the pinned `-q --tb=line` to `--tb=short -q` (`arms/testmon.json`, `pytest-impact.json`, `semgrep.json`, `trivy.json`, `files.devbox.json`). For semgrep/trivy that is a change the candidate does not need, and it changes test output tokens for every arm. (3) With `--compare-validation`, the second pass resets and re-prepares (`:379–380`) without applying the arm again, so pass 2 runs without the arm. `--recall` is also skipped in that mode. Either refuse the combination or apply the arm again. |
| AC-107.10 | met (code part) | `::test_the_record_names_the_arm_and_a_run_without_arm_is_baseline` | `scripts/cplat/runs_bench.py:417` | `benchmark.arm` is the arm name, `baseline` without `--arm`. Older records count as baseline (`runs_usage_report.py:123`). Citing run ids in records is t4–t6. |
| AC-107.3 | met (code part: recall) | `::test_a_deselected_failing_test_fails_the_record_with_a_named_reason`, `::test_recall_runs_the_full_suite_after_the_session_and_before_the_reset`, `::test_without_recall_the_full_suite_is_not_run` | `scripts/cplat/runs_bench.py:191–200`, `:372–374` | The full suite runs in the clone after a green session and before the reset. Any failure fails the record and names the `FAILED` test ids. The check cannot tell "deselected" from "selected but ignored" failures; both count against the candidate, which is acceptable. It runs on whatever HEAD the clone has at the end (the build merges onto the feature branch in the clone, so this is normally the PR head). Hypothesis and decisive measure per record: t4–t6. |

### Arm files against the sample at the pinned rev

I compared each arm's devbox.json with `ika100/todo-api@9cba320` `devbox.json`. Apart from the intended recipe, the only difference is the `test-fast` flags (AC-107.2 note (2)).

- `testmon`: `--testmon` is correct. `uv add --dev pytest-testmon` adds a `[dependency-groups] dev`, which `uv sync --all-extras` (init_hook) installs by default. `.testmondata` is removed by `git clean -ffdx` before each run, so every run starts cold. The session's `git add -A` may commit `.testmondata` into the PR (not in the sample's `.gitignore`); check this in t4.
- `pytest-impact`: `--impact --impact-base=origin/main` matches the upstream README (az-pz/pytest-impact 0.1.0). The push to the URL (`:188`) does not move the clone's `origin/main`, so the merge-base diff includes the arm commit (pyproject, uv.lock, devbox.json) and the spec commit. That probably selects everything. Check this in t4, together with the AC-107.2 fix.
- `semgrep`: `uv run semgrep scan --config p/python --error` is appended, and the existing three gates are unchanged (AC-107.4). `--error` makes `security` block on semgrep findings, as the design says. Network access is needed (the note says so).
- `trivy`: `trivy fs … --exit-code 0` is appended, and trivy 0.74.0 is already in the sample's packages. Trivy downloads its DB to `~/.cache/trivy`; the note does not say so (minor).
- `codebase-memory`: the install command is the upstream README one-liner plus the documented `--skip-config` (README "Options"), and it runs non-interactively (`install.sh` passes `-y --force`). It installs to `~/.local/bin` (a user tool dir) and keeps indexes in `~/.cache/codebase-memory-mcp/`. The note names neither (minor). It is unpinned (`main`). **Likely blocking for t6:** a project `.mcp.json` server needs approval in Claude Code. The arm only adds `mcp__codebase-memory-mcp` to `permissions.allow`, not `enabledMcpjsonServers: ["codebase-memory-mcp"]` (or `enableAllProjectMcpServers`). A headless session may then start without the server. Also, `"command": "codebase-memory-mcp"` relies on `~/.local/bin` being on the session's PATH. Verify both with one session before the 5 runs.

## Non-goals

No template, plugin or default `cplat` behaviour changed. The arms live under `scripts/cplat/benchmark/arms/` and only act with `--arm`. ✔ No benchmark task or price table changed. ✔

## Deviations from the plan

- `tests/cplat/test_bench_arms.py` and `tests/cplat/test_runs_usage_bench.py` are in no task's `files`. They are the plan's red tests, so this is acceptable. The setup line `arms.delivered_pr = None` (`test_bench_arms.py:92`) is approved by the user.
- t3–t6 are not done (expected at this point).

## Contract

`cplat runs benchmark <wf> [--arm NAME] [--recall]` and the arm file keys `{name, candidate, workflows, files, commands, note}` match `design.md`. The design says "an unknown arm, an arm that does not list the workflow, or a failing arm command exits non-zero before any session and writes no record". That holds, but a later refusal (`--plugins`) leaves the arm pushed (see AC-107.9). `docs/evaluations.md` and the ADRs are pending (t3–t6).
