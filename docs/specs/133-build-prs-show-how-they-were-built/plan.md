---
spec_id: 133-build-prs-show-how-they-were-built
shape: platform
spec_hash: 856b2a399102
summary: "New scripts/cplat/runs_built.py finds a run on this machine (active record, else the local buffer, plus the runs it resumes), collects how it ran (wall time, execution mode, re-plans, CI rounds, gates, budget ledger, agents), user decisions (budget changes, decision escalations, refused test diffs, the #324 approved_test_diffs hook, answered open questions), hand-backs (fix-round, red-ci, finding, tester, merge-conflict, re-plan events) and accepted deviations from verification.md, and renders a redacted, capped, collapsed block between markers; `cplat platform runs report --pr <run-id>` prints it; `cplat platform runs agent execution` records the sequential fallback; `cplat pr open` appends or replaces the block when the checkout has a run for the spec and never fails because of it"
tasks:
  - id: t1
    title: runs_built.py (find, collect, render, pr_section) and the `--pr` option of `cplat platform runs report`
    files: [scripts/cplat/runs_built.py, scripts/cplat/runs.py]
    covers: [AC-133.1, AC-133.2, AC-133.3, AC-133.4, AC-133.5, AC-133.6, AC-133.7, AC-133.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "`cplat platform runs agent execution parallel|sequential [--reason]` and the calls in /component:build and the worktree fallback reference"
    files: [scripts/cplat/runs_agents.py, plugins/component/commands/build.md, plugins/component/references/build-worktree-fallback.md]
    covers: [AC-133.9, AC-133.13]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: "`cplat pr open` appends or replaces the block, ignores a run for another spec, never fails because of it"
    files: [scripts/cplat/pr_open.py]
    covers: [AC-133.10, AC-133.11, AC-133.12]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: /platform:runs names `--pr`, CHANGELOG entry for #338
    files: [plugins/platform/commands/runs.md, docs/CHANGELOG.md]
    covers: [AC-133.13]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 133 Build PRs show how they were built

Contract: [design.md](design.md). ADR: [079](../../adr/079-a-pr-shows-how-it-was-built-from-the-run-records.md). The acceptance
tests (`tests/cplat/test_runs_built_133.py`) are written before t1 starts; no task edits them.

Order: t1, t2 and t4 are independent; t3 calls t1's `pr_section`. Spec 131 (open PR #379) changes `runs_report.aggregate`,
`runs.py`'s `end` branch and `pr_open.pr_allowed`; this plan touches none of those functions.

## t1 — runs_built.py and `report --pr`

**Files:** scripts/cplat/runs_built.py (new), scripts/cplat/runs.py
**Covers:** AC-133.1 to AC-133.8
**Goal:** the block of design.md from the local records.

**Implementation notes:**
- `find(run_id) -> dict | None`: `runs.active`, else the last buffered record with that `run_id`; `chain(rec)` follows `resumes`.
- `collect(rec, repo) -> dict` and `render(facts) -> str`; every string through `feedback.redact`, cut to 200 characters; 10 lines per list.
- Budget: the ledger whose `roots` holds the run id (or its root), `budget.used_of(data)` in a try; `changes` → decisions.
- Deviations: parse `## Deviations from the plan` of `docs/specs/<spec>/verification.md` (top-level `-` or `1.` items).
- `pr_section(repo, spec) -> str | None` for t3.
- `runs.py`: `--pr RUN_ID` and `--dir` on `report`; `_report` dispatches before it asks for a store; refuses the combinations of AC-133.2.

**Done when:** the AC-133.1 to AC-133.8 tests pass.

## t2 — the `execution` call

**Files:** scripts/cplat/runs_agents.py, plugins/component/commands/build.md, plugins/component/references/build-worktree-fallback.md
**Covers:** AC-133.9, AC-133.13
**Goal:** record whether the tasks ran in parallel or sequentially and why.

**Implementation notes:**
- `execution(run_id, repo, mode, reason=None)` sets the top-level `execution` section; a bad mode is malformed.
- build.md step 2.2: after the probe, `cplat platform runs agent execution parallel` or `... sequential --reason '<why>'`; Phase 7
  says `cplat pr open` adds the "How this was built" block. The fallback reference names the call with the reason.

**Done when:** the AC-133.9 and the build.md part of the AC-133.13 tests pass.

## t3 — `cplat pr open`

**Files:** scripts/cplat/pr_open.py
**Covers:** AC-133.10 to AC-133.12
**Goal:** the block in the PR body without ever blocking the PR.

**Implementation notes:**
- After the WIP note: `runs_built.pr_section(repo, o.spec)` in a try; replace a marked block or append; on an exception add the note.

**Done when:** the AC-133.10 to AC-133.12 tests pass and `tests/cplat/test_pr_open.py` stays green.

## t4 — docs

**Files:** plugins/platform/commands/runs.md, docs/CHANGELOG.md
**Covers:** AC-133.13
**Goal:** `/platform:runs` names `--pr`; a changelog entry under `[Unreleased]` → `### Added`.

**Done when:** the AC-133.13 tests pass.
