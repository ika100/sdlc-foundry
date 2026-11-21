# Verification — 214 A TypeScript service shape

**Result:** pass
**Commit:** 8f89be4e · **Base:** b579a1bc · **Trace:** 11/11 criteria named by tests (`tests/cplat/test_214_service_typescript.py`); the installed, built and running template is proved by the CI job `smoke-test-service-typescript` (four variants) and was run locally the same way

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-214.1 | met | `test_the_registry_holds_the_shape_with_its_runtime_ac_214_1`, `test_service_typescript_is_a_pair_and_a_lone_typescript_stays_a_website_ac_214_1`; `test_type_lang_pairs_come_from_the_registry_plus_service_unknown_ac_114_58`, `test_component_new_maps_the_pair_to_its_template_ac_114_33` extended | `shapes.yml`, `scripts/cplat/newsvc.py` | `scripts/shapes.py check`: OK, 9 shapes. |
| AC-214.2 | met | `test_component_new_renders_the_template_ac_214_2`, `test_detection_by_answers_and_by_a_fastify_package_ac_214_2`, `test_a_fresh_render_is_detected_ac_214_2`; `scripts/test-detect-shape.sh` | `scripts/detect-shape.sh` | A Next.js app that lists Fastify stays `web-nextjs`. |
| AC-214.3 | met | `test_the_render_has_the_canonical_recipes_behind_the_gate_helper_ac_214_3`; the AC-130 gate matrix (`test_130_empty_gates.py`, `test_130_gate_sh.py`) and `test_172_quiet.py` with the shape added | `templates/service-typescript/devbox.json.jinja`, `package.json.jinja`, `vitest.config.mts` | Locally on all four renders: install, ESLint, `tsc`, Vitest with coverage (96–100 % lines), `pnpm audit`, detect-secrets pass; a render without tests fails `test-fast` with the AC-130 line. |
| AC-214.4 | met | `test_the_app_serves_the_probes_and_metrics_ac_214_4`, `test_without_observability_there_are_no_metrics_and_no_opentelemetry_ac_214_4`; the template's own `app`, `metrics`, `logger` tests | `src/app.ts`, `src/metrics.ts`, `src/logger.ts`, `src/telemetry.ts` | Running image: `/health`, `/ready` 200, `/metrics` with `http_requests_total{method="GET",route="/health",status="200"}`, JSON log lines. |
| AC-214.5 | met | `test_the_dockerfile_is_multi_stage_distroless_and_non_root_ac_214_5`; `test_186_templates.py`, `test_ci_templates.py`, `test_promote_digest.py` with the shape added | `Dockerfile.jinja` | Local run with `--read-only`: UID 65532, Node 24, no shell, 64 MB of production `node_modules`. |
| AC-214.6 | met | `test_ci_has_the_service_job_set_and_the_registry_checks_ac_214_6`; `test_186_templates.py`, `test_tags_and_wait.py` | `.github/workflows/ci.yml` of the template | actionlint clean on the rendered workflow. |
| AC-214.7 | met | `test_the_smoke_runner_selects_smoke_tests_and_leaves_out_writes_when_read_only_ac_214_7`, `test_the_summary_prints_the_contract_lines_for_the_selected_tests_ac_214_7`; `test_smoke_091_templates.py`, `test_smoke_474_read_only.py` with the shape added | `scripts/smoke.sh`, `scripts/smoke-summary.mjs`, `vitest.smoke.config.mts`, `tests/smoke/health.test.ts` | Against the running image: exit 2 without a base URL, `smoke: 1 passed, 0 failed, 0 skipped`; a `@writes` test left out under `SMOKE_READ_ONLY=1`; a broken config gives `FAIL  (smoke recipe)`. |
| AC-214.8 | met | `test_the_database_variant_has_drizzle_migrations_and_testcontainers_ac_214_8`, `test_without_a_database_none_of_it_is_there_ac_214_8`; the template's `tests/db.test.ts` (Testcontainers) | `src/db/`, `src/server.ts`, `drizzle/`, `drizzle.config.ts` | Image with PostgreSQL started later: `/health` 200 and `/ready` 503 while waiting, ready after the migration, 503 when the database stops, ready again when it returns (no crash). |
| AC-214.9 | met | `test_the_plugin_has_its_agents_hook_readme_and_versions_ac_214_9`, `test_the_template_enables_the_plugins_ac_214_9`, `test_cplat_shape_routes_the_roles_of_a_rendered_repo_ac_214_9`, `test_every_svc_ts_prompt_has_a_register_file_ac_214_9` | `plugins/svc-ts/`, `docs/rules/plugins/svc-ts/`, `.claude-plugin/marketplace.json` | `cplat platform rules check` OK; baseline raised 362326 → 387135 bytes after the quick-task (226 k tokens) and build (3.42 M tokens) benchmarks, runs 20261121T080831Z-491cc83d, 20261121T080947Z-4f1777bb. |
| AC-214.10 | met | `test_the_platform_tooling_knows_the_shape_ac_214_10`, `test_the_platform_ci_smoke_tests_the_template_ac_214_10`; `test_deps_templates.py`, `test_deps_parse.py`, `test_189_template_image_scan.py`, `test_192_stages.py`, `test_system_render_114.py` | `scripts/cplat/{deps_parse,buildtests,comprelease,newapp,stages}.py`, `scripts/{template-image-scan,bump_template_pins,template-lint,sync-template-copies}.py`, `scripts/ci-local.sh`, gitops-app `render.py`/`plan.py`, CI workflows | |
| AC-214.11 | met | `test_the_docs_name_the_shape_and_plugin_ac_214_11`, `test_an_adr_records_the_stack_ac_214_11` | ADR-124, `docs/templates.md`, `docs/AGENTS.md`, `docs/ADOPTING.md`, PRD, site shapes page, `CLAUDE.md` | `check-docs.py` and `check-links.py` OK. |

Full cplat suite: 12,806 passed after the baseline raise (the 14 rules tests failed only on the byte baseline before it).

## Non-goals

- No TypeScript library (spec 215), no serverless runtime, no other framework option. ✔
- No contract check for the shape; `web` plugin and `web-nextjs` template unchanged. ✔

## Deviations from the plan

- The gitops-app renderer's `VALID_PAIRS` and the plan checker's `SHAPES` (copies in the template, not read from the registry) needed the shape too; found by `test_system_render_114.py`.
- Migrations run after `listen` instead of before, so liveness answers while the database starts (found by running the image).
