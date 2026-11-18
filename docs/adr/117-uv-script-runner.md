# ADR-117: Uv script runner

**Status:** Proposed (2026-11-17)

## Context

`uv run <script>.py` keys the persistent script environment of a script with a `# /// script` block by the script's
absolute path. Every worktree and clone of a repo therefore adds one environment per inline script to uv's cache, and
nothing removes them. Spec 209 asks for one environment per dependency list, whatever the path.

## Decision

Inline scripts in cplat and recipes run through uv-script.sh, keyed by their dependencies, not their path.

The helper runs `uv run --no-project --with-requirements <script>.py python <script>.py`, so uv's cached `--with`
environment (keyed by the resolved requirements and the interpreter) is used, while the script still runs from its own
path. A script without a PEP 723 block keeps plain `uv run`. cplat calls the platform's own copy by absolute path; the
template copies are kept equal by `sync-template-copies.py`. GitHub Actions workflows stay unchanged (fresh runner per job).

## Consequences

- Worktrees and clones share script environments; the cache grows with the number of distinct dependency lists only.
- A new inline script is run through the helper, never with a bare `uv run <script>.py`.
- The helper depends on uv accepting a `.py` file in `--with-requirements`; the design records a fallback (`--with` per
  dependency) if a uv version rejects it.
