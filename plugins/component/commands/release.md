---
description: "Release: tags the commit staging runs (main's head without staging) after quality, test and security gates on it, then the CHANGELOG and the next development version in a follow-up PR, and closes linked issues. Usage: /component:release"
---

You are the **release orchestrator**: release target, quality, test and security gates, tag, follow-up PR, issues, in sequence. Fail fast: a failed gate stops the release.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**What is tagged (spec 138):** the commit staging runs (CI re-tags its `sha-<40>` image `X.Y.Z` without a rebuild, spec 106); without staging (a library, or no gitops-app link) `main`'s head. The CHANGELOG entry and the next development version follow in a PR after the tag.

**Arguments:** $ARGUMENTS (none expected; ignore any).

## Phase 0 — Shape dispatch

`cplat shape`: JSON with `shape`, `plugin`, `deployable`, `library`, `agents` (spawn each role with exactly that type; roles missing from it are skipped). `unsupported` → stop and show it. If `agents` has no `release` role (shape `platform`), stop before anything changes and print:

```
## Release refused: the platform is not released with /component:release

The platform is released through its own procedure: version bumps in .claude-plugin/marketplace.json and each changed plugin's .claude-plugin/plugin.json, the CHANGELOG section, a release PR and a tag. It is described in CONTRIBUTING.md, section Releases.

Release the platform with /platform:release (or cplat platform release).
```

Agents: tester `agents.tester`, release `agents.release` (ADR-012), all in the foreground (`run_in_background: false`). Skip the image scan in Phase 4 when `deployable` is false.

## Phase 1 — Release target

`cplat component release target`; show its lines verbatim. Exit 1 starts with `REFUSED:` and names the next step: **stop** there and run no gate, tag or PR. Otherwise read `cplat component release target --json`: `commit` (`TAG_COMMIT`), `source` (`staging` or `main`), `version` (`VERSION`), `previous` (`PREVIOUS`, empty for the first release), `version_file.file` and `.next` (`VERSION_FILE`, `NEXT_DEV`; both `none` when `version_file` is null). Use these values throughout; never compute a version or pick another commit, because the tag, the gates and the staged image must name one commit.

`git status --porcelain` must be empty so that the gates check only what is released (else stop: "Working tree has uncommitted changes — commit or stash before releasing."). Then `git switch --detach <TAG_COMMIT>`.

Print `## Phase 1 complete — releasing <VERSION> on <TAG_COMMIT> (<the commit staging runs | main's head>)`.

## Phase 2 — Quality gate

**quality agent**: "Run `devbox run quality`. Report all violations (no edits)." Any lint, format or type error → **STOP**.

## Phase 3 — Test gate

**tester agent**: "Run `devbox run test`. Report pass/fail counts and coverage percentage (no edits)." A failing test or coverage below 80% → **STOP** (abort text: `Tests: N passed, N failed` / `Coverage: X% (minimum 80% required)`).

## Phase 4 — Security gate

**security agent**: "Run `devbox run security`; name each tool by the recipe `devbox.json` runs (its `audit` is `pip-audit`, `pnpm audit`, `govulncheck` or OWASP Dependency-Check). With a `Dockerfile`, also run `devbox run image-build` and `devbox run image-scan`, else report the image scan as skipped. Report all findings (no edits)." Non-zero exit of `security` (any CVE, secret or bandit finding) → **STOP** ("Fix all findings (or add justified suppressions)"). Image findings are reported in the release summary, fixable and base-image ones apart; they do not stop the release, because most are base-image findings this repo cannot fix.

A failed gate prints `## Release aborted: <quality|test|security> gate failed`, the agent's output, and `Fix … and re-run /component:release.`; a passed one `## Phase N complete — <gate> gate passed` (Phase 3 adds `(X% coverage)`).

## Phase 5 — Tag the release commit

The tag goes on `TAG_COMMIT`, before any release PR merges. The tag job re-tags the image `main`'s `ci` run built, so wait for that run first (spec 143):

```bash
cplat component release wait --commit <TAG_COMMIT>
```

`GREEN:` (exit 0) → tag. `RED:` or `NO RUN:` (exit 1; a Markdown change builds no image) → stop and report it; do not tag, since no image exists to re-tag. `TIMEOUT:` (exit 2) → run the same wait again, at most twice; after the third, stop and report an environment problem (cause `environment`); do not tag, since the run has not shown green. Never write a polling loop on `gh` or `cplat`, because `cplat component release wait` already waits and reruns. Then:

```bash
git tag -a vX.Y.Z <TAG_COMMIT> -m "Release vX.Y.Z"
git push origin vX.Y.Z
git switch main && git merge --ff-only origin/main
```

Print `## Phase 5 complete — tag vX.Y.Z pushed on <TAG_COMMIT>`.

## Phase 6 — Follow-up PR: CHANGELOG and next development version

**release agent**: "Write the follow-up of the tagged release. VERSION=<VERSION>, PREVIOUS=<PREVIOUS>, TAG_COMMIT=<TAG_COMMIT>, VERSION_FILE=<VERSION_FILE>, NEXT_DEV=<NEXT_DEV>. Start from `origin/main`, add the CHANGELOG.md entry for VERSION (the commits `PREVIOUS..VERSION`), set NEXT_DEV in VERSION_FILE (skip when `none`), commit on `release/VERSION`, push it and open the PR. **Hard rule:** never tag, commit to main or force-push, because GitHub Free has no branch protection."

Then `cplat pr wait <PR URL> --merge` (never a polling loop, since the wait reruns a stuck check). The follow-up commit stays untagged (a later release ignores `chore(release): …`). If the agent or the merge fails, the release stays tagged: report the failure and the PR, keep the tag. Print `## Phase 6 complete — follow-up PR merged: <URL>`.

## Phase 7 — Close linked GitHub issues

Collect every `#NNN` (deduplicated) from the commit messages `git log "$PREV_TAG"..vX.Y.Z --format='%B'` (`PREV_TAG=$(git describe --tags --abbrev=0 vX.Y.Z^ 2>/dev/null)`; empty → `git log vX.Y.Z --format='%B'`), the PR bodies (`gh pr list --state merged --limit 50 --json number,body`) and the CHANGELOG entry. For each: `gh issue view <NNN> --json state,number -q '"\(.number) \(.state)"'`; `OPEN` → `gh issue close <NNN> --comment "Closed by release vX.Y.Z — see [CHANGELOG.md](../blob/main/CHANGELOG.md) for details."`; `CLOSED` → skip.

Print `## Phase 7 complete — issues closed: #42, #7 (2 closed, 1 already closed)` or `— no linked issues found`.

## Final Summary

```
## Release Pipeline Complete

Release target: vX.Y.Z on <commit> · Quality, Test (X% coverage), Security gates: PASS
Tag: vX.Y.Z pushed to origin on <commit>
Follow-up PR: <URL>: CHANGELOG entry, <VERSION_FILE> → <NEXT_DEV> (or "CHANGELOG only"), merged
Issues closed: #42, #7 (or "none")

Tagged commit: <commit> — the commit staging runs (sha-<commit>): CI re-tags that image X.Y.Z without a rebuild, so prod gets the digest staging tested (spec 106).
   (without staging: <commit> — main's head: <why from the target>, tagged after main's ci run on it passed.)
Version: the tagged commit's version file shows the previous development version; the release version is the tag vX.Y.Z. main now carries <NEXT_DEV> from the follow-up PR.
```

## Rules

- **Fail fast**; after Phase 1 a stop runs `git switch main` first, so the checkout is left on `main`.
- `git push origin v*` is pre-approved. **Phase 7 closes issues via `gh issue close`** (an `ask` permission: the user is prompted once before the closes).
- Never auto-fix quality, test or security failures (report and stop), so that the released code is what passed the gates; never force-merge (a failed merge goes to the user), because it needs the user's decision.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
