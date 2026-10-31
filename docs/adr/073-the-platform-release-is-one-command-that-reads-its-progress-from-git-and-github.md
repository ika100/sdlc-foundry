# ADR-073: The platform release is one command that reads its progress from git and GitHub

**Status:** Accepted (2026-10-31)
**Builds on:** [ADR-069](069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md) (every release proves the upgrade), spec 079 (`cplat pr wait`), spec 121 (`release-check.py`, the release guard), spec 123 (the platform repo has no release role), spec 129, issue #296

## Context

The platform was released by hand along CONTRIBUTING.md, Releases: ten steps, two of them irreversible (the merge of the
release PR into `main` and the tag `vX.Y.Z`). Releasing 5.4.0 took an attended hour and two steps went wrong: the upgrade
e2e run on the merge commit was looked up before it had started, and a step crashed under the system Python. The known
traps (a cancelled duplicate CI run that shows red, a missing DCO sign-off, a tag without a green upgrade e2e) recur on
every release. `/component:release` cannot do it: the platform repo has no release agent (spec 123).

## Decision

1. The platform is released with `cplat platform release` (and `/platform:release`, which only relays it and asks at its
   stops). CONTRIBUTING.md, Releases names it as the procedure; the manual steps remain documented as what it does.
2. The command keeps **no state file**. The release branch `release/X.Y.Z`, the open PR from it, the squash commit
   `chore: release X.Y.Z (#N)` on `main`, the tag on origin, the GitHub release and the release-guard run are its state;
   every run derives the phase from them, prints it, and continues at the first step not done.
3. It stops for the maintainer before the two irreversible steps (exit 3, `CONFIRM: merge|tag`); `--confirm merge` and
   `--confirm tag` are honoured only in the phase that stop belongs to.
4. It reuses the platform's own checks instead of copying them: `cplat pr wait` for the PR's CI (newest run per
   workflow), `scripts/release-check.py rows | needs-major | gate` of the checkout being released, `devbox run validate`.
5. It never bumps a plugin or marketplace version (it only checks they agree), never closes issues, and never deletes,
   moves or force-pushes a tag.

## Consequences

- A release is one command and two confirmations; an interruption (a red check, a closed laptop, a declined confirmation)
  is resumed by running it again, on any machine with the checkout.
- The release-commit subject and the `release/X.Y.Z` branch name become a convention the command depends on; a hand-made
  release that uses other names is not recognised as in flight (the command then sees the newest tag as released).
- The upgrade e2e and the release guard are awaited by the command, so the maintainer no longer looks up runs by hand.

## Not included

Changelog fragments (#321), closing linked issues, version bumps of plugins, and any action on a tag whose release guard
is red: that stays a maintainer decision.
