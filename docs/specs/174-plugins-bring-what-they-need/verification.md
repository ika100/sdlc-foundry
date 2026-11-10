# Verification — 174 Plugins bring what they need, and one plugin installs the starter set

**Result:** pass
**Commit:** afbf5a48 · **Base:** b4ff411b · **Trace:** 7/7 criteria named by tests (`tests/cplat/test_174_plugin_deps.py`)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-174.1 | met | `test_a_live_plugin_depends_on_shared_ac_174_1[*]` (12 live plugins), `test_shared_and_tombstone_plugins_declare_no_dependencies_ac_174_1`, `test_every_non_tombstone_plugin_of_the_marketplace_is_covered_ac_174_1` | `plugins/component/.claude-plugin/plugin.json:12` (same line in the other 11 live manifests); `shared`, `app`, `gitops` unchanged | The third test walks the whole catalog through `plugin_set.is_tombstone_only`, so a new live plugin without `shared` fails it. Bare name `"shared"` as the design says. |
| AC-174.2 | met | `test_the_starter_bundle_manifest_ac_174_2`, `test_the_starter_readme_says_what_it_installs_and_how_to_remove_it_ac_174_2` | `plugins/starter/.claude-plugin/plugin.json:1-11`, `.claude-plugin/marketplace.json:208`, `plugins/starter/README.md:5-25` | Exactly the six keys, dependencies in the stated order, no commands/agents/skills/hooks/bin (the directory holds only `plugin.json` and `README.md`), version and description match the marketplace entry. The README names the four plugins, "on its own" and the `--prune` uninstall line. |
| AC-174.3 | met | `test_plugin_set_decides_tombstone_only_ac_174_3`, `test_plugin_set_reads_dependency_names_and_the_catalog_ac_174_3`, `test_a_clean_marketplace_passes_ac_174_3`, `test_a_bad_dependency_fails_with_plugin_and_entry_ac_174_3[*]` (not a list, version range, other marketplace, object, unknown name, tombstone-only, self, marketplace entry), `test_a_dependency_cycle_fails_once_ac_174_3`, `test_unreadable_json_is_one_error_line_ac_174_3`, `test_the_repository_dependencies_are_valid_ac_174_3`, `test_the_validator_runs_in_validate_ci_and_ci_local_ac_174_3` | `scripts/check-plugin-deps.py:64-94` (checks), `:21-44` (cycle DFS), `:97-110` (exit codes); `scripts/cplat/plugin_set.py:67-88`; wired at `devbox.json:17`, `.github/workflows/ci.yml:98-99` (`validate-manifests` job), `scripts/ci-local.sh:21` | Each error line names the plugin, the file and the entry; the CLI exits 1 with `FAILED:`; both `plugin.json` and marketplace-entry declarations are checked and the cycle graph is their union. Version ranges (`shared@^1.0.0`) are refused. |
| AC-174.4 | met | `test_check_docs_reads_the_starter_set_from_the_bundle_ac_174_4`, `test_check_docs_has_no_starter_constant_of_its_own_ac_174_4`, `test_the_starter_bundle_is_live_and_tombstones_are_not_ac_174_4`, `test_installing_the_bundle_counts_as_the_whole_set_ac_174_4`; AC-161.3 test still passes | `scripts/check-docs.py:27-32` (STARTER from `plugins/starter/.claude-plugin/plugin.json`), `:66-69` (`live_plugins` via `plugin_set`), `:182-183` (`starter` counts as the set) | The first test proves the value comes from the file (a scratch `starter` with two deps gives a two-tuple). A block installing only `system` still fails with "not the starter plugin(s)". |
| AC-174.5 | met | `test_the_page_installs_the_starter_set_in_two_lines_ac_174_5[*]` (4 pages); `tests/cplat/test_161_docs.py::test_the_quickstart_manifest_creates_the_system_ac_161_5` (asserts `installs == ["starter"]`), `::test_outdated_material_leaves_the_site_and_is_marked_historical_ac_161_8` | `docs/QUICKSTART.md:11,23-28`, `README.md:45-50`, `docs/USER-JOURNEY.md:65-70`, `site/src/content/docs/get-started/local-cluster.md:6-15` | Each page has the exact two-line `text` block, prose naming `component`, "alone", `2.1.311` (read from `doctor.MIN_CLAUDE_VERSION`) and `claude update`, and no single-plugin install in a fenced block. |
| AC-174.6 | met | `test_the_minimum_claude_version_is_one_constant_ac_174_6`, `test_an_old_claude_gets_a_warning_with_the_fix_ac_174_6`, `test_a_current_claude_gets_an_ok_row_ac_174_6`, `test_no_version_row_when_the_version_is_unknown_ac_174_6[*]`, `test_a_plugin_installed_without_shared_fails_with_the_fix_ac_174_6`, `test_no_shared_row_when_nothing_needs_it_ac_174_6[*]`, `test_the_none_installed_fix_names_the_starter_plugin_ac_174_6`; quickstart naming the constant: `test_the_page_installs_the_starter_set_in_two_lines_ac_174_5[docs/QUICKSTART.md]` | `scripts/cplat/doctor.py:25-39` (`_claude_version_row`), `:49-50` (after the `claude` row), `:127` (`MIN_CLAUDE_VERSION = "2.1.311"`), `:160` (none-installed fix names `starter`), `:168-174` (`plugin shared` FAIL row) | The warn row carries both versions and `claude update`; the fail row names the plugins that need `shared` and the fix `claude plugin install shared@sdlc-foundry`. |
| AC-174.7 | met | `test_a_changed_plugin_is_one_minor_up_in_both_files_ac_174_7[*]` (12 live + `shared`, against the shipped minors), `test_shared_describes_what_it_holds_today_ac_174_7`, `test_a_changelog_fragment_announces_the_starter_ac_174_7` | `.claude-plugin/marketplace.json:91-92`, `plugins/shared/.claude-plugin/plugin.json:3-4`, `docs/changelog.d/644-plugins-bring-what-they-need.added.md:1` | Every bump is minor with patch reset to 0 (for example system 1.15.1 to 1.16.0; component went to 1.17.0 because spec 172 had already taken 1.16.0). The `/new-service` text is gone. The fragment names `starter` and says that `/plugin marketplace update` followed by a plugin update is all an existing installation needs. |

## Non-goals

- Version ranges: refused by the validator (`check-plugin-deps.py:79-81`). ✔
- Shape plugins depend only on `shared`, never on pipeline plugins (`svc`, `web`, `svc-go`, `svc-java` manifests). ✔
- Nothing installs plugins from a committed `.claude/settings.json`. ✔
- The per-plugin install is still documented: in prose on the four pages and as `/plugin install component@sdlc-foundry` in `plugins/starter/README.md:21`. ✔
- No change to template-owned layout (header, footer, navigation). `local-cluster.md` gained an "Install the plugins" section in its content body, which AC-174.5 asks for. ✔

## Deviations from the plan

- These files are in no task's `files`: `docs/adr/094-…md` (new) and the addendum to `docs/adr/087-…md`, which the plan header says are written; `docs/backlog.md` (generated index row); the spec's own `spec.md`, `plan.md` and `design.md`; and the tests from the red commit `5bb2e05f`. All acceptable: this is the expected spec and ADR bookkeeping.
- `docs/backlog.md` lists 174 as `approved`, but `spec.md` says `building`. The index is generated, and the ship step regenerates it. Acceptable.
- Every task has `done: true`.

## Contract

Matches `design.md` with one difference:

- `scripts/check-docs.py:30-32` reads `plugins/starter/.claude-plugin/plugin.json` directly and maps each entry through `plugin_set.dependency_name`, where the design says `STARTER = plugin_set.starter(ROOT)`. The reason: `plugin_set.starter` reads through the marketplace catalog, and the AC-174.4 fixture test has no `marketplace.json`. This is acceptable because the spec names exactly this file as the source. A side effect: an invalid starter entry would show up as `None` here instead of raising, but `check-plugin-deps.py` already refuses such an entry in `validate` and CI.
- Small points that are not deviations: the `plugin shared` detail says "<a> need it" also when only one plugin is listed, and `starter` installed without `shared` counts as needing it, because the design calls it live. Both are wording only.

## Test run

`tests/cplat/test_174_plugin_deps.py` and `tests/cplat/test_161_docs.py`: 84 passed; `devbox run quality` ok. The 42 failures in the full `devbox run ci` run are in ship-gate, stop-hook, `pr_open` and headless tests. Those are outside this branch's touched files, and 37 of them pass with `CPLAT_UNIT` unset. Treated as environmental, as the orchestrator reported. The acceptance tests are unchanged since the red commit (`git log` shows only `5bb2e05f` touching them).

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
