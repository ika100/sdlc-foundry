# Verification — 175 A spec number means the spec and ship PRs close their issues

**Result:** pass
**Commit:** 670476c3 · **Base:** b4738390 · **Trace:** 5/5 criteria named by tests · **Cycle:** 2 (no code change since cycle 1 at 3ef537c7; only `tests/cplat/test_175_ship_pr_closes.py` changed)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-175.1 | met | `tests/cplat/test_175_steering_items.py::test_skip_prioritize_resume_act_on_the_spec_when_no_issue_is_open_ac_175_1`, `::test_a_bare_number_matches_a_spec_by_its_value_ac_175_1`, `::test_a_zero_padded_number_always_names_the_spec_never_an_issue_ac_175_1`, `::test_a_zero_padded_number_without_a_spec_is_refused_even_with_an_open_issue_ac_175_1` | `scripts/cplat/dispatch_items.py:55` (`resolve`), `scripts/cplat/dispatch_state.py` (`parse_form`: `0N` is the spec form), `scripts/cplat/dispatch.py:184,202,210` (output lines) | The exact output lines for all three verbs. `spec-154` is held and no `issue-*` key is. `54` resolves to spec 054. `054` with an open #54 still resolves to the spec. The stored reason `r` goes through the unchanged `ds.skip` (spec 167). |
| AC-175.2 | met | `::test_hash_and_issue_forms_always_name_the_issue_ac_175_2`, `::test_spec_forms_always_name_the_spec_ac_175_2`, `::test_a_bare_number_with_no_spec_names_the_open_issue_ac_175_2`, `::test_the_guide_item_line_states_the_forms_and_the_refusal_ac_175_2` | `scripts/cplat/dispatch_items.py:60-61,76-78`, `docs/dispatch.md:141` | `#154` and `issue-154` name the issue even when spec 154 and open #154 both exist. `spec-154` and `154-price-alerts` name the spec. `638` names issue #638. The guide's item line lists every form and the refusal. |
| AC-175.3 | met | `::test_a_bare_number_that_is_a_spec_and_an_open_issue_is_refused_by_all_three_commands_ac_175_3`, `::test_a_bare_number_that_matches_nothing_is_refused_ac_175_3`, `::test_a_spec_form_with_no_such_spec_is_refused_ac_175_3`, `::test_a_bare_number_that_is_a_spec_is_refused_when_the_open_issues_cannot_be_read_ac_175_3`, `::test_an_explicit_form_needs_no_github_read_ac_175_3`, and the zero-padded refusal under AC-175.1 | `scripts/cplat/dispatch_items.py:67,72,74,79`, `scripts/cplat/dispatch.py:260` (exit 2) | Each test runs through `cplat.main` and checks: rc 2, empty stdout, one `ERROR:` line, and a byte-identical `state.json`. The exact AC text is checked for the both case under all three commands. Every other message names the item and `spec-<N>` / `#<N>`. |
| AC-175.4 | met | `tests/cplat/test_175_ship_pr_closes.py::test_the_placeholder_becomes_the_tracked_and_commit_issues_ascending_ac_175_4`, `::test_the_lines_are_those_pr_open_writes_for_the_branch_ac_175_4`, `::test_no_open_issue_gives_na_ac_175_4`, `::test_without_a_spec_the_lines_come_from_the_commits_only_ac_175_4` | `scripts/cplat/ship.py:575-593` (`_fill_closes`), `scripts/cplat/ship.py:606-609`, `scripts/cplat/pr_open.py:119,129,142` | Tracks `[30, 12]` plus `Closes #44` give exactly `["Closes #30", "Closes #44"]`; the closed #12 is dropped. The lines equal the `closes` of `cplat pr open --spec 007 --json`. With no open issue, `N/A` stands on its own line. An empty `spec` gives the commit issues only. CI's `PR_BODY` is the filled body. |
| AC-175.5 | met | `::test_an_unreadable_spec_refuses_the_body_before_ci_and_push_ac_175_5`, `::test_a_missing_spec_refuses_the_body_ac_175_5`, `::test_filling_that_leaves_the_placeholder_refuses_the_body_ac_175_5`, `::test_an_open_pr_is_neither_created_nor_edited_for_a_refused_body_ac_175_5` (helper `refused`, lines 99-106) | `scripts/cplat/ship.py:570-572` (`BodyRefused.exit_code = 2`), `scripts/cplat/ship.py:589-592` (check), `scripts/cplat/ship.py:605` (check before `gh pr list`, CI, push), `scripts/cplat/cplat.py:166-170` | Tightened in cycle 2. The tests now drive `cplat.main(["component", "ship", ..., "pr", ...])` and check rc 2. They check `ERROR: PR body still contains {{CLOSES}}: ` followed by the reason: `the ship run's spec` when the spec cannot be read (a non-integer track or a deleted spec), and `filling left the placeholder` otherwise. They check the `  fix:` line. `nothing_done` confirms no CI, no push, and no `gh pr list/create/edit`, including with an open PR. The staged body keeps the placeholder. |

## Non-goals

These are unchanged: `cplat component ship <spec>`, `/component:fix #N`, `ship gitops pr` and `system ship entry pr`. The other caller of `parse_item`, `dispatch_backlog._spec_record` (`scripts/cplat/dispatch_backlog.py:154`), passes only `<NNN>-<slug>` ids, and the spec-form parse of those did not change. A reused open PR is only retitled and keeps its body (`scripts/cplat/ship.py:627-635`). No template-owned layout changed. ✔

## Deviations from the plan

- `scripts/cplat/cplat.py` changed (`return getattr(e, "exit_code", 1)`), but no task lists it in `files`. Acceptable: it is a one-line generic hook, and the default stays 1.
- The design and plan t2 say `ship.main` catches `BodyRefused` and returns 2. Instead, `cplat.main` reads `BodyRefused.exit_code = 2`. Acceptable: `cplat component ship pr` exits 2 with the `ERROR:` and `fix:` lines, and the tightened tests prove it through `cplat.main`.
- `ItemRefused` also carries `exit_code = 2` (`scripts/cplat/dispatch_state.py:196`), on top of the catch in `dispatch.main`. Acceptable, though redundant.
- Both plan tasks are `done: true`. Every other changed file is listed in a task's `files`, or is a spec document or an acceptance test.

## Contract

The steering contract matches `design.md`: the forms, the spec sources, the open issues (a fresh snapshot or one `gh issue list`), the refusal texts, and resolution before any state write.

The ship PR body contract also matches. The order is fill, check, write the staged body, then `gh pr list`, the spec rule, CI, push, and create or edit. The reason and hint texts match.

One cosmetic mismatch remains from cycle 1. When there is no spec and `closes_for` raises a `PlatformError`, the reason reads "the ship run's spec  cannot be read" instead of "filling left the placeholder" (`scripts/cplat/ship.py:587-588`). The exit code and the refusal are still right.

## Tightened acceptance tests

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_175_ship_pr_closes.py` | Cycle 1 TEST LOOSER finding on AC-175.5: the tests called `ship.main` and checked only for a raised `PlatformError`. They did not check exit code 2, and the reason check was weak (`"007" in str(e) or "spec" in str(e)`). Commit 670476c3 makes the tests drive `cplat.main` and check rc 2, the `ERROR: PR body still contains {{CLOSES}}: <reason>` line and the `  fix:` line. | yes: exit 2, the error and its reason (spec unreadable, or filling left the placeholder), nothing before CI or the push, and no PR opened or edited |

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
