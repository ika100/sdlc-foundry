# Verification — 121 Resources and environment properties upgrade safely

**Result:** pass, on condition that this PR's CI runs the e2e job (`run.sh`) and the upgrade e2e (`e2e-upgrade.yml`) green before merge. All 27 active criteria are `met`. Earlier reviews found AC-121.7, AC-121.11 and AC-121.16 `partial`, and fleet PRs held open for files the update's own re-render wrote. These commits fix them, and I rechecked each one (see "Fixes after review"):<br>- first review (73c8aaf): bc73e6b, 1a586be, 3b98429, b22cf15;<br>- second (3b98429): 228a293;<br>- third (228a293): 4009a37;<br>- fourth (4009a37): c935c5c;<br>- fifth (c935c5c): 60b209a;<br>- sixth (60b209a): d13b7ff;<br>- seventh (d13b7ff): fc0f677.<br>AC-121.24, AC-121.25 and the in-cluster parts are pending that CI.
**Commit:** fc0f677 (reviews at 73c8aaf, 3b98429, 228a293, 4009a37, c935c5c, 60b209a, d13b7ff) · **Base:** 1f5982e (`origin/main`, also the merge base) · **Trace:** 27/27 active criteria are named by tests. AC-121.1 to .27 appear in `tests/cplat/test_upgrade_121.py` (render), `test_upgrade_121_cmds.py` (cmds) and `test_upgrade_121_ops.py` (ops). AC-121.4, .11, .21, .22, .24 and .25 also appear in `tests/e2e/upgrade.sh`.

**Test run.** These figures come from the orchestrator. I did not rerun them, because this review is read-only.
- Full suite: 6149 passed, 12 skipped at 73c8aaf; 6161 passed, 12 skipped at 3b98429; 6164 passed, 12 skipped at 228a293 and at 4009a37; green at c935c5c; 6166 passed, 12 skipped at 60b209a; 6171 passed, 12 skipped at d13b7ff; green at fc0f677 (orchestrator).
- `scripts/ci-local.sh --render --site` passed.
- `uv run scripts/check-pins.py`: `OK: 81 references`. `uv run scripts/release-check.py rows`: `OK: 19 changed row(s)`.
- Pins: t1 re-verified all 13 image digests and every chart and archive digest on 2026-10-28. The earlier plain Postgres tags still exist (the design risk was corrected).

**Not run locally:** `tests/e2e/run.sh` (t16), `tests/e2e/upgrade.sh` and `.github/workflows/e2e-upgrade.yml` (t15). Until this PR's CI is green, these are **pending CI, not passed**:
- AC-121.24 and AC-121.25 as a whole;
- the cluster halves of AC-121.4, .5, .8, .11, .15, .16, .19, .21 and .22.

t15's "Done when" asks for a local run recorded here, with step durations. That was not done.

Line numbers refer to `templates/gitops-app/scripts/render.py` unless another file is named. Two copies are byte-identical to their originals (`cmp` at every reviewed commit, last at d13b7ff; fc0f677 does not touch the renderer):
- `templates/cluster-gitops/scripts/system_render.py` is a copy of `render.py`;
- `templates/cluster-gitops/scripts/local-cluster.sh` is a copy of `templates/gitops-app/scripts/local-cluster.sh`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-121.1 | met | render: `test_the_table_has_one_row_per_image_and_operator_in_the_designed_order_ac_121_1`, the row-key, image-row, chart/manifest, operator-row, constants, majors and `--versions` tests; cmds: `test_versions_prints_the_release_and_one_line_per_row_ac_121_1`, the columns, operator-row, order and `--json` tests | `render.py:247-275` (constants), `:3014-3046` (`versions_table`), `:3050`; `scripts/cplat/versions.py:57`, `:96`, `:185` | Every operator row carries `crds`, and `metrics-server` has `{}`. |
| AC-121.2 | met | render: `test_every_image_row_is_a_repository_an_exact_tag_and_a_digest_ac_121_2`, the exact-version, coverage-render and digest tests; ops: `test_the_pin_check_passes_on_the_platform_tree_ac_121_2`, the floating-tag, `stable`, differing-default, not-in-table and bad-row tests, `test_the_root_validate_recipe_and_ci_run_the_pin_check_ac_121_2` | `scripts/check-pins.py:96-128` (rows), `:163-214` (coverage render), `:217-257` (scripts); `.github/workflows/ci.yml` step "every image and chart comes from the versions table"; root `devbox.json` `validate` | Each finding names the file, the line or document path, and the reference. |
| AC-121.3 | met | render: the database, cache, broker and bucket major tests, `test_two_renders_of_the_same_release_produce_the_same_images_ac_121_3`, the quoted-major test, `test_a_major_that_is_not_in_the_table_fails_naming_the_supported_majors_ac_121_3`, `test_a_system_without_the_new_keys_renders_as_before_after_the_references_are_mapped_back_ac_121_3` ×10 (the BEFORE_120 digests are unchanged) | `:1230-1238` (`table_pin`), `:1123-1146`, `:2201-2205`, `:2526-2528` | 15 renders as deprecated, as the changelog reading says. |
| AC-121.4 | met (cluster part pending CI) | ops: `test_the_script_defaults_are_the_table_rows_with_digests_ac_121_4`, the header, override-warning (parametrised), no-warning, several-overrides, byte-equal-copy and parse tests; e2e step 3 (no `overrides the versions table` line) | `local-cluster.sh:211` (`warn_overrides`), `:267`; `check-pins.py:33-37` holds the defaults equal to the rows | Argo CD is `v3.4.12`, no longer `stable`. |
| AC-121.5 | met (cluster part pending CI) | cmds: `test_each_in_cluster_instance_reports_its_major_and_pinned_image_ac_121_5`, the external/bucket, not-rendered, JSON-order and text-unchanged tests, the eight status tests (rows, cell, health, unknown, held, grid) | `scripts/cplat/model.py:219-220`, `:377`; `scripts/cplat/status.py` `_version_cell`, `version_lines`, `collect_all` (`resource_versions`) | |
| AC-121.6 | met | cmds: `test_the_dev_step_opens_one_pr_that_sets_the_dev_version_only_ac_121_6`, the PR title/body, signed-off commit (dev files only), local-write, default-env, dry-run/JSON and archive tests; render: the instance-version tests | `scripts/cplat/upgrade.py:235-261` (`edit_system`), `:312-327` (`body_of`), `:332-339`; `render.py:1149-1158` | |
| AC-121.7 | met (after bc73e6b) | cmds: `test_the_staging_step_moves_staging_after_a_verified_dev_ac_121_7`, `test_the_prod_step_folds_the_entries_into_the_resource_version_ac_121_7`, `test_a_folded_instance_left_empty_is_removed_ac_121_7`; fixes: `test_a_held_staging_takes_its_pin_move_and_then_the_major_step_after_dev_moved_on_ac_121_11`, `test_a_render_error_after_the_edit_restores_the_tree_and_exits_1_ac_121_7`; render: the folded-form tests | `scripts/cplat/upgrade.py:116-142` (`check_previous`, `:125-127` the earlier environment may be ahead for a pin move), `:244-265`, `:436-447` (rollback) | First review: a held staging or prod could not move on after dev took a new major. Check 11 asked for a pin move, and check 10 then refused that pin move. bc73e6b lets a pin move pass check 10 when the earlier environment runs the same or a higher major, verified at its own table pin. The new test runs the hint and then the major step. A render error after the edit now restores `applications/` and `bootstrap/` (plan t5). |
| AC-121.8 | met (cluster part pending CI) | cmds: `test_after_dev_smoke_the_staging_step_starts_by_itself_after_a_verified_dev_ac_121_8`, the manual, default-manual, failed-dev, prod-never and all-on-major tests; e2e step 5 | `scripts/cplat/upgradeverify.py:223-234` (`next_line`), `:380-399` (`run`); `upgrade.py:293-303` | Nothing ever starts prod. |
| AC-121.9 | met | cmds: the staging-refused tests (old major, not verified, failed, other image), the prod-behind, unreadable-record, nearest-environment, no-instance, bad-env and dirty-tree tests | `upgrade.py:116-138`, `:165-217` | |
| AC-121.10 | met | cmds: `test_a_pr_that_changes_the_major_in_two_environments_fails_naming_resource_and_environments_ac_121_10`, the hand-edit, different-majors, one-at-a-time, folding, unrenderable-base and new-system tests, the CI-job and recipe tests | `templates/gitops-app/scripts/upgrade-check.py:40-85`; template `ci.yml` job `upgrade-check (one environment per major)`; template `devbox.json` `upgrade-check` | |
| AC-121.11 | met (after bc73e6b, 1a586be; cluster part pending CI) | render: the held-pin tests; cmds: the pin-move tests, the update tests; fixes: the two held-staging tests (16 after dev moved on; 15 deprecated); fleet: `test_files_the_rerender_wrote_are_not_lost_and_the_fleet_pr_is_not_held_ac_121_23`, `test_a_hand_edit_outside_the_generated_files_is_still_lost_ac_121_23`; e2e step 3 | `render.py:1266-1294` (`held_pin`), `:1422`; `upgrade.py:125-127`, `:200-202` (check 8 for major steps only); `scripts/cplat/update.py:581-604` (`_generated_snapshot`, `written`), `:807` | First review: (a) the dead end of AC-121.7; (b) a held 15 could never take its pin move; (c) fleet PRs were held for files the update's own re-render wrote. All three are fixed. A hand edit of a rendered file is now overwritten without a `lost` entry. That is acceptable: the repo's own `render --check` CI already rejects such edits. |
| AC-121.12 | met | cmds: the no-key, never (dev), 65-minute, 55-minute, staging, unreadable and read-like-status tests; e2e step 4 | `upgrade.py:141-162`, `:215-216`; `BACKUP_MAX_AGE_S = 3600` at `:26` | Exactly 60 minutes passes (`>` at `:159`); no test pins that boundary. |
| AC-121.13 | met | cmds: `test_an_external_instance_is_refused_with_the_owner_text_ac_121_13`, `test_an_external_dev_is_refused_by_default_too_ac_121_13` | `upgrade.py:190-191` | |
| AC-121.14 | met | cmds: the downgrade (database hint, cache without), outside-table, same-major, every-upward-jump and check-order tests | `upgrade.py:193-203` | The intermediate-major text is tested with a patched `UPGRADE_PATHS`. |
| AC-121.15 | met (cluster part pending CI) | cmds: the verified-block, healthy-at-image, missing-Secret, only-users-smoked, no-repo, record ConfigMap, first-base-backup, cache-statefulset and broker-Secrets tests, `test_the_upgrade_of_a_cell_comes_from_the_record_ac_121_15`; e2e steps 3, 5 and 6 | `upgradeverify.py:87-130` (health), `:237-350` (`verify`), `:70-78` (record) | |
| AC-121.16 | met (after the review fixes; cluster part pending CI) | cmds: the 15-minute, not-verified, failed-record and failing-smoke tests, the two restore tests; `test_upgrade_121_restore_fixes.py` (13, last `test_a_server_older_than_the_archive_list_closes_where_the_list_starts_ac_121_16`); `test_upgrade_121_restore_open.py` (5); render: the archives, restored-generation, note and invalid-archives tests; e2e step 5 | `upgradeverify.py:333-339`; `backupstate.py:390-424` (`current_archive`, `source_server`); `dbrestore.py:105-116`, `:289-297`; `upgrade.py:217-224`, `:268-287`; `render.py` `database_cluster` (`major_of`), `stepped_since`, `archive_notes` | A failed step stops with exit 1, names the environment, the check and the last backup, and for a database names `/resource:restore`. No later environment moves.<br>**The way back works:**<br>- `latest` is the current archive;<br>- every listed archive's window closes where the next starts, and an unlisted (pre-first-step) server's window closes where the list starts (fc0f677), so a time picks exactly one source. Several unlisted 117 generations still resolve by `GEN`, as in spec 117;<br>- every cluster role renders on the major of its data (checked role by role at d13b7ff; fc0f677 changes only the choice of source);<br>- a switched generation archives under its own name;<br>- a re-upgrade after a switch writes a fresh archive and moves the image;<br>- a major step is refused while a restore is open;<br>- the note names a way forward that works.<br>The fc0f677 test covers all three periods: after the step `…-g1-pg17`, between the switch and the step `…-g1`, before the switch `<db>`. |
| AC-121.17 | met | render: the twelve property-operator tests (no answer, cache/broker/bucket, secrets, external and backup, plain, Kyverno, LGTM application and need, one per repo, removed, directory goes, table rows); cmds: the copier-default and `system new` tests; ops: the Argo-path, bootstrap and e2e-answer tests | `render.py:2790-2837`, `:2814`, `:2840-2859`, `:2862-2890`; `templates/gitops-app/copier.yml` (`property_operators`, default `owner`); `scripts/cplat/newapp.py:138-139` | Existing repos get `owner` (the copier default) and render nothing new. Their clusters are unchanged. |
| AC-121.18 | met | render: `test_an_owner_environment_gets_no_operator_application_ac_121_18`, the non-owner-environments test, `test_any_other_operators_value_fails_naming_owner_ac_121_18`; ops: `test_an_owner_environment_is_checked_the_same_way_ac_121_18` | `render.py:2840-2845`; `scripts/cplat/doctor.py` `check_operators` | |
| AC-121.19 | met (cluster part pending CI) | ops: the JSON-row, missing-fails-with-context, without-context (two), older/newer (parametrised), 0.x-major, order and property-row tests, `test_the_broker_rows_compare_without_digests_ac_121_19` | `doctor.py:544-560`, `:625`; `--context` at `:785` | FAIL only with `--context`, as the changelog reading says. |
| AC-121.20 | met (reading) | cmds: `test_the_update_moves_the_shared_operator_once_with_dev_ac_121_20` | `update.py:581-622`, `:654` (one group; the comment names AC-121.20) | A gitops repo has one `cluster_server`, so AC-121.21 governs (changelog reading). |
| AC-121.21 | met (cluster part pending CI) | ops: `test_with_a_context_the_detail_lists_the_crds_and_who_shares_the_operator_ac_121_21`, the one-environment test; cmds: the update `--verify` option test; e2e step 3 (no chart moves twice) | `update.py:654-711` (smoke of every instance); `doctor.py` `shared` | |
| AC-121.22 | met (cluster part pending CI) | render: the crds-per-operator, waited-CRD and cnpg-v1 tests; ops: the lacking-version and gone-CRD tests; e2e step 6 (server-side dry runs) | `render.py:280-410` (`_CRDS_*`); `doctor.py:553-560` | |
| AC-121.23 | met | cmds: the four `versions` diff and changelog tests, `test_the_update_json_carries_the_versions_and_the_pr_body_lists_them_ac_121_23`; ops: the release-check rows tests, the branch-green test, the CHANGELOG-entry test | `versions.py:132-183`; `scripts/release-check.py:106-127`; `scripts/cplat/fleet_pr.py:132-134` | See "To fix" 4 for the same PR body's false "lost" entries. |
| AC-121.24 | met (pending CI) | ops: the ten e2e-script tests, the gate (success, refusals), workflow, release-guard, no-tag, CI-job and CONTRIBUTING tests; e2e steps 1 to 6 | `tests/e2e/upgrade.sh`; `.github/workflows/e2e-upgrade.yml`; `.github/workflows/release-guard.yml`; `release-check.py:148-161` | The job name and `E2E_NAME` are byte-identical (`od -c`). "Not tagged" is a gate plus the procedure (changelog reading). |
| AC-121.25 | met (pending CI) | ops: `test_the_e2e_script_refuses_an_upgrade_without_a_recent_backup_and_changes_nothing_ac_121_25`, `test_the_e2e_script_forces_a_failed_verification_and_keeps_staging_and_prod_readable_ac_121_25`; e2e steps 4 and 5 | `tests/e2e/upgrade.sh` steps 4 and 5 | Checks HEAD, the tree, `imageName` and `.metadata.generation`; staging and prod stay on 16 and their rows read back. |
| AC-121.26 | met | ops: `test_an_operator_major_move_fails_on_a_minor_release_ac_121_26`, the major-release pass, removed-CRD and dropped-major tests, `test_ci_runs_the_release_check_job_and_waits_for_it_ac_121_26` | `release-check.py:79-97`, `:113-120` | |
| AC-121.27 | met | cmds: the cache (no backup read, "has no backup"), no-restore-state, broker (string version), bucket-refused and cache-earlier-environment tests | `upgrade.py:177-178`, `:215`, `:316` | |

## Non-goals

- External resources are refused (`upgrade.py:190-191`, `upgradeverify.py:261-262`). ✔
- No automatic rollback or downgrade: downgrades are refused and the way back is named, never run. ✔
- No per-system minor choice: `system.yaml` holds only the major. ✔
- No Kubernetes upgrade: the k3s pin applies to new local clusters only. ✔
- No component image pins are touched. ✔
- Spec 114 is not amended (`docs/specs/114-*` is untouched). ✔
- Backup and restore mechanics: 121 adds `archives` and a line in `dbrestore`. This is in scope (design.md), but it is where AC-121.16's defect comes from.

## Approved test changes

1. **5947174 (t19).** Every changed line carries `# spec 121`:
   - digested pins and `PIN_RE`;
   - `version` in the instance key lists;
   - 118's `test_version_is_not_an_instance_key` becomes the unsupported-version test, as the plan names it;
   - byte-identity through `unpin` with the BEFORE digests unchanged;
   - the collector digest in the 4.7 comparisons;
   - the model normalisation.
2. **4fef075, 1278a86, 8d9d558** and the t12 line in `test_service_crds.py`:
   - the `crds` key is dropped before the 116, 119 and 120 operator equalities;
   - `pin` and `chart_version` in the effective values;
   - plugin versions;
   - `/resource:upgrade` in the command list (39 → 40);
   - the `upgrade-check` job.

   Each only adds the new value.
3. **ebdfb7a.** The 117 status test now asserts "no backup reads" instead of "no kubectl call at all". That is narrower than before, but the cause is 121's new health read, and the 117 intent (no backup reads) is kept. Also: the 114 grid filter stops at "Resource versions", and the doctor fixture gains an environment backup.
4. **Slips f027e00 and faa55ca.** Fixture fixes in the 121 tests (an unused backup target; staging's cluster for the guard). No assertion changed.

None weakens a criterion. `git log b36cbc3..HEAD` on the 121 test files shows only 5947174, f027e00, faa55ca and ebdfb7a.

## Deviations from the plan

1. **t5: a render error after the edit is not rolled back.** `upgrade.py:405-412` writes `system.yaml` and `restore-state.yaml`, then calls `gitops.render` without a try or restore. The plan says "on any render error restore the files and raise it". This is recoverable with `git checkout`. Fix with the other items.
2. **t15 and t16 "Done when"** require local e2e runs recorded here. Not done; pending CI.
3. **design.md has no "Re-verified at build" line** for t1's re-verification (120 added one). Add it.
4. **Files outside every task's `files`:**
   - the planning artefacts (ADR-068, ADR-069, `docs/adr/README.md`, `docs/backlog.md`, spec, design, plan);
   - the red commit's tests and `upgrade_fixtures.py`;
   - `test_backup_117_cmds.py`, `test_broker_119_cmds.py`, `test_cache_118_cmds.py`, `test_nouns_114.py`, `test_plugins_114.py`, `test_resources_115_cmds.py`, `test_scale_120_cmds.py`, `test_service_crds.py` (the approved amendments);
   - `site/scripts/sync-docs.mjs` (the guide on the site).

   Acceptable.
5. **Task status.** The plan has no `done` flags. Each of t1 to t19 has a commit:
   - a9ccafa, 48ccb18, 0048349, b1cc0bf, 13e7113, dda4494;
   - 07f95ab (+d6d05f1), b338433, 7e5436d, 5e570e5, 4b7fda7 (+8cb4c23), 2481558;
   - 69f9efb, b2e0226, 73c8aaf, e27fde8, 9ea9c87, 121f8e3, 5947174.
6. **`needs-upgrade-e2e` compares with the newest tag, not with the PR base** (`release-check.py:130-138`). This is what design.md says. Until the next release, though, every PR that triggers the workflow's paths (including `docs/CHANGELOG.md`, which most feature PRs touch) runs the 75-minute upgrade e2e, because the table differs from `v5.3.0`. This is CI cost only. Consider comparing against the PR base for `pull_request`.
7. `plugins/resource/commands/upgrade.md:2` describes "a database or cache" and leaves out brokers. This is cosmetic.

## Design decisions taken by default (all 25 checked)

1. In-place `pg_upgrade` by `imageName`: `render.py:2201-2205`. ✔
2. `standard-trixie` immutable tags with digests: `:247-252`. ✔
3. 15 is deprecated, not dropped: `:273`. ✔ (its pin move fixed in bc73e6b)
4. Held pins live in the rendered files: `:1266-1294`. ✔
5. A Barman server per major, recorded as `archives`: `upgrade.py:264-277`, `render.py:2221-2223`. ✔ as designed, the switched-generation rule was corrected in 3b98429; see AC-121.16 for the remaining re-upgrade defect.
6. Records are ConfigMaps: `upgradeverify.py:70-78`. ✔
7. Smoke runs from a shallow clone or `--component-dir`: `upgradeverify.py:160-182`. ✔
8. No smoke recipe or repo fails the check: `:163-164`, `:198-201`. ✔
9. Check 11 (the held pin first): `upgrade.py:209-212`. ✔ as designed, the dead ends it caused were fixed in bc73e6b.
10. `property_operators`: default `owner`, `install` for `system new`: `copier.yml`, `newapp.py:138-139`, `render.py:2814`. ✔
11. LGTM as plain manifests, not in cluster repos: `:2862-2890`; `lgtm` is not an `OPERATORS` row. ✔
12. ESO also for caches, brokers, buckets and environment backups: `:2852-2855`. ✔
13. Argo CD v3.4.12: `:266-267`. ✔
14. k3s and the Gateway API manifest are rows: `:266-270`, `versions_table`. ✔
15. Doctor escalates only with `--context`: `doctor.py:625`. ✔
16. `--to <current major>` is the pin move: `upgrade.py:198`, `:213`. ✔
17. The default `--env` is the first environment with an instance: `upgrade.py:101-102`. ✔
18. No `--confirm prod`. ✔
19. Its own workflow, 75 minutes: `e2e-upgrade.yml`. ✔
20. The NATS digest rides in `tag`: `:2526-2528`. ✔
21. Literal script defaults, held equal by the pin check: `check-pins.py:217-257`. ✔
22. Broker rows compare without digests: `doctor.py` `check_brokers`. ✔
23. The CHANGELOG line format: `versions.py:161-183`, `docs/CHANGELOG.md`. ✔
24. Plugins `resource` 1.6.0, `platform` 1.3.0 and `system` 1.5.0, in both places. ✔
25. Two ADRs (068, 069); both numbers are free on `origin/main`. ✔

## Contract

Matches `design.md` in these parts:
- the versions table and its rows;
- `cplat platform versions`;
- the `system.yaml` key and its errors;
- effective majors and held pins;
- archives;
- property operators;
- every refusal text and its order (checks 1 to 16);
- the PR title and body;
- verification and its record;
- the `/platform:update` block and `--verify`;
- the gitops CI check;
- doctor;
- model and status;
- the local cluster;
- the pin check;
- the release check, the gate and the workflows.

The defects below follow the design itself, so design.md needs the same corrections.

## Safety checks requested

- **Tags and releases.** Nothing creates, moves, publishes or deletes a tag or a release:
  - `release-check.py` only reads (`git describe`, `gh api …/check-runs`);
  - both new workflows only read;
  - `test_no_workflow_tags_releases_or_deletes_tags_ac_121_24` scans them;
  - deleting a tag is a human step in CONTRIBUTING. ✔
- **Gate name.** `e2e upgrade (previous release → candidate)` is byte-identical in `e2e-upgrade.yml` (job `name:`) and `release-check.py:31`. ✔
- **Permissions.** `release-guard.yml` has `contents: read, checks: read`; `e2e-upgrade.yml` has `contents: read`; the new `release-check` job inherits ci.yml's workflow permissions. ✔
- **CI gates.** ci.yml only adds the pin-check step and the `release-check` job, which is in `ci-success`'s needs. Nothing is removed or relaxed. ✔
- **Byte-identity.** Systems without the new keys render byte-identically after `unpin` (×10). BEFORE_118, BEFORE_119 and BEFORE_120 are unchanged. ✔
- **Existing clusters.** `property_operators` defaults to `owner` for existing repos: `/platform:update` writes copier's default, and a missing answer reads as `owner` (`render.py:2814`, `doctor._property_operators_answer`). Existing clusters get no new operator Applications. ✔
- **YAML 1.1.** `version: yes` fails as `version 'True'` (`test_a_boolean_is_never_a_version_ac_121_6`). The e2e compares YAML as strings. ✔
- **The 60-minute guard.** It reads exactly `backup.last_success` from `status.public_backups(status.collect_backups(...))`. It applies in dev. It runs after checks 1 to 12 and before the dirty-tree check, as designed. Residual risk: the guard runs when the step is written. A `--pr` step merged much later (no `--wait`, or a PR left open) applies without a recent backup. Consider re-checking in CI or before `--wait` verifies.

## To fix before the PR

Nothing blocking. The items of all seven reviews are fixed (see "Fixes after review"). Before merge:

1. This PR's CI must run the e2e job (`run.sh`) and the upgrade e2e (`e2e-upgrade.yml`, job `e2e upgrade (previous release → candidate)`) green. Neither e2e exercises the restore-after-upgrade paths. Those rest on the unit tests named in the AC-121.16 row.
2. Optional, unchanged:
   - `needs-upgrade-e2e` compares with the newest tag, so until the next release most PRs touching `docs/CHANGELOG.md` run the 75-minute upgrade e2e (CI cost);
   - the `/resource:upgrade` description omits brokers.
3. Residual, outside this spec: a hand edit of one environment's `instances.<env>.version` bypasses the backup guard and the rollout order. AC-121.10's CI check refuses only multi-environment changes.

## Fixes after review

Rechecked at 3b98429 by reading `git diff 73c8aaf..3b98429` and the new tests. No tests rerun (read-only). `system_render.py` is still byte-identical to `render.py`.

- **b22cf15.** design.md records the build-time re-verification of every pin (Deviation 3). ✔
- **bc73e6b (AC-121.7, AC-121.11 (a)(b), Deviation 1).**
  - `check_previous` (`upgrade.py:124-127`): for a pin move, an earlier environment on a higher major is held to its own major's table pin and record.
  - Check 8 applies only when `to != cur` (`:200-202`).
  - `snapshot_tree`/`restore_tree` put `applications/` and `bootstrap/` back on any failure of the edit or the render (`:436-447`).
  - Tests: `test_upgrade_121_fixes.py` (3). They run the formerly dead hint and then the major step, for 16 and for deprecated 15.
  - UPGRADES.md and design.md updated. ✔
- **1a586be (fleet false positive).**
  - `render_and_compare` collects every path under `applications/` and `operators/` the re-render created or changed (`update.py:581-604`), and `_lost` skips them (`:807`).
  - Tests: `test_update_121_fleet.py` (2): velero.yaml and a broker's server.yaml are not `lost`, and the PR is not held. A hand edit of `scripts/render.py` is still `lost` and holds the PR.
  - The `applications/` digest rule from d6d05f1 stays; it now matters only for the 4.x migration proof. ✔
- **3b98429 (AC-121.16 (a)(b)(c)).**
  - `current_archive` for `latest`;
  - windows closed at the next archive's first point (exclusive);
  - `--switch` appends the generation as its own archive with the major it runs, and records `archive` on the previous cluster;
  - `database_cluster` uses that `archive` for the previous cluster (`render.py:2224-2226`);
  - `read_restore_state` validates `archive`;
  - `_major_before_upgrade` names only a real upgrade (next major higher).
  - Tests: `test_upgrade_121_restore_fixes.py` (7), each with both windows present. design.md marks the paragraph "Changed after review". It also records the known gap: a time between the major step and the new archive's first base backup is refused, never restored from the wrong major. Acceptable.
  - The spec 117 restore tests stay green (orchestrator).
  - The re-upgrade defect above was not introduced by these fixes. It was already there at 73c8aaf; I missed it in the first review.

- **228a293 (the re-upgrade after a switch, second review).**
  - `write_archives` (`upgrade.py:268-287`) names the new archive after the active cluster: `<system>-<db>-pg<to>` unswitched, as before; `<db>-g1-pg17` after a switch. A taken name gets the smallest free numeric suffix, so a name is never reused.
  - The note offers only "set `…version: <m>`, then `/resource:upgrade …`".
  - The amended note-text test in `test_upgrade_121.py` carries `# spec 121 review: …`. It is the renderer's own text, changed by the fix, so this is acceptable.
  - Three tests were added.
  - The archive half is fixed ✔. The step still renders the active generation on 16 (see "To fix" 1).

- **4009a37 (the image after a re-upgrade, third review).**
  - `stepped_since` is true when the generation's own archive entry precedes `archives[-1]` and `archives[-1]` has the effective major. Then the active cluster renders `conf["pin"]`, and `archive_notes` stops printing the note.
  - The previous cluster keeps its own image.
  - The extended test asserts 16 before, 17 after, the previous on 17, and no note.
  - Documented deviation: a hand-written state without the generation's own entry keeps the note. The real `--switch` always appends that entry. Acceptable.
  - The active case is fixed ✔. The `previous` case after a second switch is still open (see "To fix" 1).

- **c935c5c (a stepped generation that becomes previous, fourth review).**
  - The rule is now `role == "restored" or not stepped_since(...)`.
  - The new test (`g1` previous after its 17 step, `g2` restored from `…-g1-pg17`: both on 17, no note) fails on the old condition and passes on the new (orchestrator).
  - That case is fixed ✔. The unstepped `previous` case above is not.

- **60b209a (an unstepped previous cluster, fifth review).**
  - A `previous` cluster's image now follows the major of its recorded `archive`: the pin when that is the effective major, else that major's table image. Restored generations follow their source archive; `stepped_since` applies only to the active cluster.
  - The new test fails on the old rule and passes now (orchestrator); c935c5c's test still passes.
  - design.md is updated. This case is fixed ✔.
  - The paths without a recorded archive (above) remain.

- **d13b7ff (spec 117 restores meeting a major step, sixth review).**
  - (a), (b): a database major step is refused while a `restored` or `previous` instance exists. The check is placed after check 11, before anything is written. Pin moves stay allowed, and the hint is `--discard` (or `--switch`).
  - (c): `major_of` and `_major_before_upgrade` treat a server missing from `archives` as `archives[0].major`.
  - The note starts with the discard step when an instance is open.
  - Tests: `test_upgrade_121_restore_open.py` (5); two tests amended with `# spec 121 review` (acceptable, see the row).
  - design.md (check 11a) and UPGRADES.md updated.
  - The rendering is fixed ✔. The choice of the restore source after the step is still open (see "To fix" 1).

- **fc0f677 (the restore source after the first step, seventh review).**
  - `source_server` closes the window of a server missing from a non-empty `archives` where the first listed archive with a window starts (exclusive).
  - The new test covers the three periods and fails on the previous code (orchestrator).
  - design.md has one line, marked "changed after review". ✔

**Test changes during the review rounds (all in the 121 suites, each marked `# spec 121 review`):**
- 228a293: the note-text test expects the single way forward.
- d13b7ff:
  - the note-text test expects the discard step;
  - the re-upgrade-after-switch test discards the previous instance first, because the new refusal makes the old state unreachable for a major step. It now asserts that the discarded cluster is not rendered.

Each follows the reviewed fix of the renderer's own text or of the refused state. None weakens a criterion. Every other review change only adds tests (`test_upgrade_121_fixes.py`, `test_update_121_fleet.py`, `test_upgrade_121_restore_fixes.py`, `test_upgrade_121_restore_open.py`).

RESULT: pass, on condition that this PR's CI runs the e2e job and the upgrade e2e green before merge. All 27 active criteria are met. AC-121.24, AC-121.25 and the cluster halves of AC-121.4, .5, .8, .11, .15, .16, .19, .21 and .22 are pending that CI.
