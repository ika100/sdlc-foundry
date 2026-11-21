# Verification — 213 Library releases publish their package

**Result:** pass
**Trace:** 8/8 criteria named by tests (`tests/cplat/test_213_library_publish.py`)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-213.1 | met | `test_library_python_declares_the_github_release_registry_ac_213_1`, `test_every_known_registry_is_accepted_ac_213_1`, `test_a_library_without_a_valid_publish_block_is_refused_ac_213_1`, `test_a_planned_library_needs_no_publish_block_yet_ac_213_1`, `test_a_non_library_shape_with_a_publish_block_is_refused_ac_213_1` | `scripts/shapes.py` (`REGISTRIES`, `_publish_field_errors`), `shapes.yml` | Missing, non-map, unknown registry and non-library cases each named. |
| AC-213.2 | met | `test_the_library_python_template_meets_the_publish_contract_ac_213_2`, `test_the_publish_job_runs_on_the_tag_after_every_gate_with_the_only_write_permission_ac_213_2`, `test_a_template_that_breaks_the_contract_is_named_with_the_missing_piece_ac_213_2` (7 mutations), `test_a_template_without_the_publish_recipe_is_named_ac_213_2`, `test_a_gitHub_packages_registry_needs_packages_write_ac_213_2` | `scripts/shapes.py` (`workflow`, `publish_errors`, called from `check_contract`) | The workflow is read as YAML after undoing the Copier escapes. |
| AC-213.3 | met | `test_a_tagged_head_publishes_wheel_and_sdist_to_a_new_release_ac_213_3`, `test_a_second_run_replaces_the_files_on_the_existing_release_ac_213_3`, `test_an_existing_release_is_reused_not_created_ac_213_3`, `test_the_recipe_runs_the_script_with_its_arguments_ac_213_3`, `test_the_script_is_rendered_by_copier_unchanged_ac_213_3`, `test_a_wrong_call_prints_the_usage_and_exits_2_ac_213_3`, `test_the_real_build_of_a_rendered_library_matches_its_tag_ac_213_3` | `templates/library-python/scripts/publish.sh`, `devbox.json` (`publish`), `.github/workflows/ci.yml` (`publish` job) | Real script with fake `uv`/`gh`; one test renders with copier and runs the real `uv build` (hatch-vcs). |
| AC-213.4 | met | `test_a_built_version_other_than_the_tag_fails_before_github_is_called_ac_213_4` (tag on parent, no tag), the real-build test | `publish.sh` (version check) | No `gh` call and no release state after a mismatch. |
| AC-213.5 | met | `test_a_dry_run_builds_checks_and_names_the_upload_without_github_ac_213_5`, `test_a_dry_run_still_fails_on_a_version_mismatch_ac_213_5` | `publish.sh` (`--dry-run`) | |
| AC-213.6 | met | `test_the_template_smoke_job_runs_the_publish_dry_run_and_the_mismatch_ac_213_6` | `.github/workflows/ci.yml` (`smoke-test-templates`, step "Publish dry run builds the tagged version") | The step runs in this PR's CI on the rendered library. |
| AC-213.7 | met | `test_the_library_guide_says_how_it_is_released_and_installed_ac_213_7` | `templates/library-python/CLAUDE.md` (`## Releasing the package`, recipe row) | Public: release asset URL; private: git tag with a read token. |
| AC-213.8 | met | `test_the_convention_is_recorded_in_an_adr_and_the_registry_docs_ac_213_8` | `docs/adr/125-…`, `docs/adr/README.md`, `docs/adr/015-…` (field reference), `docs/templates.md` | |

## Non-goals

- No TS/Java/.NET library, no public registry, no consumer template wiring, `/component:release` unchanged, no signing. ✔

## Deviations from the plan

- None.
