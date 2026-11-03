# ADR-078: Platform changelog entries are fragments the release assembles

**Status:** Accepted (2026-11-03, spec 132)

## Context

Every platform PR added its entry at the top of `## [Unreleased]` in `docs/CHANGELOG.md`, so parallel PRs conflicted there one after
another (#307–#311, #315): each needed a rebase, hand-merged entries and another CI round. Acceptance tests that located "their" release
section by searching a spec or ADR string broke whenever a later entry mentioned that spec (#309), tests that searched only
`[Unreleased]` broke in the release PR (#331), and `==` pins of plugin versions broke on the next bump (#328) (#321).

## Decision

1. **One file per entry.** A platform changelog entry is `docs/changelog.d/<id>-<slug>.<added|changed|fixed>.md` (`<id>`: the issue,
   or the spec number without an issue). The section is in the file name, not in frontmatter: visible in `ls` and the PR file list, one
   regex to validate. `docs/changelog.d/README.md` documents the format and is not a fragment.
2. **The release assembles and deletes them.** `cplat platform release` puts the `[Unreleased]` text and every fragment under the new
   `## [X.Y.Z]` heading (subsections Added, Changed, Fixed; `[Unreleased]` entries first, then fragments by file name) and deletes the
   fragments in the release commit. Relative links are written from the fragment and lose one `../` on assembly.
3. **Additive.** Text written directly under `[Unreleased]` keeps working and is released with the fragments; without fragments the
   release behaves exactly as before.
4. **Everything that reads "unreleased" reads fragments too**: the release preflight, `release-check.py rows` (which also rejects an
   invalid fragment on every PR) and the version proposal through `platrelease_changelog.unreleased_text`.
5. **Tests find a released entry by its version heading** (`## [5.4.0]`) or by content in any section or fragment, never by the first
   section that mentions a spec or ADR; plugin version checks assert `>=` the version a spec shipped.

## Consequences

- Parallel platform PRs no longer touch `docs/CHANGELOG.md`, so they do not conflict there and no longer start the upgrade e2e just for
  a changelog line; the release PR still does.
- A malformed fragment fails CI on the PR that adds it.
- Generated component repos keep their single `CHANGELOG.md`; this ADR covers the platform repo only.
