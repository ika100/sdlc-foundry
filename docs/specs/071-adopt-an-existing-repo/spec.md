---
spec_id: 071-adopt-an-existing-repo
title: Adopt an existing repo
status: done
priority: P2
---

# 071 — Adopt an existing repo

## Problem

A repo not created from a template has no `.copier-answers.yml`, so `/shared:update-service` refuses it, `cplat shape` sniffs, and it lacks the generated `CLAUDE.md`, permission allowlist, devbox recipes and spec scaffolding the pipeline needs. stock-manager is such a repo. Adopting it today means writing the answers file by hand (docs/ADOPTING.md, Step 5) and then letting update-service overwrite its CI and Dockerfile.

## Stories

As a founder, I want to bring an existing repo onto the platform without losing its own files, so that the spec-driven pipeline and template updates work there.

## Acceptance criteria

- **AC-071.1** Given `cplat adopt --type <shape>` in a clean repo without `.copier-answers.yml`, when it runs, then it renders the shape's template and adds only files the repo does not have (CLAUDE.md, `.claude/settings.json`, docs scaffolding …), never the template's starter code or tests, and commits once on `chore/adopt-platform`.
- **AC-071.2** Given files that exist, when adopt runs, then none is overwritten: `devbox.json` keeps the repo's recipes and gets the template's missing ones, `.gitignore` gets the missing lines, and every other file that differs is listed.
- **AC-071.3** Given an adopted repo, when the platform looks at it, then `.copier-answers.yml` records the shape's template and answers taken from the repo (name and org from `origin`, description from the README, `--data` overrides), `.platform-version` is stamped, and `cplat shape` and `/shared:update-service` accept it.
- **AC-071.4** Given `--dry-run`, an unknown shape or an existing `.copier-answers.yml`, when adopt runs, then it changes nothing (and names update-service in the last case).

## Non-goals

- Restructuring the repo's code to the template's layout.

## Open questions

None.

## References

- [Review of stock-manager, stock-manager-gitops and ai-ops](../../e2e/2026-10-22-review-unattended-delivery.md)
- [ADR-028](../../adr/028-unattended-delivery-without-branch-protection.md)

## Changelog

- 2026-10-22 created from the review of the three lan repos
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
