# Verification — 098 Gitops CI checks Components against the service branch CRDs

**Result:** pass
**Commit:** a239bdc · **Base:** 836861c (merge base with origin/main; origin/main has since gained 7be680c, spec 085, which this branch does not touch) · **Trace:** 17/17 criteria named by tests · **Test diff:** `cplat spec test-diff 178c94d`: no acceptance test changed

Tests: `pytest tests/cplat/test_service_crds.py tests/cplat/test_service_ref.py tests/cplat/test_ci_gates.py`: 101 passed, 1 skipped; full `pytest tests/cplat -n auto`: exit 0; `devbox run ci-local` (orchestrator): 729 passed, 4 skipped.

Abbreviations: `crds.py` = `templates/gitops-app/scripts/check-service-crds.py`; `T_CRDS` = `tests/cplat/test_service_crds.py`; `T_REF` = `tests/cplat/test_service_ref.py`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-098.1 | met | `T_REF::test_ac_098_1_with_service_ref_is_pure_and_idempotent`, `::test_ac_098_1_a_new_gitops_pr_carries_exactly_one_marker`, `::test_ac_098_1_a_body_without_marker_gets_one` | `scripts/cplat/ship.py:516-535` (`with_service_ref`), `:553`, `:563-565` | ref is `service_slug(repo)@st['branch']`; marked body is written to `<gitops dir>/../<task>-body.md`, the caller's file is untouched (asserted). Test feeds two candidate lines (one bad) and asserts exactly one marker. |
| AC-098.2 | met | `T_REF::test_ac_098_2_a_reused_pr_without_marker_gets_it_and_nothing_else_changes`, `::test_ac_098_2_a_different_marker_is_replaced`, `::test_ac_098_2_a_reused_pr_with_the_marker_is_not_edited` | `scripts/cplat/ship.py:555-561` | `pr list --json number,url,body`; one `pr edit <url> --body-file` only when the marked body differs; rest of the body asserted byte-equal by lines. |
| AC-098.3 | met | `T_CRDS::test_ac_098_3_every_component_is_validated_and_other_manifests_are_not`, `::…_skip_list_names_every_served_version_of_every_service_crd`, `::…_an_unserved_version_is_an_error`, `::…_crds_come_from_chart_crds_and_untemplated_templates`, `::…_external_helm_path_selects_the_chart`, `::…_reads_are_pinned_to_the_branch_commit`, `::test_ac_098_3_the_skip_list_reaches_kubeconform_as_one_skip_argument` | `crds.py:210-255` (chart dirs, CRD discovery), `:258-291` (schema conversion), `:358-390` (all `applications/**` YAML), `:431-437` (skip list to stdout and `GITHUB_ENV`); `templates/gitops-app/devbox.json:28` (`${SERVICE_CRD_SKIP:+-skip …}`) | Other groups, other kinds, patch files and unparsable files are asserted untouched; kubeconform gets exactly the old args plus one `-skip`. kubeconform matches `-skip` entries against `<apiVersion>/<Kind>`, so the format is right. |
| AC-098.4 | met | `T_CRDS::test_ac_098_4_a_component_that_does_not_match_fails_with_file_kind_field_and_ref` (unknown field, wrong type, missing required, list index), `::…_unknown_top_level_field_is_reported_at_the_root`, `::…_int_or_string_accepts_both` | `crds.py:288-290` (strict `additionalProperties: false`), `:334-355` (field path and problem), `:380` (line with file, kind, name, ref) | The full ERROR line is asserted literally. |
| AC-098.5 | met | `T_CRDS::test_ac_098_5_valid_components_pass_and_the_log_lists_the_kinds` | `crds.py:427-430` | Asserts the `OK:` line with count, the kinds line with `<owner>/<repo>@<ref>` and commit, the skip list, `GITHUB_ENV` and the summary. |
| AC-098.6 | met | `T_CRDS::test_ac_098_6_a_missing_branch_falls_back_to_the_default_branch_and_says_so`, `::test_ac_098_6_the_fallback_passes_when_components_match` | `crds.py:195-205`, `:161-162` (only a branch 404 falls through) | WARNING line names both branches; every contents read uses the default-branch sha (asserted). |
| AC-098.7 | met | `T_CRDS::test_ac_098_7_a_ref_without_crds_changes_nothing` | `crds.py:413-415` | Exit 0, empty stdout and `GITHUB_ENV`, so kubeconform runs as without a marker; an invalid Component is not reported. |
| AC-098.8 | met | `T_CRDS::test_ac_098_8_a_repo_that_is_not_a_service_fails_and_nothing_is_fetched`, `::test_ac_098_8_the_repo_comparison_ignores_case` | `crds.py:92-102`, `:402-405` | `fake.requests == []` asserted; the check runs before the token check and before any `Repo` is built. |
| AC-098.9 | met | `T_CRDS::test_ac_098_9_a_malformed_or_repeated_marker_fails_with_the_expected_form` (13 cases), `::…_a_valid_marker_with_crlf_and_trailing_space_is_accepted` | `crds.py:37-42`, `:72-82` | Hint asserted literally; nothing fetched. |
| AC-098.10 | met | `T_CRDS::test_ac_098_10_a_marker_without_the_token_fails_with_a_hint_and_fetches_nothing`, `::test_ac_098_10_an_empty_token_counts_as_missing`, `::test_ac_098_10_the_step_gets_the_body_and_the_token_through_env` | `crds.py:406-408`; `templates/gitops-app/.github/workflows/ci.yml:40-45` | An empty secret (how Actions passes an unset secret) fails, it does not skip. |
| AC-098.11 | met | `T_CRDS::test_ac_098_11_a_repo_that_cannot_be_read_fails_naming_repo_and_reason` (401/403/404/418), `::…_a_forbidden_contents_read_also_fails`, `::…_a_server_error_is_retried_once`, `::…_a_network_failure_fails_naming_repo_and_reason` | `crds.py:115-148` (reasons, one retry, 30 s timeout), `:157-163` | |
| AC-098.12 | met | `T_CRDS::test_ac_098_12_invalid_yaml_in_a_crd_file_fails_naming_file_and_ref`, `::…_a_crd_without_an_openapi_schema_fails`, `::…_a_templated_crd_fails` | `crds.py:237-251`, `:307-313` | "file too large" (`:239-240`) has no test; it is a design detail, not a criterion case. |
| AC-098.13 | met | `T_CRDS::test_ac_098_13_the_token_is_redacted_everywhere_and_sent_only_to_the_api`, `::…_when_it_appears_in_a_marker_error`, `::…_in_a_network_error`, `::test_ac_098_13_the_token_appears_only_in_the_crd_step` | `crds.py:51-63` (one redacting `emit`), `:107-114` (no redirects, so the token never leaves `GITHUB_API_URL`), `:131-133` (token only in the `Authorization` header), `:436-437`; `ci.yml:40-45` | Every request goes to `/repos/<marker repo>` (asserted); the quality step has no secret in its env. |
| AC-098.14 | met | `T_CRDS::test_ac_098_14_without_a_marker_the_script_does_nothing_and_needs_no_token`, `::…_nothing_is_read_even_with_a_token`, `::test_ac_098_14_the_crd_step_runs_only_on_pull_requests_and_before_quality`, `::test_ac_098_14_the_devbox_recipe_runs_the_script`, `::test_ac_098_17_without_a_skip_list_kubeconform_gets_the_previous_arguments` | `crds.py:396-399`; `ci.yml:41` (`if: github.event_name == 'pull_request'`) | pin-dev calls `ci.yml` from a `repository_dispatch` run, so the step is skipped there; push and `workflow_dispatch` skip it too. |
| AC-098.15 | met | `T_CRDS::test_ac_098_15_a_body_edit_runs_ci_again_in_its_own_concurrency_group` | `ci.yml:10` (`edited` already a trigger), `:25` (edit runs in their own `-edited` group) | No code change was needed; the test pins the trigger and group the behaviour relies on, and the script reads the body from the event of the run (`ci.yml:43`). A static check is the only test possible offline. |
| AC-098.16 | met | `T_REF::test_ac_098_16_missing_secret_is_a_warning_with_the_fix`, `::…_unreadable_secret_list_is_a_warning`, `::…_present_secret_is_ok`, `::…_other_shapes_do_not_show_the_check`, `::…_run_checks_includes_it_for_a_gitops_app` | `scripts/cplat/doctor.py:193-213`, `:216-220` | WARN, never FAIL; the fix names the secret and `gh secret set … -R <slug>`; other shapes do not even list the secrets (asserted). |
| AC-098.17 | met | `T_CRDS::test_ac_098_17_without_a_skip_list_kubeconform_gets_the_previous_arguments`, `::test_ac_098_17_triggers_and_job_names_are_unchanged`, `::test_ac_098_17_the_rest_of_validate_is_unchanged`, plus the AC-098.14 no-marker tests | `devbox.json:28`; `ci.yml:40-45` | `ci.yml`, `devbox.json` and the script are not in `_skip_if_exists` of `templates/gitops-app/copier.yml`, so `/shared:update-service` brings the step, the recipe and the script together. A no-marker PR now runs one extra step (`uv run` with `pyyaml`, `jsonschema`) that exits 0. |

## Non-goals

- Only resources whose group and kind match a service CRD are validated (`crds.py:373-376`); Helm values, chart templates and the service's own manifests are not. ✔
- Kinds unknown to both the catalog and the service ref are still skipped by `-ignore-missing-schemas`; without a service CRD the skip list is empty and kubeconform runs unchanged. ✔
- The script reads one repo, the one in the single marker (`crds.py:76-77` refuses a second marker). ✔
- No cluster install or dry-run apply. No spec 097 code. The token is neither created nor granted; doctor only reports. ✔

## Deviations from the plan

- **`templates/gitops-app/devbox.json`: the `ci` recipe now runs `devbox run service-crds && devbox run validate && devbox run security`.** The design only named the new `service-crds` recipe and the `-skip` in `validate`. The change is required by the existing invariant AC-075.1 (`tests/cplat/test_ci_gates.py::test_devbox_ci_runs_the_workflow_gates_in_job_order`: `devbox run ci` chains exactly the `devbox run` steps of `ci.yml`). Locally `PR_BODY` is unset, so the step logs "no Service-ref marker" and exits 0, and without `GITHUB_ENV` it exports nothing; `validate` runs as before. The file is in t3's `files` and the gitops-app `CLAUDE.md.jinja` documents the new chain. **Acceptable.**
- Every changed file is in one task's `files`; all five tasks are `done: true`. The diff against `origin/main` also shows spec 085 files as "removed". That is only because the branch is based on 836861c and 085 landed afterwards (7be680c). Rebase before the PR. Not a deviation of this build.

## Contract

Matches `design.md`:
- Marker: the candidate and valid regexes and the branch rules (`crds.py:38-42`, `:80`; `ship.py:516`).
- Order of checks: steps 2 to 4 happen before any request (`crds.py:396-409`).
- Messages: the ERROR/WARNING/OK texts are asserted literally.
- The skip list goes to stdout and to `GITHUB_ENV`.
- The token is only in the `Authorization` header for `GITHUB_API_URL`, and redirects are refused.
- CI step and devbox recipes as specified.
- Doctor messages and fix text match.
- The `ship.py` change is small: one helper plus about 8 lines inside `gitops_pr()`. ✔

## Findings (none blocking)

- **Low:** `resolve_ref` (`crds.py:203`): if the default branch itself returns 404 after the fallback, the `ApiError` is not caught. The run ends with a traceback and exit 1: it fails, not silently, but without the formatted `cannot read` line.
- **Low:** for a reused PR, `with_service_ref` replaces a CRLF marker line (which a web edit produces) with an LF line. A body that already carries the right marker can then get one more, harmless, `gh pr edit`.
- **Info:** `file too large for the contents API` (`crds.py:239-240`) has no test.
