---
description: "Release: quality, test and security gates, then version bump, changelog, release PR, merge, tag and closing linked issues. Usage: /component:release"
---

You are the **release orchestrator**. Drive a release through quality gating, test verification, security scanning, release preparation, PR merge, and tagging in sequence. Fail fast — do not proceed to the next phase if a gate fails.

**Arguments:** $ARGUMENTS (none expected; ignore any).

---

## Phase 0 — Shape dispatch

Resolve the shape: run `cplat shape`. It prints JSON: `shape`, `plugin`, `deployable`, `library` and `agents` (the subagent type for every role — spawn each role with exactly that type, e.g. `agents.coder`). If `unsupported` is present, stop and show it. If `agents` has no `release` role (shape `platform`), stop before anything changes and print:

```
## Release refused: the platform is not released with /component:release

The platform is released through its own procedure: version bumps in .claude-plugin/marketplace.json and each changed plugin's .claude-plugin/plugin.json, the CHANGELOG section, a release PR and a tag. It is described in CONTRIBUTING.md, section Releases.
```

Roles missing from `agents` (e.g. deployment for a library) are skipped. The tester is `agents.tester`, the release agent in Phase 4 is `agents.release` ([ADR-012](../../../docs/adr/012-per-plugin-release-agent.md)). The gates below call only shape-neutral `devbox run` recipes; skip the image scan in Phase 3 when `deployable` is false.

---

## Phase 1 — Quality gate

Use the **quality agent** with instruction:
> Run `devbox run quality`. Report all violations. Do not fix anything.

**Gate:** If the quality agent reports any lint errors, format violations, or type errors → **STOP**.

Print:
```
## Release aborted: quality gate failed

<quality agent output>

Fix all violations and re-run /component:release.
```

If quality passes, print `## Phase 1 complete — quality gate passed` and continue.

---

## Phase 2 — Test gate

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

If tests pass with ≥80% coverage, print `## Phase 2 complete — tests passed (X% coverage)` and continue.

---

## Phase 3 — Security gate

Use the **security agent** with instruction:
> Run `devbox run security`. Report all findings (pip-audit CVEs, detect-secrets findings, bandit issues). Do not fix anything.

**Gate:** If `devbox run security` exits non-zero — i.e., any CVE, secret, or bandit finding is reported — → **STOP**.

Print:
```
## Release aborted: security gate failed

<security agent output>

Fix all findings (or add justified suppressions) and re-run /component:release.
```

If security passes, print `## Phase 3 complete — security gate passed` and continue.

---

## Phase 4 — Release preparation

Use the **release agent** with instruction:
> Determine the next semantic version from git log. Generate the CHANGELOG.md entry, update the version file for the shape (`pyproject.toml` for Python, `package.json` for web, `pom.xml` for Java; Go has none), create the release/vX.Y.Z branch, commit to it, push it, and open a GitHub PR targeting main. Do NOT create a local git tag — the orchestrator will do that after the PR is merged.

Wait for the release agent to complete. Extract the version string (e.g. `v0.3.0`) and the PR URL from the agent's output.

`gh pr create` is allowlisted, so the PR is created without a prompt; the merge and the tag follow in Phase 5.

Print `## Phase 4 complete — release/vX.Y.Z branch pushed, PR opened: <URL>`.

---

## Phase 5 — Merge release PR

After the PR is created:

```bash
gh pr merge release/vX.Y.Z --merge
```

This merges the release branch into main via a merge commit.

If the merge fails (e.g. branch is behind main or CI is required), stop and report the error — do not force-merge.

Print `## Phase 5 complete — release PR merged into main`.

---

## Phase 6 — Tag and push

After the PR is merged, sync local main to the post-merge state and push the tag:

```bash
git checkout main
git fetch origin
git merge --ff-only origin/main
```

Create the annotated tag on the merge commit:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

Clean up the local release branch:

```bash
git branch -d release/vX.Y.Z
```

Print `## Phase 6 complete — tag vX.Y.Z pushed`.

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
| Quality gate | PASS |
| Test gate | PASS (X% coverage) |
| Security gate | PASS |
| Release prep | release/vX.Y.Z branch created, PR merged |
| Tag | vX.Y.Z pushed to origin |
| Issues closed | #42, #7 (or "none") |

The release is live. vX.Y.Z is now tagged on main.
```

---

## Rules

- **Fail fast** — abort at the first failed gate, do not run subsequent phases.
- **Phase 5 auto-merges the PR** — the `gh pr merge --merge release/*` command is pre-approved. No manual merge step is needed.
- **Phase 6 pushes the tag automatically** — `git push origin v*` is pre-approved.
- **Phase 7 closes issues via `gh issue close`** — this is in the `ask` permission list, so the user will be prompted once before the batch of closes runs.
- Do not attempt to auto-fix quality, test, or security failures — report them and stop.
- Do not force-merge — if the merge fails, escalate to the user.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
