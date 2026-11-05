---
spec_id: 145-smoke-tests-that-write-run-only-in-dev
shape: platform
spec_hash: dcfacaf8496b
summary: "smoke.py passes SMOKE_ENV and SMOKE_READ_ONLY (1 outside dev) to devbox run smoke, turns a read-only run that checked nothing into not-run, records it and adds read_only to the section; each deployable template's smoke.sh leaves out the writing tests (pytest marker, JUnit tag, Go name, Playwright tag) and its CLAUDE.md documents the rule; tester agents, testing reference, /instance:verify, ADR-040 and the changelog fragment"
tasks:
  - id: t1
    title: cplat smoke read-only mode (env vars, not-run without a read-only test, record, section field) and its tests
    files: [scripts/cplat/smoke.py, tests/cplat/test_smoke_474_read_only.py, tests/cplat/test_deploy_checks.py, tests/cplat/test_smoke_091_ship.py]
    covers: [AC-145.1, AC-145.2, AC-145.3, AC-145.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: the templates' smoke harness leaves out writing tests when read-only; CLAUDE.md Smoke tests sections; read-only sample smoke tests
    files: [templates/service-python/scripts/smoke.sh, templates/service-python/scripts/smoke_pytest.py, templates/service-python/CLAUDE.md, templates/service-python/tests/test_smoke_health.py, templates/service-python/tests/test_smoke_metrics.py, templates/service-java/scripts/smoke.sh, templates/service-java/CLAUDE.md.jinja, "templates/service-java/src/test/java/{{ package_path }}/SmokeHealthTest.java.jinja", templates/service-go/scripts/smoke.sh, templates/service-go/CLAUDE.md.jinja, templates/service-go/internal/server/smoke_test.go, templates/web-nextjs/scripts/smoke.sh, templates/web-nextjs/CLAUDE.md.jinja, templates/web-nextjs/e2e/smoke.spec.ts.jinja]
    covers: [AC-145.5, AC-145.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: tester agents, spec-format testing reference, /instance:verify, ADR-040 amendment, plugin versions, changelog fragment
    files: [plugins/svc/agents/tester.md, plugins/svc-java/agents/tester.md, plugins/svc-go/agents/tester.md, plugins/web/agents/tester.md, plugins/svc/skills/spec-format/references/testing.md, plugins/instance/commands/verify.md, docs/adr/040-smoke-tests-against-a-deployed-environment.md, .claude-plugin/marketplace.json, docs/changelog.d/474-smoke-read-only-outside-dev.fixed.md]
    covers: [AC-145.7]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 145 Smoke tests that write run only in dev

Built as the fix of #474; the three tasks are independent. The read-only decision is cplat's (`read_only(env)`: everything
but dev), the exclusion is each template's harness, so a repo gets it through `/platform:update` and marks its own tests.
