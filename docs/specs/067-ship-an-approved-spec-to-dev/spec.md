---
spec_id: 067-ship-an-approved-spec-to-dev
title: Ship an approved spec to dev unattended
status: done
priority: P0
---

# 067 — Ship an approved spec to dev unattended

## Problem

The pipeline stops at "PR opened": `/svc:build` ends with a PR, then the user waits for CI, fixes red checks, merges, waits for the pin and checks `dev` themselves. In stock-manager the user ran each of those steps by hand for every fix (32 "Deploy image" commits); ai-ops pinned every image by hand in stock-manager-gitops. The approval of the spec is the decision that matters; the rest can run without the user.

## Stories

As a founder, I want one command that takes an approved spec through plan, build, PR, green CI, merge and the `dev` deployment, and that I can resume, so that the only human step is approving the spec.

## Acceptance criteria

- **AC-067.1** Given `/svc:ship <spec>`, when it starts, then an approved spec begins at plan or build (a valid plan skips planning), a done spec at the PR, a draft or superseded spec is refused, and a second start resumes the same run from its state in the git directory (never committed).
- **AC-067.2** Given a built spec, when the run opens the PR, then it pushes only the spec's feature branch, opens or reuses its PR with a Conventional Commit title, and squash-merges it after all checks passed.
- **AC-067.3** Given red checks, when the run lands, then nothing is merged, the failed checks and their log tails are printed for the fix loop, and the fix rounds are counted (the command escalates after 3).
- **AC-067.4** Given `--no-merge`, when the checks are green, then the run ends at the green PR.
- **AC-067.5** Given a merged PR of a service linked to a gitops-app, when the run deploys, then it waits for the merged pin PR `pin/dev-<service>-<sha7>` of the merge commit in every linked gitops-app (and, with a kube context, for Argo CD to report `<service>-dev` Synced/Healthy); a closed pin PR fails with a hint; an unlinked repo or a library finishes with a note.

## Non-goals

- Promotion to staging or prod (stays `/gitops:promote`, reviewed).
- Multi-repo features (`/app:build` keeps its flow).

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
