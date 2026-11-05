# Verification — 138 A component release tags the build staging tested

**Result:** pass
**Trace:** 7/7 criteria named by tests

Tests: `T` = `tests/cplat/test_release_target_138.py` (red at cae71864; afterwards only its `commit` helper changed, to one
file per commit so the merge in the fix-only case does not conflict). `tests/cplat/test_platrelease_129_docs.py` follows the
tag phase to its new number (Phase 5). Full `tests/cplat` suite, `devbox run validate` and `devbox run quality` green locally.
Templates: `service-python` rendered with and without observability (ruff, ruff format, mypy, pytest green, `app.version`
reads `0.1.0` from `pyproject.toml`); `library-python` rendered (ruff, mypy, pytest green), version `0.0.0` without git,
`0.1.0` on the tag `v0.1.0`, `0.1.1.dev1+g…` one commit later; `uv.lock` records no version for the project.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-138.1 | met | `T::test_the_release_tags_the_commit_staging_runs_ac_138_1`, `T::test_the_version_comes_from_the_commits_up_to_the_staging_commit_ac_138_1`, `T::test_a_fix_only_staging_commit_is_a_patch_even_if_main_has_a_feature_after_it_ac_138_1`, `T::test_commits_after_the_staging_commit_are_named_as_not_released_ac_138_1`, `T::test_the_cli_routes_component_release_target` | `scripts/cplat/comprelease.py:76-131` (`target`), `:133-160` (`lines`); `scripts/cplat/cplat.py` (`component release`); `plugins/component/commands/release.md` Phase 1 (`git switch --detach`), Phase 5 | the gates run on the detached tagged commit |
| AC-138.2 | met | `T::test_a_library_releases_mains_head_and_says_why_ac_138_2`, `T::test_a_service_not_linked_to_a_gitops_app_releases_mains_head_ac_138_2`, `T::test_the_command_waits_for_mains_ci_run_on_the_tagged_commit_ac_138_2` | `comprelease.py:94-98`; `release.md` Phase 5 (#470 wait kept, on `TAG_COMMIT`) | |
| AC-138.3 | met | `T::test_no_staging_instance_refuses_ac_138_3`, `T::test_a_staging_pin_that_is_not_a_sha_build_refuses_ac_138_3`, `T::test_a_staging_commit_not_on_main_refuses_ac_138_3`, `T::test_a_staging_commit_already_released_refuses_ac_138_3`, `T::test_only_release_follow_up_commits_since_the_tag_refuses_ac_138_3`, `T::test_without_origin_main_it_refuses_ac_138_3`, `T::test_the_command_stops_on_a_refusal_before_the_gates_ac_138_3` | `comprelease.py:84-124` (`refuse`), `lines` refusal block; `release.md` Phase 1 | every refusal test checks that no tag was created |
| AC-138.4 | met | `T::test_the_next_development_version_per_template_ac_138_4` (6 cases), `T::test_the_target_names_the_version_file_of_the_follow_up_ac_138_4`, `T::test_the_command_tags_before_the_follow_up_pr_and_merges_none_before_ac_138_4`, `T::test_every_release_agent_writes_the_follow_up_from_main_and_never_tags_ac_138_4` (4 agents), `T::test_the_agents_set_the_next_development_version_of_their_template_ac_138_4` | `comprelease.py:55-73` (`next_dev`); `release.md` Phase 6; `plugins/{svc,svc-java,svc-go,web}/agents/release.md` | #468 (`uv lock`, `git add … uv.lock`) kept; `test_generated_repos.py` still checks it |
| AC-138.5 | met | `T::test_the_library_template_reads_its_version_from_the_git_tag_ac_138_5` | `templates/library-python/pyproject.toml` (`dynamic`, `hatch-vcs`, `fallback-version`, uv `cache-keys`), `src/{{ module_name }}/__init__.py`, `tests/test_smoke.py` | checked by hand on a render (see above) |
| AC-138.6 | met | `T::test_the_service_template_reads_its_version_from_the_package_metadata_ac_138_6` | `templates/service-python/src/{{ module_name }}/__init__.py`, `main.py` (`version=__version__`) | |
| AC-138.7 | met | `T::test_the_summary_names_the_tagged_commit_and_why_ac_138_7`, `T::test_the_target_output_explains_the_version_file_ac_138_7`, `T::test_the_changelog_fragment_exists_ac_138_7` | `release.md` intro, Final Summary; `comprelease.py` `lines` (`Version file:`); `docs/changelog.d/138-release-tags-the-staging-build.changed.md` | |

## Non-goals

The digest rule of spec 106 and `/instance:promote` are unchanged. No new slash command. No image is rebuilt or relabelled.
Existing repos keep their project-owned `pyproject.toml` and `src/` (`_skip_if_exists`); the svc release agent handles a
static library version like a service's.
