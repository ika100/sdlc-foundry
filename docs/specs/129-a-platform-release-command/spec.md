---
spec_id: 129-a-platform-release-command
title: A platform release command
status: done
priority: P1
shape: platform
tracks: [296]
---

# 129 — A platform release command

## Problem

Releasing the platform is a manual procedure in CONTRIBUTING.md, Releases: `/component:release` refuses in the platform repo and points there. Releasing 5.4.0 by hand took ten steps (changelog, release-check and validate, commit, PR, waiting for CI including a roughly 20-minute upgrade e2e, merge, waiting for the upgrade e2e on the merge commit, release gate, tag and GitHub release, release-guard check), and two of them went wrong: the upgrade e2e run on the merge commit was looked up before it had started, and a step crashed under the system Python. Each release costs a maintainer an attended hour and invites the same traps: a cancelled duplicate CI run that shows red (#322), a missing DCO sign-off, a tag pushed without a green upgrade e2e. A command that drives the procedure, stops for the maintainer at the two irreversible points and picks up where it left off removes that cost.

## Stories

As a platform maintainer, I want `/platform:release` (or `cplat platform release`) to prepare, merge, tag and publish a release with the checks the procedure requires, so that a release is one command and two confirmations instead of ten manual steps.

As a platform maintainer, I want an interrupted release to continue from where it stopped when I run the command again, so that a failed check, a closed laptop or a declined confirmation never forces me to redo or repair steps by hand.

As a platform maintainer, I want the command to say what it detected and what it will do before it does anything, so that I can trust it with the release.

## Acceptance criteria

- **AC-129.1** Given the platform repo, when `cplat platform release --dry-run` runs, then it prints the state it detected (newest release tag, release branch, open release PR, merged release commit, tag, GitHub release, each present or absent), the version it would release with the reason, and the numbered steps it would take from that state, exits 0 and creates no commit, branch, push, PR, merge, tag or GitHub release.
- **AC-129.2** Given newest tag `v5.4.0` and `release-check rows` requiring no major release, when the command runs without `--version`, then it proposes 5.5.0; given a change that release-check says needs a major release, then it proposes 6.0.0 and names that change as the reason.
- **AC-129.3** Given `--version X.Y.Z`, when X.Y.Z is valid semver and newer than the newest tag and is a major release whenever one is required, then it is used instead of the proposal; otherwise (not semver, not newer, or non-major while a major is required) the command exits non-zero naming the reason (for a required major: the change that requires it) and changes nothing.
- **AC-129.4** Given no release in flight, when the working tree has uncommitted changes, local main differs from the remote main, or `## [Unreleased]` in the changelog has no content, then the command exits non-zero naming the problem before it creates a branch or commit.
- **AC-129.5** Given a plugin whose version in the marketplace catalog differs from its plugin manifest, when the command runs, then it exits non-zero naming the plugin and both versions, changes nothing and never edits either version.
- **AC-129.6** Given a release of x.y.z being prepared, when the command prepares it, then on a release branch for x.y.z the changelog's former `[Unreleased]` content sits under `## [x.y.z] - <date of the run, YYYY-MM-DD>`, an empty `## [Unreleased]` heading stays above it, and no other file changes.
- **AC-129.7** Given the prepared changelog, when `release-check rows` or the repository validation fails, then the command prints their output, exits non-zero and has neither committed nor pushed.
- **AC-129.8** Given the checks pass, when the command commits, then it creates exactly one commit with subject `chore: release x.y.z` carrying a `Signed-off-by:` trailer of the git user, pushes the release branch and opens a PR against main titled `chore: release x.y.z`, and prints the PR URL.
- **AC-129.9** Given an open release PR, when the command waits for CI, then it waits for every check on the PR's head commit including the upgrade e2e, and where a workflow has two runs on that commit it judges only the newest one, so a cancelled older run does not count as red.
- **AC-129.10** Given a red check in the newest runs of the release PR, when the wait ends, then the command exits non-zero naming the check and its link and does not merge.
- **AC-129.11** Given a green release PR, when the command reaches the merge, then it stops before squash-merging, printing the version, the PR URL, the check summary and the command to continue (`cplat platform release --confirm merge`); only a run with that confirmation squash-merges the PR into main.
- **AC-129.12** Given the release PR was just merged, when the command looks for the upgrade e2e run on the merge commit and none exists yet, then it keeps waiting for the run to appear for up to 10 minutes instead of failing, then waits for it (newest run if two exist); if none appears in that time, or the run is red, it exits non-zero naming the merge commit and the reason, and creates no tag.
- **AC-129.13** Given a green upgrade e2e on the merge commit, when the command runs the release gate (`release-check gate <merge sha>`) and it fails, then the command prints the gate's output, exits non-zero and creates no tag and no GitHub release.
- **AC-129.14** Given a passed release gate, when the command reaches tagging, then it stops before creating anything, printing the tag, the merge commit, the release notes it will publish and the command to continue (`cplat platform release --confirm tag`); only a run with that confirmation tags.
- **AC-129.15** Given the tag confirmation, when the command tags, then the annotated tag `vX.Y.Z` points at the merge commit and is pushed, and a GitHub release `vX.Y.Z` is created whose notes are exactly the body of the changelog's `## [x.y.z]` section.
- **AC-129.16** Given the pushed tag, when the command checks the release-guard run on it, then it waits for that run (allowing it not to have started yet, as in AC-129.12) and reports green as a finished release with the tag and release URLs; on red it exits non-zero with the run's link and leaves the tag and the release untouched.
- **AC-129.17** Given a release that stopped after any step, when the command runs again, then it prints the detected state and continues at the first step not done, with no local state file: release branch without PR → opens the PR; open release PR → waits for CI; merged release commit without tag → waits for the upgrade e2e on that commit; tag without GitHub release → creates the release; tag and release → checks the release-guard run.
- **AC-129.18** Given a release in flight for x.y.z (release branch, open PR or merged release commit without tag), when the command runs with `--version` naming another version, then it exits non-zero naming the release in flight and changes nothing.
- **AC-129.19** Given a tag `vX.Y.Z` that already exists on a commit other than the release's merge commit, when the command reaches tagging, then it exits non-zero naming both commits; the command never deletes, moves or force-pushes a tag in any state.
- **AC-129.20** Given the platform repo, when `/platform:release [--version X.Y.Z]` runs, then it runs `cplat platform release` with those arguments, shows its output, and at each confirmation stop asks the user and continues with the matching `--confirm` only after the user agrees.
- **AC-129.21** Given the platform repo, when `/component:release` runs, then it still refuses before changing anything and its refusal names `/platform:release` (and `cplat platform release`) as the way to release the platform; CONTRIBUTING.md, Releases names the same command as the procedure.

## Non-goals

- Bumping plugin or marketplace versions; the command only checks that they match (AC-129.5).
- Releasing component repos; `/component:release` stays as it is there.
- Changelog fragments instead of a single `[Unreleased]` section (#321).
- Closing linked issues after the release.
- Deleting or moving a tag after a red release guard; that stays a maintainer decision.

## Open questions

## Changelog

- 2026-10-31 created
- 2026-10-31 filled from #296 with the user's decisions: `cplat platform release` plus `/platform:release`, confirmation stops before merge and before tag, version proposal with `--version` override, resume from git/GitHub state without a state file
- 2026-10-31 approved
- 2026-10-31 building
- 2026-10-31 done
