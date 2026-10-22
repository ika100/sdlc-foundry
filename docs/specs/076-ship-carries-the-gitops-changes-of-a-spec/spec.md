---
spec_id: 076-ship-carries-the-gitops-changes-of-a-spec
title: Ship carries the gitops changes of a spec
status: approved
priority: P1
tracks: [106]
---

# 076 — Ship carries the gitops changes of a spec

## Problem

In the ai-ops spec 011 run (2026-10-22) design.md listed three gitops follow-ups, but nothing executed them: `ship deploy` finished once the pin merged. The Component PR opened 64 minutes later, and the new CRD (fields and a namespace removed) broke `ai-ops-config` (`namespaces "ai-ops-build" not found`), which nobody watched because deploy only waits for `<service>-dev`.

## Stories

As the orchestrator of a ship run, I want the spec's gitops changes planned as tasks, opened as PRs during the build and merged in order around the deploy, so that a service change and its gitops change land together and a broken sync is caught by the run.

## Acceptance criteria

- **AC-076.1** Given a plan task with `repo: <owner>/<gitops-repo>`, when `cplat spec check` runs, then it requires `order: before-merge | after-release` and a non-empty `files` list, and rejects a repo that `.platform-app.yml` does not list.
- **AC-076.2** Given a ship run whose plan has gitops tasks, when the orchestrator calls `cplat ship gitops prepare <task>`, then it gets a checkout of that repo on branch `spec/<spec_id>-<task>`, and `cplat ship gitops pr <task> --title T --body-file F` pushes it and opens (or reuses) a draft PR recorded in the run's state.
- **AC-076.3** Given `before-merge` gitops PRs, when `cplat ship land` finds the service PR green, then it marks each ready, waits for its checks (spec 072) and merges them in plan order before the service PR; a red or missing one merges nothing.
- **AC-076.4** Given `after-release` gitops PRs, when `cplat ship deploy` sees the pin merged, then it merges them in plan order after their checks pass and, with `--context`, waits for Synced/Healthy of `<service>-dev` and every app the gitops tasks name (`apps:`); a SyncError or Degraded app stops the deploy with its message.
- **AC-076.5** Given a plan with `human_steps`, when the deploy finishes, then its output ends with them as a checklist.
- **AC-076.6** Given the architect agent and `/svc:plan`, when a spec changes the gitops side, then they plan it as gitops tasks, and removing CRD fields is planned in two releases (expand/contract).

## Non-goals

- Validating Components against the CRD and chart from the service branch in gitops CI (follow-up issue).
- Gitops tasks outside a ship run (`/svc:build` alone keeps asking for gitops changes in its report).

## Open questions

None.

## References

- Issue #106, [Spec 067](../067-ship-an-approved-spec-to-dev/spec.md), [Spec 072](../072-ship-land-fails-fast-and-heals-stuck-checks/spec.md)

## Changelog

- 2026-10-22 created from issue #106
- 2026-10-22 approved
