---
spec_id: 132-changelog-fragments-that-the-release
title: Changelog fragments that the release assembles
status: done
priority: P2
shape: platform
tracks: [321]
---

# 132 — Changelog fragments that the release assembles

## Problem

Every pull request in the platform repo adds its entry at the top of `## [Unreleased]` in `docs/CHANGELOG.md`, so parallel PRs
conflict there one after another (#307–#311, #315 in the 5.5.0 work). Each conflict costs a rebase, entries merged by hand and a fresh
CI round. Separately, older acceptance tests find "their" release section by searching a spec or ADR string (`spec 118|ADR-064`) across
the whole changelog and take the first hit, so a new entry that merely mentions such a spec breaks them (#309, the #316 entry); tests
that searched only `[Unreleased]` broke in the release PR once the release moved their entries (#331); and tests that pinned a plugin
version with `==` broke on the next bump (#328). The release command `cplat platform release` (spec 129) only knows `[Unreleased]` (#321).

## Stories

As a contributor (person or agent) to the platform repo, I want to add my changelog entry as its own file, so that parallel PRs never
conflict in `docs/CHANGELOG.md`.

As the maintainer releasing the platform, I want `cplat platform release` to assemble those files into the new release section and remove
them in the release commit, so that the changelog reads as before and nothing is left behind.

As a maintainer, I want acceptance tests to find their changelog entry by the released version heading or by content, and to pin plugin
versions with `>=`, so that a later entry, a release or a later bump does not turn them red.

## Acceptance criteria

- **AC-132.1** Given the platform repo, when a contributor adds a changelog entry, then it is one file
  `docs/changelog.d/<id>-<slug>.<section>.md` with `<section>` one of `added`, `changed`, `fixed` and a non-empty Markdown body (the
  entry text in the existing style); `docs/changelog.d/README.md` describes the format and is never treated as a fragment.
- **AC-132.2** Given `[Unreleased]` text and fragments on `main`, when `cplat platform release` prepares release X.Y.Z, then the new
  `## [X.Y.Z] - <date>` section holds the `[Unreleased]` text plus every fragment body: text before the first `###` heading of
  `[Unreleased]` first, then the subsections `### Added`, `### Changed`, `### Fixed` in that order (each existing subsection of another
  name after them, in its original order); within a subsection the `[Unreleased]` entries come first, then the fragments in file-name
  order, separated by blank lines; `## [Unreleased]` stays, empty.
- **AC-132.3** Given fragments on `main`, when the release commit is made, then it deletes every fragment (the README stays) and
  changes nothing outside `docs/CHANGELOG.md` and `docs/changelog.d/`; it is still one signed-off commit `chore: release X.Y.Z`.
- **AC-132.4** Given a fragment with a relative Markdown link written from its own location (`../adr/078-….md`), when it is assembled,
  then the link is rewritten to resolve from `docs/CHANGELOG.md` (`adr/078-….md`); absolute and anchor links are unchanged.
- **AC-132.5** Given no fragments, when `cplat platform release` prepares a release, then the changelog, the commit and the PR body are
  exactly what they were before this spec (direct `[Unreleased]` edits keep working).
- **AC-132.6** Given `origin/main` whose `[Unreleased]` is empty but which holds at least one fragment, when the release runs its
  preflight, then it does not refuse for lack of content; with neither text nor fragments it refuses as before.
- **AC-132.7** Given a file in `docs/changelog.d/` other than the README whose name does not match AC-132.1, or a fragment with an empty
  body, when `cplat platform release` runs its preflight or `scripts/release-check.py rows` runs (CI on every PR), then it fails with an
  error naming the file and the expected form `<id>-<slug>.<added|changed|fixed>.md`, and the release creates no branch.
- **AC-132.8** Given a changed row of the versions table that is listed in a fragment but not in `[Unreleased]`, when
  `scripts/release-check.py rows` runs before the release, then the row counts as listed.
- **AC-132.9** Given a repo whose `[Unreleased]` is empty and whose only fragments are `fixed` ones, when the unreleased content is read
  for the version proposal (`platrelease_changelog.unreleased_text(repo)`), then it is the assembled text with only a `### Fixed`
  subsection; with an `added` fragment it also has `### Added`.
- **AC-132.10** Given the contributor guidance (CONTRIBUTING.md, CLAUDE.md, the pull request template), when a contributor reads where
  a platform changelog entry goes, then it names a fragment in `docs/changelog.d/` with the AC-132.1 form and no longer says to add a
  line under `[Unreleased]`.
- **AC-132.11** Given the changelog acceptance tests of specs 115, 116, 117, 118, 119, 120, 121, 125, 128 and 130, when
  `docs/CHANGELOG.md` gains a new `[Unreleased]` entry that names every one of those specs and their ADRs, then they still pass: each
  finds its entry in its released section by the version heading (`## [5.4.0]`), not by searching a spec or ADR string.
- **AC-132.12** Given the plugin version tests of specs 117, 118, 119 and 121, when a plugin they check is bumped beyond the version
  their spec shipped, then they still pass: they assert `>=` the shipped version and that `plugin.json` and `marketplace.json` agree.
- **AC-132.13** Given this change, when its changelog entry is looked up, then it is found by content (#321) in a fragment or in any
  section of `docs/CHANGELOG.md`, and before the release it is a fragment, not a line under `[Unreleased]`.

## Non-goals

- Generated (component) repos: their `CHANGELOG.md` and the release agents stay as they are.
- A changelog tool dependency (towncrier, changie); assembly is a few lines in `platrelease_changelog.py`.
- Moving the text already under `[Unreleased]` into fragments, or forbidding direct `[Unreleased]` edits.
- Running the test suite inside `cplat platform release` before the release PR (#334).
- Showing unreleased fragments on the documentation site.

## Open questions

- ~~Where does the section of a fragment live: file name or frontmatter?~~ Answered (recommended default, 2026-11-03): in the file name
  (`<id>-<slug>.<added|changed|fixed>.md`), visible in `ls` and in the PR file list, no parser; see AC-132.1 and ADR-078.
- ~~Which order do assembled entries take?~~ Answered (recommended default, 2026-11-03): subsections Added, Changed, Fixed; existing
  `[Unreleased]` entries first, then fragments by file name; see AC-132.2.
- ~~How do relative links in a fragment survive the move into docs/CHANGELOG.md?~~ Answered (recommended default, 2026-11-03): written
  relative to the fragment so the link check passes in place, rewritten by one `../` on assembly; see AC-132.4.
- ~~Which name does the proposal read, given that the patch/minor proposal (`only_fixes`) is not on main yet?~~ Answered (recommended
  default, 2026-11-03): `platrelease_changelog.unreleased_text(repo)` returns the assembled unreleased text; the proposal reads that
  instead of `unreleased_body` once both changes are on main; see AC-132.9.

## Changelog

- 2026-11-03 created
- 2026-11-03 approved
- 2026-11-03 building
- 2026-11-03 done
