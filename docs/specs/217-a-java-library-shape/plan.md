---
spec_id: 217-a-java-library-shape
shape: platform
spec_hash: fb8ad32bb2fd
summary: "A library-java template (Maven jar, publish.sh to GitHub Packages on the tag), its registry entry, detection, the svc-java release agent's no-version-file case and every shape-wide list and CI job"
tasks:
  - id: t1
    title: "Acceptance tests for every criterion"
    files: [tests/cplat/test_217_library_java.py]
    covers: [AC-217.1, AC-217.2, AC-217.3, AC-217.4, AC-217.5, AC-217.6, AC-217.7, AC-217.8, AC-217.9, AC-217.10, AC-217.11]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: "The library-java template and its publish script"
    files: [templates/library-java/]
    covers: [AC-217.3, AC-217.4, AC-217.5, AC-217.6, AC-217.7, AC-217.8, AC-217.9]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: "Registry entry, PRD row, detection and the shape-wide lists"
    files: [shapes.yml, docs/requirements/platform-vision.md, scripts/detect-shape.sh, scripts/test-detect-shape.sh, scripts/cplat/newsvc.py, scripts/cplat/deps_parse.py, scripts/cplat/buildtests.py, scripts/bump_template_pins.py, scripts/sync-template-copies.py, scripts/template-lint.py, scripts/ci-local.sh, templates/gitops-app/scripts/render.py, templates/gitops-app/scripts/plan.py, templates/cluster-gitops/scripts/system_render.py, .github/dependabot.yml, tests/cplat/]
    covers: [AC-217.1, AC-217.2, AC-217.10]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: "Platform CI smoke job, devbox smoke script, svc-java agents and docs"
    files: [.github/workflows/ci.yml, devbox.json, plugins/svc-java/, plugins/system/commands/new.md, .claude-plugin/marketplace.json, plugins/system/.claude-plugin/plugin.json, docs/templates.md, docs/AGENTS.md, docs/ADOPTING.md, docs/ARCHITECTURE.md, docs/USER-JOURNEY.md, CLAUDE.md, site/src/content/docs/concepts/shapes.md, docs/changelog.d/]
    covers: [AC-217.10, AC-217.11]
    parallel_safe: false
    depends_on: [t3]
    done: true
---

# Plan — 217 A Java library shape

See [design.md](design.md). One PR: tests first (t1), then the template (t2), the registry and lists (t3), CI, agents and docs (t4).
