---
spec_id: 114-the-platform-speaks-the-domain-model-5-0
spec_hash: 504e69b8294b
summary: 5.0 — one system.yaml per system, checked by render.py and loaded into the spec-113 model (schema 2); a migration
  that converts 4.x repos and proves a byte-identical render with a frozen 4.7 renderer, rolled out and auto-merged by the
  fleet; cplat grouped by noun with moved-name errors; seven noun plugins with the 30 working slash commands and generated
  tombstones for the 27 old ones; agents, templates, docs, site, CHANGELOG and versions in the 5.0 words
tasks:
  - id: t1
    title: render.py reads system.yaml (load, validate, resolve instances, refuse unmigrated) and the frozen 4.7 renderer asset
    files: [templates/gitops-app/scripts/render.py, scripts/cplat/assets/render_v4.py]
    covers: [AC-114.1, AC-114.2, AC-114.3, AC-114.4, AC-114.5, AC-114.7, AC-114.8, AC-114.9, AC-114.12, AC-114.13, AC-114.14, AC-114.15, AC-114.16, AC-114.17, AC-114.18, AC-114.19, AC-114.20, AC-114.21, AC-114.22, AC-114.57, AC-114.58, AC-114.70]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: gitops-app template around render.py — system.yaml starter, owner answer, pin/plan/CRD scripts, cluster and policy scripts
    files: ["templates/gitops-app/applications/{{ app_name }}/system.yaml.jinja", "templates/gitops-app/applications/{{ app_name }}/app.yaml.jinja", "templates/gitops-app/applications/{{ app_name }}/services.yaml.jinja", templates/gitops-app/copier.yml, templates/gitops-app/scripts/pin.py, templates/gitops-app/scripts/plan.py, templates/gitops-app/scripts/check-service-crds.py, templates/gitops-app/scripts/local-cluster.sh, templates/gitops-app/scripts/check-policies.sh, templates/gitops-app/scripts/alert-poll.sh, templates/gitops-app/.github/workflows/pin-staging.yml, templates/gitops-app/.github/workflows/pin-dev.yml]
    covers: [AC-114.1, AC-114.20]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: model.py loads system.yaml (schema 2, owner, APIs, libraries, instance overrides, NotMigrated, type/lang helpers); model show; gitops helpers
    files: [scripts/cplat/model.py, scripts/cplat/modelcmd.py, scripts/cplat/gitops.py]
    covers: [AC-114.6, AC-114.23, AC-114.58, AC-114.69, AC-114.70]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: migrate5.py — pure conversion of app.yaml + services.yaml into system.yaml, problems list, header dump
    files: [scripts/cplat/migrate5.py]
    covers: [AC-114.41, AC-114.42, AC-114.48, AC-114.67]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t5
    title: platform update --migrate — refusal, already migrated, dry-run, byte-identical proof against render_v4, rollback, report
    files: [scripts/cplat/update.py]
    covers: [AC-114.40, AC-114.42, AC-114.43, AC-114.44, AC-114.45, AC-114.46, AC-114.47, AC-114.48]
    parallel_safe: true
    depends_on: [t1, t4, t6]
    done: true
  - id: t6
    title: enabledPlugins merge with plugin report; the templates enable the 5.0 noun plugins
    files: [scripts/cplat/settingsmerge.py, templates/gitops-app/.claude/settings.json.jinja, templates/service-python/.claude/settings.json, templates/library-python/.claude/settings.json, templates/service-java/.claude/settings.json.jinja, templates/service-go/.claude/settings.json.jinja, templates/web-nextjs/.claude/settings.json.jinja]
    covers: [AC-114.45]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: fleet update runs the migration and merges a proved one on green CI
    files: [scripts/cplat/fleet.py, scripts/cplat/fleet_pr.py]
    covers: [AC-114.49, AC-114.68]
    parallel_safe: true
    depends_on: [t5]
    done: true
  - id: t8
    title: cplat noun dispatcher, moved-name errors (exit 2) and the 5.0 help
    files: [scripts/cplat/cplat.py]
    covers: [AC-114.26, AC-114.60]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: cplat api list
    files: [scripts/cplat/apilist.py]
    covers: [AC-114.60, AC-114.61]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t10
    title: component add|set|remove edit components in system.yaml (type/lang, instances, --instance ENV --replicas)
    files: [scripts/cplat/compose.py]
    covers: [AC-114.23, AC-114.35]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t11
    title: resource add|remove postgres in system.yaml; observability refused; no list
    files: [scripts/cplat/addon.py]
    covers: [AC-114.23, AC-114.36]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t12
    title: instance promote <component...|--all> --to <env> (source from the order, instances key, pins, digest check)
    files: [scripts/cplat/promote.py]
    covers: [AC-114.23, AC-114.28, AC-114.29]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t13
    title: instance secret set <component>/<env> and list, with per-instance overrides
    files: [scripts/cplat/secret.py]
    covers: [AC-114.18, AC-114.23, AC-114.30]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t14
    title: system status — one row per component, one column per environment, resource section
    files: [scripts/cplat/status.py]
    covers: [AC-114.23, AC-114.32]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t15
    title: instance verify [ENV], env URLs from system.yaml, staging promotion after-dev-smoke
    files: [scripts/cplat/smoke.py, scripts/cplat/staging.py, scripts/cplat/staging_deploy.py]
    covers: [AC-114.6, AC-114.8, AC-114.23, AC-114.31, AC-114.38]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t16
    title: ship and system ship in 5.0 names (gates, hints, budget gate, Stop hooks); model reads in appship
    files: [scripts/cplat/ship.py, scripts/cplat/appship.py, scripts/cplat/appship_state.py, scripts/cplat/appship_sched.py, scripts/cplat/appship_report.py, scripts/cplat/appship_merge.py, scripts/cplat/budget.py, plugins/shared/hooks/hooks.json]
    covers: [AC-114.23, AC-114.38]
    parallel_safe: true
    depends_on: [t3, t8]
    done: true
  - id: t17
    title: alert poll per environment (rules and endpoints of each environment's observability); telemetry lgtm detection
    files: [scripts/cplat/alertsources.py, scripts/cplat/alerts.py, scripts/cplat/telemetry.py]
    covers: [AC-114.9, AC-114.10, AC-114.23]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t18
    title: component new --type/--lang/--system and system new (system, owner, components with type/lang)
    files: [scripts/cplat/newsvc.py, scripts/cplat/newapp.py]
    covers: [AC-114.33, AC-114.34, AC-114.58]
    parallel_safe: true
    depends_on: [t2, t3]
    done: true
  - id: t19
    title: platform doctor warns about the 4.x plugins and files; its checks read the model
    files: [scripts/cplat/doctor.py]
    covers: [AC-114.39]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t20
    title: 5.0 names in the hints of spec, build, adopt, shape and helper modules
    files: [scripts/cplat/spec.py, scripts/cplat/buildcmd.py, scripts/cplat/replan.py, scripts/cplat/adopt.py, scripts/cplat/shapecmd.py, scripts/cplat/core.py, scripts/cplat/gates.py, scripts/cplat/headless.py, scripts/check-spec-required.py, scripts/test-detect-shape.sh]
    covers: [AC-114.60]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t21
    title: 5.0 names in the runs, retro, triage, feedback, deps and issue modules and their assets
    files: [scripts/cplat/runs.py, scripts/cplat/runs_report.py, scripts/cplat/runs_agents.py, scripts/cplat/runs_bench.py, scripts/cplat/runs_usage_cli.py, scripts/cplat/runs_usage_report.py, scripts/cplat/retro.py, scripts/cplat/retro_setup.py, scripts/cplat/retro_report.py, scripts/cplat/retro_proposals.py, scripts/cplat/triage.py, scripts/cplat/feedback.py, scripts/cplat/deps.py, scripts/cplat/autoissue.py, scripts/cplat/alertissues.py, scripts/cplat/evidence.py, scripts/cplat/claim.py, scripts/cplat/assets/workflows/cplat-retro.yml, scripts/cplat/assets/retro-prompt.md, scripts/cplat/benchmark/tasks.json]
    covers: [AC-114.60]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t22
    title: plugin system — new, status, spec, plan, ship; planner agent moved from app
    files: [plugins/system/.claude-plugin/plugin.json, plugins/system/README.md, plugins/system/commands/new.md, plugins/system/commands/status.md, plugins/system/commands/spec.md, plugins/system/commands/plan.md, plugins/system/commands/ship.md, plugins/system/agents/planner.md, plugins/app/agents/planner.md]
    covers: [AC-114.32, AC-114.34, AC-114.59, AC-114.64, AC-114.66]
    parallel_safe: true
    depends_on: [t14, t16, t18]
    done: true
  - id: t23
    title: plugin component — new, add, set, remove, spec, plan, build, verify, check, ship, fix, release; references moved from svc
    files: [plugins/component/.claude-plugin/plugin.json, plugins/component/README.md, plugins/component/commands/new.md, plugins/component/commands/add.md, plugins/component/commands/set.md, plugins/component/commands/remove.md, plugins/component/commands/spec.md, plugins/component/commands/plan.md, plugins/component/commands/build.md, plugins/component/commands/verify.md, plugins/component/commands/check.md, plugins/component/commands/ship.md, plugins/component/commands/fix.md, plugins/component/commands/release.md, plugins/component/references/build-red-rounds.md, plugins/component/references/build-replan.md, plugins/component/references/build-resume.md, plugins/component/references/build-security-red.md, plugins/component/references/build-worktree-fallback.md, plugins/component/references/fix-on-main.md, plugins/component/references/ship-gitops.md, plugins/component/references/ship-land-red.md, plugins/svc/references/build-red-rounds.md, plugins/svc/references/build-replan.md, plugins/svc/references/build-resume.md, plugins/svc/references/build-security-red.md, plugins/svc/references/build-worktree-fallback.md, plugins/svc/references/quick-task-on-main.md, plugins/svc/references/ship-gitops.md, plugins/svc/references/ship-land-red.md]
    covers: [AC-114.33, AC-114.35, AC-114.59, AC-114.62, AC-114.63, AC-114.64]
    parallel_safe: true
    depends_on: [t10, t16, t18]
    done: true
  - id: t24
    title: plugins api, resource, instance, issue, platform
    files: [plugins/api/.claude-plugin/plugin.json, plugins/api/README.md, plugins/api/commands/list.md, plugins/resource/.claude-plugin/plugin.json, plugins/resource/README.md, plugins/resource/commands/add.md, plugins/resource/commands/remove.md, plugins/instance/.claude-plugin/plugin.json, plugins/instance/README.md, plugins/instance/commands/promote.md, plugins/instance/commands/secret.md, plugins/instance/commands/verify.md, plugins/issue/.claude-plugin/plugin.json, plugins/issue/README.md, plugins/issue/commands/triage.md, plugins/issue/commands/report.md, plugins/platform/.claude-plugin/plugin.json, plugins/platform/README.md, plugins/platform/commands/doctor.md, plugins/platform/commands/update.md, plugins/platform/commands/fleet.md, plugins/platform/commands/runs.md, plugins/platform/commands/retro.md]
    covers: [AC-114.28, AC-114.30, AC-114.31, AC-114.36, AC-114.59, AC-114.61]
    parallel_safe: true
    depends_on: [t9, t11, t12, t13, t15, t19]
    done: true
  - id: t25
    title: tombstones — scripts/tombstones.py, the 27 old command files, app/gitops emptied of agents and hooks
    files: [scripts/tombstones.py, scripts/ci-local.sh, plugins/svc/commands/build.md, plugins/svc/commands/fix-bug.md, plugins/svc/commands/plan.md, plugins/svc/commands/quick-task.md, plugins/svc/commands/release.md, plugins/svc/commands/ship.md, plugins/svc/commands/spec.md, plugins/svc/commands/specs.md, plugins/svc/commands/verify.md, plugins/app/commands/build.md, plugins/app/commands/plan.md, plugins/app/commands/ship.md, plugins/app/commands/spec.md, plugins/app/commands/specs.md, plugins/gitops/commands/addon.md, plugins/gitops/commands/compose.md, plugins/gitops/commands/promote.md, plugins/gitops/commands/secret.md, plugins/shared/commands/check-quality.md, plugins/shared/commands/doctor.md, plugins/shared/commands/fleet.md, plugins/shared/commands/new-app.md, plugins/shared/commands/new-service.md, plugins/shared/commands/report-issue.md, plugins/shared/commands/status.md, plugins/shared/commands/triage.md, plugins/shared/commands/update-service.md, plugins/gitops/agents/deployment.md, plugins/gitops/hooks/hooks.json]
    covers: [AC-114.27, AC-114.59, AC-114.65, AC-114.66]
    parallel_safe: true
    depends_on: [t22, t23, t24]
    done: true
  - id: t26
    title: versions — marketplace, plugin manifests, plugin READMEs of svc/shared/app/gitops; shapes.yml and the shape check
    files: [.claude-plugin/marketplace.json, plugins/svc/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/app/.claude-plugin/plugin.json, plugins/gitops/.claude-plugin/plugin.json, plugins/web/.claude-plugin/plugin.json, plugins/svc-go/.claude-plugin/plugin.json, plugins/svc-java/.claude-plugin/plugin.json, plugins/svc/README.md, plugins/shared/README.md, plugins/app/README.md, plugins/gitops/README.md, shapes.yml, scripts/shapes.py]
    covers: [AC-114.50, AC-114.55, AC-114.66]
    parallel_safe: true
    depends_on: [t25]
    done: true
  - id: t27
    title: agent prompts and skills in the 5.0 words (svc, shared, web, svc-go, svc-java)
    files: [plugins/svc/agents/architect.md, plugins/svc/agents/coder.md, plugins/svc/agents/deployment.md, plugins/svc/agents/migrations.md, plugins/svc/agents/observability.md, plugins/svc/agents/product-manager.md, plugins/svc/agents/release.md, plugins/svc/agents/reviewer.md, plugins/svc/agents/tester.md, plugins/svc/skills/spec-format/SKILL.md, plugins/svc/skills/spec-format/references/spec.md, plugins/svc/skills/spec-format/references/design.md, plugins/svc/skills/spec-format/references/plan.md, plugins/svc/skills/spec-format/references/testing.md, plugins/svc/skills/spec-format/references/verification.md, plugins/shared/agents/quality.md, plugins/shared/agents/security.md, plugins/web/agents/coder.md, plugins/web/agents/deployment.md, plugins/web/agents/observability.md, plugins/web/agents/release.md, plugins/web/agents/tester.md, plugins/svc-go/agents/coder.md, plugins/svc-go/agents/deployment.md, plugins/svc-go/agents/observability.md, plugins/svc-go/agents/release.md, plugins/svc-go/agents/tester.md, plugins/svc-java/agents/coder.md, plugins/svc-java/agents/deployment.md, plugins/svc-java/agents/observability.md, plugins/svc-java/agents/release.md, plugins/svc-java/agents/tester.md, plugins/web/README.md, plugins/svc-go/README.md, plugins/svc-java/README.md]
    covers: [AC-114.52]
    parallel_safe: true
    depends_on: [t8]
    done: true
  - id: t28
    title: templates' CLAUDE.md, README and spec docs in the 5.0 words; spec-first names /component:spec and /system:spec
    files: [templates/gitops-app/CLAUDE.md.jinja, templates/gitops-app/README.md.jinja, templates/gitops-app/docs/specs/README.md, templates/service-python/CLAUDE.md, templates/service-python/README.md, templates/service-python/docs/specs/README.md, templates/service-python/docs/backlog.md, templates/library-python/CLAUDE.md, templates/library-python/README.md, templates/library-python/docs/specs/README.md, templates/library-python/docs/backlog.md, templates/service-java/CLAUDE.md.jinja, templates/service-java/README.md.jinja, templates/service-java/docs/specs/README.md, templates/service-java/docs/backlog.md, templates/service-go/CLAUDE.md.jinja, templates/service-go/README.md.jinja, templates/service-go/docs/specs/README.md, templates/service-go/docs/backlog.md, templates/web-nextjs/CLAUDE.md.jinja, templates/web-nextjs/README.md.jinja, templates/web-nextjs/docs/specs/README.md, templates/web-nextjs/docs/backlog.md]
    covers: [AC-114.52, AC-114.55]
    parallel_safe: true
    depends_on: [t2, t22, t23, t24]
    done: true
  - id: t29
    title: DOMAIN-MODEL guide on 5.0 (final schema, full example, command tables) and "Migrating from 4.x to 5.0" in ADOPTING
    files: [docs/DOMAIN-MODEL.md, docs/ADOPTING.md]
    covers: [AC-114.52, AC-114.54, AC-114.71]
    parallel_safe: true
    depends_on: [t1, t5]
    done: true
  - id: t30
    title: guides in the 5.0 words — user journey, how it works, agents, architecture
    files: [docs/USER-JOURNEY.md, docs/HOW-IT-WORKS.md, docs/AGENTS.md, docs/ARCHITECTURE.md]
    covers: [AC-114.52]
    parallel_safe: true
    depends_on: [t25]
    done: true
  - id: t31
    title: remaining docs in the 5.0 words — unattended delivery, agent deck, baselines, templates guide, runners, README, CONTRIBUTING, CLAUDE.md
    files: [docs/unattended-delivery.md, docs/agent-deck.md, docs/BASELINES.md, docs/templates.md, docs/self-hosted-runners.md, README.md, CONTRIBUTING.md, CLAUDE.md]
    covers: [AC-114.52]
    parallel_safe: true
    depends_on: [t25]
    done: true
  - id: t32
    title: plans, requirements, spikes and diagrams in the 5.0 words (PRD shape table matches shapes.yml)
    files: [docs/plan/issue-triage.md, docs/plan/new-app.md, docs/plan/spec-driven-bootstrap.md, docs/requirements/platform-vision.md, docs/requirements/end-to-end-scenario.md, docs/spikes/kro.md, docs/img/sdlc-map.svg, docs/img/model-lifecycles.svg]
    covers: [AC-114.52]
    parallel_safe: true
    depends_on: [t25, t26]
    done: true
  - id: t33
    title: site command reference grouped by noun; configuration and cplat reference; concepts and get-started pages
    files: [site/scripts/generate-reference.mjs, site/src/content/docs/concepts/addons.md, site/src/content/docs/concepts/agents.md, site/src/content/docs/concepts/environments.md, site/src/content/docs/concepts/gitops-model.md, site/src/content/docs/concepts/guard-rails.md, site/src/content/docs/concepts/index.md, site/src/content/docs/concepts/secrets.md, site/src/content/docs/concepts/shapes.md, site/src/content/docs/get-started/index.md, site/src/content/docs/get-started/local-cluster.md]
    covers: [AC-114.52, AC-114.53]
    parallel_safe: true
    depends_on: [t25, t26]
    done: true
  - id: t34
    title: site scenarios and landing pages in the 5.0 words
    files: [site/src/content/docs/index.mdx, site/src/content/docs/problem.md, site/src/content/docs/value.md, site/src/content/docs/vision/index.md, site/src/content/docs/scenarios/index.md, site/src/content/docs/scenarios/addons-secrets-observability.md, site/src/content/docs/scenarios/adopt-existing.md, site/src/content/docs/scenarios/build-a-feature.md, site/src/content/docs/scenarios/extend-the-platform.md, site/src/content/docs/scenarios/harden-for-audit.md, site/src/content/docs/scenarios/project-management-app.md, site/src/content/docs/scenarios/promote-safely.md, site/src/content/docs/scenarios/ship-a-product.md]
    covers: [AC-114.52]
    parallel_safe: true
    depends_on: [t25]
    done: true
  - id: t35
    title: CHANGELOG 5.0.0 (BREAKING, old → new table, migration steps, app/gitops leave in 6.0) and the ADR index
    files: [docs/CHANGELOG.md, docs/adr/README.md]
    covers: [AC-114.50, AC-114.51, AC-114.66]
    parallel_safe: true
    depends_on: [t25, t26]
    done: true
  - id: t36
    title: e2e cluster test on 5.0 names — system new, a shipped spec, instance promote --to staging, instance verify
    files: [tests/e2e/run.sh]
    covers: [AC-114.56]
    parallel_safe: true
    depends_on: [t1, t10, t11, t12, t15, t18]
    done: true
  - id: t37
    title: port the existing cplat tests that build 4.x gitops-app files to system.yaml
    files: [tests/cplat/model_fixtures.py, tests/cplat/test_model.py, tests/cplat/test_model_show.py, tests/cplat/test_model_callers.py, tests/cplat/test_model_release.py, tests/cplat/test_gitops.py, tests/cplat/test_addons.py, tests/cplat/test_policies.py, tests/cplat/test_alerts_render.py, tests/cplat/test_alertsources.py, tests/cplat/test_alertissues.py, tests/cplat/test_alerts_poll.py, tests/cplat/test_alerts_doctor.py, tests/cplat/alerts_fakes.py, tests/cplat/test_staging_093_setting.py, tests/cplat/test_staging_093_ship.py, tests/cplat/test_smoke_091_run.py, tests/cplat/test_ship_checks.py, tests/cplat/test_telemetry.py, tests/cplat/test_telemetry_more.py, tests/cplat/test_service_crds.py, tests/cplat/test_appship_097.py, tests/cplat/fixtures/plans/001-todo-list.md]
    covers: [AC-114.69]
    parallel_safe: false
    depends_on: [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17, t18, t19, t20, t21]
    done: true
  - id: t38
    title: port the existing tests that use 4.x names and plugin paths; the whole suite and ci-local green
    files: [tests/cplat/conftest.py, tests/cplat/fleet_world.py, tests/cplat/test_newsvc.py, tests/cplat/test_newapp.py, tests/cplat/test_fast_suite_112.py, tests/cplat/test_smoke_091_templates.py, tests/cplat/test_java_database.py, tests/cplat/test_spec_driven.py, tests/cplat/test_ci_extra.py, tests/cplat/test_gates.py, tests/cplat/test_update_doctor.py, tests/cplat/test_update_lost.py, tests/cplat/test_adopt.py, tests/cplat/test_rename_migration.py, tests/cplat/test_autoissue_ship.py, tests/cplat/test_feedback.py, tests/cplat/test_runs.py, tests/cplat/test_retro_setup.py, tests/cplat/test_retro_cli.py, tests/cplat/test_replan.py, tests/cplat/test_fleet.py, tests/cplat/test_fleet_pr.py, tests/cplat/test_smoke_091_ship.py, tests/cplat/test_smoke_091_spec.py, tests/cplat/test_promote_digest.py, tests/cplat/test_spec_agents.py, tests/cplat/test_build_replan_docs.py, tests/cplat/test_lean_prompts.py, tests/cplat/test_lean_briefs.py, tests/cplat/test_launcher.py, tests/cplat/test_ship.py, tests/cplat/test_budget.py, tests/cplat/test_runs_agents.py, tests/cplat/test_runs_bench_plugins.py, tests/cplat/test_headless_model.py, tests/cplat/test_validate_review.py, tests/cplat/test_state_per_worktree.py, tests/cplat/test_pr_body_staging.py, tests/cplat/test_issue_forms.py, tests/cplat/test_deps_templates.py, tests/cplat/test_tags_and_wait.py, tests/cplat/test_pr_open.py, tests/cplat/test_ci_gates.py]
    covers: [AC-114.50, AC-114.52]
    parallel_safe: false
    depends_on: [t22, t23, t24, t25, t26, t27, t28, t29, t30, t31, t32, t33, t34, t35, t36, t37]
    done: true
human_steps:
  - After the 5.0 PR merges, tag and publish the release v5.0.0 (AC-114.50).
  - Then run `/platform:fleet update` once with v5.0.0 and fix by hand the repos it reports failed (unconvertible keys or a render difference).
---

# Plan — 114 The platform speaks the domain model (5.0)

The design ([design.md](design.md)) is the contract for every task: the `system.yaml` schema and render errors, model schema 2, the `cplat` noun table and changed arguments, the migration, the plugin layout, tombstones and versions. ADR: [054](../../adr/054-five-zero-interface-and-proved-migration.md).

**Order.** Level 0: `render.py` with the frozen 4.7 renderer (t1), the gitops-app template (t2), the model (t3), the plugin merge (t6), the `cplat` dispatcher (t8) and two hint sweeps (t20, t21). Level 1: the migration converter (t4) and every command module on the model (t9–t19), agent prompts (t27). Level 2: `platform update --migrate` (t5), the noun plugins (t22–t24), the e2e test (t36). Level 3+: fleet (t7), tombstones (t25), versions (t26), templates' and platform docs, site, CHANGELOG (t28–t35). Last, serially: porting the existing tests (t37, t38).

**Shared working tree.** No two parallel-safe tasks of one level share a file. Tasks that move content out of an old command file (t22–t24) finish before t25 overwrites it with a tombstone. Coders do not edit the acceptance tests; existing tests that a task breaks are ported in t37/t38, so the suite may stay red until then.

**Gates** (every task's "Done when" includes its own acceptance tests): `uv run --with pytest --with pytest-xdist --with pyyaml --with ruamel.yaml pytest tests/cplat -q -n auto`, then `bash scripts/ci-local.sh` (green from t38 on).

## t1 — render.py reads system.yaml and the frozen 4.7 renderer asset

**Files:** templates/gitops-app/scripts/render.py, scripts/cplat/assets/render_v4.py
**Covers:** AC-114.1–AC-114.5, AC-114.7–AC-114.9, AC-114.12–AC-114.22, AC-114.57, AC-114.58, AC-114.70
**Goal:** the gitops-app renderer takes `applications/<system>/system.yaml` as its only input, rejects every malformed file with the design's messages, and produces for a converted system the bytes 4.7 produced.

**Implementation notes:**
- First, before any edit: copy the current `templates/gitops-app/scripts/render.py` byte for byte to `scripts/cplat/assets/render_v4.py` (the migration's reference; never edited again).
- `main`: every `applications/<dir>/` with `app.yaml` or `services.yaml` → `ERROR: applications/<dir>: not migrated to 5.0: run `cplat platform update --migrate``, exit 1, before anything is written (also in `--check`). Apps = `applications/*/system.yaml`.
- `load_system(app_dir)`: parse, then validate in the order of the design's error table (top-level keys, `system`, `owner`, environments, components, APIs, resources, `uses`); treat YAML `false` as `off` for `policy`.
- Resolve into the 4.x shapes the builders use: services with `name`, `environments` = instance keys (absent = `[dev]`, library = none), per-instance effective entries (replicas, resources, env merged, secrets fields replaced); a cfg with `gateway`, `secretStore`, per-env host, per-env policy mode (`audit`→`Audit`…), per-env observability, `registries`, postgres conf per env.
- Make the builders per environment where 5.0 is: OTEL variables and the collector only for environments with observability; the policy registries of an environment add the collector image only when that environment has observability; postgres sizing from the resource and its instance overrides.
- Placeholders: `host` `{component}`, `{system}`, `{env}`; secret `path` `{system}`, `{env}`, `{secret}`, `{component}` (default `{system}-{env}-{secret}`); `{service}`/`{app}` fail with the design's text.
- Library components render nothing; `uses` of a library changes no manifest; `apis:` changes no manifest.
- Keep `ENVS`, `render_app(app_dir, ans)`, `stale_paths`, the `--check` output, and every manifest builder's output byte for byte.
- Rewrite the module docstring as the `system.yaml` reference (the site's configuration page is generated from it): keys, placeholders, defaults, one full example.

**Done when:** the acceptance tests of AC-114.2–AC-114.5, AC-114.7–AC-114.9, AC-114.12–AC-114.22, AC-114.57, AC-114.58 and AC-114.70 pass, including the byte-identical comparison of `render_v4.py` on 4.x fixtures against this renderer on their converted `system.yaml`.

## t2 — gitops-app template around render.py

**Files:** `templates/gitops-app/applications/{{ app_name }}/system.yaml.jinja` (new), `app.yaml.jinja` and `services.yaml.jinja` (deleted), templates/gitops-app/copier.yml, scripts/pin.py, scripts/plan.py, scripts/check-service-crds.py, scripts/local-cluster.sh, scripts/check-policies.sh, scripts/alert-poll.sh, .github/workflows/pin-staging.yml, .github/workflows/pin-dev.yml
**Covers:** AC-114.1, AC-114.20
**Goal:** a new gitops-app repo has one `system.yaml` and its scripts read it.

**Implementation notes:**
- `system.yaml.jinja`: the 4.x starter behaviour in 5.0 keys (`system: {{ app_name }}`, `owner: {{ owner }}`, `secretStore`, `gateway`, dev `host: "{component}.{system}-dev.localhost"`, staging `promote: after-dev-smoke`, `policy: "off"` on every environment as the 4.x starter had no policies, `components: {}`), with short comments pointing to `docs/DOMAIN-MODEL.md`.
- `copier.yml`: question `owner` (default `{{ github_org }}`); `_skip_if_exists` lists `applications/**/system.yaml` instead of `app.yaml`/`services.yaml`; header comments in the 5.0 words.
- `pin.py`: components and their instance keys from `system.yaml`; error texts say component; it writes only the overlay (and re-renders an external component's overlay as before).
- `plan.py`: components from `system.yaml`; the gitops operations accept `resource` (alias of `addon`) and `component` (alias of `service`); known resources = `{postgres}`.
- `check-service-crds.py`: components whose `repo` is the slug, from `system.yaml`; messages say component and `system.yaml`.
- `local-cluster.sh`: Kyverno when any environment's policy (defaults audit/audit/enforce) is not off; lgtm when any environment's `observability.ui` is `lgtm`; CloudNativePG when `resources.postgres` exists. `check-policies.sh` and `alert-poll.sh` texts in 5.0 words (`/platform:update`).
- Workflow comments: `/instance:promote`, `environments.staging.promote: after-dev-smoke`.

**Done when:** a fresh `copier copy` of the template renders and `render --check`s, `pin.py dev <c> sha-…` changes only the overlay, and the AC-114.1 and AC-114.20 acceptance tests pass.

## t3 — model.py loads system.yaml (schema 2); model show; gitops helpers

**Files:** scripts/cplat/model.py, scripts/cplat/modelcmd.py, scripts/cplat/gitops.py
**Covers:** AC-114.6, AC-114.23, AC-114.58, AC-114.69, AC-114.70
**Goal:** every command gets its component-in-environment answers from a model loaded from `system.yaml`.

**Implementation notes:**
- `build(doc, system, *, pins, shapes)` per the design (lenient: skip malformed parts); remove the 4.x builder and `declared_addons`.
- `load_dir`: `NotMigrated` when `app.yaml` or `services.yaml` is in the directory; strict parse of `system.yaml` (`ModelError` naming it). `load_remote`: reads `system.yaml`; `NotMigrated` when it is absent and `services.yaml` is readable.
- New: `NOT_MIGRATED`, `NotMigrated`, `TYPE_LANGS`, `type_lang`, `shape_for`, `Api`, `owner`, `provides`/`consumes`/`libraries`, instance overrides (replicas, secrets with `overridden`), sizing `replicas`, 5.0 policy and promotion words, URL placeholders `{component}`/`{system}`.
- `to_dict` schema 2 and relations as in the design; `modelcmd.render` text as in the design.
- `gitops.find_app(repo, name)`: application dirs with `system.yaml`, `app.yaml` or `services.yaml`; the chosen one unmigrated → `PlatformError(NOT_MIGRATED)`; none → `no applications/*/system.yaml here` with the hint `/system:new`. `gitops.load`/`save` round-trip `system.yaml` (ruamel); `components_of(data)` returns the `components` mapping (created when missing). Keep `ENVS` as the alias of `model.ENVIRONMENTS`.
- Keep the AC-113.13 guard true: no environment list or pin read outside `model.py`.

**Done when:** the AC-114.69 and AC-114.70 acceptance tests and the model parts of AC-114.6, AC-114.23 and AC-114.58 pass.

## t4 — migrate5.py: pure conversion

**Files:** scripts/cplat/migrate5.py
**Covers:** AC-114.41, AC-114.42, AC-114.48, AC-114.67
**Goal:** `convert` turns the parsed 4.x files into the `system.yaml` document of the design's conversion table, or lists every key it cannot convert.

**Implementation notes:**
- `convert(system, app, services, owner, shapes=None) -> Conversion(doc, problems, comments)`; `dump(doc) -> str` with the design's header and key order; `has_comments(text) -> bool` for the two old files.
- `shape` → `type`/`lang` through `model.type_lang`; environment names from `model.ENVIRONMENTS`.
- Placeholders `{service}`→`{component}`, `{app}`→`{system}` in hosts, urls and secret paths.
- Policies absent/false → `"off"` on every environment; mode map or scalar → lowercase per environment; postgres per-env maps → `instances.<env>`; `addons.observability` copied to every environment.
- Every value with no 5.0 place is a problem `"<file>: <dotted key> (<why>)"`.

**Done when:** the AC-114.41, AC-114.48 and AC-114.67 acceptance tests and the unconvertible-key part of AC-114.42 pass.

## t5 — platform update --migrate

**Files:** scripts/cplat/update.py
**Covers:** AC-114.40, AC-114.42–AC-114.48
**Goal:** one command converts a repo exactly, or changes nothing.

**Implementation notes:**
- `prog` `cplat platform update`; `--migrate` help: 4.x → 5.0 (system.yaml, plugins; v1 `k8s/` removal included).
- Unmigrated (design rule) without `--migrate` → the refusal; migrated with `--migrate` → normal update plus `already migrated`.
- gitops-app: convert first (problems → exit 1); reference render with `scripts/cplat/assets/render_v4.py` in a temp copy of `HEAD`; after the template step write `system.yaml`, delete the old files, `gitops.render`, compare; any difference → full rollback (tree, branch) and the design's error.
- `--dry-run --migrate`: system.yaml text, files to delete, plugin switch (from `settingsmerge` against the 5.0 template's settings); nothing written.
- Report lines and `data["migration"]` exactly as the design; the plugin report from `settingsmerge`.
- Component repos: no `system.yaml`; `.copier-answers.yml` keeps its shape id; `k8s/` removal stays part of `--migrate`.

**Done when:** the AC-114.40, AC-114.42–AC-114.48 acceptance tests pass.

## t6 — enabledPlugins merge; templates enable the noun plugins

**Files:** scripts/cplat/settingsmerge.py, the six templates' `.claude/settings.json(.jinja)`
**Covers:** AC-114.45
**Goal:** the update switches a repo's plugins without dropping the ones the repo added.

**Implementation notes:**
- `merge_settings`: `enabledPlugins` = template map + the repo's own entries − `app@sdlc-foundry`, `gitops@sdlc-foundry`; never a `replaced` entry; report `plugins: {added, removed}` against the repo's previous map; `merge_settings_file` writes it when it differs from the rendered file.
- Template maps per the design (gitops-app: the seven noun plugins + `svc` + `shared`; component templates: `component`, `api`, `instance`, `issue`, `platform`, `svc`, `shared`, and the language plugin where it has one). Add `Bash(git push -u origin component/*)` and `resource/*` to the gitops-app allow list.

**Done when:** the AC-114.45 acceptance tests pass.

## t7 — fleet update runs and merges the migration

**Files:** scripts/cplat/fleet.py, scripts/cplat/fleet_pr.py
**Covers:** AC-114.49, AC-114.68
**Goal:** `/platform:fleet update` with 5.0 gives every repo one migration PR and merges the proved ones.

**Implementation notes:**
- `_run_update` adds `--migrate` for a repo below 5 when the target is 5 or more.
- `pre_wait_reasons(old, target, data)`: drop the major-version reason under the design's condition; keep `local customisation`.
- A failed migration stays a `failed` row with its first line and no PR (it raises before the push).
- Dry run: `5.0 migration: merges on green CI when proved` for 4 → 5. PR body and comment texts in 5.0 words (`/platform:update`).

**Done when:** the AC-114.49 and AC-114.68 acceptance tests pass.

## t8 — cplat noun dispatcher

**Files:** scripts/cplat/cplat.py
**Covers:** AC-114.26, AC-114.60
**Goal:** `cplat <noun> <verb>` runs the 4.7 behaviour; a 4.7 name exits 2 with one line.

**Implementation notes:**
- Tables `NOUNS` (noun → verb → module and argv prefix), `PLUMBING`, `MOVED` (old → new form) exactly as the design.
- Moved name: the design's line on stderr, exit 2, the module is not imported.
- Noun without verb or unknown verb: the noun's verbs, exit 2. `-h/--help`: the docstring, exit 0.
- Docstring: one line per noun verb and plumbing command with its usage (the site's cplat reference reads it). `_REPORT_HINT` names `/issue:report`.
- `api list` dispatches to `apilist` (t9). The crash hook (spec 088) gets the full argv.

**Done when:** the AC-114.26 and AC-114.60 acceptance tests pass.

## t9 — cplat api list

**Files:** scripts/cplat/apilist.py
**Covers:** AC-114.60, AC-114.61
**Goal:** list each API with type, provider and consumers from `system.yaml`.

**Implementation notes:**
- `main(argv)`: `--system`, `--repo-dir`, `--json`; `gitops.find_app` + `model.load_dir`; output exactly as the design; exit 0, also for no APIs.

**Done when:** the AC-114.61 acceptance tests pass.

## t10 — component add|set|remove on system.yaml

**Files:** scripts/cplat/compose.py
**Covers:** AC-114.23, AC-114.35
**Goal:** 4.7 compose behaviour on `components:` of `system.yaml`, in one PR.

**Implementation notes:**
- `prog` `cplat component`; `--system` replaces `--app`; `--type`/`--lang` replace `--shape`.
- Entries keyed by name under `components` (round-trip), with `type`/`lang` from the shape (`model.type_lang`) and `instances: {dev: {}}`; v1 migration via `--from-k8s` keeps its environments as instance keys.
- `set --instance ENV --replicas N` → `instances.<ENV>.replicas`; the design's errors.
- Branch `component/<action>-<names>`, title `feat(component): …`, body naming `/component:<action>`; next steps name `/instance:promote` and `/resource:add`.
- Unmigrated → `NOT_MIGRATED` (through `gitops.find_app`).

**Done when:** the AC-114.35 acceptance tests and the component part of AC-114.23 pass.

## t11 — resource add|remove postgres

**Files:** scripts/cplat/addon.py
**Covers:** AC-114.23, AC-114.36
**Goal:** 4.7 `addon add|remove postgres` on `resources:` of `system.yaml`.

**Implementation notes:**
- `prog` `cplat resource`; actions `add`, `remove` (no `list`); `--system` replaces `--app`; `--ui`/`--export-to` removed.
- Default entry and the observability and other-name errors exactly as the design; remove refuses while a component `uses` it.
- Branch `resource/<action>-postgres`; next steps name `/component:set <c> --uses postgres`.

**Done when:** the AC-114.36 acceptance tests and the resource part of AC-114.23 pass.

## t12 — instance promote --to

**Files:** scripts/cplat/promote.py
**Covers:** AC-114.23, AC-114.28, AC-114.29
**Goal:** promote to the next environment named by `--to`, the source taken from the order.

**Implementation notes:**
- `prog` `cplat instance promote`; positionals are components (or `--all`); `--to` required; `--system` replaces `--app`.
- Source = `ENVIRONMENTS[index(to) - 1]`; the four errors of the design, all before any change (dry run included).
- Add `instances.<to>: {}` via `gitops.load`/`save` (comments kept), render, `model.write_pin`, render; prod: release tag, spec 106 digest check and evidence unchanged.
- Hints name `/component:release`; PR body/JSON as 4.7 with `component`.

**Done when:** the AC-114.28 and AC-114.29 acceptance tests and the promote part of AC-114.23 pass.

## t13 — instance secret set|list

**Files:** scripts/cplat/secret.py
**Covers:** AC-114.18, AC-114.23, AC-114.30
**Goal:** 4.7 secret behaviour addressed per instance.

**Implementation notes:**
- `set <component>/<env> <secret> <KEY>`; `list [--env]`; `--system` replaces `--app`.
- Remote secrets and store keys from `m.secrets(component, env)` (instance overrides applied).
- The design's error for undeclared or generated secrets; the `MISSING →` hint in the new form.

**Done when:** the AC-114.30 acceptance tests and the override part of AC-114.18 pass.

## t14 — system status

**Files:** scripts/cplat/status.py
**Covers:** AC-114.23, AC-114.32
**Goal:** the component × environment table of the design.

**Implementation notes:**
- `collect` returns rows per component with cells per environment in `environments:` order (`None` without an instance), plus resource rows (postgres Resource instances, observability per environment with instances).
- `render_table` and `--json` exactly as the design; Argo, CI, pin PR and platform lookups unchanged (one CI/platform call per component with a `repo`); `--system` replaces `--app`.

**Done when:** the AC-114.32 acceptance tests pass.

## t15 — instance verify, env URLs, after-dev-smoke

**Files:** scripts/cplat/smoke.py, scripts/cplat/staging.py, scripts/cplat/staging_deploy.py
**Covers:** AC-114.6, AC-114.8, AC-114.23, AC-114.31, AC-114.38
**Goal:** smoke tests reach any environment's instance through the system's model.

**Implementation notes:**
- `smoke.main`: `run [ENV]` positional (default dev) plus `--env`; without `--base-url` the URL comes from `dev_url(repo, apps, component, env=ENV)` for every environment; `prog` `cplat instance verify`.
- `dev_url`/`staging._find`: `model.load_remote` (system.yaml); `NotMigrated` propagates (exit 1 with the message).
- `staging.decide`: `m.staging_promotion(c) != "after-dev-smoke"`; remove the unused `effective`.
- Texts: `Resume with /component:ship <spec>`, `/instance:promote`, `cplat instance verify`.

**Done when:** the AC-114.6, AC-114.31 acceptance tests and the staging part of AC-114.8 pass.

## t16 — ship and system ship in 5.0 names

**Files:** scripts/cplat/ship.py, appship.py, appship_state.py, appship_sched.py, appship_report.py, appship_merge.py, budget.py, plugins/shared/hooks/hooks.json
**Covers:** AC-114.23, AC-114.38
**Goal:** every message of a run names `/component:ship`, `/system:ship` and the 5.0 cplat forms.

**Implementation notes:**
- Docstrings, `prog`, phase hints, escalation and gate texts: `cplat component ship …`, `cplat system ship …`, `/component:plan|build|spec`, `/system:plan|spec`, `/system:status`, `/component:add`, `/instance:promote`; `--command` default `/component:ship`.
- `budget.py`: gate and escalate texts in 5.0 forms; the spec-count parser accepts `/component:ship` and `/system:ship` prompts.
- `ship.dev_namespace`, `appship_state.services`, `appship_sched.gate_class`: read `system.yaml` through the model (`model.build(doc, system)` for the `git show` reads).
- Stop hooks: `"${CLAUDE_PLUGIN_ROOT}/bin/cplat" component ship gate` and `… system ship gate` (state file names unchanged).

**Done when:** the AC-114.38 acceptance tests and the ship part of AC-114.23 pass.

## t17 — alert poll per environment

**Files:** scripts/cplat/alertsources.py, scripts/cplat/alerts.py, scripts/cplat/telemetry.py
**Covers:** AC-114.9, AC-114.10, AC-114.23
**Goal:** each environment's observability drives its own rules and endpoints.

**Implementation notes:**
- `AppConfig.sources: list[EnvSource]` built from `model.load_dir`-equivalent lenient reading of `system.yaml` (keep the lenient `_read_yaml`, then `model.build`); unmigrated dir → a `SourceError` with `NOT_MIGRATED`.
- Per-source skip reasons, rules validation (`applications/<s>/system.yaml` as the endpoint name), `ServiceDown` per instance, `querySecret` namespace rule, series filtering by environment, exactly as the design.
- `alerts.poll`: apps = dirs with `system.yaml` (or legacy files, reported); collects every source, reconciles once; output lines name the environments.
- `telemetry.has_addon`: lgtm when any environment's `observability.ui` is `lgtm` (local `system.yaml` or through `smoke._read`).

**Done when:** the AC-114.10 acceptance tests pass.

## t18 — component new and system new

**Files:** scripts/cplat/newsvc.py, scripts/cplat/newapp.py
**Covers:** AC-114.33, AC-114.34, AC-114.58
**Goal:** create repos from `type`/`lang`; the 4.x flags and manifest keys fail with their replacement.

**Implementation notes:**
- `newsvc`: `--type`/`--lang` resolution and errors as the design (`model.shape_for`, no `unknown`); hidden `--shape`; `--system OWNER/REPO` writes `.platform-app.yml` as `--app` did; `prog` `cplat component new`; next steps `/component:spec`, `/component:plan`, `/component:build` (gitops-app: `/system:spec`, `/system:plan`, `/system:ship`).
- `newapp`: manifest `system`, `owner`, `org`, `visibility`, `components[{name, description, type, lang, data}]`; errors for `app` and `shape`; gitops-app via `--shape gitops-app --data owner=<owner>`; compose step `compose.main(["add", …])` with the 5.0 next-step text (`/component:add … --pr`); `prog` `cplat system new`.

**Done when:** the AC-114.33, AC-114.34 and AC-114.58 (command part) acceptance tests pass.

## t19 — platform doctor

**Files:** scripts/cplat/doctor.py
**Covers:** AC-114.39
**Goal:** doctor points at the migration when 4.x is still in place.

**Implementation notes:**
- The two warn checks of the design (repo and user `settings.json`; `applications/*/app.yaml|services.yaml`), fix `cplat platform update --migrate`.
- The policies (Kyverno) and token checks read components and environments from `system.yaml` through the model (skip quietly on an unmigrated dir: the new warning covers it). Texts name `/platform:update`, `/component:ship`; `prog` `cplat platform doctor`.

**Done when:** the AC-114.39 acceptance tests pass.

## t20 — hints of spec, build, adopt, shape and helpers

**Files:** scripts/cplat/spec.py, buildcmd.py, replan.py, adopt.py, shapecmd.py, core.py, gates.py, headless.py, scripts/check-spec-required.py, scripts/test-detect-shape.sh
**Covers:** AC-114.60
**Goal:** no user-facing text of these modules names a 4.x command.

**Implementation notes:**
- `spec.py`: `/component:spec approve|--amend`, `/component:plan`, `/component:verify`; in a gitops-app repo `/system:spec`, `/system:plan`. `buildcmd`/`replan`: `cplat component build`, `/component:plan`. `adopt`, `core.write_stamp` comment, `gates`: `/platform:update`. `headless` examples `/component:ship 012`, `/component:fix …`. `shapecmd` gitops-app `unsupported`: `/component:* commands do not apply to a gitops-app repo; use /system:spec, /component:add or /instance:promote`.

**Done when:** a grep of these files for `/(svc|app|gitops|shared):` and the 4.7 cplat names of the design's table finds nothing, and their existing tests (ported in t38) pass.

## t21 — hints of runs, retro, triage, feedback, deps and issue modules

**Files:** scripts/cplat/runs*.py (six listed), retro*.py (four), triage.py, feedback.py, deps.py, autoissue.py, alertissues.py, evidence.py, claim.py, assets/workflows/cplat-retro.yml, assets/retro-prompt.md, benchmark/tasks.json
**Covers:** AC-114.60
**Goal:** the same sweep for the feedback-loop modules.

**Implementation notes:**
- `cplat platform runs …`, `cplat platform retro …`, `cplat issue triage …`, `/issue:triage`, `/issue:report`, `/component:spec` (retro proposals), `/component:fix` and `/component:ship` in the benchmark tasks; the retro workflow asset runs `cplat platform retro`.
- `runs_agents`: agent prefixes unchanged (agents stay in `svc`/`shared`); the planner is `system:planner`.

**Done when:** the same grep finds nothing in these files and their existing tests (ported in t38) pass.

## t22 — plugin system

**Files:** plugins/system/** (plugin.json 1.0.0, README, commands new/status/spec/plan/ship, agents/planner.md), plugins/app/agents/planner.md (deleted)
**Covers:** AC-114.32, AC-114.34, AC-114.59, AC-114.64, AC-114.66
**Goal:** the system-level commands, with their 4.7 bodies in 5.0 words.

**Implementation notes:**
- `new` ← `shared:new-app` (`cplat system new`, manifest keys of the design); `status` ← `shared:status` (`cplat system status`); `spec` ← `app:spec` + `app:specs` with the argument dispatch of the design; `plan` ← `app:plan` (agent `system:planner`); `ship` ← `app:ship` (`cplat system ship …`, reads `${CLAUDE_PLUGIN_ROOT}/commands/plan.md`, gitops operations via `cplat resource add` / `cplat component set`).
- Move `planner.md` to `plugins/system/agents/` (git mv) and rewrite it in 5.0 words; the plan format's gitops operations use `resource`/`component` keys.
- Description lines: `<summary>. Usage: /system:<verb> …` (≤ 260 chars, quoted YAML).

**Done when:** the AC-114.59, AC-114.64 and AC-114.66 acceptance tests for the system plugin pass and `python scripts/shapes.py check`'s front-matter check is clean for these files.

## t23 — plugin component

**Files:** plugins/component/** (plugin.json 1.0.0, README, 12 commands, references/), plugins/svc/references/* (deleted)
**Covers:** AC-114.33, AC-114.35, AC-114.59, AC-114.62, AC-114.63, AC-114.64
**Goal:** the component-level commands, moved from `svc`, `shared` and `gitops`.

**Implementation notes:**
- `new` ← `shared:new-service` (`--type/--lang/--system`); `add`/`set`/`remove` ← `gitops:compose`, one file per verb; `spec` ← `svc:spec` + `svc:specs` (dispatch per the design, `--from-plan`); `plan`, `build`, `verify`, `ship`, `release` ← `svc`; `fix` ← `svc:quick-task` (the fix-bug pipeline is not carried over; bugs use the same pipeline); `check` ← `shared:check-quality`.
- Move `plugins/svc/references/*` to `plugins/component/references/` (`quick-task-on-main.md` → `fix-on-main.md`) and update every `${CLAUDE_PLUGIN_ROOT}/references/…` path.
- Every cplat call in 5.0 form (`cplat component ship|build`, `cplat platform runs`, `cplat instance verify`); agents keep their `svc:`/`shared:`/shape-plugin names.

**Done when:** the AC-114.59, AC-114.62–AC-114.64 acceptance tests for the component plugin pass.

## t24 — plugins api, resource, instance, issue, platform

**Files:** plugins/{api,resource,instance,issue,platform}/** (plugin.json 1.0.0, README, commands)
**Covers:** AC-114.28, AC-114.30, AC-114.31, AC-114.36, AC-114.59, AC-114.61
**Goal:** the remaining noun commands.

**Implementation notes:**
- `api:list` → `cplat api list`; `resource:add|remove` ← `gitops:addon` (postgres only; observability answer from the design); `instance:promote` ← `gitops:promote` (`--to`, production gate kept), `instance:secret` ← `gitops:secret` (`set <component>/<env>`, `list`), `instance:verify` → `cplat instance verify [<env>]`; `issue:triage` ← `shared:triage`, `issue:report` ← `shared:report-issue`; `platform:doctor|update|fleet` ← `shared` (`update` explains `--migrate`), `platform:runs` → `cplat platform runs report …`, `platform:retro` → `cplat platform retro …`.
- The closing "report a platform issue" line of every command names `/issue:report`.

**Done when:** the AC-114.59 acceptance test lists these commands and the usage-line tests of AC-114.28, AC-114.30, AC-114.31, AC-114.36, AC-114.61 pass.

## t25 — tombstones

**Files:** scripts/tombstones.py, scripts/ci-local.sh, the 27 command files of svc/app/gitops/shared, plugins/gitops/agents/deployment.md and plugins/gitops/hooks/hooks.json (deleted)
**Covers:** AC-114.27, AC-114.59, AC-114.65, AC-114.66
**Goal:** every 4.7 command answers with one line and runs nothing.

**Implementation notes:**
- `scripts/tombstones.py`: `MOVED` (27 entries, AC-114.65 targets), `write`, `check`; the file format of the design.
- Run `write`; delete the gitops `deployment` agent and the gitops hooks; `app` keeps only tombstones.
- `ci-local.sh`: run `python3 scripts/tombstones.py check` in the plugins step.

**Done when:** the AC-114.27, AC-114.65 and AC-114.66 acceptance tests pass and `tombstones.py check` exits 0.

## t26 — versions, plugin READMEs, shape registry

**Files:** .claude-plugin/marketplace.json, seven plugin.json files, READMEs of svc/shared/app/gitops, shapes.yml, scripts/shapes.py
**Covers:** AC-114.50, AC-114.55, AC-114.66
**Goal:** the 5.0 marketplace validates and the shape check knows the noun plugins.

**Implementation notes:**
- Marketplace: the seven noun plugins at 1.0.0 with descriptions; `svc` 4.0.0, `shared` 1.0.0, `app` 2.0.0, `gitops` 2.0.0 ("tombstones only; leaves the marketplace in 6.0"), `web`, `svc-go`, `svc-java` 0.4.0; each plugin.json equals its entry.
- READMEs: `svc` (agents and skills; commands moved), `shared` (launcher, hooks, quality/security), `app`/`gitops` (tombstones, removal in 6.0).
- `shapes.yml`: `gitops-app.plugin: system`. `shapes.py`: spec-first rule names `/system:spec` (gitops-app) or `/component:spec`; the gitops special case becomes `system`.

**Done when:** `bash scripts/ci-local.sh`'s manifest step passes and the AC-114.50 and AC-114.55 acceptance tests pass (AC-114.55 together with t28).

## t27 — agent prompts and skills

**Files:** plugins/svc/agents/*, plugins/svc/skills/spec-format/**, plugins/shared/agents/*, plugins/{web,svc-go,svc-java}/agents/* and READMEs
**Covers:** AC-114.52
**Goal:** agents speak the model: System, Component, API, Resource, Environment, Instance; 5.0 commands; `system.yaml`.

**Implementation notes:**
- Replace 4.x commands with 5.0 commands, `services.yaml`/`app.yaml` with `system.yaml` (`components.<c>`, `instances.<env>`, `environments.<env>`), product/app/addon/service with the model noun wherever they name one (a "service" component type stays `service`).
- Keep every rule and output format of the prompts; the architect's re-plan section names `/component:build`.

**Done when:** the AC-114.52 test finds no hit in these files.

## t28 — templates' docs

**Files:** CLAUDE.md, README and docs/specs/README.md (plus docs/backlog.md where present) of the six templates
**Covers:** AC-114.52, AC-114.55
**Goal:** a generated repo explains itself in 5.0 words.

**Implementation notes:**
- gitops-app `CLAUDE.md.jinja`: the tree shows `system.yaml` (only hand-edited file), commands table in 5.0 forms, alerts and promotion sections on `environments.<env>`; "Spec first" names `/system:spec`.
- Component templates: "Spec first" names `/component:spec`; the plugin lists name the noun plugins; `/platform:update` for updates.

**Done when:** `python scripts/shapes.py check` passes and the AC-114.52/AC-114.55 tests find no hit in these files.

## t29 — DOMAIN-MODEL and ADOPTING

**Files:** docs/DOMAIN-MODEL.md, docs/ADOPTING.md
**Covers:** AC-114.52, AC-114.54, AC-114.71
**Goal:** the guide documents the shipped 5.0 model.

**Implementation notes:**
- Status: 5.0 is current; the `system.yaml` sketch becomes the final schema (key table, semantics) and a full example: instance keys as environments (a component in dev, staging and prod lists all three), database `replicas`, website `lang: typescript`, required `owner`.
- Command tables: 5.0 verbs; `api` has `list` only, `check` marked "coming with spec 110"; `component check`; `component fix` = the quick-task pipeline. The 4.x mapping tables stay as history.
- ADOPTING: "Migrating from 4.x to 5.0" (update plugins, `cplat platform update --migrate` or `/platform:fleet update`, what the proof checks, unconvertible keys and how to fix them, the plugin switch).

**Done when:** the AC-114.54 and AC-114.71 acceptance tests pass.

## t30 — guides

**Files:** docs/USER-JOURNEY.md, docs/HOW-IT-WORKS.md, docs/AGENTS.md, docs/ARCHITECTURE.md
**Covers:** AC-114.52
**Goal:** the main guides in 5.0 words and commands; `AGENTS.md` names the planner as `system:planner` and the noun plugins.

**Done when:** the AC-114.52 test finds no hit in these files and `site` link sync stays clean.

## t31 — remaining docs

**Files:** docs/unattended-delivery.md, docs/agent-deck.md, docs/BASELINES.md, docs/templates.md, docs/self-hosted-runners.md, README.md, CONTRIBUTING.md, CLAUDE.md
**Covers:** AC-114.52
**Goal:** as t30; `CLAUDE.md`'s "Add an agent" and layout name the 5.0 plugins (`/component:spec` for platform changes).

**Done when:** the AC-114.52 test finds no hit in these files.

## t32 — plans, requirements, spikes, diagrams

**Files:** docs/plan/*.md (three), docs/requirements/*.md (two), docs/spikes/kro.md, docs/img/sdlc-map.svg, docs/img/model-lifecycles.svg
**Covers:** AC-114.52
**Goal:** as t30; the PRD's shape table row for gitops-app names the `system` plugin so `shapes.py check` passes. `model-today.svg` stays (the 4.7 model).

**Done when:** the AC-114.52 test finds no hit and `python scripts/shapes.py check` passes.

## t33 — site reference and concept pages

**Files:** site/scripts/generate-reference.mjs, site/src/content/docs/concepts/*.md (eight), site/src/content/docs/get-started/*.md (two)
**Covers:** AC-114.52, AC-114.53
**Goal:** the generated command reference is grouped by noun; concept pages use the model.

**Implementation notes:**
- Commands: sections in the design's noun order, rows `/noun:verb`, summary, usage; files with `moved-to` skipped; plugins without working commands left out.
- Configuration page: "`system.yaml`" title, description and intro (from `render.py`'s docstring). cplat page: subcommand list from the noun lines.
- Page file names stay (URLs stable); titles and text use Resource/Environment where they said addon.

**Done when:** `node site/scripts/generate-reference.mjs` writes the grouped page and the AC-114.53 test passes.

## t34 — site scenarios and landing pages

**Files:** the thirteen site pages listed
**Covers:** AC-114.52
**Goal:** as t30 for the site.

**Done when:** the AC-114.52 test finds no hit in these files.

## t35 — CHANGELOG and ADR index

**Files:** docs/CHANGELOG.md, docs/adr/README.md
**Covers:** AC-114.50, AC-114.51, AC-114.66
**Goal:** the 5.0.0 section a user migrates from.

**Implementation notes:**
- `## [5.0.0]` marked **BREAKING**: an old → new table with a row for each of the 27 slash commands (the `tombstones.MOVED` targets), each regrouped cplat subcommand, `app.yaml`, `services.yaml` and every converted key of the design's table; then the migration steps (update plugins, `cplat platform update --migrate` or `/platform:fleet update`); plugin versions; `app` and `gitops` leave the marketplace in 6.0.
- ADR index row for 054.

**Done when:** the AC-114.51 acceptance test passes and `core.platform_version()` reads `5.0.0`.

## t36 — e2e cluster test on 5.0

**Files:** tests/e2e/run.sh
**Covers:** AC-114.56
**Goal:** the cluster test uses only 5.0 command names and a `system.yaml`.

**Implementation notes:**
- `cplat system new <manifest> --no-github` (system, owner, e2e-api `service/java`, e2e-web `website/typescript`); `cplat resource add postgres`; observability and `policy: enforce` for dev written into `system.yaml`; components described with `compose.build_entry` into `components:`.
- Ship a spec as the design describes (spec new/approve, `cplat component ship start`, build/apply, `cplat instance verify dev --base-url`, `cplat instance promote e2e-api --to staging --sha … --no-verify`, staging render/apply, `cplat instance verify staging --base-url`, `cplat component ship finish`); `cplat instance secret set e2e-api/dev …`.

**Done when:** a grep of `run.sh` finds no 4.x name, the AC-114.56 test passes, and the script runs green on a machine with docker and k3d.

## t37 — port the tests that build 4.x gitops-app files

**Files:** the 23 test files listed
**Covers:** AC-114.69
**Goal:** the existing behaviour tests describe the same behaviour on `system.yaml`.

**Implementation notes:**
- `model_fixtures.py` writes `system.yaml` (owner, environments, components with `type`/`lang`/`instances`); spec-113 tests assert schema 2 and the 5.0 words; caller tests use the 5.0 entry points.
- Assertions on 4.x error texts and `services.yaml`/`app.yaml` contents move to their 5.0 equivalents; nothing tested before is dropped without an equivalent.

**Done when:** these files pass.

## t38 — port the tests that use 4.x names; everything green

**Files:** the 43 test files listed
**Covers:** AC-114.50, AC-114.52
**Goal:** the whole suite and `scripts/ci-local.sh` are green on 5.0.

**Implementation notes:**
- `--gitops`/`--web`/`--library`/`--type <shape>` argv in fixtures → hidden `--shape <id>` (or `--type/--lang`); `cplat.main(["status"…])` → `["system", "status", …]` and the other moved names; plugin paths `plugins/svc/commands/*` → `plugins/component/commands/*`, `plugins/app/…` → `plugins/system/…`, references to `plugins/component/references/`.
- Fix any remaining red test in the suite the same way (list it in the task's report).

**Done when:** `uv run --with pytest --with pytest-xdist --with pyyaml --with ruamel.yaml pytest tests/cplat -q -n auto` and `bash scripts/ci-local.sh` both pass.
