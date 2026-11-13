# Verification — 189 The web image has no known critical CVE and the platform scans template images

**Result:** fail
**Commit:** 5c4b3f3b · **Base:** 75da00d2 · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-189.1 | not met | `tests/cplat/test_189_web_image.py::test_runtime_stage_is_distroless_node_of_the_pinned_major`, `::test_runtime_stage_has_no_shell_package_manager_or_npm`, `::test_runtime_entrypoint_is_node_with_server_js`; `tests/cplat/test_generated_repos.py::test_web_runtime_image_ships_no_npm` | `templates/web-nextjs/Dockerfile.jinja:19` (distroless runtime), `:43` (`CMD ["server.js"]`), no `RUN` in the runtime stage | TEST LOOSER. The code looks right. But every traced test is a static Dockerfile text check. Nothing asserts that **starting the image with `sh` as the command fails**: neither the tests nor `ci.yml` `smoke-test-web-nextjs` (`.github/workflows/ci.yml:476-487`) run it. The "no CRITICAL, CVE-2023-45853 absent" part is enforced only by the PR's `scan web-nextjs` job (`.github/workflows/template-image-scan.yml`), and only through CI. |
| AC-189.2 | not met | `tests/cplat/test_189_web_image.py::test_runtime_runs_as_uid_1000_and_copies_are_chowned_numerically`, `::test_healthcheck_is_exec_form_with_the_distroless_node` | `templates/web-nextjs/Dockerfile.jinja:31-33` (`--chown=1000:1000`), `:36` (`USER 1000:1000`), `:40-41` (exec-form HEALTHCHECK) | TEST LOOSER. The traced tests are static. The existing CI smoke job (`ci.yml:480-487`) does prove these parts: read-only root fs, `/api/health` within 60 s, and `smoke: 1 passed, 0 failed, 0 skipped`. No test asserts that **the image health check reports `healthy`**, and none asserts that **the running Node major equals `node_major`**. The static test checks the literal `nodejs24` and never compares it with a running `node`. |
| AC-189.3 | met | `tests/cplat/test_189_template_image_scan.py::test_select_pr_changing_one_template_selects_only_it`, `::test_select_pr_ignores_templates_without_an_image`, `::test_unaccepted_critical_fails_and_names_template_cve_package_version`, `::test_critical_with_a_fix_names_the_fixed_version`, `::test_high_findings_are_listed_but_do_not_fail`, `::test_workflow_scans_critical_and_high_with_unfixed_included_and_evaluates`, `::test_workflow_pins_trivy_like_the_templates` | `scripts/template-image-scan.py:38-45` (select), `:108-147` (evaluate, exit 1 on an unaccepted CRITICAL, HIGH listed only); `.github/workflows/template-image-scan.yml:42-82` | The log line names the template, CVE, package and installed version, and its exact text is asserted. |
| AC-189.4 | met | `::test_select_non_pr_event_selects_all_four`, `::test_select_cli_prints_output_lines_for_a_schedule`, `::test_scheduled_run_fails_and_names_the_template`, `::test_workflow_runs_on_pull_requests_daily_and_on_demand` | `scripts/template-image-scan.py:40-41`; `.github/workflows/template-image-scan.yml:7-11` (cron `17 3 * * *`) | |
| AC-189.5 | met | `::test_accepted_entry_passes_and_prints_the_finding`, `::test_accepted_entry_is_printed_once_per_cve`, `::test_an_entry_covers_only_the_template_it_names`, `::test_review_date_exactly_90_days_after_added_is_valid`, `::test_accepted_list_parses_and_every_entry_is_valid` | `scripts/template-image-scan.py:114-116` (only entries for this template), `:131-139` (the `accepted:` line) | The exact `accepted: <CVE> in <template>: <reason> (review by <date>)` text is asserted. |
| AC-189.6 | met | `::test_entry_without_a_reason_fails`, `::test_entry_with_a_passed_review_date_fails`, `::test_entry_with_a_review_date_too_far_fails`, `::test_entry_for_a_cve_no_longer_found_fails`, `::test_entry_is_found_at_any_severity` | `scripts/template-image-scan.py:117-128`, `:147` | Each of the four problem strings is asserted in an `entry <CVE> in <template>: <problem>` line, with exit 1. |
| AC-189.7 | met | `::test_dependabot_header_names_the_template_image_scan` | `.github/dependabot.yml:1-5` | |

## What the coder must add (AC-189.1, AC-189.2)

Add the missing runtime assertions to the `smoke-test-web-nextjs` image step, or to a dedicated step in that job:

- `docker run --rm smoke:web sh` exits non-zero (AC-189.1).
- `docker run --user 1000 ...`, then wait until `docker inspect -f '{{.State.Health.Status}}' smoke` prints `healthy` (AC-189.2).
- The running Node's major equals the rendered `node_major` (AC-189.2), for example `docker exec smoke /nodejs/bin/node -p 'process.versions.node.split(".")[0]'` compared with the copier default.

These are new CI assertions, not edits to the frozen acceptance tests. The orchestrator decides whether they count as acceptance tests for the criteria.

## Non-goals

- The deps and builder stages stay on `node:{{ node_major }}-slim` (`Dockerfile.jinja:3,10`). ✔
- The base images of service-python, service-java and service-go are unchanged. ✔
- `.github/image-scan-accepted.yml` is platform-only: nothing under `templates/` references it, and the generated repos' own scan rules are unchanged. ✔
- No Dependabot Docker entry was added. ✔
- Only the four image templates are scanned (`scripts/template-image-scan.py:24`). ✔
- No HIGH fixes. No template-owned layout changes. ✔

## Deviations from the plan

- `.github/image-scan-accepted.yml` is `findings: []`, because no local trivy run was available (t2 allowed this). This PR touches the scan's own files, so `select` picks all four templates (`scripts/template-image-scan.py:43-44`). Any "won't fix" CRITICAL in a service image will fail this PR's `scan <template>` job until an entry and its follow-up issue (the plan's human step) are added. **Acceptable**, provided the PR's scan jobs are green or the entries are added before merge.
- `tests/cplat/test_generated_repos.py::test_web_runtime_image_ships_no_npm` was rewritten by the t1 coder and now carries `# AC-189.1`. The plan's t1 `files` and notes asked for exactly this change, and the red acceptance tests in `test_189_web_image.py` were not touched. **Acceptable.**
- `docs/backlog.md` (generated index) and `docs/specs/189-*/{spec,plan}.md` (status, `done` flags) are in no task's `files`. They are spec bookkeeping. **Acceptable.**
- `docs/adr/109-...md` is not in t2's `files` list, but the t2 notes assign it to t2. **Acceptable.**
- The spec 148/194 and system ship files in the diff came from main (`a945aac0`, #702), not from this spec. They are out of scope.
- All tasks have `done: true`.

## Contract

`scripts/template-image-scan.py` matches `design.md`:
- `select` and `evaluate` behave as specified.
- Output lines follow the specified order (CRITICAL, HIGH, accepted, entry problems, summary).
- The problem strings are exact.
- Exit codes are 0/1/2, with usage errors for a missing field, an unknown template, an unreadable report or a malformed list.

The workflow matches design.md "Workflow": permissions, concurrency, the `decide` job with `fetch-depth: 0`, and the matrix with `fail-fast: false` and timeouts of 2 and 30 minutes. The trivy inputs and the trivy pin are the templates' own. ✔
