---
spec_id: 219-website-specs-get-a-ux-design-step
shape: platform
spec_hash: f7a9fcf5f6ac
summary: "cplat decides and checks the UX step (registry flag, routing, spec ux, ux.md check); a web ux-designer agent; plan, ship, build and reviewer prompts use it; docs"
tasks:
  - id: t1
    title: "Acceptance tests for every criterion"
    files: [tests/cplat/test_219_ux_design.py]
    covers: [AC-219.1, AC-219.2, AC-219.3, AC-219.4, AC-219.5, AC-219.6, AC-219.7, AC-219.8, AC-219.9, AC-219.10, AC-219.11]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: "Registry flag, routing, cplat spec ux and the ux.md check"
    files: [shapes.yml, scripts/shapes.py, scripts/cplat/shapecmd.py, scripts/cplat/spec_ux.py, scripts/cplat/spec.py, scripts/cplat/stages.py]
    covers: [AC-219.1, AC-219.2, AC-219.3, AC-219.4, AC-219.5, AC-219.6, AC-219.7]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: "The ux-designer agent, the plan, ship, build and reviewer prompts, register entries and docs"
    files: [plugins/web/, plugins/component/, plugins/svc/, docs/rules/, .claude-plugin/marketplace.json, docs/AGENTS.md, docs/adr/, docs/changelog.d/]
    covers: [AC-219.8, AC-219.9, AC-219.10, AC-219.11]
    parallel_safe: false
    depends_on: [t2]
    done: true
---

# Plan — 219 Website specs get a UX design step

See [design.md](design.md). One PR: tests first (t1), then the cplat side (t2), then the agent, prompts and docs (t3).
