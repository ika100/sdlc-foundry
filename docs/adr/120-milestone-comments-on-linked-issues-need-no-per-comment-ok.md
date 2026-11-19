# ADR-120: Milestone comments on linked issues need no per comment ok

**Status:** Accepted (2026-11-19)

## Context

[ADR-033](033-auto-filed-issues-with-signatures.md) lets the platform file an issue itself only for a `platform` escalation; every other
issue needs the user's OK, because the platform repository is public (#428). People who report or track an issue still learn nothing
when its spec is written or approved, its PR merges or its release ships, unless someone writes the comment by hand. Spec 158 closes that gap.
The user answered on 2026-11-08: one new comment per milestone, no per-comment OK.

## Decision

cplat posts a milestone comment on an issue a spec tracks or a PR closes without a per-comment OK; it never files issues.

- **Linked** means the spec tracks the issue, a closing reference in the PR body names it, or a changelog fragment of the release names it. An issue
  that is only mentioned, a pull request, an issue of another repository and a platform-owned issue (`auto-filed`, `notify`, `retro`) get nothing.
- The texts are fixed and built from records (the spec, the PR, the changelog); no model writes them and nothing in them comes from an
  issue's text.
- A hidden last line `<!-- cplat:milestone <milestone> <key> -->` is the record: an issue that has it gets no second comment, and a failed
  post is retried by the next run. A failure of `gh` or a locked issue is a `note:` line, never a failed command.

## Consequences

- Authors of issues hear about each milestone without anyone typing it; a release closes the open ones it fixed.
- The comments are the only thing the platform posts on an issue without being asked; the closing note of every command and ADR-033's rule
  name them next to `platform` escalations, and filing an issue still needs the user's OK.
- There is no switch to turn them off (spec 158, A8); a later change that adds a milestone must keep the marker, the time limits and the
  linking rule.
