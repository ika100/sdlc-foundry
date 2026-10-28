---
spec_id: 127-the-cache-url-names-its-user-and-ci-pins
title: the cache URL names its user and CI pins its test tools
status: approved
priority: P2
shape: platform
---

# 127 — the cache URL names its user and CI pins its test tools

## Problem

Two loose ends from the 5.x resources round, decided by the user on 2026-10-28.

**The cache URL.** Spec 118 gives a component that uses a cache `REDIS_URL` as `redis://:<password>@<host>:6379/0`. Client libraries read the empty user as "no user" and authenticate as `default`, but `valkey-cli -u` and `redis-cli -u` read it as the user `""` and fail `AUTH`; both e2e scripts rewrite the URL before probing with the CLI. The password belongs to the ACL user `default`, so naming it costs nothing and works everywhere.

**Unpinned test tools.** The cplat suite runs with `uv run --with pytest --with pytest-xdist --with pyyaml --with ruamel.yaml` in CI, `scripts/ci-local.sh` and `devbox run test-fast`, so every run takes the newest release. During spec 118, pytest 9.2.0 was released mid-run and broke the shard-coverage check, which cost a full rerun. Spec 121 pins everything the platform runs; the platform's own test tools should be pinned too, and move only through a PR that passes CI.

## Stories

- As a component developer, I want `REDIS_URL` to work unchanged with every Redis client and CLI, so that I never rewrite it.
- As the platform maintainer, I want CI to run the same test tools until a reviewed PR moves them, so that a third-party release cannot turn CI red mid-run.

## Acceptance criteria

### The cache URL
- **AC-127.1** Given a component whose `uses` lists a cache resource `<name>`, when it is rendered in an environment, then the key `url` of the Secret `<system>-<name>-app` is `redis://default:<password>@<host>:6379/0` (amends the URL form of AC-118.18; the variables, keys and Secret name stay as spec 118 defines them).
- **AC-127.2** Given a system whose cache Secret template still has the 5.3 form, when `/platform:update` re-renders it, then the change list names the new `url` form and that running pods take it on their next restart; the old and new form authenticate as the same user, so no component fails in between.
- **AC-127.3** Given the e2e cluster test, when it probes a cache with `valkey-cli -u "$<NAME>_REDIS_URL"`, then the probe uses the component's variable unchanged (the rewrite to `redis://default:` is removed from `tests/e2e/run.sh`; `tests/e2e/upgrade.sh` keeps it only for a cache created by the previous release).

### Pinned test tools
- **AC-127.4** Given the repository, then `requirements-test.txt` at the root pins every package the cplat suite needs (pytest, pytest-xdist, pyyaml, ruamel.yaml and each of their dependencies) to an exact version, compiled from `requirements-test.in` by `uv pip compile`.
- **AC-127.5** Given the cplat test step of `.github/workflows/ci.yml`, `scripts/ci-local.sh` and the `test-fast` script of `devbox.json`, when they run the suite, then they install the tools only from `requirements-test.txt` (`uv run --with-requirements requirements-test.txt …`); a check in CI fails when any of them installs pytest, pytest-xdist, pyyaml or ruamel.yaml without that file.
- **AC-127.6** Given `.github/dependabot.yml`, then a `pip` entry for `/` updates `requirements-test.txt` monthly in one grouped PR, which runs the full CI like any other PR.

## Non-goals

- Pinning the test tools of the templates (generated repos lock theirs with `uv.lock`).
- Changing `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` or the broker's URLs.
- Moving any e2e step to the nightly run (the user decided to keep the resource steps on PRs).

## Open questions

- ~~REDIS_URL form~~ — `redis://default:` (user, 2026-10-28).
- ~~Pin pytest in CI~~ — pin, with Dependabot bump PRs (user, 2026-10-28).

## Changelog

- 2026-10-28 created
- 2026-10-28 approved
