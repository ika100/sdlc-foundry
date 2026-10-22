---
spec_id: 081-gates-that-can-fail
title: 'Gates that can fail: pinned tools and a doctor check'
status: done
priority: P1
tracks: [120, 123, 126]
---

# 081 — Gates that can fail: pinned tools and a doctor check

## Problem

- A gate can pass while checking nothing: stock-manager-gitops's baseline had no heuristic filters for weeks (#120).
- Gate tools other than the scanners are still `@latest`, so CI can turn red with no code change (#123).
- An adopted repo's CI can lack template gates, and nobody is told: stock-manager has no security job (#126).

## Stories

As a maintainer, I want every gate to be pinned and checked for being real, so that green means checked.

## Acceptance criteria

- **AC-081.1** Given any template, when its devbox.json is read, then every gate tool (linters, type checkers, auditors, scanners) is pinned to a version, and `bump_template_pins.py` bumps those pins (minor/patch) in its weekly PR.
- **AC-081.2** Given `cplat doctor` in a platform repo, when it runs, then a gates section checks that: the secrets baseline has `is_line_allowlisted` and no gibberish filter; detect-secrets is pinned; `ci` and `secrets-baseline` exist; `ci` chains the `devbox run` gates of `.github/workflows/ci.yml`. Each failed check names its fix.
- **AC-081.3** Given `cplat adopt` or `cplat doctor`, when the repo's CI has no job running a template gate (quality, test, security), then it lists the missing gate and the template job to copy, and changes nothing.

## Non-goals

- Pinning git or gh.

## Open questions

None.

## Changelog

- 2026-10-22 created from #120, #123, #126
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
