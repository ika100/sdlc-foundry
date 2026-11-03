# Changelog fragments

Each platform change that users can notice adds **one file here** instead of editing `docs/CHANGELOG.md`, so parallel pull requests
never conflict in the changelog ([ADR-078](../adr/078-platform-changelog-entries-are-fragments-the-release-assembles.md), spec 132).

## Name

`<id>-<slug>.<added|changed|fixed>.md`

- `<id>`: the issue number (`321`), or the spec number when there is no issue.
- `<slug>`: a few lowercase words with hyphens.
- The last part before `.md` is the changelog section: `added`, `changed` or `fixed`.

Example: `321-changelog-fragments.added.md`. Any other file here (except this README) and an empty fragment fail
`scripts/release-check.py rows` in CI and stop `cplat platform release`.

## Content

The entry text exactly as it should appear in the changelog, in the existing style: one paragraph that starts with a bold one-sentence
summary ending in `(#NNN).`, then what was wrong and what happens now; `**Action:**` or "Update the plugins (`/plugin marketplace
update`)" when users must do something. No heading: the section comes from the file name.

Write relative links from this directory (`../adr/078-….md`, `../specs/132-…/spec.md`) so the link check passes here; the release
removes one `../` when it moves the text into `docs/CHANGELOG.md`.

## Release

`cplat platform release` puts the text under `## [Unreleased]` and every fragment under the new `## [X.Y.Z]` heading (sections Added,
Changed, Fixed; `[Unreleased]` entries first, then fragments by file name) and deletes the fragments in the release commit. Text written
directly under `[Unreleased]` still works and is released with them.
