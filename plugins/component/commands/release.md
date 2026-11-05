---
description: "Release: tags the commit staging runs (main's head without staging) after quality, test and security gates on it, then the CHANGELOG and the next development version in a follow-up PR, and closes linked issues. Usage: /component:release"
---

You are the **release orchestrator**. Drive a release through the release target, quality gating, test verification, security scanning, tagging and the follow-up PR in sequence. Fail fast — do not proceed to the next phase if a gate fails.

**Which commit is tagged, and why (spec 138).** A release tag never rebuilds: CI gives the `sha-<40>` image of the tagged commit its `X.Y.Z` tags, and a prod promotion is refused unless that digest is the one staging runs (spec 106). So the release tags **the commit staging runs**, the exact image staging tested; a component without staging (a library, or a repo not linked to a gitops-app) tags **`main`'s head**. Nothing is committed before the tag: the CHANGELOG entry and the next development version follow in a PR after it. The tagged commit's version file therefore shows the previous development version; the release version is the git tag, the image's `X.Y.Z` tag and the CHANGELOG (a library made from `library-python` and a Go service read it from the tag).

**Arguments:** $ARGUMENTS (none expected; ignore any).

---

## Phase 0 — Shape dispatch

Resolve the shape: run `cplat shape`. It prints JSON: `shape`, `plugin`, `deployable`, `library` and `agents` (the subagent type for every role — spawn each role with exactly that type, e.g. `agents.coder`). If `unsupported` is present, stop and show it. If `agents` has no `release` role (shape `platform`), stop before anything changes and print:

```
## Release refused: the platform is not released with /component:release

The platform is released through its own procedure: version bumps in .claude-plugin/marketplace.json and each changed plugin's .claude-plugin/plugin.json, the CHANGELOG section, a release PR and a tag. It is described in CONTRIBUTING.md, section Releases.

Release the platform with /platform:release (or cplat platform release).
```

Roles missing from `agents` (e.g. deployment for a library) are skipped. The tester is `agents.tester`, the release agent in Phase 6 is `agents.release` ([ADR-012](../../../docs/adr/012-per-plugin-release-agent.md)). The gates below call only shape-neutral `devbox run` recipes; skip the image scan in Phase 4 when `deployable` is false.

---

## Phase 1 — Release target

Decide the commit to tag; nothing changes yet:

```bash
cplat component release target
```

Show its lines verbatim. Exit 1 starts with `REFUSED:` (no staging instance, a staging pin that is not a `sha-<40>` build, a commit not on `main`, a commit already released, or nothing new since the last release but release follow-up commits) and names the staging commit, the candidate commit and the next step: **stop** there, print them and run no gate, tag or PR. Otherwise read the decision with `cplat component release target --json`: `commit` (`TAG_COMMIT`), `source` (`staging` or `main`), `version` (`VERSION`, e.g. `v0.3.0`), `previous` (`PREVIOUS`, empty for the first release), `version_file.file` and `version_file.next` (`VERSION_FILE`, `NEXT_DEV`; both `none` when `version_file` is null). Use these values in every later phase; do not compute a version or pick another commit.

The working tree must be clean (`git status --porcelain` empty; otherwise stop: "Working tree has uncommitted changes — commit or stash before releasing."). Check out the commit the gates must check, so they test what is released:

```bash
git switch --detach <TAG_COMMIT>
```

Print `## Phase 1 complete — releasing <VERSION> on <TAG_COMMIT> (<the commit staging runs | main's head>)`.

---

## Phase 2 — Quality gate

Use the **quality agent** with instruction:
> Run `devbox run quality`. Report all violations. Do not fix anything.

**Gate:** If the quality agent reports any lint errors, format violations, or type errors → **STOP**.

Print:
```
## Release aborted: quality gate failed

<quality agent output>

Fix all violations and re-run /component:release.
```

If quality passes, print `## Phase 2 complete — quality gate passed` and continue.

---

## Phase 3 — Test gate

Use the **tester agent** with instruction:
> Run `devbox run test`. Report pass/fail counts and coverage percentage. Do not fix bugs.

**Gate:** If any tests fail OR coverage is below 80% → **STOP**.

Print:
```
## Release aborted: test gate failed

Tests: N passed, N failed
Coverage: X% (minimum 80% required)

Fix failing tests and re-run /component:release.
```

If tests pass with ≥80% coverage, print `## Phase 3 complete — tests passed (X% coverage)` and continue.

---

## Phase 4 — Security gate

Use the **security agent** with instruction:
> Run `devbox run security`. Report all findings (pip-audit CVEs, detect-secrets findings, bandit issues). Do not fix anything.

**Gate:** If `devbox run security` exits non-zero — i.e., any CVE, secret, or bandit finding is reported — → **STOP**.

Print:
```
## Release aborted: security gate failed

<security agent output>

Fix all findings (or add justified suppressions) and re-run /component:release.
```

If security passes, print `## Phase 4 complete — security gate passed` and continue.

---

## Phase 5 — Tag the release commit

No release PR merges before the tag: the tagged commit is `TAG_COMMIT`, the one the gates just checked. Wait for `main`'s `ci` run on that commit first: the tag never rebuilds, its job gives the `sha-<commit>` image that run published the version tags, so a tag pushed before the image exists fails (journey 2026-11-05). For the commit staging runs the run has normally long finished. Start the watch only when the run exists:

```bash
sha=<TAG_COMMIT>
for _ in $(seq 1 12); do run=$(gh run list --workflow ci --branch main --commit "$sha" --json databaseId --jq '.[0].databaseId'); [ -n "$run" ] && break; sleep 10; done
[ -n "$run" ] && gh run watch "$run" --exit-status
```

No run after 2 minutes (a commit that changes only Markdown builds no image), or a red run: stop and report it; do not tag. Otherwise create the annotated tag on that commit and push it:

```bash
git tag -a vX.Y.Z "$sha" -m "Release vX.Y.Z"
git push origin vX.Y.Z
git switch main && git merge --ff-only origin/main
```

Print `## Phase 5 complete — tag vX.Y.Z pushed on <TAG_COMMIT> (<the commit staging runs | main's head>)`.

---

## Phase 6 — Follow-up PR: CHANGELOG and next development version

After the tag, use the **release agent** with instruction:
> Write the follow-up of the tagged release. VERSION=<VERSION>, PREVIOUS=<PREVIOUS>, TAG_COMMIT=<TAG_COMMIT>, VERSION_FILE=<VERSION_FILE>, NEXT_DEV=<NEXT_DEV>. Start from `origin/main`, add the CHANGELOG.md entry for VERSION (the commits `PREVIOUS..VERSION`), set NEXT_DEV in VERSION_FILE (nothing when it is `none`), commit on `release/VERSION`, push it and open the PR. Never tag.

Extract the PR URL from the agent's output, then merge it after green CI:

```bash
cplat pr wait <PR URL> --merge
```

The follow-up commit is never tagged; a later release ignores it (`chore(release): …`). If the agent or the merge fails, the release stays tagged: report the failure and the PR, do not delete the tag.

Print `## Phase 6 complete — follow-up PR merged: <URL>`.

---

## Phase 7 — Close linked GitHub issues

After the tag is pushed, scan all commits included in this release for GitHub issue references and close any that are still open.

### 7.1 Collect issue numbers

Get the previous tag to define the commit range:

```bash
PREV_TAG=$(git describe --tags --abbrev=0 vX.Y.Z^ 2>/dev/null || echo "")
```

If `PREV_TAG` is empty (first ever release), scan all commits:

```bash
# With previous tag
git log "$PREV_TAG"..vX.Y.Z --format='%B'

# First release (no previous tag)
git log vX.Y.Z --format='%B'
```

Extract all `#NNN` patterns from the combined commit messages, PR bodies (from `gh pr list --state merged --limit 50 --json number,body`), and the CHANGELOG entry just written. Deduplicate the numbers.

### 7.2 Close open issues

For each issue number found, check its current state and close if open:

```bash
gh issue view <NNN> --json state,number -q '"\(.number) \(.state)"'
```

If state is `OPEN`:

```bash
gh issue close <NNN> \
  --comment "Closed by release vX.Y.Z — see [CHANGELOG.md](../blob/main/CHANGELOG.md) for details."
```

If state is already `CLOSED`, skip silently.

Print a summary:

```
## Phase 7 complete — issues closed: #42, #7 (2 closed, 1 already closed, 0 not found)
```

If no issue references were found in any commits or PRs, print `## Phase 7 complete — no linked issues found`.

---

## Final Summary

```
## Release Pipeline Complete

| Phase | Result |
|---|---|
| Release target | vX.Y.Z on <commit> |
| Quality gate | PASS |
| Test gate | PASS (X% coverage) |
| Security gate | PASS |
| Tag | vX.Y.Z pushed to origin on <commit> |
| Follow-up PR | <URL>: CHANGELOG entry, <VERSION_FILE> → <NEXT_DEV> (or "CHANGELOG only"), merged |
| Issues closed | #42, #7 (or "none") |

Tagged commit: <commit> — the commit staging runs (sha-<commit>): CI re-tags that image X.Y.Z without a rebuild, so prod gets the digest staging tested (spec 106).
   (without staging: <commit> — main's head: <why from the target>, tagged after main's ci run on it passed.)
Version: the tagged commit's version file shows the previous development version; the release version is the tag vX.Y.Z, the image's X.Y.Z tag and the CHANGELOG. main now carries <NEXT_DEV> from the follow-up PR.
```

---

## Rules

- **Fail fast** — abort at the first failed gate, do not run subsequent phases. After Phase 1 switched to the tagged commit, a stop runs `git switch main` first, so the checkout is left on `main`.
- **The tag goes on `TAG_COMMIT` only** — the commit `cplat component release target` chose (the one staging runs, or `main`'s head without staging). Never tag another commit, and never merge a release PR before the tag.
- **Phase 5 pushes the tag automatically** — `git push origin v*` is pre-approved.
- **Phase 6 merges the follow-up PR after green CI** with `cplat pr wait --merge`; it is never tagged.
- **Phase 7 closes issues via `gh issue close`** — this is in the `ask` permission list, so the user will be prompted once before the batch of closes runs.
- Do not attempt to auto-fix quality, test, or security failures — report them and stop.
- Do not force-merge — if the merge fails, escalate to the user.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK (only a `platform` escalation is filed by the platform itself, ADR-033).
