# Design — 213 Library releases publish their package

## Decisions

- **One convention for every library shape** ([ADR-124](../../adr/124-library-releases-publish-to-github-on-the-tag.md)).
  A library shape declares `publish: {registry: <r>}` in `shapes.yml`; `r` is `github-release` (Python: the GitHub
  release of the tag holds the wheel and the source archive), `github-npm` (npm.pkg.github.com), `github-maven`
  (maven.pkg.github.com) or `github-nuget` (nuget.pkg.github.com). Everything else is the same for every registry.
- **The tag publishes, nothing else.** The template's `ci.yml` gets a job `publish` with
  `if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')`, `needs: [quality, test, security, ci-extra]`,
  a checkout with `fetch-depth: 0` (the Python version is read from the tag, spec 138), and one step
  `devbox run publish "$GITHUB_REF_NAME"` with `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}`. The workflow default stays
  `permissions: contents: read`; only `publish` gets `contents: write` (`github-release`) or `packages: write` (the
  GitHub Packages registries).
- **One script, three callers (A3).** `scripts/publish.sh <tag> [--dry-run]` behind the `publish` recipe. CI, a person
  and the platform's smoke test run the same code. For `library-python`:
  1. `rm -rf dist && uv build --out-dir dist` (sdist + wheel; hatch-vcs gives the version).
  2. Version check: `dist/*-<X.Y.Z>-py3-none-any.whl` and `dist/*-<X.Y.Z>.tar.gz` must exist; otherwise exit 1 with
     `publish: the built version is <built> but the tag is vX.Y.Z (<X.Y.Z>)` and the fix (tag `HEAD`, fetch tags,
     commit or stash local changes).
  3. `--dry-run`: print `publish: would upload <files> to the GitHub release vX.Y.Z` and stop.
  4. `gh release view <tag>` or `gh release create <tag> --verify-tag --title <tag> --generate-notes`, then
     `gh release upload <tag> <wheel> <sdist> --clobber` (a rerun replaces, AC-213.3).
- **The registry checks it (AC-213.1, AC-213.2).** `scripts/shapes.py`: `validate` checks the `publish` field
  (library ⇔ present, registry in the set); `check_contract` checks the template: a `publish` recipe in `devbox.json`;
  in `ci.yml` the job `publish` with the tag condition, the four needs and `devbox run publish`; the workflow default
  `contents: read`; no other job with `write` in its permissions.
- **CI proves it (AC-213.6).** The `smoke-test-templates` job for `library-python` commits the render, tags `v1.2.3`,
  runs the recipe's command with `--dry-run`, then adds a commit, tags `v1.2.4` on the parent and expects the version
  failure.
- **Consumers (A6).** Documented in the template's `CLAUDE.md` (`## Releasing the package`) and the ADR: a public Python
  library installs from the release asset URL, a private one from `git+https://github.com/<owner>/<repo>@vX.Y.Z` with a
  token that can read the repo; npm, Maven and NuGet read with a `read:packages` token, the CI secret
  `PACKAGES_READ_TOKEN`.

## Contract for the next library shapes (#717, #718, #720)

| Piece | Value |
|---|---|
| `shapes.yml` | `publish: {registry: github-npm \| github-maven \| github-nuget}` |
| devbox recipe | `publish` → `bash scripts/publish.sh "$@"`; arguments `<tag> [--dry-run]` |
| CI job | `publish`, tag-only, needs `quality, test, security, ci-extra`, `permissions: {contents: read, packages: write}`, `GH_TOKEN`/`NODE_AUTH_TOKEN` from `secrets.GITHUB_TOKEN` |
| version check | the manifest version (or the built artifact's) must equal the tag without `v`; fail before any upload |
| consumers | secret `PACKAGES_READ_TOKEN` (`read:packages`) |
