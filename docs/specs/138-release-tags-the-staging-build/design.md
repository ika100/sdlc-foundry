# Design — 138 A component release tags the build staging tested

Answer of the user: option (b). The release tags the commit staging runs and writes the CHANGELOG and the next development
version in a follow-up PR after the tag. No release PR merges before the tag, so there is no extra dev → staging round and
no version bump that a frozen lock file refuses (#468) before the tag.

## Decisions

1. **The commit to tag is decided by code**, `cplat component release target` (new module `scripts/cplat/comprelease.py`),
   not by the orchestrator's prose. It reads the staging pin the way `cplat instance verify` does (`smoke.pinned_image`,
   the linked gitops-apps of `.platform-app.yml`), checks it against `origin/main` and the release tags, and computes the next
   version from the commits between the previous release tag and the tagged commit (`releases.next_version`, the rule the
   release agents used). The command and the agents only use its result.
2. **Two sources of the tagged commit.** A deployable component linked to a gitops-app releases what staging runs (the
   `sha-<40>` pin). A component without staging (a library, or a repo not linked to a gitops-app) releases `main`'s head.
   In both cases the tag waits for `main`'s `ci` run on that commit (#470, kept in the command); for the staging commit the
   run has normally long finished.
3. **Refusals before anything changes.** No staging instance, a pin that is not `sha-<40>`, a commit that is not on
   `origin/main`, a commit that already carries a `v*.*.*` tag, or nothing new since the previous tag but release follow-up
   commits (`chore(release): …`) stop the release before the gates with exit 1, the staging commit, the candidate commit
   (`main`'s head) and the next step.
4. **The gates run on the tagged commit**: the command switches to it (`git switch --detach <commit>`) before the quality,
   test and security gates, so the gates check what is released, not `main`'s head.
5. **The follow-up PR** is the release agent's job, started after the tag from `origin/main`: branch `release/vX.Y.Z`,
   the CHANGELOG entry for `vX.Y.Z` (commits between the previous tag and the tag) and the next development version; title
   `chore(release): vX.Y.Z changelog and next development version`, so a later release ignores it (decision 3). It merges with
   `cplat pr wait <pr> --merge` (green CI first, ADR of spec 079) and is never tagged. A failure here leaves the release
   tagged and is reported; it is not rolled back.
6. **Version per template** (the tagged commit was built before the tag existed, so its image cannot carry `X.Y.Z`):

   | Template | Version file | After the tag | At the tagged commit |
   |---|---|---|---|
   | service-python | `pyproject.toml` (+ `uv.lock`), read by `__version__` and the FastAPI app through package metadata | `X.Y.(Z+1).dev0` (PEP 440) | the previous development version |
   | library-python | none: `hatch-vcs` reads the version from the git tag at build time | CHANGELOG only | the tag's version when installed from the tag |
   | service-java | `pom.xml` `<version>` | `X.Y.(Z+1)-SNAPSHOT` (Maven convention) | the previous `-SNAPSHOT` |
   | web-nextjs | `package.json` `version` (pnpm's lock does not record it) | `X.Y.(Z+1)-dev.0` (semver pre-release) | the previous development version |
   | service-go | none: `-ldflags -X main.Version` from the CI ref | CHANGELOG only | the build's ref |

   The first release (no tag yet) is `v0.1.0`, which is what the templates declare. The release version of a service is the
   git tag, the image's `X.Y.Z` tag on the same digest and the CHANGELOG; the summary says so. A library is installed from
   its tag, so its version must be right there: it reads the tag. Existing libraries keep their static version (the
   template's `pyproject.toml` and `src/` are project-owned); the agent treats a static version like a service's.
7. **Next development version in code**: `comprelease.next_dev(version, shape, repo)` returns the file and value per the
   table (None when there is none), so the agents do not compute it.

## Contract

### `cplat component release target [--repo DIR] [--json]`

Runs `git fetch origin --tags` (failure ignored), then decides. Exit 0 with:

```
Release: v0.3.0 (previous v0.2.0, 4 commits)
Tag: <40-hex> — the commit staging runs (sha-<40-hex>): CI re-tags its image 0.3.0 without a rebuild, so prod gets the digest staging tested (spec 106)
Main: <40-hex> — 2 commits after the tagged commit are not in this release
  - feat: ...
Version file: pyproject.toml → 0.3.1.dev0 in the follow-up PR; the tagged commit's file shows the previous development version, the release version is the tag, the image's 0.3.0 tag and the CHANGELOG
```

For `main`'s head the `Tag:` line reads `— main's head: <reason, e.g. a library has no staging environment>`. `--json`
prints `{"ok": true, "commit", "source": "staging"|"main", "why", "version", "previous", "subjects", "main", "after",
"staging", "version_file": {"file", "next"} | null}`.

Exit 1 (refused), nothing changed:

```
REFUSED: <reason>
Staging commit: <40-hex or none>
Candidate commit: <40-hex> (main's head)
Next: promote <candidate> to staging in the gitops-app (/instance:promote <service> --to staging --sha <candidate>), verify it (/instance:verify staging), then run /component:release again.
```

`--json` prints `{"ok": false, "reason", "staging", "candidate", "next"}`. Without `origin/main` the reason says so.

### `/component:release` phases

0 shape dispatch (unchanged refusal for the platform) · 1 release target (`cplat component release target`; exit 1 →
show and stop) · 2–4 gates on the detached tagged commit · 5 wait for `main`'s `ci` run on the tagged commit, then
`git tag -a vX.Y.Z <commit>` and push · 6 follow-up PR by the release agent, merged with `cplat pr wait --merge` · 7 close
linked issues · summary naming the tagged commit and why.

### Release agents (svc, svc-java, svc-go, web)

Input from the orchestrator: `VERSION`, `PREVIOUS`, `TAG_COMMIT`, `VERSION_FILE` and `NEXT_DEV` from the target. They
start from `origin/main`, write the CHANGELOG entry from `git log PREVIOUS..VERSION`, set `NEXT_DEV` in the version file
(Python: also `devbox run -- uv lock`, #468), commit `chore(release): …`, push `release/vX.Y.Z`, open the PR. They never
tag and never compute the version or the tagged commit.
