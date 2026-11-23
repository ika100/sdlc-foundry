# Verification — 218 A .NET service shape

**Result:** pass
**Commit:** 3601d9b3 · **Base:** facaa305 · **Trace:** 11/11 criteria named by tests (`tests/cplat/test_218_service_dotnet.py`); the restored, built and running template is proved by the CI job `smoke-test-service-dotnet` (four variants) and was run locally the same way

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-218.1 | met | `test_the_registry_holds_the_shape_with_its_runtime_ac_218_1`, `test_service_csharp_is_a_pair_and_a_lone_csharp_is_a_service_ac_218_1`; `test_type_lang_pairs_come_from_the_registry_plus_service_unknown_ac_114_58` extended | `shapes.yml`, `scripts/cplat/newsvc.py` | `scripts/shapes.py check`: OK, 11 shapes. |
| AC-218.2 | met | `test_component_new_renders_the_template_with_a_pascal_case_namespace_ac_218_2`, `test_detection_by_answers_and_by_a_project_with_a_dockerfile_ac_218_2`, `test_a_fresh_render_is_detected_ac_218_2`; `scripts/test-detect-shape.sh` | `scripts/detect-shape.sh`, `copier.yml` (`namespace`) | A .NET project without a Dockerfile resolves to no shape (left for a .NET library). |
| AC-218.3 | met | `test_the_render_has_the_canonical_recipes_behind_the_gate_helper_ac_218_3`, `test_the_dotnet_runner_of_gate_sh_counts_the_trx_results_ac_218_3`; the AC-130 gate matrix (`test_130_empty_gates.py`) and `test_172_quiet.py` with the shape added | `devbox.json.jinja`, `Directory.Build.props.jinja`, `scripts/gate.sh` (`dotnet` runner) | Locally on all four renders: locked restore, `dotnet format`, the analyzer build, xUnit with coverage (93–100 % lines), trivy, detect-secrets pass. |
| AC-218.4 | met | `test_the_app_serves_the_probes_and_metrics_ac_218_4`, `test_without_observability_there_are_no_metrics_and_no_opentelemetry_ac_218_4`; the template's own `AppTests`, `MetricsTests`, `LoggingTests` | `ServiceApp.cs`, `HttpMetrics.cs`, `JsonLineFormatter.cs`, `Telemetry.cs` | Running image: `/health`, `/ready` 200, `/metrics` with `http_requests_total{method="GET",route="/health",status="200"}`, JSON log lines. |
| AC-218.5 | met | `test_the_dockerfile_is_multi_stage_chiseled_and_non_root_ac_218_5`; `test_186_templates.py`, `test_ci_templates.py`, `test_promote_digest.py` with the shape added | `Dockerfile.jinja` | Local run with `--read-only`: `USER 65532:65532`, 187 MB image. |
| AC-218.6 | met | `test_ci_has_the_service_job_set_and_the_registry_checks_ac_218_6`; `test_tags_and_wait.py` | `.github/workflows/ci.yml` of the template | actionlint clean. |
| AC-218.7 | met | `test_the_smoke_runner_selects_smoke_tests_and_leaves_out_writes_when_read_only_ac_218_7`, `test_the_summary_prints_the_contract_lines_with_the_test_file_path_ac_218_7`; `test_smoke_091_templates.py`, `test_smoke_474_read_only.py` with the shape added | `scripts/smoke.sh`, `scripts/smoke-summary.sh`, `Smoke/HealthSmokeTests.cs` | Against the running image: exit 2 without a base URL, `smoke: 1 passed, 0 failed, 0 skipped` (also read-only); an unreachable URL gives a FAIL line. |
| AC-218.8 | met | `test_the_database_variant_has_ef_core_migrations_and_testcontainers_ac_218_8`, `test_without_a_database_none_of_it_is_there_ac_218_8`; the template's `DatabaseTests` (Testcontainers) | `Data/`, `.config/dotnet-tools.json` | Image with PostgreSQL started later: `/health` 200, `/ready` 503 while waiting, ready after the migration, 503 when the database stops, ready again when it returns. `migrate-new` generated a migration that builds and lints (marked generated code). |
| AC-218.9 | met | `test_the_plugin_has_its_agents_hook_readme_and_versions_ac_218_9`, `test_the_template_enables_the_plugins_ac_218_9`, `test_cplat_shape_routes_the_roles_of_a_rendered_repo_ac_218_9`, `test_every_svc_dotnet_prompt_has_a_register_file_ac_218_9` | `plugins/svc-dotnet/`, `docs/rules/plugins/svc-dotnet/`, `.claude-plugin/marketplace.json` | `cplat platform rules check` OK; baseline raised 390314 → 415271 bytes (on top of spec 219's raise) after the quick-task (318 k tokens) and build (2.63 M tokens) benchmarks on the rebased prompts, runs 20261123T101426Z-644188be, 20261123T101806Z-c78e833a. |
| AC-218.10 | met | `test_the_platform_tooling_knows_the_shape_ac_218_10`, `test_deps_reads_the_central_versions_and_finds_the_lock_files_ac_218_10`, `test_build_tests_filters_dotnet_test_by_the_test_classes_ac_218_10`, `test_failure_summaries_read_dotnet_test_and_build_output_ac_218_10`, `test_the_platform_ci_smoke_tests_the_template_ac_218_10`; `test_deps_parse.py`, `test_189_template_image_scan.py`, `test_192_stages.py`, `test_system_render_114.py` | `scripts/cplat/{deps_parse,deps,buildtests,newapp,stages}.py`, `scripts/cplat/failsum/dotnet.py`, `scripts/{template-image-scan,bump_template_pins,dotnet_bump_minor,template-lint,sync-template-copies}.py`, `scripts/ci-local.sh`, gitops-app `render.py`/`plan.py`, CI workflows | `template-lint.py service-dotnet` names file, line and rule of a `dotnet format` finding. |
| AC-218.11 | met | `test_the_docs_name_the_shape_and_plugin_ac_218_11`, `test_an_adr_records_the_stack_ac_218_11` | ADR-127, `docs/templates.md`, `docs/AGENTS.md`, `docs/ADOPTING.md`, PRD, site shapes page, `CLAUDE.md` | `check-docs.py` and `check-links.py` OK. |

Full cplat suite after the rebase onto spec 219: 13,274 passed; the 14 rules tests failed only on the byte baseline (raised in this branch) and one runtemp test was a load flake that passes alone.

## Non-goals

- No .NET library (#720), no .NET Framework, Windows containers or IIS, no controllers/MVC option, no Microsoft.Testing.Platform. ✔
- No contract check for the shape. ✔

## Deviations from the plan

- `dotnet list package --vulnerable` was replaced by trivy over the lock files (A7), so `cplat deps` reuses the trivy parser of `service-java`.
- xUnit v3 4.x needs Microsoft.Testing.Platform on the .NET 10 SDK unless the project takes `xunit.v3.mtp-off`; the template does (A8).
- EF migrations are marked `generated_code` in `.editorconfig`, because the generated files broke the style rules.
- The platform smoke job does not run the trivy audit (as in the Java job); the template's own CI `security` job does.
