# Verification — 132 Changelog fragments that the release assembles

**Result:** pass
**Trace:** 13/13 criteria named by tests

Tests: `F` = `tests/cplat/test_changelog_fragments_132.py` (the release runs offline in `platrelease_world`; release-check in the
spec 121 mini platform). `F` is unchanged since the red commit; `release_support.section` strips trailing blank lines, the shape the
AC-132.11 unit test expects.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-132.1 | met | `F::test_a_fragment_names_its_section_in_the_file_name_ac_132_1`, `F::test_read_fragments_skips_the_readme_and_sorts_by_name_ac_132_1`, `F::test_the_fragment_readme_describes_the_format_ac_132_1` | `scripts/cplat/platrelease_changelog.py:14-46` (`FRAGMENTS`, `FRAGMENT_NAME`, `parse_fragment`, `read_fragments`); `docs/changelog.d/README.md` | |
| AC-132.2 | met | `F::test_assembly_orders_added_changed_fixed_then_others_unreleased_first_ac_132_2`, `F::test_move_unreleased_puts_the_fragments_under_the_new_heading_ac_132_2`, `F::test_fragments_alone_make_a_section_ac_132_2`, `F::test_the_release_assembles_unreleased_and_fragments_on_the_branch_ac_132_2` | `platrelease_changelog.py:49-65` (`assemble`), `:87-100` (`move_unreleased`); `scripts/cplat/platrelease.py:97-104` | |
| AC-132.3 | met | `F::test_the_release_commit_deletes_the_fragments_and_keeps_the_readme_ac_132_3` | `platrelease.py:105-106` (`git rm` of the assembled fragments), `:109-111` (one signed commit), `:113-116` (PR body) | |
| AC-132.4 | met | `F::test_relative_links_are_rewritten_for_the_changelog_ac_132_4`, `F::test_the_release_rewrites_links_ac_132_4` | `platrelease_changelog.py:20` (`UP_LINK`), `:35` | Only `](../` is rewritten; absolute, anchor and same-directory links stay |
| AC-132.5 | met | `F::test_without_fragments_the_release_is_unchanged_ac_132_5`; the spec 129 suite (`tests/cplat/test_platrelease_129_*.py`) unchanged and green | `platrelease_changelog.py:54-55` (no fragments → body unchanged); `platrelease.py:113-116` (old PR body without fragments) | |
| AC-132.6 | met | `F::test_fragments_count_as_content_in_the_preflight_ac_132_6`, `F::test_neither_text_nor_fragments_still_stops_the_run_ac_132_6` | `platrelease.py:52-55`, `:58-69` (`_fragments_at` via `git ls-tree`/`git show` at origin/main) | |
| AC-132.7 | met | `F::test_an_invalid_fragment_is_an_error_naming_the_file_ac_132_7` (4 cases), `F::test_read_fragments_rejects_a_stray_file_ac_132_7`, `F::test_an_invalid_fragment_stops_the_release_before_a_branch_ac_132_7`, `F::test_release_check_rows_fails_on_an_invalid_fragment_ac_132_7`, `F::test_the_git_tree_has_no_stray_fragment_ac_132_7` | `platrelease_changelog.py:23-35`; `platrelease.py:63-67` (preflight, before any branch); `scripts/release-check.py:127-130` (CI on every PR; `main` prints the error as one `ERROR:` line) | |
| AC-132.8 | met | `F::test_a_row_listed_in_a_fragment_counts_as_listed_ac_132_8`, `F::test_a_row_missing_from_text_and_fragments_still_fails_ac_132_8` | `release-check.py:127-130` | Only while the released section is `[Unreleased]`; after the release the fragments are gone |
| AC-132.9 | met | `F::test_unreleased_text_includes_the_fragments_ac_132_9` | `platrelease_changelog.py:68-72` (`unreleased_text`) | The patch/minor proposal (`only_fixes`, branch `fix/wave1-cplat-fixes`) is not on main; its `_unreleased(repo)` should return `changelog.unreleased_text(repo)` once both are merged |
| AC-132.10 | met | `F::test_the_guidance_names_a_fragment_ac_132_10` (CONTRIBUTING.md, CLAUDE.md, PR template) | `CONTRIBUTING.md:88`, `:95`, `:97`; `CLAUDE.md:26`, `:36`, `:38`; `.github/PULL_REQUEST_TEMPLATE.md:11` | |
| AC-132.11 | met | `F::test_old_changelog_tests_survive_a_new_entry_naming_their_spec_ac_132_11` (12 tests of specs 115–121, 125, 128, 130 run against a changelog with a new `[Unreleased]` entry naming every spec and ADR, and "BREAKING"), `F::test_section_reads_a_release_by_its_heading_ac_132_11` | `tests/cplat/release_support.py` (`section`, `paragraphs`); the ten test files use `section("5.1.0" / "5.2.0" / "5.4.0" / "5.5.0")` | Each test keeps its needles and its "not breaking" / ordering checks inside the release section |
| AC-132.12 | met | `F::test_plugin_version_tests_survive_a_later_bump_ac_132_12`, `F::test_plugin_version_tests_still_catch_a_mismatch_or_an_old_version_ac_132_12` (5 tests each), `F::test_at_least_compares_versions_numerically_ac_132_12` | `release_support.py` (`plugin_versions`, `at_least`, `assert_bumped`); 117 resource ≥1.3.0, system ≥1.2.0; 118 resource ≥1.4.0; 119 resource ≥1.5.0, api ≥1.1.0; 121 resource ≥1.6.0, platform ≥1.3.0, system ≥1.5.0 | |
| AC-132.13 | met | `F::test_this_change_has_its_entry_and_it_is_a_fragment_until_released_ac_132_13`, `F::test_entry_searches_fragments_then_every_section_ac_132_13` | `docs/changelog.d/321-changelog-fragments.added.md` | Durable: after the release the entry is found in its `[X.Y.Z]` section |

## Review points

- Resume safety: when the version heading already exists, `move_unreleased` returns the text unchanged and the fragments still in the
  tree were assembled by the earlier run before its `git rm`, so deleting them loses nothing.
- Naming and dev-latest scans (`tests/cplat/test_naming.py`, `tests/cplat/test_spec_agents.py`) treat `docs/changelog.d/` like
  `docs/CHANGELOG.md` (history text).
- The upgrade e2e no longer starts on a PR whose only changelog change is a fragment (its path filter names `docs/CHANGELOG.md`); the
  release PR still touches `docs/CHANGELOG.md` and runs it.
