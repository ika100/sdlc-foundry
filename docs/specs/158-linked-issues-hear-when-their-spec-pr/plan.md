---
spec_id: 158-linked-issues-hear-when-their-spec-pr
shape: platform
spec_hash: dacfc0268f89
summary: cplat comments on linked issues when their spec is written and approved, their PR merges and a release ships them
tasks:
  - id: t1
    title: Milestone comment core (gh seam, time limits, marker dedup, spec and PR texts)
    files: [scripts/cplat/milestones.py, tests/cplat/conftest.py]
    covers: [AC-158.1, AC-158.2, AC-158.3, AC-158.6, AC-158.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Release milestone (linked issues, texts, close, summary) and `cplat component release issues`
    files: [scripts/cplat/milestones_release.py, scripts/cplat/comprelease.py]
    covers: [AC-158.4, AC-158.5, AC-158.6, AC-158.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: spec publish and spec land post spec-written and spec-approved
    files: [scripts/cplat/spec_pr.py]
    covers: [AC-158.1, AC-158.2, AC-158.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: cplat merges post pr-merged (pr wait --merge, component ship land, system ship)
    files: [scripts/cplat/pr.py, scripts/cplat/ship.py, scripts/cplat/appship_merge.py]
    covers: [AC-158.3, AC-158.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t5
    title: cplat platform release posts released comments and closes issues
    files: [scripts/cplat/platrelease_publish.py]
    covers: [AC-158.4, AC-158.7]
    parallel_safe: true
    depends_on: [t2]
  - id: t6
    title: Release Phase 7 as one cplat call; spec, ship and system ship docs; ADR; changelog fragment
    files: [plugins/component/commands/release.md, plugins/component/commands/spec.md, plugins/component/commands/ship.md, plugins/system/commands/ship.md, docs/rules/plugins/component/commands/release.yml, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/system/commands/ship.yml, docs/rules/register.yml, docs/adr/README.md, docs/changelog.d/158-linked-issues-hear-milestones.added.md]
    covers: [AC-158.5, AC-158.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: Closing note of every other command names milestone comments; plugin versions
    files: [plugins/system/commands/status.md, plugins/system/commands/spec.md, plugins/system/commands/set.md, plugins/system/commands/restore.md, plugins/system/commands/plan.md, plugins/system/commands/new.md, plugins/system/commands/explore.md, plugins/system/commands/autonomy.md, plugins/resource/commands/upgrade.md, plugins/resource/commands/restore.md, plugins/resource/commands/remove.md, plugins/resource/commands/query.md, plugins/resource/commands/backup.md, plugins/resource/commands/add.md, plugins/platform/commands/update.md, plugins/platform/commands/ui.md, plugins/platform/commands/runs.md, plugins/platform/commands/retro.md, plugins/platform/commands/release.md, plugins/platform/commands/next.md, plugins/platform/commands/fleet.md, plugins/platform/commands/doctor.md, plugins/issue/commands/triage.md, plugins/instance/commands/verify.md, plugins/instance/commands/secret.md, plugins/instance/commands/promote.md, plugins/component/commands/verify.md, plugins/component/commands/set.md, plugins/component/commands/remove.md, plugins/component/commands/plan.md, plugins/component/commands/new.md, plugins/component/commands/explore.md, plugins/component/commands/check.md, plugins/component/commands/build.md, plugins/component/commands/add.md, plugins/cluster/commands/remove.md, plugins/cluster/commands/promote.md, plugins/cluster/commands/new.md, plugins/cluster/commands/add.md, plugins/api/commands/list.md, docs/rules/plugins/system/commands/status.yml, docs/rules/plugins/system/commands/spec.yml, docs/rules/plugins/system/commands/set.yml, docs/rules/plugins/system/commands/restore.yml, docs/rules/plugins/system/commands/plan.yml, docs/rules/plugins/system/commands/new.yml, docs/rules/plugins/system/commands/explore.yml, docs/rules/plugins/system/commands/autonomy.yml, docs/rules/plugins/resource/commands/upgrade.yml, docs/rules/plugins/resource/commands/restore.yml, docs/rules/plugins/resource/commands/remove.yml, docs/rules/plugins/resource/commands/query.yml, docs/rules/plugins/resource/commands/backup.yml, docs/rules/plugins/resource/commands/add.yml, docs/rules/plugins/platform/commands/update.yml, docs/rules/plugins/platform/commands/ui.yml, docs/rules/plugins/platform/commands/runs.yml, docs/rules/plugins/platform/commands/retro.yml, docs/rules/plugins/platform/commands/release.yml, docs/rules/plugins/platform/commands/next.yml, docs/rules/plugins/platform/commands/fleet.yml, docs/rules/plugins/platform/commands/doctor.yml, docs/rules/plugins/issue/commands/triage.yml, docs/rules/plugins/instance/commands/verify.yml, docs/rules/plugins/instance/commands/secret.yml, docs/rules/plugins/instance/commands/promote.yml, docs/rules/plugins/component/commands/verify.yml, docs/rules/plugins/component/commands/set.yml, docs/rules/plugins/component/commands/remove.yml, docs/rules/plugins/component/commands/plan.yml, docs/rules/plugins/component/commands/new.yml, docs/rules/plugins/component/commands/explore.yml, docs/rules/plugins/component/commands/check.yml, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/commands/add.yml, docs/rules/plugins/cluster/commands/remove.yml, docs/rules/plugins/cluster/commands/promote.yml, docs/rules/plugins/cluster/commands/new.yml, docs/rules/plugins/cluster/commands/add.yml, docs/rules/plugins/api/commands/list.yml, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/resource/.claude-plugin/plugin.json, plugins/platform/.claude-plugin/plugin.json, plugins/issue/.claude-plugin/plugin.json, plugins/instance/.claude-plugin/plugin.json, plugins/cluster/.claude-plugin/plugin.json, plugins/api/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-158.8]
    parallel_safe: false
    depends_on: [t6]
human_steps:
  - Before the next platform release, run the two benchmarks the eval gate asks for (quick-task and build), because t6 and t7 change command prompts.
---

# Plan — 158 Linked issues hear when their spec, PR and release land

The contract (texts, marker, gh calls, outputs) is in [design.md](design.md). Spec 157 should merge first so PR bodies
carry the summary block; this plan does not import 157's code (it reads the block), so the build does not wait for it.

## t1 — Milestone comment core (gh seam, time limits, marker dedup, spec and PR texts)

**Files:** scripts/cplat/milestones.py, tests/cplat/conftest.py
**Covers:** AC-158.1, AC-158.2, AC-158.3, AC-158.6, AC-158.7
**Goal:** one module that renders the spec-written, spec-approved and pr-merged comments and posts any milestone comment
under the marker, the 20 s / 120 s limits and per-issue error isolation, returning output lines instead of raising.

**Implementation notes:**
- `gh(args, *, cwd, timeout) -> (rc, out, err)` on `subprocess.run` directly (never `core.run`, design Decisions);
  `clock()` = `time.monotonic`; a module-level step budget started at the first call, `reset()` for tests.
- `post(repo, slug, issues, milestone, key, body, close=False)`: the four gh calls per issue of design "gh calls per
  issue", each with `timeout = min(issue deadline, step deadline) - clock()`; no time left → `note:` with
  `comment step time limit (120s) reached` (or `timed out after 20s`) and the rest skipped. `try/except Exception` per
  issue. Returns `(lines, status_by_issue)`.
- Marker line `<!-- cplat:milestone <milestone> <key> -->` appended as the body's last line; dedup by substring.
- Skip silently: `pull_request` in the issue JSON, labels `auto-filed|notify|retro`; tracks entries with `/` dropped.
- `spec_written(root, spec, branch, pr_url)`, `spec_approved(root, spec)`: slug and default branch from one
  `gh repo view --json nameWithOwner,defaultBranchRef`; first story (≤400 chars, `…`), `len(spec.active_acs())`,
  `spec.open_questions()` (≤5, `… and <k> more`, else `No open questions.`), approval date from `## Changelog`.
- `pr_merged(repo, pr)`: `gh pr view <pr> --json number,url,title,body`; closing references by the keyword regex of
  design; `Changed`/`Why` from the `<!-- cplat:summary -->` block, else PR title / `not recorded`.
- Every entry point wraps its own reads in `try/except Exception` and returns lines; it never changes a caller's result.
- `tests/cplat/conftest.py`: autouse fixture `no_real_milestone_comments` that saves `milestones.REAL_GH` once and
  replaces `milestones.gh` with a stub answering `(127, "", "tests never call GitHub")`, and calls `milestones.reset()`;
  acceptance tests install their own fake after it.

**Done when:** the acceptance tests of AC-158.6 and AC-158.7 that call `milestones` directly pass, and the text tests of
AC-158.1 to AC-158.3 that render through `spec_written`, `spec_approved` and `pr_merged` pass.

## t2 — Release milestone (linked issues, texts, close, summary) and `cplat component release issues`

**Files:** scripts/cplat/milestones_release.py, scripts/cplat/comprelease.py
**Covers:** AC-158.4, AC-158.5, AC-158.6, AC-158.7
**Goal:** the issues linked to a release get one `Fixed in vX.Y.Z` comment and open ones are closed; one call prints the
Phase 7 summary.

**Implementation notes:**
- `released(repo, version, previous=None) -> Result(lines, issues, summary)`, never raises: previous tag by
  `git describe` (design "Linked issues"); git calls through a local seam with a timeout from the same step budget
  (`milestones` exposes the remaining time).
- Merged PRs: one `gh pr list … --json number,title,body,url,mergeCommit` filtered to `git rev-list <prev>..<tag>`; a
  failed list gives `note: issue comment skipped: merged PRs of vX.Y.Z: <why>` and the fragments alone.
- Fragments `docs/changelog.d/<N>-*.md` at `<tag>` and `<tag>^` (`git ls-tree`, `git show`), kept when the text has `#<N>`.
- `<what>` from the changelog section at `origin/main` (after `git fetch -q origin main`), else the PR's `Changed`, else
  its title (≤300 chars); `<how>` by shape (`shapecmd.route(repo)["shape"] == "platform"`).
- `milestones.post(..., close=True)`; summary line and `--json` exactly as design "cplat component release issues".
- `comprelease.main`: subparser `issues` (`--version`, `--previous`, `--repo`, `--json`); exit 0 with notes, 2 on an
  unknown tag.

**Done when:** the acceptance tests of AC-158.4 and AC-158.5 against `cplat component release issues` pass.

## t3 — spec publish and spec land post spec-written and spec-approved

**Files:** scripts/cplat/spec_pr.py
**Covers:** AC-158.1, AC-158.2, AC-158.7
**Goal:** the two spec milestones are posted from the commands that talk to GitHub (A4).

**Implementation notes:**
- `publish`: after the PR number and URL are known, `info["issue_comments"] = milestones.spec_written(root, spec, branch, url)`.
- `main` publish: text mode prints each line after the URL line; `--json` carries the key.
- `land`: keep publish's lines; after `pr.wait` returns ok, add `milestones.spec_approved(root, spec)`; a red or failed
  land posts nothing. Return `(ok, publish lines + wait lines + approved lines)`.
- Exit codes and the existing lines stay as they are.

**Done when:** the acceptance tests of AC-158.1 and AC-158.2 through `cplat spec publish` / `cplat spec land` pass, and
the existing `spec_pr` tests still pass.

## t4 — cplat merges post pr-merged (pr wait --merge, component ship land, system ship)

**Files:** scripts/cplat/pr.py, scripts/cplat/ship.py, scripts/cplat/appship_merge.py
**Covers:** AC-158.3, AC-158.7
**Goal:** every merge `cplat` performs or finds done posts the pr-merged comment; nothing else does (A5).

**Implementation notes:**
- `pr.wait`: when `merge` and the result is ok (merged now, or `already merged`), append `milestones.pr_merged(repo, url)`.
  A plain wait (no `--merge`) posts nothing.
- `ship._merged`: append `milestones.pr_merged(repo, st["pr"])` after the merge is saved; covers a fresh merge and a
  resumed run that finds the PR merged.
- `ship.merge_gitops`: after `info["merged"] = True`, append `milestones.pr_merged(repo, pr)` for the gitops-task PR.
- `appship_merge.land`: on both success returns (`already merged`, `merged`), append `milestones.pr_merged(gitops_dir, pr)`.
- Nothing moves before the merge is recorded; the lines are only appended.

**Done when:** the acceptance tests of AC-158.3 pass and the existing pr wait, ship land and system ship tests still pass.

## t5 — cplat platform release posts released comments and closes issues

**Files:** scripts/cplat/platrelease_publish.py
**Covers:** AC-158.4, AC-158.7
**Goal:** `cplat platform release` runs the release milestone once the GitHub release exists.

**Implementation notes:**
- In `continue_from`, after the `release: <url>` line and before `_guard` (every phase that reaches it, so a resumed run
  posts what is missing): `milestones_release.released(repo, version)`; print its lines and its summary with the prefix
  `release issues — `; with any `note:` line add `  post the missing ones: cplat component release issues --version v<X.Y.Z>`.
- The return code and the `RELEASED:` block stay unchanged.

**Done when:** the acceptance tests of AC-158.4 for the platform release pass and the existing platform release tests pass.

## t6 — Release Phase 7 as one cplat call; spec, ship and system ship docs; ADR; changelog fragment

**Files:** plugins/component/commands/release.md, plugins/component/commands/spec.md, plugins/component/commands/ship.md, plugins/system/commands/ship.md, docs/rules/plugins/component/commands/release.yml, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/system/commands/ship.yml, docs/rules/register.yml, docs/adr/README.md, docs/changelog.d/158-linked-issues-hear-milestones.added.md
**Covers:** AC-158.5, AC-158.8
**Goal:** the command docs say `cplat` posts the milestone comments without asking; Phase 7 is one call; the ADR and the
changelog entry exist.

**Implementation notes:**
- Run `cplat adr add milestone-comments-on-linked-issues-need-no-per-comment-ok --decision "cplat posts a milestone comment on an issue a spec tracks or a PR closes without a per-comment OK; it never files issues"`; fill Context (#428, ADR-033, the user's answer of 2026-11-08), Decision (linked = tracks / closing reference / fragment; fixed texts from records; marker dedup), Consequences. The new `docs/adr/<n>-….md` belongs to this task.
- `release.md` Phase 7: one line, run `cplat component release issues --version <VERSION>` and show its output; it
  prints the `## Phase 7 complete — …` line. Remove every `gh issue close` and the Rules line about it. Final Summary keeps `Issues closed:`.
- `component/spec.md` (publish and land steps), `component/ship.md` (land), `system/ship.md` (land): one short sentence
  each that `cplat` comments on linked issues itself, without asking.
- Closing note of these four files (where present) and of `register.yml`'s `issue-filing-needs-consent` source: the tail
  becomes ``the platform posts only `platform` escalations and milestone comments itself.`` (ADR references move to the
  register entry's `source`: `ADR-033, ADR-<n>`). Update the quoting register entries.
- Changelog fragment names #568 (`(#568).`) per `docs/changelog.d/README.md`; says users need `/plugin marketplace update`.
- Prompt bytes must not grow (docs/rules/README.md rule 6): the shorter Phase 7 pays for the new sentences; check with
  `cplat platform rules check`.

**Done when:** `cplat platform rules check` passes, the doc acceptance tests of AC-158.5 and AC-158.8 pass, and
`release.md` has no `gh issue close`.

## t7 — Closing note of every other command names milestone comments; plugin versions

**Files:** the 40 command prompts and their 40 register files listed in the metadata, the plugin.json of component,
system, resource, platform, issue, instance, cluster and api, .claude-plugin/marketplace.json
**Covers:** AC-158.8
**Goal:** every command's closing note names milestone comments next to `platform` escalations as what the platform posts.

**Implementation notes:**
- In each listed command, replace ``a `platform` escalation is the one issue the platform files itself (ADR-033).`` with
  the t6 wording (one byte shorter); update the quoting entry in its register file (`source: "ADR-033, ADR-<n>"`, the
  number t6 created). `component/commands/build.md` has the note but its register file may not quote it: change what is there.
- Agent prompts keep their note (the spec names the commands).
- Bump minor versions of the eight plugins in their `plugin.json` and in `marketplace.json` (both places, CLAUDE.md).

**Done when:** `cplat platform rules check`, `devbox run validate` and the AC-158.8 doc test pass; no command prompt still has
`the one issue the platform files itself`.
