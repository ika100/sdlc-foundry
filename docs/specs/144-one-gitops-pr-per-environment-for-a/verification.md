# Verification — 144 One gitops PR per environment for a system ship

**Result:** pass
**Trace:** 8/8 criteria named by tests

Tests: `J` = `tests/cplat/test_144_joint_pr.py` (spec 097's system ship world: real git on a bare origin, fake `gh`,
`kubectl`, `devbox`; the template's `pin-dev.yml` and `pin.py`), `M` = `tests/cplat/test_144_pin_dev_marker.py` (the pin step of
`pin-dev.yml` run with bash against a bare origin). Red at 66a58d7c (21 of 27 failing; the other six pin today's behaviour that
AC-144.6 keeps). Two fixture corrections in the build commit: the stale Argo CD revision is an older commit of `main` (a revision
the clone does not know counts as newer, spec 143), and two merge counts count the dev PR only (staging merges a second PR).
Full `tests/cplat` suite (CI's pytest command), `devbox run validate` and `devbox run quality` green locally.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-144.1 | met | `M::test_a_build_with_a_system_ship_marker_gets_no_pin_pr_ac_144_1`, `M::test_the_marker_check_comes_before_the_pin_ac_144_1`, `J::test_a_gitops_app_with_the_new_pin_dev_runs_joint_ac_144_1`, `J::test_an_older_gitops_app_keeps_one_pr_per_component_with_one_line_ac_144_1`, `J::test_the_component_ship_inside_a_joint_run_knows_it_ac_144_1`, `J::test_the_merge_of_a_joint_component_ship_pushes_its_marker_ac_144_1`, `J::test_result_pins_the_build_on_the_compose_branch_and_closes_a_stray_pin_pr_ac_144_1`, `J::test_without_a_gitops_entry_the_first_pin_opens_the_joint_pr_ac_144_1` | `pin-dev.yml` (marker check before `pin.py`); `appship_joint.supported`, `push_marker`, `pin`; `ship.product_link`, `ship._merged`; `appship_sched._pin_result`; `appship_state.start` (mode) | old gitops-apps: one line, entry merged first (answered question 5) |
| AC-144.2 | met | `J::test_the_entry_pr_waits_for_green_checks_but_stays_open_ac_144_2`, `J::test_a_red_entry_pr_still_escalates_ac_144_2`, `J::test_land_is_not_offered_or_run_before_the_last_component_ac_144_2`, `J::test_land_merges_the_one_pr_once_and_dev_syncs_once_ac_144_2`, `J::test_an_argo_timeout_exits_2_and_land_resumes_after_the_merge_ac_144_2`, `J::test_a_red_dev_app_escalates_with_cause_environment_ac_144_2` | `appship._entry_green`; `appship_sched.next_action` (`land`); `appship_joint.land`, `_argo` (spec 143's `envwait.watch`), `delete_markers`; `appship.complete` refuses before landing | no sync waves added: resources are their own Argo CD apps (design decision 4) |
| AC-144.3 | met | `J::test_a_joint_component_deploy_ends_pinned_in_the_system_ships_pr_ac_144_3`, `J::test_a_joint_component_deploy_with_red_main_ci_fails_as_today_ac_144_3`, `J::test_a_pinned_component_counts_as_delivered_for_the_scheduler_ac_144_3` | `appship_joint.component_deploy`; `ship.deploy` hand-off; `appship_state.PASSED` holds `pinned` | |
| AC-144.4 | met | `J::test_land_runs_the_dev_smoke_of_every_component_and_records_it_ac_144_4`, `J::test_a_red_dev_smoke_escalates_naming_the_component_ac_144_4` | `appship_joint._dev_smokes`, `_smoke` (`smoke.run_smoke`, `smoke.record` as `instance verify`), `_issue` | internal components: Argo CD only, as the old gate |
| AC-144.5 | met | `J::test_a_failed_component_keeps_the_joint_pr_open_and_escalates_ac_144_5` | `appship_sched.next_action` (escalate); `appship_joint.land` refuses an escalated run or a repo not past its gate | |
| AC-144.6 | met | `M::test_a_build_without_a_marker_is_pinned_in_its_own_pr_as_today_ac_144_6`, `M::test_a_marker_of_another_build_does_not_stop_this_pin_ac_144_6` (3 cases) | `pin-dev.yml` matches `ship/<spec>/<service>-<sha7>` exactly; `ship._merged` pushes no marker without a joint product link | existing deploy tests (spec 062/077/093) unchanged and green |
| AC-144.7 | met | `J::test_staging_after_dev_smoke_is_promoted_in_one_pr_for_the_spec_ac_144_7`, `J::test_manual_staging_is_not_promoted_ac_144_7` | `appship_joint._candidates` (spec 093's decision, spec 105's digest check), `_staging_pr`, `_staging`; `appship_report.final_report` | no `pin-staging` dispatch in a joint run |
| AC-144.8 | met (simulated) | `J::test_a_system_spec_across_the_gitops_repo_and_two_components_gives_one_dev_pr_ac_144_8` | the whole flow | the journey record (`2.pr-ci`, `2.deploy-dev`) comes from the next recorded part 2 journey after the release |

## Non-goals

No change to the spec, plan and done PRs, to prod (`/instance:promote`), to the component PRs or their CI, to a gitops CI run's
length, or to a component ship outside a system ship. The e2e (`tests/e2e/`) has no system ship scenario; none added.
