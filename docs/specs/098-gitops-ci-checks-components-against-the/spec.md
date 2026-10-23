---
spec_id: 098-gitops-ci-checks-components-against-the
title: Gitops CI checks Components against the service branch CRDs
status: draft
priority: P1
tracks: [110]
---

# 098 — Gitops CI checks Components against the service branch CRDs

## Problem

`/svc:ship` opens gitops changes as draft PRs and merges them in plan order (spec 076), but gitops CI validates custom resources (Components) only against the public CRD schema catalog and skips kinds it does not know. A Component written for a CRD that the service branch adds or changes is therefore never checked against that CRD, and the gitops change and its service change can land in a broken combination. This broke `ai-ops-config` during ai-ops spec 011 (`namespaces "ai-ops-build" not found`; issue #110). Spec 097 ships whole products unattended and needs this check first, so this spec ships before 097.

## Stories

As a founder, I want gitops CI to check a Component against the CRD from the service branch it belongs to, so that a gitops change and its service change cannot land in a broken combination.
**Repos:** the gitops-app repo; the service repo that ships the CRD.

As a founder, I want `cplat doctor` to tell me when the gitops-app cannot read its service repos, so that I add the access before the first gitops PR fails on it.
**Repos:** the gitops-app repo.

## Acceptance criteria

- **AC-098.1** Given a gitops PR opened by `cplat ship gitops pr`, when it is opened, then its body contains exactly one marker line `Service-ref: <owner>/<repo>@<branch>` naming the repo that runs the ship and its ship branch, whatever the given body file contains (a marker line in the body file is replaced, never duplicated).
- **AC-098.2** Given an open gitops PR that `cplat ship gitops pr` reuses and whose body has no marker or a different one, when the command runs, then the body is updated to carry the marker of AC-098.1 and the rest of the body is left unchanged.
- **AC-098.3** Given a gitops PR with a marker, when gitops CI validates it, then every Component in the gitops-app repo (changed or not) whose kind is defined by a CRD that the service ref ships in its chart is validated against that CRD instead of the catalog, and every other manifest is validated exactly as before this spec.
- **AC-098.4** Given a Component that does not match the CRD from the service ref (unknown field with strict checking, wrong type, missing required field), when gitops CI validates the PR, then the check fails, and its log names the file, the kind, the offending field and the `<owner>/<repo>@<ref>` it was checked against.
- **AC-098.5** Given a gitops PR with a marker whose Components all match the CRDs from the service ref, when gitops CI validates it, then the check passes and its log lists each CRD kind used and the `<owner>/<repo>@<ref>` it came from.
- **AC-098.6** Given a marker whose branch no longer exists (merged or deleted), when gitops CI validates the PR, then it validates against the service repo's default branch and the check log says so, naming both the missing branch and the default branch used.
- **AC-098.7** Given a service ref that ships no CRD in its chart, when gitops CI validates the PR, then the check log says that `<owner>/<repo>@<ref>` defines no CRDs and the validation result is the same as for a PR without a marker.
- **AC-098.8** Given a marker naming a repo that the gitops-app does not list among its services, when gitops CI validates the PR, then the check fails naming that repo, and nothing is fetched from it.
- **AC-098.9** Given a PR body with a malformed marker or more than one marker line, when gitops CI validates it, then the check fails with the expected form `Service-ref: <owner>/<repo>@<branch>` as the hint, and nothing is fetched.
- **AC-098.10** Given a marker and no `SERVICE_REPOS_READ_TOKEN` secret in the gitops-app repo, when gitops CI validates the PR, then the check fails with a hint naming `SERVICE_REPOS_READ_TOKEN` and `cplat doctor`; it never skips the CRD validation silently.
- **AC-098.11** Given a marker and a token that cannot read the named service repo (no access, repo not found, network failure), when gitops CI validates the PR, then the check fails naming the repo and the reason, never skipping the CRD validation silently.
- **AC-098.12** Given a CRD from the service ref that cannot be turned into a schema (invalid YAML, no OpenAPI schema), when gitops CI validates the PR, then the check fails naming the CRD file and the `<owner>/<repo>@<ref>`.
- **AC-098.13** Given any check run of gitops CI, when its log and summary are shown, then the token's value never appears in them, and the token is used only to read the service repo.
- **AC-098.14** Given a gitops PR or push without a marker (a hand-written PR, a pin PR, a push to the default branch), when gitops CI runs, then it validates exactly as before this spec and does not need the token secret.
- **AC-098.15** Given a gitops PR whose marker is added, changed or removed by editing the PR body, when the edit is saved, then gitops CI runs again and validates against the new marker (or as in AC-098.14 when it was removed).
- **AC-098.16** Given a gitops-app repo without the `SERVICE_REPOS_READ_TOKEN` secret, when `cplat doctor` runs there, then it reports a warning (not a failure) naming `SERVICE_REPOS_READ_TOKEN` and how to add it; with the secret present the check is OK; in a repo of any other shape, the check is not shown.
- **AC-098.17** Given an existing gitops-app updated with `/shared:update-service` to the platform version that ships this spec, when its next PR without a marker runs CI, then the result is the same as before the update.

## Non-goals

- Validating anything other than Components against CRDs from a service branch (Helm values, chart templates, the service's own manifests).
- Changing how manifests without a CRD from the service ref are validated, including kinds that neither the catalog nor the service ref knows (they stay skipped as today).
- Reading more than one service repo per PR; a gitops change that needs CRDs from two service branches is split into two PRs, as `/svc:ship` already opens one gitops PR per task.
- Installing the CRDs in a cluster or running a dry-run apply against one.
- Shipping a whole product across repos (spec 097, which depends on this spec).
- Creating the token or granting it access; the user does that once, guided by `cplat doctor`.

## Open questions

- ~~Gitops CI needs read access to private service repos to fetch their CRDs. Where does it come from?~~ Answered: one read-only token secret in the gitops-app repo; `cplat doctor` warns when it is missing; without it a PR with a marker fails with a hint and a PR without a marker is unaffected. See AC-098.10, AC-098.14, AC-098.16.
- ~~When the marker's branch is gone, does CI fail or fall back?~~ Answered: validate against the service repo's default branch and say so. See AC-098.6.
- ~~What is the secret called?~~ Answered: `SERVICE_REPOS_READ_TOKEN`. See AC-098.10, AC-098.16.
- ~~Confirm: the marker is a PR body line rather than a committed file.~~ Answered: a PR body line `Service-ref: <owner>/<repo>@<branch>`. See AC-098.1, AC-098.2, AC-098.9.
- ~~Confirm: CI validates every Component of a kind the service ref defines, not only changed ones.~~ Answered: yes, every Component of such a kind. See AC-098.3.
- ~~Confirm: the service ref's CRD replaces the catalog schema for that kind.~~ Answered: yes, it replaces the catalog schema for that kind. See AC-098.3.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended: open questions answered; the secret is named `SERVICE_REPOS_READ_TOKEN` in AC-098.10 and AC-098.16; marker form and AC-098.3 scope confirmed
