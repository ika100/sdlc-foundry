---
spec_id: 145-smoke-tests-that-write-run-only-in-dev
title: Smoke tests that write run only in dev
status: done
priority: P1
shape: platform
tracks: [474]
---

# 145 — Smoke tests that write run only in dev

## Problem

The components' smoke tests run in dev, staging and prod: after every deploy and on `/instance:verify <env>`. Tests that
create data (for example tasks) never remove it, so prod's task list shows `smoke-…` tasks next to the real ones, and every
run adds more; a component without a delete endpoint cannot even remove them (#474, journey 2 of 2026-11-05). The user
decided: smoke tests that write run only in dev; staging and prod run read-only smoke checks, with no cleanup mechanism.

## Stories

- As the owner of a system, I want staging and prod smoke checks that never create or change data, so that prod data holds
  only real data.
- As the owner of a component, I want a smoke run outside dev that checked nothing to say so, so that a green result always
  means something was verified.

**Repos:** sdlc-foundry (cplat `instance verify`, ship deploy, staging smoke and resource upgrade verify; the service-python,
service-java, service-go and web-nextjs templates; the tester agents).

## Acceptance criteria

- **AC-145.1** Given any smoke run cplat starts (ship deploy in dev, the staging smoke, `cplat instance verify <env>`, the
  resource upgrade verify), when it runs `devbox run smoke`, then the recipe gets `SMOKE_ENV=<env>` and `SMOKE_READ_ONLY=1`
  outside dev, `SMOKE_READ_ONLY=0` in dev (also when the caller's shell set it).
- **AC-145.2** Given a smoke run outside dev in which at least one test passed and none failed, then it passes as before, its
  output has the line `read-only (<env>): smoke tests marked as writing data are not run outside dev`, and its record section
  has `read_only: true` (`false` in dev).
- **AC-145.3** Given a smoke run outside dev in which no test passed and none failed (every smoke test writes, or there is
  none), then its outcome is `not-run` (never passed) with the reason `no read-only smoke test ran in <env>: smoke tests that
  write data run only in dev (<n> skipped); add a read-only smoke check …`, the `(smoke)` criteria stay unchecked, and
  `cplat instance verify <env>` exits 3. In dev such a run still passes as before.
- **AC-145.4** Given `cplat instance verify <env>` without `--base-url`, when the recipe ran and the outcome is the `not-run`
  of AC-145.3, then the run is recorded as a `verify` record (#422) with its smoke section, so the prod evidence shows why
  staging checked nothing.
- **AC-145.5** Given a repo of each deployable shape, generated or updated with `/platform:update`, when `devbox run smoke`
  runs with `SMOKE_READ_ONLY=1`, then the smoke tests marked as writing are left out: `@pytest.mark.writes` (service-python,
  skipped with a reason), `@Tag("writes")` (service-java), the name `TestSmokeWrites<Name>` (service-go), `@writes` in the
  title or tags (web-nextjs); without it they run. The `writes` marker is registered for `test` and `ci` too.
- **AC-145.6** Given a freshly generated repo of each deployable shape, then its CLAUDE.md has a "Smoke tests" section naming
  `SMOKE_ENV`, `SMOKE_READ_ONLY=1`, the shape's writing mark, the rule to keep a read-only smoke check, and the not-run outcome;
  and its sample smoke test is read-only (it does not carry the mark) and names the mark.
- **AC-145.7** Given the tester agents of every deployable shape and the spec-format testing reference, then they say that a
  smoke test that creates, changes or deletes data must carry the shape's writing mark, that smoke runs read-only outside dev,
  and that read-only checks must exist so staging and prod still verify something.

## Non-goals

- No cleanup of smoke data: nothing removes what smoke tests wrote, and smoke data already in staging or prod stays until
  someone removes it.
- No scratch store or header that routes smoke writes elsewhere.
- No change to the tests a repo owns (`tests/`, `src/test/`, `internal/`, `e2e/`): an existing repo marks its writing smoke
  tests itself.

## Open questions

None.

## Changelog

- 2026-11-05 drafted from #474 with the user's decision (writes only in dev, read-only elsewhere, no cleanup).
- 2026-11-05 approved
- 2026-11-05 building
- 2026-11-05 done
