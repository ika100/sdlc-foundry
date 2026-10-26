# ADR-051 — Run state is per worktree

**Status:** accepted (2026-10-26)

## Context

`cplat` kept per-run state (`cplat-ship.json`, the app-ship state, the `cplat runs begin` pointer, the recovery
snapshot, pending replans) in `git rev-parse --git-common-dir`, which every worktree of a repo shares. One session's
ship run therefore blocked the Stop hook of every unrelated session in the same repo (one run blocked another
session eight times), and `runs.attach_point` could attach a build in one worktree to a run of another. Since
`cplat ship start` switches branches, sharing is also unsafe.

## Decision

- Per-run state lives in the checkout's own git dir (`git rev-parse --git-dir`, absolute), through `core.git_dir`.
  For the main checkout this is the same `.git`, so nothing migrates.
- The Stop hooks and the budget `PreToolUse` hook test the same location in shell.
- Two things stay in the common dir on purpose: the gitops merge slot (merges must serialise across every checkout of
  a gitops-app) and the validation evidence cache (keyed by content and merge base, so sharing is safe).

## Consequences

- A worktree does not see another checkout's run. A run started inside a worktree before this change must be resumed
  from the main checkout or restarted.
- Sessions in different worktrees no longer interfere through hooks or run attachment.
