# Verification — 205 Acceptance tests are proven passable before they freeze

**Result:** pass
**Commit:** 712a5da3 · **Base:** e642dd43 (spec 205 commits from 993e6f7f) · **Trace:** 7/7 criteria named by tests

The branch also carries commits of other specs (190, 191, 196, 198 and fixes). This review judges only the spec 205 commits (`git diff 993e6f7f..HEAD`).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-205.1 | met | `tests/cplat/test_205_no_assertion_changed.py::test_a_comment_only_edit_passes_in_every_language_ac_205_1`, `::test_a_comment_marker_inside_a_string_is_no_comment_ac_205_1`, `::test_the_check_prints_the_line_and_exits_0_without_a_record_ac_205_1`, `::test_a_changed_string_in_a_commented_file_is_still_refused_by_the_check_ac_205_1` | `scripts/cplat/testdiff_neutral.py:96` (lexer keeps strings, template, raw, text-block and regex literals as code), `:201`; hook `scripts/cplat/spec.py:760-766` | Tests assert the exact line `no assertion changed: comments`, exit 0, `_approvals == {}` (no record) and refusal of `"http://a"` → `"http://b"` in py/ts/go/java, including `//` inside template, regex, raw and text-block literals |
| AC-205.2 | met | `::test_a_changed_added_or_removed_docstring_passes_ac_205_2`, `::test_added_removed_and_local_imports_pass_ac_205_2`, `::test_the_kinds_found_are_named_in_a_fixed_order_ac_205_2`, `::test_other_changed_strings_calls_and_statements_are_refused_ac_205_2`, `::test_a_pure_reorder_of_imports_is_no_difference_ac_205_2` | `scripts/cplat/testdiff_neutral.py:33-81` (`_Strip` drops docstrings of Module/Class/Function bodies and Import/ImportFrom at every level), `:26` fixed kind order | `importlib.import_module`, `__import__`, a non-docstring string and an added skip are refused. A pure reorder returns None and falls back to `formatting_only` (design Contract 1: "no kind differs"), so it still passes |
| AC-205.3 | met | `::test_static_imports_and_comments_pass_ac_205_3`, `::test_dynamic_imports_requires_and_other_changes_are_refused_ac_205_3` | `scripts/cplat/testdiff_neutral.py:87-93` (anchored TS/JS, Go single and block, Java patterns), `:168-196` | Dynamic `import(…)`, `require(…)` and `import x = require(…)` are refused, as is an unsupported suffix (`.rb`) |
| AC-205.4 | met | `::test_a_mixed_change_keeps_the_reason_of_before_ac_205_4`, `::test_an_added_dropped_or_changed_criterion_id_is_refused_ac_205_4`, `::test_a_second_mention_of_an_id_already_in_the_file_is_no_change_ac_205_4`, `::test_a_directive_comment_is_no_plain_comment_ac_205_4`, `::test_text_that_does_not_lex_or_parse_is_refused_ac_205_4`, `::test_the_type_only_path_still_applies_…`, `::test_the_helper_path_still_applies_…` | `scripts/cplat/testdiff_neutral.py:214` (criterion id set), `:223` (directives as a multiset, remaining code); `scripts/cplat/spec.py:766` (`fmt` = the reason from before this spec) | The mixed case asserts equality with `formatting_only`'s result. The type-only and helper reasons are asserted verbatim |
| AC-205.5 | met | `tests/cplat/test_205_red_check.py::test_each_test_gets_its_class_and_the_exception_line_ac_205_5` and 12 more tests in the file | `scripts/cplat/test_progress/cplat_red_check.py:86-118` (records), `scripts/cplat/quiet_red.py:118-145` (rules 2–8), `:148` (collection error once per static test), `:253` (exit), `:220-222` (exit 2 usage); `scripts/cplat/quiet.py:80-83, 112-114` | The tests run real pytest through a fake devbox. They assert each class, the exception lines (`ModuleNotFoundError: No module named 'pkg.redcheck'`, and since #956 `<pkg> is not installed: add it to the dev dependencies` for a missing third-party package, `ValueError: bad input`), the spec 157 `mkdir` case → `test error` with `FileNotFoundError`, a helper `TypeError`, fixture and conftest errors, exit 0/1/2 and the usage line verbatim |
| AC-205.6 | met | `tests/cplat/test_205_build_red_check.py::test_the_red_flag_prints_the_check_on_the_trace_files_test_fast_runs_ac_205_6`, `::test_the_tests_do_not_freeze_without_a_passing_red_check_ac_205_6`, `::test_already_reviewed_stays_first_and_other_repos_are_not_gated_ac_205_6`, `::test_phase_1_runs_the_red_check_and_records_wrong_failures_ac_205_6` and 4 more | `scripts/cplat/buildtests.py:85-97`; freeze gate `scripts/cplat/testreview.py:85-109`; `plugins/component/commands/build.md:34` (rounds, the review round included, 2-round escalation with `--cause code` before Phase 2), `:36` (`--wrong-failure` record) | The code gate makes "freeze only where the check exits 0" hold: missing record, exit 1, a missing file and a changed hash are all refused. The tester's rounds and the escalation are prompt behaviour, tested by structure (spec 180). The text at `build.md:34` matches design 5 |
| AC-205.7 | met | `::test_the_harness_fix_uses_the_red_check_and_the_tightening_record_ac_205_7`, `::test_the_tester_agents_run_their_own_red_check_ac_205_7` | `plugins/component/commands/build.md:79` (2.5: `test error` → tester harness fix, unasked); `plugins/component/references/build-tighten.md:12` (tester prompt, `--tighten … --reason '<test>: <exception line>'`, `UNRESOLVED`/exit 1 → `build-test-approval.md`) | The PR listing comes from the existing `--tighten` record (AC-165.3). "A task's test run" is not handled on its own: a coder cannot fix a test-code error, so the test stays red and reaches 2.5. That is acceptable |

## Non-goals

- No throwaway implementation or stub: there is none in the tester or build prompts. ✔
- No classification for Go, Surefire or Vitest: `quiet_red.runs_pytest` (`scripts/cplat/quiet_red.py:25`) gates the check, and other repos keep the old Phase 1 bullet (`build.md:34`, "`none: …` → an erroring test goes back"). ✔
- Type annotations, fixtures and helper logic are not accepted without a record: they return None and keep the type-only and helper paths (tests at lines 261 and 269). ✔
- Specs 165, 169 and 172 are unchanged: the approvals, helper and type-only passes in `spec.test_diff` are untouched. ✔
- A coder never edits a frozen test: the harness fix goes to the tester (`build-tighten.md:12`). ✔
- No template-owned layout change. ✔

## Deviations from the plan

- `tests/cplat/test_160_lint_suppressions.py:131`: the expectation changes from `(True, "")` to `no assertion changed: comments`. Acceptable, because plan t1 foresaw exactly this.
- `tests/cplat/test_172_quiet.py`: the docstring and the `USAGE` constant follow the new usage line (design Contract 2). Acceptable.
- `tests/cplat/test_205_no_assertion_changed.py` changed after the freeze (0e6319f1): the `page.test.js` fixture used to comment out its own assertion. Acceptable, because the user approved it on 2026-11-19 with `cplat spec test-diff --approve`.
- `plugins/svc/agents/tester.md` and `plugins/component/commands/build.md`: to stay within the prompt size baseline, the build shortened sentences beyond the ones it replaced (tester steps 1–8, the smoke and fixture paragraphs, build 2.2 and 2.6). The plan said to tighten only the replaced text. Acceptable: every rule and its reason clause are kept, and `cplat platform rules check` is OK. Small details were lost (for example "Fixtures in `conftest.py`", and the "wait until it is gone" after `pg_terminate_backend`).
- Non-spec-205 fixes in this build. After the freeze, the build restored prompt phrases in `tester.md` and `build.md` that other specs' tests pin (4e43eba5, 712a5da3). It also made `tests/cplat/test_122_final_evidence.py:76` independent of today's date: it used a fixed 2026-10-20 release that fell outside the 30-day window. Acceptable: neither change touches an acceptance test of spec 205 or a criterion.
- Plan t2 "done when" names a run under `-n 2`, but no test covers it. This is not a criterion, so there is no verdict impact.

## Contract

Matches design.md sections 1–5: the `judge` signature and return line, directive list, usage line verbatim, plugin records, classification order, record file `<git dir>/cplat-red-check.json`, `build tests --red` output and refusal text, and the freeze-gate refusal and hint. ✔

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
