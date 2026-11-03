# Design — 132 Changelog fragments that the release assembles

## Decisions

1. **One file per entry, the section in the file name.** `docs/changelog.d/<id>-<slug>.<added|changed|fixed>.md`, where `<id>` is the
   issue number (or the spec number when there is no issue). The name is validated by one regex; anything else in the directory except
   `README.md` is an error. No frontmatter, no tool dependency. ADR: [078](../../adr/078-platform-changelog-entries-are-fragments-the-release-assembles.md).
2. **Assembly is pure text in `platrelease_changelog.py`.** `assemble(unreleased_body, fragments)` splits the `[Unreleased]` body into a
   preamble and `###` subsections, appends each fragment body to its subsection, and emits preamble, then Added, Changed, Fixed, then any
   other subsection in its original order. `move_unreleased(text, version, date, fragments=())` uses it; with no fragments it returns
   exactly what it returned before (AC-132.5), so the spec 129 tests stay as they are.
3. **Links are written from the fragment.** The link checker runs over `docs/` and must pass in place, so a fragment links `../adr/…`;
   assembly strips one leading `../` from relative link targets (`](../x)` → `](x)`).
4. **The release deletes what it assembled in the same commit.** `_prepare` writes the changelog, then `git rm`s the fragments; the
   release commit stages both. Resuming on the release branch allows uncommitted changes in `docs/changelog.d/` next to the changelog.
   If the version heading already exists (a resumed run), nothing is assembled again.
5. **Every reader of "unreleased" sees fragments.** Preflight on `origin/main` reads fragments with `git ls-tree`/`git show`;
   `release-check.py rows` adds them to the `[Unreleased]` body before it looks for rows and fails on an invalid fragment (CI feedback on
   the PR, not at release time); `unreleased_text(repo)` is the one entry point for the version proposal (`only_fixes`, not on main yet).
6. **Tests find their release by the version heading.** A test helper `tests/cplat/changelog_support.py` gives `section(version)`,
   `paragraphs(text, pattern)` and `entry(pattern)` (fragments, then every section); the released specs' changelog tests use
   `section("5.x.y")`. Plugin version tests assert `>=` the shipped version.

## Contract

```python
# scripts/cplat/platrelease_changelog.py
FRAGMENTS = "docs/changelog.d"
SECTIONS = ("Added", "Changed", "Fixed")
class FragmentError(ValueError): ...                 # message: "docs/changelog.d/<name>: <why>; expected <id>-<slug>.<added|changed|fixed>.md"
def parse_fragment(name: str, text: str) -> tuple[str, str]         # (section title, body with links rewritten); FragmentError
def read_fragments(repo: Path) -> list[tuple[str, str]]             # (name, text) sorted by name, README.md left out
def assemble(body: str, fragments: list[tuple[str, str]]) -> str     # the [Unreleased] body plus the fragments
def move_unreleased(text: str, version: str, date: str, fragments=()) -> str
def unreleased_text(repo: Path) -> str                              # assemble(unreleased_body(CHANGELOG), read_fragments(repo))
```

Release PR body with fragments: `Release X.Y.Z: [Unreleased] of docs/CHANGELOG.md and N fragment(s) of docs/changelog.d moved under
## [X.Y.Z].` (unchanged text without fragments).
