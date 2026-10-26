# Design — 111 Unattended runs spend turns only on judgement

## Decisions

- **`cplat ship continue` is a composition, not a new state machine** (AC-111.1, AC-111.2). It calls the existing
  `land(repo, …)`; if that returns ok it calls `deploy(repo, …)` with the same options (`--timeout`, `--interval`,
  `--queue-timeout`, `--context`, `--base-url`), printing both line lists in order. Exit codes: 0 when deploy ends
  done, 1 when land is red (the coordinator starts a fix round, then `cplat ship land` and, when green, `cplat ship
  deploy` or `continue` again), 2 when the run is escalated (state `escalated`), so the coordinator can tell the three
  apart without parsing. Every rule lives in `land` and `deploy` and so holds unchanged: merge on green only, the
  budget safe points (`set_phase`, `allow_rerun`), the deploy gate and the record. A phase that is already past
  (`deploy` or `done`) is skipped, so `continue` after a deploy-only resume runs just `deploy`.
- **ship.md** (AC-111.3): the step after `cplat ship pr` becomes one `cplat ship continue` with the meaning of exit
  0/1/2; the existing red-round reference (`references/ship-land-red.md`) keeps `cplat ship land` for the resume after
  a fix. The command file must stay under spec 100's size cap, so the two old step paragraphs shrink into the one.
- **Headless sessions load only the repo's MCP** (AC-111.4–AC-111.6). `headless.claude_cmd` always adds
  `--strict-mcp-config`, `--mcp-config <repo>/.mcp.json` when that file exists, `--mcp-config <file>` for
  `headless: {mcp_config: <file>}` in `.platform-settings.yml` (path relative to the repo, must exist, else
  PlatformError naming the setting), and `disableClaudeAiConnectors: true` merged into the `--settings` JSON it already
  passes for plugin dirs (one `--settings` argument). `cplat runs benchmark` goes through `headless`, so it gets the
  same. Interactive sessions are not started by cplat and stay as they are.
- **The inline check is code** (AC-111.7–AC-111.9). New `cplat quick-task inline-check [--base REF]` (module
  `quicktask.py`) reads `git diff --numstat <base>...HEAD` plus the working tree and untracked files. Allowed: at most
  one non-test source file and at most one test file (test = the shape's `test_globs` from `shapes.yml`), at most 60
  added+removed lines, and none of: dependency manifests and lock files (the list of spec 103's `mandatory`
  categories, reused from `validate.py`), `.github/**`, `Dockerfile*`, `.claude/**`, `.platform-settings.yml`,
  `docs/specs/**`. Exit 0 prints `inline: allowed (<n> files, <m> lines)`; exit 1 prints `inline: refused — <rule>`.
  quick-task.md: the coordinator may make a change itself only if the check passes, then runs `cplat quiet
  quality` and `cplat quiet test-fast` itself (both must be green), and states "made inline: <check line>" in the PR
  body; on exit 1 or a red gate it hands the task to the coder → quality → tester path and never retries inline.
- **Measurement** (AC-111.10): each part is merged only with its benchmark in `benchmarks.md`. Order: session start
  (cheapest to measure, affects every later run), then the quick-task path, then `ship continue`. Runs use
  `--plugins <worktree>/plugins`, `CPLAT_PLATFORM=<worktree>` and `CPLAT_KUBE_CONTEXT=truenas-k8s` for ships.

## Contract

```
cplat ship continue [--timeout S] [--interval S] [--queue-timeout S] [--context C] [--base-url URL]   exit 0 done | 1 red | 2 escalated
cplat quick-task inline-check [--base REF]                                                             exit 0 allowed | 1 refused
.platform-settings.yml: headless: {mcp_config: <path>}
claude -p … --strict-mcp-config [--mcp-config .mcp.json] [--mcp-config <extra>] --settings '{"disableClaudeAiConnectors": true, …}'
```
