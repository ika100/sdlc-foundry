# Verification — 123 The platform repo declares its own shape

**Result:** pass
**Commit:** 08d0a89 · **Base:** 7de9f05 (origin/main) · **Trace:** 23/23 criteria named by tests

Tests: `tests/cplat` 3352 passed, 7 skipped (Kyverno CLI not installed); `bash scripts/ci-local.sh` green; site `npm test` and build green.
All test ids below are in `tests/cplat/test_platform_shape_123.py` (abbreviated `T::`).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-123.1 | met | `T::test_ac_123_1_declared_platform_resolves_with_its_routing`, `T::test_ac_123_1_the_platform_entry_is_registered_without_a_template` | `scripts/cplat/shapecmd.py:17` (`resolve`), `:45` (drops `release`), `shapes.yml:178` | Asserts the exact key order, the 7 agent types, no `unsupported` and no deployment/observability/migrations/release role. |
| AC-123.2 | met | `T::test_ac_123_2_without_a_shape_key_the_platform_repo_stays_unresolved`, `T::test_ac_123_2_no_settings_file_at_all_is_unresolved_too` | `scripts/cplat/settings.py:156-157` (no `shape` → None), `scripts/cplat/shapecmd.py:39` | The first test even plants `shapes.yml` and `plugins/` in the repo: still "cannot determine the repo's shape". `detect-shape.sh` is unchanged. |
| AC-123.3 | met | `T::test_ac_123_3_an_unknown_shape_fails_before_anything_happens` (`shape`, `spec new`, `component ship start`), `T::test_ac_123_3_declared_shape_raises_a_declaration_error` | `scripts/cplat/settings.py:165`, `scripts/cplat/spec.py:218`, `scripts/cplat/ship.py:204` | Asserts rc 1, file and value named, "the shapes that can be declared are: platform", no file changed, no ship state. |
| AC-123.4 | met | `T::test_ac_123_4_a_component_shape_cannot_be_declared` (3 values × `shape`, `spec new`) | `scripts/cplat/settings.py:161` | `ship start` is not exercised for this case but reaches the same `declared_shape` call through `shapecmd.resolve` (`ship.py:204`). |
| AC-123.5 | met | `T::test_ac_123_5_two_sources_conflict_and_nothing_changes`, `T::test_ac_123_5_answers_naming_no_platform_template_do_not_conflict` | `scripts/cplat/shapecmd.py:20-31` | Both sources named, `git status` clean. |
| AC-123.6 | met | `T::test_ac_123_6_shape_in_the_personal_file_is_refused`, `T::test_ac_123_6_any_personal_shape_value_is_refused` | `scripts/cplat/settings.py:145-152` | User file checked first, any value. |
| AC-123.7 | met | `T::test_ac_123_7_the_shape_key_changes_no_other_setting`, `T::test_ac_123_7_a_settings_file_without_shape_changes_nothing` | `scripts/cplat/settings.py:143` (only reader of `shape`); `:127` | Compares `coordinator_model`, `kube_context`, `budget_defaults`, `validate.settings_full` with and without the key. See deviation 2 for `:127`. |
| AC-123.8 | met | `T::test_ac_123_8_the_platform_repo_commits_its_declaration` | `.platform-settings.yml:2` | Asserts the file is tracked, not ignored, and `cplat shape` on the checkout resolves `platform`. |
| AC-123.9 | met | `T::test_ac_123_9_platform_is_registered_but_never_offered_for_creation`, `T::test_ac_123_9_adopt_type_platform_lists_the_valid_shapes_without_it` | `scripts/shapes.py:44` (`load()` filters declared), `scripts/cplat/adopt.py:86-88`, `scripts/cplat/model.py:78` | Callers unchanged; they keep `load()`. |
| AC-123.10 | met | `T::test_ac_123_10_the_registry_check_passes_with_platform_registered`, `T::test_ac_123_10_a_declared_entry_validates_without_template_or_sniff_rule`, `T::test_ac_123_10_a_malformed_declared_entry_fails` (7 cases), `T::test_ac_123_10_other_shapes_still_need_template_plugin_and_detection` | `scripts/shapes.py:57` (`_declared_errors`), `:87-91`, `:156`, `:223`, `:391` | Real `shapes.py check` passes; non-declared shapes still fail without template, detection or plugin. |
| AC-123.11 | met | `T::test_ac_123_11_platform_update_refuses_the_platform_repo` (plain, `--dry-run`, `--migrate`) | `scripts/cplat/update.py:49-51` | Message, rc 1, no file changed, git status clean, still on `main`. See deviation 1 (test fix). |
| AC-123.12 | met | `T::test_ac_123_12_fleet_with_only_names_the_platform_repo_and_skips_it`, `T::test_ac_123_12_fleet_without_only_opens_nothing_for_it` | `scripts/cplat/fleet.py:139-145` | No clone, no PR/label writes, no unexpected `gh` call in both modes. |
| AC-123.13 | met | `T::test_ac_123_13_doctor_reports_the_platform_source_version`, `T::test_ac_123_13_doctor_reports_a_bad_declaration_as_a_failure` | `scripts/cplat/doctor.py:135-147` | `repo shape: platform` OK, `platform source at v7.3.1`, no stamp warning; FAIL row for `platfrom`. |
| AC-123.14 | met | `T::test_ac_123_14_a_declaration_error_stops_the_commands_and_the_shape_is_never_asked` (spec, plan, verify, build, ship), `T::test_ac_123_14_spec_records_the_shape_of_a_repo_that_has_one`, `T::test_ac_123_14_the_routed_agents_are_the_platforms` | `plugins/component/commands/spec.md:39`, `plan.md:22`, `verify.md:17`; `scripts/cplat/shapecmd.py:36` | Prompt-driven commands, so the proof is the command text plus the routing JSON; adequate for this repo's convention. |
| AC-123.15 | met | `T::test_ac_123_15_spec_new_records_the_platform_shape_and_check_accepts_it`, `T::test_ac_123_15_no_shape_still_records_none` | `scripts/cplat/spec.py:262` (`known` from `load_all()`), `:213-220` (`repo_shape`) | |
| AC-123.16 | met | `T::test_ac_123_16_existing_specs_keep_passing_with_the_shape_declared`, `T::test_ac_123_16_the_spec_104_smoke_criterion_is_still_in_the_repo` | `scripts/cplat/spec.py:243` (`spec_shape`), used at `:274`, `:946`, `:1073` | Compares `check` and `ci_problems` on a copy of all real specs before and after declaring the shape: identical; no `(smoke)` error; AC-104.4 still present and spec 104 has no `shape:`. |
| AC-123.17 | met | `T::test_ac_123_17_a_platform_spec_cannot_have_a_smoke_criterion`, `T::test_ac_123_17_a_spec_without_a_shape_line_keeps_its_smoke_criterion`, `T::test_ac_123_17_spec_shape_prefers_the_specs_own_line` | `scripts/cplat/spec.py:274-276` | Exact message "AC-900.1: (smoke) needs a deployable shape (platform has no smoke tests)". |
| AC-123.18 | met | `T::test_ac_123_18_build_gates_run_through_the_repos_own_devbox_scripts` | `plugins/component/commands/build.md:102`, `:129`; `devbox.json` scripts | Gates are the existing `cplat quiet test-fast|quality|lint-fix|ci`; routing has `deployable: false` and no deployment role, so Phase 5 prints the skip line. |
| AC-123.19 | met | `T::test_ac_123_19_ship_start_asks_for_no_gitops_link_or_token` | `scripts/cplat/ship.py:239` | No `secret list` call, state records `shape: platform`. |
| AC-123.20 | met | `T::test_ac_123_20_land_waits_for_the_platform_checks_and_squash_merges`, `T::test_ac_123_20_land_ends_at_the_first_red_platform_check` | `scripts/cplat/ship.py:705` (`land`, unchanged) | Platform check names plus a `skipping` job; squash-merge with `--delete-branch`; stops at red `DCO sign-off`. |
| AC-123.21 | met | `T::test_ac_123_21_deploy_is_done_at_once_for_the_platform`, `T::test_ac_123_21_deploy_never_runs_devbox_smoke_even_with_a_context` | `scripts/cplat/ship.py:1052-1057` | Phase `done`, no `gh` call after land, no `run` call at all (no kubectl, no `devbox run smoke`), even with `--context`. |
| AC-123.22 | met | `T::test_ac_123_22_the_finished_run_reports_not_deployable_and_names_the_shape`, `T::test_ac_123_22_ship_md_prints_not_deployable_rows_and_no_promote_step` | `scripts/cplat/ship.py:1054-1057`, `:196-198` (`_record_shape`), `:257`; `plugins/component/commands/ship.md:63` | Run record has `shape: platform`, outcome `done`; no `/instance:promote` line. See deviation 3. |
| AC-123.23 | met | `T::test_ac_123_23_release_refuses_without_a_release_role`, `T::test_ac_123_23_contributing_says_where_the_procedure_is` | `plugins/component/commands/release.md:13-19`, `scripts/cplat/shapecmd.py:45`, `CONTRIBUTING.md:94` | The refusal is keyed on the missing `release` role, as designed. |

## Non-goals

- No sniffing or name-based detection: `scripts/detect-shape.sh` is untouched; the only path to `platform` is `settings.declared_shape`. ✔
- No template for `platform` (`template: null`), and `platform` is hidden from `load()`, so it cannot be created or adopted. ✔
- No `.platform-version` stamp added; `update` and `fleet` refuse or skip the repo. ✔
- Nothing is deployed: `deploy` returns before the kube context, pin, Argo, smoke and staging. ✔
- Component repo resolution unchanged: without a declaration `resolve` falls through to `detect-shape.sh` (`shapecmd.py:32-33`, `return det.stdout.strip() or None`). ✔
- No existing spec's front matter changed (only `docs/specs/123-*/` and `docs/specs/README.md` are in the diff). ✔
- Release procedure unchanged: CONTRIBUTING.md gains one sentence only. ✔

## Deviations from the plan

1. **AC-123.11 test edited after the red commit** (`bb1fe1a`): `git(r, "branch", "--show-current")` became `.strip() == "main"`. The helper returns the raw output with a newline, so the original assert could never pass; the change does not weaken what the test proves. User-approved. Acceptable.
2. **`settings.budget_defaults` change** (`settings.py:127`) in t3: a bare YAML `off` (parsed as `False`) is now treated as off instead of raising "must be a number or off". It fixes an existing bug the AC-123.7 test hit; the documented meaning of `off` is unchanged and `True` is still rejected. Acceptable. It is a behaviour change for every repo (a value that used to be an error is now accepted): it should get a CHANGELOG line.
3. **Deploy sets the not-deployable state directly** (`ship.py:1054-1055`) instead of using `_smoke_not_run`, which would add a "not promoted" row and contradict AC-123.22. The design asked for `outcome: "not-deployable"`; the code uses `"not-run"`, which is in `smoke.OUTCOMES`, so no reader meets an unknown value. The state's `row` fields read `not deployable`. Acceptable.
4. **ADR number 056** (055 is taken by spec 122 in another session). `docs/adr/056-…md` and `docs/adr/README.md` are in no task's `files`, but the plan names ADR-056 as the decision record. Acceptable.
5. **Files outside every task's `files`:** `docs/adr/056-the-platform-repo-declares-its-shape.md`, `docs/adr/README.md`, and the spec's own `spec.md`/`design.md`/`plan.md`. These are spec and ADR files. Acceptable.
6. **Edits in `build.md` and `ship.md` that are not part of the spec** (t9/t10). `build.md:13` dropped "(no fetch)" and left a stray `installed from ;`. `build.md` also dropped "Print its output verbatim." after `cplat shape`, and trimmed the run-record and agent-metric notes ("a buffered-record warning is fine", "a `WARNING: agent metric not recorded` line is not an error") and the BASE_REF wording. `ship.md:21` shortened the system-clone link explanation. No check enforces a size limit on command files. The edits look like trimming to keep the file length. They change orchestrator instructions shipped to every consumer repo and are not covered by any criterion. **Not acceptable as is:** restore the removed sentences and fix the typo before merge. No criterion depends on them, so no AC verdict changes.
7. **Contract differences in design.md, all minor:**
   - `update.resolve` checks `settings.declared_shape` instead of `shapecmd.resolve`. Its hint reads "change it with a normal pull request", where the design said "the platform is released through its own procedure: CONTRIBUTING.md, Releases". Acceptable: it still refuses before any check or write. Aligning the hint with the design would be better.
   - `doctor.check_repo` uses `settings.declared_shape`, not `shapecmd.resolve`, so a repo with a declaration and a conflicting `.copier-answers.yml` shows `repo shape: platform` OK in doctor instead of a FAIL row. Every other command refuses it (AC-123.5). Acceptable, but a follow-up is worth it.
   - `fleet` matches `^shape:\s*platform\s*$` with a regex instead of parsing YAML, so a trailing comment would fall back to "not a platform repo". The repo still gets no PR either way. Acceptable.
   - The issue-draft fallback was not implemented (`shape=core.read_stamp(repo).get("shape", "none")` at `ship.py:344` and `:980` is unchanged). A platform run that escalates files its issue with shape `none`. No criterion covers it. Acceptable as a follow-up.
- Every plan task t1–t12 has `done: true`.

**Resolved after review:**
- 2: CHANGELOG `[Unreleased]` has a Fix line for the bare `off`.
- 6: the trims are enforced by `tests/cplat/test_lean_prompts.py` (AC-100.13: `build.md` < 19912 and `ship.md` < 12106 bytes), so the check exists. The typo is fixed, and the dropped rule "a warning is not an error" is restored within the budget. "(no fetch)", "Print its output verbatim." and the longer `ship.md` link aside stay shortened; no rule is lost.
- 7: `update` and `doctor` now use `shapecmd.resolve`, and update has the design's hint. Doctor shows a FAIL row for a conflicting `.copier-answers.yml`. `fleet` parses YAML. Issue drafts fall back to the run's shape (`st["shape"]`). Full suite still green (3352 passed).

## Contract

Matches `design.md` for the registry entry and API, the settings check order and messages, the resolution and conflict message, the `cplat shape` JSON, `spec_shape` and the spec rules, ship `start`/`land`/`deploy`, and the command texts. The differences are the ones listed in deviations 3 and 7.

RESULT: pass
