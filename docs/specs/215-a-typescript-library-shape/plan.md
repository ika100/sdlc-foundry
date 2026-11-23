---
spec_id: 215-a-typescript-library-shape
shape: platform
spec_hash: dba34ea0d086
summary: "A library-typescript template (ESM npm package, publish.sh to GitHub Packages on the tag), its registry entry, detection, the svc-ts release agent's no-version-file case and every shape-wide list and CI job"
tasks:
  - id: t1
    title: "Acceptance tests for every criterion"
    files: [tests/cplat/test_215_library_typescript.py]
    covers: [AC-215.1, AC-215.2, AC-215.3, AC-215.4, AC-215.5, AC-215.6, AC-215.7, AC-215.8, AC-215.9, AC-215.10, AC-215.11]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: "The library-typescript template and its publish script"
    files: [templates/library-typescript/]
    covers: [AC-215.3, AC-215.4, AC-215.5, AC-215.6, AC-215.7, AC-215.8, AC-215.9]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: "Registry entry, PRD row, detection and the shape-wide lists"
    files: [shapes.yml, docs/requirements/platform-vision.md, scripts/detect-shape.sh, scripts/test-detect-shape.sh, scripts/cplat/newsvc.py, scripts/cplat/deps_parse.py, scripts/cplat/buildtests.py, scripts/bump_template_pins.py, scripts/sync-template-copies.py, scripts/template-lint.py, scripts/ci-local.sh, templates/gitops-app/scripts/render.py, templates/gitops-app/scripts/plan.py, templates/cluster-gitops/scripts/system_render.py, .github/dependabot.yml, tests/cplat/system_fixtures.py, tests/cplat/test_template_allowlists.py]
    covers: [AC-215.1, AC-215.2, AC-215.10]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: "Platform CI smoke job, devbox smoke script, svc-ts release agent and docs"
    files: [.github/workflows/ci.yml, devbox.json, plugins/svc-ts/, plugins/system/commands/new.md, .claude-plugin/marketplace.json, plugins/system/.claude-plugin/plugin.json, docs/templates.md, docs/AGENTS.md, docs/ADOPTING.md, docs/ARCHITECTURE.md, docs/USER-JOURNEY.md, CLAUDE.md, site/src/content/docs/concepts/shapes.md, docs/changelog.d/]
    covers: [AC-215.10, AC-215.11]
    parallel_safe: false
    depends_on: [t3]
    done: true
---

# Plan — 215 A TypeScript library shape

See [design.md](design.md). One PR: tests first (t1), then the template (t2), the registry and lists (t3), CI, agent and docs (t4).
