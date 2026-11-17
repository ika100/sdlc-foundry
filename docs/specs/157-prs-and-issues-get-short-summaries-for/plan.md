---
spec_id: 157-prs-and-issues-get-short-summaries-for
shape: platform
spec_hash: 77f987e5867a
summary: cplat renders a four-line summary block from records at the top of every PR body it opens (pr open, component ship, system ship)
tasks:
  - id: t1
    title: Add pr_summary and put the block on top of every cplat pr open body
    files: [scripts/cplat/pr_summary.py, scripts/cplat/pr_open.py, tests/cplat/test_runs_built_133.py]
    covers: [AC-157.1, AC-157.2, AC-157.3, AC-157.4, AC-157.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Component ship PRs get the summary block
    files: [scripts/cplat/ship.py]
    covers: [AC-157.5, AC-157.6]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: System ship gitops PRs get the summary block of the system spec
    files: [scripts/cplat/appship.py, scripts/cplat/appship_joint.py]
    covers: [AC-157.5, AC-157.6]
    parallel_safe: true
    depends_on: [t1]
  - id: t4
    title: Commands say cplat writes the summary; changelog and plugin versions
    files: [plugins/component/commands/build.md, plugins/component/references/build-pr.md, plugins/component/commands/ship.md, plugins/system/commands/ship.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/build-pr.yml, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/system/commands/ship.yml, docs/changelog.d/568-pr-summary.added.md, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-157.7]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 157 Build and ship PRs start with a short summary

The contract is in [design.md](design.md). Level 1 has t1 and t4, and level 2 has t2 and t3. t2 and t3 import `pr_summary` from t1
and share no file with each other.

## t1 — Add pr_summary and put the block on top of every cplat pr open body

**Files:** scripts/cplat/pr_summary.py, scripts/cplat/pr_open.py, tests/cplat/test_runs_built_133.py
**Covers:** AC-157.1, AC-157.2, AC-157.3, AC-157.4, AC-157.5
**Goal:** Create the module that renders the four-line block purely from records, exactly as in design.md's Contract, and call it
from `cplat pr open`. Every body `pr open` sends then starts with the block, with or without a run.

**Implementation notes:**
- `pr_summary.py` holds `START`, `END`, `MAX_LINE`, `MAX_ITEMS`, `render`, `apply` and `add` with the signatures in design.md. It
  imports from `runs_built` (`find`, `_events`, `_same_spec`, `_section`, `accepted_deviations`), `runs.current_run`, `spec`
  (`find`, `active_acs`, `_verdicts`), `pr_rules.CLOSES` and `feedback.redact`. Do not change `runs_built.py`.
- Changed: spec title, else the fragment's first sentence without emphasis, else the PR title. Add the `(<n> criteria of spec <NNN>,
  <m> files)` suffix. `m` is the union of `git diff --name-only <base>...HEAD` and `git status --porcelain`. An unknown `--spec`
  raises, so the block is skipped.
- Why: the first story's `so that` clause, else `Closes #N: <title>` from the body's closing lines (via `gh issue view`, falling back
  to `Closes #N` when that fails), at most 3, else `not recorded`.
- Review, and Risks and follow-ups: follow design.md's definitions of state, f, sev, x, d and the Risks items. That includes the
  `## Follow-ups` parser with first sentence and continuation lines.
- Every value goes through redaction and then onto one line, with `<!--` and `-->` removed. Each line is capped at 300 characters
  with `…`.
- `add` catches every exception and returns the body unchanged plus `note: summary skipped: <Type>: <message>`, at most 200 characters.
- In `pr_open.open_pr`, add `_summary(repo, o, body_path, base_ref, res)` right after `_how_built(...)`. It writes the file only when
  the text changed and appends the note to `res.notes`. Update the module docstring with one line about the summary.
- `tests/cplat/test_runs_built_133.py`: AC-157.1 supersedes the "body unchanged" part of AC-133.11. The three AC-133.11 tests and the
  AC-133.12/`startswith("## Summary…")` assertions compare the body with the summary block removed (`pr_summary.apply`'s removal, or a
  regex on `START…END`). Their how-built assertions stay as they are.
- Run `tests/cplat/test_pr_open.py`, `test_pr_body_staging.py`, `test_runs_built_133.py` and `test_171_pr_check_tracks.py`. Fix only
  assertions that compare a whole body, and never this spec's acceptance tests.

**Done when:** the AC-157.1 to AC-157.5 tests that go through `cplat pr open` or `pr_summary` pass, `test_runs_built_133.py` and
`test_pr_open.py` are green, and `devbox run quality` passes.

## t2 — Component ship PRs get the summary block

**Files:** scripts/cplat/ship.py
**Covers:** AC-157.5, AC-157.6
**Goal:** The PR that `cplat component ship pr` opens or updates starts with the block for the clone's repo spec and branch. This is
also the component-repo PR of a `/system:ship`, whose repos ship in their own `/component:ship` session. The "How this was built"
rule of `_built_block` stays as it is.

**Implementation notes:**
- Add `_summary(repo, st, title, body, body_file) -> str` next to `_built_block`. The base is `origin/main` when it resolves, else
  `main`. It calls `pr_summary.add(repo, body, title=title, spec=st["spec"], base=base)`, writes `body_file` when changed and prints
  the note with `say`.
- In `open_pr`, call it right after `original_body = body` and before `_built_block`. An existing PR then gets `gh pr edit --body-file`
  through the existing `body != original_body` branch.
- Run `test_ship.py`, `test_ship_pr_126.py`, `test_175_ship_pr_closes.py`, `test_ship_draft_pr_ready.py`,
  `test_ship_no_duplicate_pr_452.py`, `test_200_helper_fix.py` and `test_141_no_new_questions.py`. They must stay green. A fake `gh`
  that fails on `issue view` only drops the issue title.

**Done when:** the AC-157.6 tests for component-repo PRs pass, and the ship test files above are green.

## t3 — System ship gitops PRs get the summary block of the system spec

**Files:** scripts/cplat/appship.py, scripts/cplat/appship_joint.py
**Covers:** AC-157.5, AC-157.6
**Goal:** Every PR that `/system:ship` creates in the gitops repo starts with the block rendered for the system spec and that branch.
That covers publish, the entry, the joint dev PR, staging and complete. No "How this was built" block is added.

**Implementation notes:**
- `appship.open_pr(repo, branch, title, body, *, spec: str)`. For a new PR only, it sends `pr_summary.add(repo, body, title=<fitted
  title>, spec=spec, base="origin/main")[0]` and prints the note. An existing PR is returned as today.
- Pass `spec=sid` in `publish` and `complete`, and `spec=spec_id` in both `appship_joint` calls (the dev PR and the staging PR).
- In `entry_pr`, for a new PR, build the body from `--body-file` or from `entry_body(...)`. Add the block with `repo=wt`,
  `spec=st["spec"]` and `base="origin/main"`, then send it with `--body`. Write no file.
- Run `test_appship_097.py` and `test_144_joint_pr.py`. They must stay green.

**Done when:** the AC-157.6 tests for gitops PRs pass, and `test_appship_097.py` and `test_144_joint_pr.py` are green.

## t4 — Commands say cplat writes the summary; changelog and plugin versions

**Files:** plugins/component/commands/build.md, plugins/component/references/build-pr.md, plugins/component/commands/ship.md,
plugins/system/commands/ship.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/build-pr.yml,
docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/system/commands/ship.yml, docs/changelog.d/568-pr-summary.added.md,
plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-157.7
**Goal:** `/component:build`, `/component:ship` and `/system:ship` each state that `cplat` adds the summary block at the top of the PR
body and that the orchestrator does not write one. The changelog gains an entry for #568.

**Implementation notes:**
- Write one statement, not a new instruction, in `build.md` (Phase 7 line), `build-pr.md` ("Open it"), component `ship.md`
  (Phase `pr`) and system `ship.md` (Phase `repos` or `complete`). For example: "`cplat` puts a generated **Summary** block (changed,
  why, review, risks) at the top of the body; the orchestrator writes none." Leave the orchestrator's `## Summary` template text
  unchanged (non-goal).
- Prompts may not grow (rules register, rule 6), so shorten other sentences in the same files by at least the bytes you add, without
  changing what they ask.
- Run `cplat platform rules check --only <file>` for each prompt. Add or update register entries in the four `docs/rules/...yml` files
  only where the check asks for it.
- Write `docs/changelog.d/568-pr-summary.added.md`, one paragraph in the style of the existing fragments. Name the four lines, say that
  they come from records with no agent text, and cover `cplat pr open`, the component ship and the system ship. Link spec 157.
- Bump the component plugin 1.23.0 → 1.24.0 and the system plugin 1.21.0 → 1.22.0, or the next minor of what `main` holds, in both
  `plugin.json` files and `.claude-plugin/marketplace.json`.

**Done when:** the AC-157.7 test passes, `cplat platform rules check` passes, and `devbox run validate` passes.
