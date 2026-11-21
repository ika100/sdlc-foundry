# ADR-125: Library releases publish to GitHub on the tag

**Status:** Accepted (2026-11-21, spec 213)

## Context

A release of a library repo tagged `main` and wrote the changelog, but published nothing: consumers copied code or installed
from a branch, and nothing tied the installed code to a gated version. The TypeScript, Java and .NET library shapes
(#717, #718, #720) each need a release that publishes a package. Without one convention each would choose its own
registry, version check and tokens. The platform already publishes container images to GHCR with `GITHUB_TOKEN`, and
GitHub Free gives every owner the GitHub Packages registries for npm, Maven and NuGet, but none for Python.

## Decision

1. **Every library shape declares where it publishes.** `shapes.yml` gives a library shape (not `planned`) a block
   `publish: {registry: <r>}`; no other shape has one. `scripts/shapes.py check` enforces it.

   | `registry` | Where the package goes | Write permission of the `publish` job |
   |---|---|---|
   | `github-release` | the GitHub release of the tag, as assets (Python: wheel and source archive) | `contents: write` |
   | `github-npm` | `npm.pkg.github.com`, package `@<owner>/<repo>` | `packages: write` |
   | `github-maven` | `maven.pkg.github.com/<owner>/<repo>` | `packages: write` |
   | `github-nuget` | `nuget.pkg.github.com/<owner>` | `packages: write` |

2. **Only the release tag publishes, after every gate.** The template's `ci.yml` has a job `publish` with
   `if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')`, `needs: [quality, test, security, ci-extra]`,
   and one step `devbox run publish "$GITHUB_REF_NAME"` with `GITHUB_TOKEN` (as `GH_TOKEN`, and `NODE_AUTH_TOKEN` for npm).
   The workflow's default permission stays `contents: read`; `publish` is the only job with a write permission (table
   above). `main` builds publish nothing. `/component:release` is unchanged: it tags, the tag's run publishes.
3. **One recipe, three callers.** `devbox run publish vX.Y.Z [--dry-run]` (a template script, `scripts/publish.sh`) builds
   the package, checks the version, and uploads; `--dry-run` stops after the check and prints what it would upload. CI, a
   person and the platform's template smoke test run the same code.
4. **The tag is the version.** Before any upload the recipe compares the built package's (or the manifest's) version with
   the tag without `v` and exits 1 naming both and the fix. For Python the version already comes from the tag
   (hatch-vcs, spec 138), so the check catches a checkout without tags (CI checks out with `fetch-depth: 0`), a tag on
   another commit, or local changes. A rerun replaces the assets of the same name (Python: `gh release upload --clobber`);
   a registry that refuses a republished version fails the rerun, which is then a no-op to fix by a new version.
5. **Consumers read with a token.** A public Python library installs from the release asset URL
   (`<name> @ https://github.com/<owner>/<repo>/releases/download/vX.Y.Z/<file>.whl`), a private one from its git tag
   (`<name> @ git+https://github.com/<owner>/<repo>@vX.Y.Z`) with a token that can read the repo. The npm, Maven and NuGet
   registries need a token with `read:packages` even for public packages; a consuming repo's CI gets it as the secret
   `PACKAGES_READ_TOKEN` (or `GITHUB_TOKEN` when the package grants the consuming repo access). The library repo's
   `CLAUDE.md` says how; consuming templates do not generate the wiring yet.

## Consequences

- A new library shape is incomplete until its `publish` block, recipe and job pass `shapes.py check`; the contract is the
  same for every ecosystem, only the build, the version source and the upload differ.
- PyPI, npmjs.org, Maven Central and nuget.org are not used; a public registry would be a new `registry` value.
- Packages are not signed and carry no provenance attestation yet.
