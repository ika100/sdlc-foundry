---
spec_id: 106-prod-runs-the-exact-image-staging-tested
title: Prod runs the exact image staging tested
status: approved
priority: P1
tracks: [157]
---

# 106 — Prod runs the exact image staging tested

## Problem

`/gitops:promote <service> staging prod` checks only that the release tag (`X.Y.Z`) exists in the registry. It never checks that this tag points to the same image that `staging` ran and that its smoke tests passed against. If the release image was rebuilt, or the tag moved, `prod` runs bits nobody tested, and the evidence summary of spec 093 (AC-093.11) would vouch for a build that is not what ships. This is a release-integrity gap, separate from functional smoke (specs 091, 093). Spec 093 adds the prod evidence summary; this spec adds one check on the same promote path: the image identity (its digest) must be the same in `staging` and in the release.

## Stories

As the person who promotes to `prod`, I want the promotion refused when the release image is not the image `staging` runs, so that `prod` runs exactly what was tested.

As the person who promotes to `prod`, I want `--dry-run` to show both digests and whether they match, so that I can see the integrity result before any PR exists.

As a release manager, I want releases published from the already-tested image rather than a rebuild, so that the check can pass for a normal release.

## Acceptance criteria

- **AC-106.1** Given `/gitops:promote <service> staging prod` for a service whose `staging` pins tag T_s and whose release tag is T_r, when both tags exist in the registry and resolve to the same image digest, then the promotion proceeds as before (forward-only, PR flow, `[PRODUCTION]` marking unchanged).
- **AC-106.2** Given the same promotion where T_s and T_r resolve to different digests, when the command runs without a release-validation override (AC-106.7), then it exits non-zero, opens no PR and changes nothing. The message names the service, both tags and both digests, says that `prod` would not run what `staging` tested, and names the next step (re-publish the release from the tested image, or promote a release whose image is the staging one).
- **AC-106.3** Given `--dry-run` (with or without `--json`), when the promotion has a staging source and a prod target, then the output shows the source tag and digest, the target tag and digest, and `match` or `mismatch`. A mismatch in dry-run exits non-zero and writes nothing.
- **AC-106.4** Given a staging tag or a release tag that does not exist in the registry, when the digest check runs, then the promotion is refused and the message names which of the two tags is missing. The existing "image does not exist" refusal for the release tag is kept.
- **AC-106.5** Given a registry lookup that fails (authentication, network, rate limit, unreadable response), when a digest is to be resolved, then the promotion fails with a message naming the failed lookup and the fix (for example the missing token scope). It never treats an unresolved digest as a match.
- **AC-106.6** Given `--no-verify`, when promoting to `prod`, then no digest check is made (for `prod` too) and the output says in one line that image identity was not verified. Given a promotion to `staging`, then behaviour is unchanged (no digest check).
- **AC-106.7** Given a release whose image intentionally differs from the one in `staging`, when the person passes the explicit release-validation override (a named flag that takes a reason of at least one sentence), then the promotion proceeds (the reason is mandatory; without it the flag is refused), and the PR body and the output state "digest mismatch accepted: <reason>" with both digests.
- **AC-106.8** Given a promotion where `staging` pins a tag that is not an immutable `sha-<40>` build (for example `latest`), when the check runs, then it is refused with a message that the staging image cannot be identified. Resolution is done on the digest, never on matching tag names or commit labels.
- **AC-106.9** Given the prod evidence summary of spec 093 (AC-093.11) and the PR body, when the digests match, then both show the digest that `staging` tested and `prod` will run, in a line "image digest: <digest> (same in staging and prod)". Given spec 093 is not yet in place, this criterion applies once the evidence summary exists.
- **AC-106.10** Given a release cut by the platform's release flow for a service, when CI publishes the `X.Y.Z` image, then it is the existing `sha-<40>` image of the tagged commit re-tagged (same digest), not a rebuild. Given that commit has no published `sha-<40>` image, then the release job fails with a message naming the missing image.
- **AC-106.11** Given a promotion of several services to `prod` in one command, when one service fails the check, then no service is promoted and the output names every failing service.
- **AC-106.12** Given the docs and the `/gitops:promote` command text, when they describe promotion to `prod`, then they state the digest rule, the dry-run output and the override.

## Non-goals

- Functional verification after deploy (specs 091 and 093).
- Image signing, attestation or SBOM checks.
- Preview environments, a new registry abstraction or a new service.
- Changing forward-only promotion, the PR flow or the explicit production confirmation.
- Checking digests for promotions to `staging`.
- Backfilling or re-tagging releases that were already published.

## Open questions

- ~~Should the same spec change the release job to re-tag?~~ Answered: yes, AC-106.10 is part of this spec, see AC-106.1 and AC-106.10.
- ~~Should the override (AC-106.7) exist at all, or must a mismatching release always be re-published?~~ Answered: keep it, with a mandatory reason, see AC-106.7.
- ~~Should `--no-verify` also skip the digest check for prod?~~ Answered: yes, with the one-line notice, see AC-106.6.
- ~~Confirm: a failed registry lookup refuses the promotion rather than warning.~~ Answered: yes, see AC-106.5.

## Changelog

- 2026-10-25 created
- 2026-10-25 amended: folded in the user's answers (release job re-tags, override kept with a mandatory reason, `--no-verify` skips the digest check, failed lookups refuse).
- 2026-10-25 approved
