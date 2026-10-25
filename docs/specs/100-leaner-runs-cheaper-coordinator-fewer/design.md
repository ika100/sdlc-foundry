# Design — 100 Leaner runs: cheaper coordinator, fewer turns, smaller context

## Decisions

- **Coordinator model is resolved by cplat, always passed as `--model`.** `cplat headless` decides the model before the
  first session and always adds `--model <alias>` to `claude -p`, so the session never falls back to the user's
  default (Opus). Default `sonnet`. Subagents keep their frontmatter model: `architect`, `reviewer`,
  `product-manager` (and `app:planner`) say `model: opus`, and `--model` only sets the main session's model
  (CLI reference: "`--model` Sets the model for the current session"). AC-100.6 needs no code, only a test that pins
  those frontmatter values. ADR: [036](../../adr/036-coordinator-model-default-and-settings.md).
- **No settings loader existed.** cplat had only environment variables for user configuration (`CPLAT_RUNS_REPO`,
  `CPLAT_FEEDBACK_REPO`, …) and per-repo YAML files it reads ad hoc (`.platform-app.yml`, `.platform-version`). The
  coordinator model needs a committed project setting and a personal user setting with the same shape, so one small
  module `scripts/cplat/settings.py` reads both. Later settings (budgets, #144) go in the same files.
- **Steps are measured before release with the worktree's plugins (`--plugins`).** Verified in the Claude Code docs
  (2026-10-25):
  - CLI reference (code.claude.com/docs/en/cli-reference): "`--plugin-dir` Load a plugin from a directory or `.zip`
    archive … for this session only. Each flag takes one path. Repeat the flag for more paths."
  - Plugin loading reference, "Name conflicts" (code.claude.com/docs/en/plugins/loading#name-conflicts): "An enabled
    `--plugin-dir` … plugin … replaces a same-named installed marketplace plugin … replaced silently", unless managed
    settings lock the id (not the case on this machine). No clash: the worktree's `svc` and `shared` replace the
    installed `svc@sdlc-foundry` and `shared@sdlc-foundry` for that session only.
  - `--plugin-dir` plugins load in place, so `${CLAUDE_PLUGIN_ROOT}` is the worktree folder and the shared plugin's
    `bin/cplat` launcher already resolves `source=in-place` to the worktree's `scripts/cplat` (resolution step 3 of
    `plugins/shared/bin/cplat`). Commands and cplat are both the worktree's.
  - Reads under `${CLAUDE_PLUGIN_ROOT}` (ship reads build.md, step 4 adds reference files) are allowed by the
    template's `Read(~/.claude/plugins/**)` only for installed plugins, so headless adds one inline
    `--settings '{"permissions":{"allow":["Read(/<abs dir>/**)"]}}'` rule per plugin dir (`//path` is an absolute
    path in permission rules; `--settings` takes "a settings JSON file or an inline JSON string").
  Each step's benchmark therefore runs before any release, with `--plugins <worktree>/plugins`, and the record says
  which plugins ran.
- **One finishing command: `cplat pr open`.** It commits (always `-s`), pushes and opens the PR, and also does the two
  deterministic steps around it that cost the coordinator turns today: collecting the `Closes #N` lines and the WIP
  note. It is safe to run again: a clean tree is not committed twice, an open PR is never duplicated.
- **cplat bundles never widen the session's permissions.** `Bash(cplat *)` is allowlisted, so a cplat command that
  pushes or opens PRs must apply the same limits the allowlist gives the separate commands: push only the branch
  prefixes the templates allow, open a PR only when `gh pr create` is allowed in the repo's settings, and run no
  free-form command. ADR: [037](../../adr/037-cplat-bundles-honour-the-allowlist.md).
- **Quiet output through `cplat quiet <devbox-script>`**, not through shell redirection: redirection and pipes are not
  allowlisted, and a wrapper works for every shape. The full log is a file the agent can read on failure.
- **Rare branches move to `plugins/svc/references/`**, a folder that is not a component directory (a file under
  `commands/` would become a command). The normal path keeps one line per moved branch: the trigger and
  "read `${CLAUDE_PLUGIN_ROOT}/references/<file>` and follow it".

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/settings.py` | read project and user settings, validate and resolve the coordinator model | new |
| `scripts/cplat/headless.py` | resolve the model, always pass `--model`; `--plugin-dir` passthrough with Read rules; record model | changed |
| `scripts/cplat/runs_bench.py` | `--plugins DIR`; record plugins and coordinator model in the benchmark record | changed |
| `scripts/cplat/runs_usage_report.py` | group `--benchmarks` cells by plugins label too | changed |
| `scripts/cplat/pr_open.py` | `cplat pr open`: commit, push, PR, closes, WIP note | new |
| `scripts/cplat/pr.py` | `open` subcommand next to `wait` | changed |
| `scripts/cplat/quiet.py` | `cplat quiet <script>` | new |
| `scripts/cplat/cplat.py` | register `quiet`, usage lines | changed |
| `plugins/svc/commands/{quick-task,fix-bug,build}.md` | finishing step = `cplat pr open`; compact briefs; quiet commands | changed |
| `plugins/svc/commands/ship.md`, `build.md`, `quick-task.md` | rare branches moved out | changed |
| `plugins/svc/references/*.md` | the moved branches | new |
| `plugins/*/agents/{coder,tester}.md`, `plugins/shared/agents/quality.md` | start from the brief; quiet commands | changed |

## Contract

### Coordinator model (AC-100.1–100.6)

Settings files, both optional, same schema:

- project: `<repo>/.platform-settings.yml` (committed, project-owned; no template renders it)
- user: `${XDG_CONFIG_HOME:-~/.config}/sdlc-foundry/settings.yml`

```yaml
coordinator_model: sonnet        # a string: every workflow
# or a map:
coordinator_model:
  default: sonnet                # optional: every workflow not listed
  build: opus                    # key = workflow name, the command part of /<plugin>:<command>
```

Other top-level keys are ignored. A file that is not valid YAML, or a `coordinator_model` that is neither a string nor a
map of strings, is refused with a `PlatformError` naming the file.

- Allowed values: exactly `sonnet`, `opus`, `haiku` (lowercase).
- Workflow of a prompt: the first match of `^/(?:[a-z0-9-]+:)?([a-z0-9-]+)` on the stripped prompt
  (`/svc:build 900` → `build`, `/svc:quick-task …` → `quick-task`); no match → no workflow.
- Resolution, first hit wins: `--model` flag → project `coordinator_model.<workflow>` → project general (the string,
  or `default`) → user `.<workflow>` → user general → `sonnet`. Source names: `flag`, `project`, `user`, `default`.
- Validation (AC-100.5): the flag and **every** value in both files are checked on every `cplat headless` call,
  including `--dry-run`, before the run record is started or anything is spawned. Refusal: `PlatformError`, exit as
  for other cplat errors, message
  `unknown coordinator model '<value>' in <where>: use sonnet, opus or haiku`, `<where>` = `--model`,
  or `<path> (coordinator_model)` / `<path> (coordinator_model.<key>)`.
- `cplat headless` prints `coordinator: <model> (<source>)` before the first session; the claude command always
  contains `--model <model>` (also in `--dry-run` output). The headless run record gets
  `coordinator_model: <model>` and `coordinator_model_source: <source>`.

`settings.py` public interface:

```python
MODELS = ("sonnet", "opus", "haiku"); DEFAULT_MODEL = "sonnet"; PROJECT_FILE = ".platform-settings.yml"
def user_file() -> Path
def workflow_of(prompt: str) -> str | None
def coordinator_model(repo: Path, prompt: str, flag: str | None) -> tuple[str, str]   # (model, source); raises PlatformError
```

### Benchmark with local plugins (AC-100.17)

`cplat headless … [--plugin-dir PATH]...` (repeatable): each PATH must contain `.claude-plugin/plugin.json`, else
`PlatformError` before anything starts. Each adds `--plugin-dir <abs PATH>` to the claude command, and one
`--settings <json>` is added with `{"permissions": {"allow": ["Read(/<abs PATH>/**)", …]}}` (one rule per PATH;
`<abs PATH>` starts with `/`, so the rule reads `Read(//Users/…/**)`).

`cplat runs benchmark <quick-task|build|ship> [--reset-first] [--plugins DIR]`:

- `DIR` is a folder of plugins (this worktree's `plugins/`). For every `<name>@<marketplace>: true` in the clone's
  `.claude/settings.json` `enabledPlugins`, `DIR/<name>/.claude-plugin/plugin.json` must exist with `"name": "<name>"`;
  otherwise `PlatformError` before the run starts. Only those plugins are passed (`--plugin-dir DIR/svc
  --plugin-dir DIR/shared`), so plugins the sample does not enable do not inflate the context.
- The benchmark record's `benchmark` section gains `plugins` and `coordinator_model`:
  `"plugins": null` (installed plugins) or `{"dir": "<abs DIR>", "commit": "<40-hex HEAD of DIR's repo>", "dirty": bool}`;
  `"coordinator_model": "<model>"` (resolved as above for the clone, which has no project file).
- The final line gains `plugins <installed|local <sha7>[+dirty]>, coordinator <model>`.
- `cplat runs report --benchmarks` keys its cells by workflow, platform version **and** that plugins label, so
  local-plugin runs never mix with installed ones.

### `cplat pr open` (AC-100.7–100.9)

```
cplat pr open --title "<type>(<scope>): <subject>" [--body-file .git/PR_BODY.md] [--message <commit subject>]
              [--base main] [--issues "#12 #7"] [--spec <id>] [--no-pr] [--json]
```

Before anything (exit **2**, nothing changed): not a git repo; the body file missing; the current branch is `--base`
or does not match `^(feature|fix|chore|docs|refactor|perf|test|release)/[A-Za-z0-9._/-]+$`; the title does not match
`^(feat|fix|refactor|perf|test|docs|chore|ci|build|revert|style)(\([^)]+\))?!?: \S.*$`.

Then, in order; the first failed part stops the rest (they print `not run`):

1. **closes**: candidates = `#N` in `--issues`, the `tracks:` of `--spec`'s spec.md, and `#N` in
   `git log <base>..HEAD --format=%B` and in `--message`. Kept when `gh issue view N --json state -q .state` is
   `OPEN`. A `{{CLOSES}}` placeholder in the body file is replaced by `Closes #N` lines (one per issue, ascending) or
   `N/A`; without gh, `N/A`. The body file is rewritten in place. Never fails the command.
2. **wip note**: when a subject in `<base>..HEAD` starts with `wip(` and the body lacks it, append
   `Contains WIP commits from an interrupted build: squash-merge.`
3. **commit**: tree dirty → `git add -A`, `git <core.git_identity> commit -q -s -m <message or title>` →
   `done <sha7>`. Tree clean and ≥ 1 commit ahead of `<base>` → `skipped (clean tree, <n> commits ahead)`. Tree clean
   and 0 ahead → `failed: nothing to commit`. `<base>` = `origin/<base>` when it exists, else `<base>`.
4. **push**: `git push -u origin <branch>` (never force) → `done`; rejected → `failed: <last stderr line>`.
5. **pr**: an open PR for the head branch (`gh pr list --head <branch> --state open --json url`) →
   `failed: already open <url>` (no second PR). `gh pr create` not allowed (below), `--no-pr`, gh missing or not
   logged in → `ready: gh pr create --base <base> --head <branch> --title '<title>' --body-file <body file>`
   (spec 051: not an error). Otherwise `gh pr create --base <base> --head <branch> --title <title>
   --body-file <body file>` → `opened <url>`; failure → `failed: <reason>`.

`gh pr create` is allowed when `.claude/settings.json` or `.claude/settings.local.json` has one of `Bash(gh pr create *)`,
`Bash(gh pr create:*)`, `Bash(gh pr *)`, `Bash(gh pr:*)`, `Bash(gh *)`, `Bash(gh:*)` under `permissions.allow` and
none of them under `deny` or `ask`. Without either file: not allowed.

Output (text), always three lines in this order, the `ready` command last when present:

```
commit: done 1a2b3c4 | skipped (clean tree, 3 commits ahead) | failed: <why> | not run
push: done | failed: <why> | not run
pr: opened <url> | ready: <command> | failed: <why> | not run
```

`--json`: `{"commit": {"status": "...", "sha": str|null, "detail": str}, "push": {"status", "detail"},
"pr": {"status", "url": str|null, "command": str|null, "detail"}, "closes": [int], "exit": int}`.

Exit: **0** PR opened or ready; **1** a part failed (nothing to commit, push rejected, PR already open, gh error);
**2** refused before start. A re-run after exit 1 makes no second commit (clean tree → skipped) and no second PR.

### `cplat quiet <script>` (AC-100.12)

`cplat quiet <devbox-script>`: `<devbox-script>` must be a key of `shell.scripts` in `./devbox.json`, else exit 2
(no extra arguments are accepted, so nothing can be injected). Runs `devbox run <script>` with stdout and stderr
into `${XDG_CACHE_HOME:-~/.cache}/sdlc-foundry/logs/<repo dir name>/<YYYYmmdd-HHMMSS>-<script>.log`.

- success: `ok: devbox run <script> (<n> lines, log: <path>)` and the last non-empty output line (pytest's summary);
  exit 0.
- failure: `FAILED (exit <code>): devbox run <script> (log: <path>)`, then the last 40 output lines; exit = the
  command's exit code.

Python templates: `test-fast` becomes `uv run pytest tests/ -q --tb=line` (service-python, library-python).

### Briefs (AC-100.10, AC-100.11)

Coder, tester and quality briefs from build, quick-task and fix-bug carry, under fixed headings:
`Criteria` (id and full text of every criterion the task covers; acceptance mode: every active criterion and the
non-goals), `Task` (prose section verbatim, `files`), `Contract` (the design.md sections the task touches, verbatim, or
`none`), `Tests` (test files from TRACE), `Commands` (`cplat quiet test-fast`, `cplat quiet quality`, …). The coder,
tester and quality agents start from the brief and read spec.md, plan.md or design.md only when the brief lacks a fact
they need, saying which. The reviewer brief and agent are unchanged: it reads the full spec.

### Reference files (AC-100.13, AC-100.14)

| File | Moved from | Trigger line left behind |
|---|---|---|
| `build-resume.md` | build Phase 0.1 (interrupted build, WIP commit, stale staged files) | dirty tree on a `building` spec |
| `build-worktree-fallback.md` | build 2.2 error and wrong-HEAD branches | the probe errors or reports another HEAD |
| `build-replan.md` | build 2.3 re-planned-task bullet and 2.4a | `cplat build merge` exit 3 / a task in `replans[]` |
| `build-security-red.md` | build Phase 3 security branch (`deps patch` exit 0/3/4, security agent) | the security gate is red |
| `ship-gitops.md` | ship Phase `build` gitops-task paragraph | the plan has tasks with `repo:` |
| `ship-land-red.md` | ship Phase `land` RED, security-red and error branches | `cplat ship land` exits non-zero |
| `quick-task-on-main.md` | quick-task "already on main" handling | Phase 0 found `main` and no branch |

The moved text is unchanged except for heading levels and links. Sizes are compared with the same files at release
`v4.5.0`.

## Risks

- `--settings` permission rules merge with the project's; if a Claude Code version replaces the array instead, reads
  of plugin files fail in the benchmark. t2 checks it once with a dry session and the step benchmarks show it at once.
- Single benchmark runs are noisy; the verification records both runs per step, and a step is rolled back only for a
  failed gate or a changed outcome (AC-100.17), not for a cost within noise.
- Sonnet as coordinator may take more turns; step 1's benchmark is the check, and AC-100.4 lets a project put `build`
  back on Opus.
