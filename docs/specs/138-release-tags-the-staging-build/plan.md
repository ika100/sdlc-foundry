---
spec_id: 138-release-tags-the-staging-build
shape: platform
spec_hash: 4d3558f8c857
summary: "New scripts/cplat/comprelease.py (`cplat component release target`) decides the commit to tag (staging's sha-<40> pin, or main's head without staging), refuses with the staging and candidate commits and the next step, computes the version and the next development version; /component:release tags that commit after main's ci run and lets the release agents write the CHANGELOG and the next development version in a follow-up PR; library-python reads its version from the git tag, service-python reads it from the package metadata"
tasks:
  - id: t1
    title: "comprelease.py: target (staging or main's head), refusals, next version, next development version per template; `component release` in cplat.py"
    files: [scripts/cplat/comprelease.py, scripts/cplat/cplat.py]
    covers: [AC-138.1, AC-138.2, AC-138.3, AC-138.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "/component:release: target phase, gates on the tagged commit, tag after main's ci run, follow-up PR, summary naming the tagged commit; console glossary"
    files: [plugins/component/commands/release.md, scripts/cplat/console/glossary.py, plugins/component/README.md, docs/AGENTS.md, docs/USER-JOURNEY.md, site/src/content/docs/scenarios/promote-safely.md, tests/cplat/test_platrelease_129_docs.py]
    covers: [AC-138.1, AC-138.2, AC-138.3, AC-138.4, AC-138.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: "Release agents (svc, svc-java, svc-go, web) write the follow-up PR from main: CHANGELOG and next development version, never tag"
    files: [plugins/svc/agents/release.md, plugins/svc-java/agents/release.md, plugins/svc-go/agents/release.md, plugins/web/agents/release.md]
    covers: [AC-138.4]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: "Templates: library-python reads its version from the git tag (hatch-vcs); service-python reads it from the package metadata"
    files: [templates/library-python/pyproject.toml, "templates/library-python/src/{{ module_name }}/__init__.py", templates/library-python/tests/test_smoke.py, "templates/service-python/src/{{ module_name }}/__init__.py", "templates/service-python/src/{{ module_name }}/main.py"]
    covers: [AC-138.5, AC-138.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: "Plugin versions (component, svc, svc-java, svc-go, web) in plugin.json and marketplace.json; changelog fragment"
    files: [.claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, plugins/svc-java/.claude-plugin/plugin.json, plugins/svc-go/.claude-plugin/plugin.json, plugins/web/.claude-plugin/plugin.json, docs/changelog.d/138-release-tags-the-staging-build.changed.md]
    covers: [AC-138.7]
    parallel_safe: false
    depends_on: [t2, t3, t4]
    done: true
---

# Plan — 138 A component release tags the build staging tested

Contract: [design.md](design.md). The acceptance tests (`tests/cplat/test_release_target_138.py`) are written before t1
starts and fail first; no task edits them.

| Level | Task | Covers | Parallel | Files |
|---|---|---|---|---|
| 0 | t1 comprelease.py | AC-138.1–4 | yes | `scripts/cplat/comprelease.py`, `cplat.py` |
| 0 | t4 templates | AC-138.5, AC-138.6 | yes | library-python, service-python |
| 1 | t2 release command | AC-138.1–4, AC-138.7 | yes | `plugins/component/commands/release.md` |
| 1 | t3 release agents | AC-138.4 | yes | four `agents/release.md` |
| 2 | t5 versions, fragment | AC-138.7 | no | manifests, `docs/changelog.d/` |
