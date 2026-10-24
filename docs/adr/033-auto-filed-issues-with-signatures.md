# ADR-033 — Failures become auto-filed issues, deduplicated by a signature line

**Status:** accepted (2026-10-24, spec 088)

## Context

Unattended runs stop on platform defects, smoke tests fail after a deploy, and alerts fire. None of these reached an
issue tracker unless someone read the output and filed it by hand. Specs 062–084 started from such failures that a
person happened to notice, and the same failure seen in five repos looked like one anecdote. Specs 088 (platform
failures), 091 (smoke failures) and 092 (firing alerts) all need to turn a failure into an issue. Each failure must
give one issue, and each repeat must add to a count.

## Decision

- **One module files every automatic issue:** `scripts/cplat/autoissue.py`. Callers pass a draft (kind, signature,
  reason, command, phase, evidence, run id, target repo). The module redacts, deduplicates, caps, files or keeps the
  filing pending, and records the result in the run record (ADR-032).
- **A failure is identified by a signature,** `<kind>:<16 lowercase hex>`. The hex is the first 16 hex digits of the
  SHA-256 of the failure's inputs after normalisation. Kinds are `platform`, `smoke` and `alert`. Normalisation removes
  volatile parts: numbers, hashes, dates and durations, URLs, paths, repo, spec and branch names, and versions. The
  same defect in another repo, on another day or at another version then gives the same signature.
- **The issue carries the signature as exactly one body line,** `Signature: <kind>:<hex>`. That line is the only
  dedupe key. Titles start with `[auto] `. Labels are `triage`, `auto-filed`, and one per kind: `bug` for platform,
  `smoke-failure` for smoke, `alert` for alert.
- **Dedupe rules:**
  - A repeat on an open issue adds a counted comment to the oldest open issue with that signature.
  - A repeat after every such issue was closed opens a new issue linked to the most recently closed one.
  - If the most recently closed one is labelled `wontfix`, nothing is filed (`suppressed`).
  - Open issues are found through the issue list (no search-index delay). Closed ones are found through search.
- **New issues are capped per machine:** 10 per 24 h per target repo by default. Callers may pass another cap, for
  example 092 per poll. A filing over the cap, or one that GitHub refused, is kept pending in the run store's filings
  and retried at the next flush. +1 comments are never capped.
- **Text that leaves the machine is redacted.** `cplat feedback`'s redaction applies to every piece. Names the caller
  marks as private (the consumer repo, spec and branch for platform issues, the run store's name always) are
  replaced by placeholders. An issue names the run id but never links the private run store.
- **`CPLAT_AUTO_ISSUES=off` turns sending off.** The draft is then printed with the `/shared:report-issue` hint.
  `CPLAT_FEEDBACK_REPO` moves platform issues to another repo.

## Consequences

- The platform repo's intake queue (`/shared:triage`) receives platform failures without anyone filing them. The weekly
  retro (090) ranks them by signature and occurrence count, and finds them by the `auto-filed` label.
- 091 and 092 reuse the module with their own kind, labels, cap and target repo. They do not invent a second dedupe
  convention.
- Changing the normalisation changes signatures. Old issues then no longer match and get a fresh issue on the next
  repeat. Changes to the normalisation therefore need a spec.
- Two machines filing the same new signature at the same moment can create two issues. Later repeats converge on the
  oldest one.

## Not included

- Deduplicating issues filed by hand with `/shared:report-issue`.
- Closing or relabelling issues when a failure stops recurring (alert resolution is 092's).
