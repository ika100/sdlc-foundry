---
spec_id: 100-leaner-runs-cheaper-coordinator-fewer
spec_hash: 877fbf61dce6
summary: Coordinator on Sonnet by default (flag > project > user settings), benchmark with the worktree's plugins,
  cplat pr open for the finishing step, compact briefs and cplat quiet, rare command branches moved to reference
  files; each step benchmarked before the next
tasks:
  - id: t1
    title: Coordinator model setting (settings.py) and --model in cplat headless
    files: [scripts/cplat/settings.py, scripts/cplat/headless.py]
    covers: [AC-100.1, AC-100.2, AC-100.3, AC-100.4, AC-100.5, AC-100.6]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: Benchmark with the worktree's plugins (--plugins, headless --plugin-dir)
    files: [scripts/cplat/headless.py, scripts/cplat/runs_bench.py, scripts/cplat/runs_usage_report.py, scripts/cplat/runs.py]
    covers: [AC-100.17]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: b1
    title: Benchmark step 1 (quick-task and build) and record it
    files: [docs/specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md]
    covers: [AC-100.1, AC-100.17]
    parallel_safe: false
    depends_on: [t1, t2]
    done: true
  - id: t3
    title: cplat pr open (commit -s, push, PR, closes, WIP note, ready-PR fallback)
    files: [scripts/cplat/pr_open.py, scripts/cplat/pr.py, scripts/cplat/cplat.py]
    covers: [AC-100.7, AC-100.8, AC-100.9]
    parallel_safe: false
    depends_on: [b1]
    done: true
  - id: t4
    title: quick-task, fix-bug and build finish with one cplat pr open call
    files: [plugins/svc/commands/quick-task.md, plugins/svc/commands/fix-bug.md, plugins/svc/commands/build.md]
    covers: [AC-100.7]
    parallel_safe: false
    depends_on: [t3]
    done: true
  - id: b2
    title: Benchmark step 2 and record it
    files: [docs/specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md]
    covers: [AC-100.17]
    parallel_safe: false
    depends_on: [t4]
    done: true
  - id: t5
    title: cplat quiet <devbox-script> and quiet pytest in the Python templates
    files: [scripts/cplat/quiet.py, scripts/cplat/cplat.py, templates/service-python/devbox.json, templates/library-python/devbox.json]
    covers: [AC-100.12]
    parallel_safe: false
    depends_on: [b2]
    done: true
  - id: t6
    title: Compact briefs and quiet commands in quick-task, fix-bug and build
    files: [plugins/svc/commands/quick-task.md, plugins/svc/commands/fix-bug.md, plugins/svc/commands/build.md]
    covers: [AC-100.10, AC-100.11, AC-100.12]
    parallel_safe: true
    depends_on: [t5]
    done: true
  - id: t7
    title: Coder, tester and quality agents start from the brief and use cplat quiet
    files: [plugins/svc/agents/coder.md, plugins/svc/agents/tester.md, plugins/shared/agents/quality.md, plugins/svc-go/agents/coder.md, plugins/svc-go/agents/tester.md, plugins/svc-java/agents/coder.md, plugins/svc-java/agents/tester.md, plugins/web/agents/coder.md, plugins/web/agents/tester.md]
    covers: [AC-100.10, AC-100.12]
    parallel_safe: true
    depends_on: [t5]
    done: true
  - id: b3
    title: Benchmark step 3 and record it
    files: [docs/specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md]
    covers: [AC-100.17]
    parallel_safe: false
    depends_on: [t6, t7]
    done: true
  - id: t8
    title: Move rare branches of build, ship and quick-task into plugins/svc/references/
    files: [plugins/svc/commands/build.md, plugins/svc/commands/ship.md, plugins/svc/commands/quick-task.md, plugins/svc/references/build-resume.md, plugins/svc/references/build-worktree-fallback.md, plugins/svc/references/build-replan.md, plugins/svc/references/build-security-red.md, plugins/svc/references/ship-gitops.md, plugins/svc/references/ship-land-red.md, plugins/svc/references/quick-task-on-main.md]
    covers: [AC-100.13, AC-100.14]
    parallel_safe: false
    depends_on: [b3]
    done: true
  - id: b4
    title: Final benchmarks against the targets ($0.30 quick-task, $1.15 build)
    files: [docs/specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md]
    covers: [AC-100.15, AC-100.16, AC-100.17]
    parallel_safe: false
    depends_on: [t8]
    done: true
  - id: t9
    title: Versions, changelog, docs and ADR index
    files: [.claude-plugin/marketplace.json, plugins/svc/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/svc-go/.claude-plugin/plugin.json, plugins/svc-java/.claude-plugin/plugin.json, plugins/web/.claude-plugin/plugin.json, docs/CHANGELOG.md, docs/unattended-delivery.md, docs/adr/README.md]
    covers: [AC-100.3, AC-100.4]
    parallel_safe: false
    depends_on: [b4]
    done: true
---

# Plan — 100 Leaner runs

The steps run in spec order 1 → 2 → 3 → 4, each followed by its benchmark task (AC-100.17). The `depends_on` chain
between a benchmark and the next step is real: a benchmark measures the worktree's plugins and scripts, so the next
step must not change them while it runs. The contract is in [design.md](design.md); ADRs
[036](../../adr/036-coordinator-model-default-and-settings.md) and
[037](../../adr/037-cplat-bundles-honour-the-allowlist.md).

**Benchmark tasks (b1–b4), common rules.** Run from this worktree, so the outer cplat is the worktree's:
`uv run scripts/cplat/cplat.py runs benchmark quick-task --reset-first --plugins "$PWD/plugins"`, then the same for
`build`. A build benchmark takes up to 2 h: start it with the Bash tool's `run_in_background` and poll its output;
never wrap it in a hand-written sleep loop. Append to `benchmarks.md` one row per run: step, workflow, run id,
outcome, PR, gates (from the run record), reviewer result (build), calls, tokens, estimated cost, coordinator model,
plugins label. Compare with the previous step (step 1 with the spec's baselines). **Rollback:** a step whose run is
not `done`, opens no PR, has a failed gate, or (build) a failed reviewer, while the previous step's passed, is
reverted with `git revert` of that step's task commits, the row says `rolled back`, and the next step starts from the
reverted tree. A step that costs more in both workflows is marked `regression` for the reviewer. The reviewer copies
the table into verification.md.

## t1 — Coordinator model setting and --model in cplat headless

**Files:** scripts/cplat/settings.py, scripts/cplat/headless.py
**Covers:** AC-100.1, AC-100.2, AC-100.3, AC-100.4, AC-100.5, AC-100.6
**Goal:** every headless session runs on a model cplat chose: flag, project setting (with per-workflow map), user
setting, else Sonnet; unknown names are refused before anything starts.

**Implementation notes:**
- `settings.py` exactly as the contract's interface: `MODELS`, `DEFAULT_MODEL`, `PROJECT_FILE`, `user_file()`
  (`XDG_CONFIG_HOME`, else `~/.config`), `workflow_of()`, `coordinator_model()`. Read YAML with `yaml.safe_load`
  (pyyaml is already a script dependency).
- Validate the flag and every value of both files on each call; the refusal message names the source and the three
  values.
- `headless.main`: resolve before `--dry-run` handling and before `runlog.start`; `claude_cmd(prompt, model)` always
  adds `--model`. Print `coordinator: <model> (<source>)`.
- Add `coordinator_model` and `coordinator_model_source` to both `runlog.finish` field sets.
- `argparse` keeps `--model` free text (validation is ours, for the message).
- Update the module docstring with the settings files and precedence.
- AC-100.6: no agent change; the frontmatter `model: opus` of architect, reviewer, product-manager stays.

**Done when:** the acceptance tests for AC-100.1–100.6 pass; `cplat headless --dry-run "/svc:build 1"` in a repo
without settings prints a command with `--model sonnet`.

## t2 — Benchmark with the worktree's plugins

**Files:** scripts/cplat/headless.py, scripts/cplat/runs_bench.py, scripts/cplat/runs_usage_report.py, scripts/cplat/runs.py
**Covers:** AC-100.17
**Goal:** `cplat runs benchmark <wf> --plugins DIR` runs the benchmark with this worktree's plugins and records which
plugins and coordinator model ran, so each step is measured before a release.

**Implementation notes:**
- `headless --plugin-dir PATH` (repeatable, `action="append"`): validate the manifest, add `--plugin-dir <abs>` and
  one inline `--settings` JSON with a `Read(/<abs>/**)` allow rule per path (contract).
- `runs_bench --plugins DIR`: pick the plugins the clone's `enabledPlugins` enable, validate each manifest name,
  pass them on to `headless.main` as `--plugin-dir` args; refuse before `runs.start` when one is missing.
- Record `benchmark.plugins` (`null` or `{dir, commit, dirty}` from `git -C DIR rev-parse HEAD` and
  `git status --porcelain`) and `benchmark.coordinator_model` (via `settings.coordinator_model(clone, prompt, None)`).
- Final line: `plugins <label>, coordinator <model>`.
- `aggregate_benchmarks`: key cells by (workflow, platform_version, plugins label); the text render shows the label.
- `runs.py`: the usage line for `benchmark` gains `[--plugins DIR]`.
- Check once by hand that a `claude -p --plugin-dir … --settings …` session can Read a file under the plugin dir
  (design Risks); note the result in the PR.

**Done when:** the acceptance tests for the benchmark record and the `--plugin-dir` command line pass.

## b1 — Benchmark step 1

**Files:** docs/specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md
**Covers:** AC-100.1, AC-100.17
**Goal:** quick-task and build benchmarks with the coordinator on Sonnet, against the spec's baselines.

**Implementation notes:**
- Create `benchmarks.md` with the baselines from the spec as the first two rows and the column set of the common
  rules; then run both benchmarks (common rules). The records must say `coordinator_model: sonnet`.

**Done when:** both rows are recorded; the step is accepted or rolled back by the rule.

## t3 — cplat pr open

**Files:** scripts/cplat/pr_open.py, scripts/cplat/pr.py, scripts/cplat/cplat.py
**Covers:** AC-100.7, AC-100.8, AC-100.9
**Goal:** one tested command for the finishing step, safe to run again (ADR-037).

**Implementation notes:**
- `pr.py` gains the `open` subparser; the logic lives in `pr_open.py` (`run(repo, opts) -> Result` plus rendering),
  git and gh through `core.run`, identity through `core.git_identity`.
- Order and statuses exactly as the contract: preconditions (exit 2), closes, WIP note, commit, push, PR.
- Closes: `tracks:` read via `spec.py`'s spec loader; `gh issue view` per candidate; replace `{{CLOSES}}`.
- Allowed-check for `gh pr create` from `.claude/settings.json` + `.claude/settings.local.json`, rules as listed.
- Never force-push, never `--amend`, never a second `gh pr create` when one is open.
- Text output: three lines; `--json` as the contract.
- `cplat.py`: usage line `pr wait|open …`.

**Done when:** the acceptance tests for AC-100.7–100.9 pass, including a re-run after each failure leaving one commit
and at most one PR.

## t4 — Finishing step is one cplat pr open call

**Files:** plugins/svc/commands/quick-task.md, plugins/svc/commands/fix-bug.md, plugins/svc/commands/build.md
**Covers:** AC-100.7
**Goal:** the coordinator writes the PR body to `.git/PR_BODY.md` (with `{{CLOSES}}` where the closing lines go) and
makes one Bash call, `cplat pr open --title … [--spec <id>] [--issues …]`.

**Implementation notes:**
- Replace quick-task Phase 3 steps 1–5, fix-bug's commit/push/PR steps and build Phase 7 steps 1–4 (issue scan, push,
  PR, WIP note) with: write the body, `cplat pr open …`, relay its three lines. Exit 1 → report the failed part;
  `failed: already open <url>` means the PR exists (use it); exit 2 → fix the reason it prints.
- The spec-051 paragraph becomes: a `pr: ready: <command>` line is not an error; end the report with that command.
- Build: `--spec <id>`; fix-bug: type `fix`; quick-task keeps choosing the type from the task.
- Build 2.3: the parallel coder's local commit becomes `git commit -s -m '<type>(<scope>): <title>'` (DCO; the unsigned
  form is what stopped a build).
- Keep the PR body templates; only the issue lines become `{{CLOSES}}`.

**Done when:** the acceptance tests for AC-100.7 pass (each of the three commands names `cplat pr open` once in its
finishing step and no longer contains `git push` or `gh pr create` there).

## b2 — Benchmark step 2

**Files:** docs/specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md
**Covers:** AC-100.17
**Goal:** both benchmarks with steps 1–2.

**Implementation notes:**
- Common rules. Also note the coordinator's tool calls in the finishing phase (`benchmark:run` / `build:pr` phase)
  from the usage section.

**Done when:** both rows are recorded; the step is accepted or rolled back.

## t5 — cplat quiet and quiet pytest in the Python templates

**Files:** scripts/cplat/quiet.py, scripts/cplat/cplat.py, templates/service-python/devbox.json, templates/library-python/devbox.json
**Covers:** AC-100.12
**Goal:** test and tool commands print a short line on success and a tail plus the log path on failure.

**Implementation notes:**
- `quiet.py`: contract behaviour; script name must be in `devbox.json` `shell.scripts`; no extra arguments; log path
  under `XDG_CACHE_HOME`; exit code passes through.
- Register `"quiet": "quiet"` in `COMMANDS` and add a usage line.
- Templates: `test-fast` → `uv run pytest tests/ -q --tb=line` (the full `test` recipe keeps coverage output).

**Done when:** the acceptance tests for `cplat quiet` (success line, failure tail, log file, refused script) pass.

## t6 — Compact briefs in quick-task, fix-bug and build

**Files:** plugins/svc/commands/quick-task.md, plugins/svc/commands/fix-bug.md, plugins/svc/commands/build.md
**Covers:** AC-100.10, AC-100.11, AC-100.12
**Goal:** the coordinator gives coder, tester and quality the facts they need, so they do not read the spec files.

**Implementation notes:**
- Build 2.3 coder prompt, Phase 1 tester (acceptance mode), Phase 3 quality and tester prompts, and the quick-task and
  fix-bug agent prompts use the brief headings of the contract: Criteria, Task, Contract, Tests, Commands.
- The coordinator reads spec.md, plan.md and design.md once (Phase 0) and copies the needed parts; it does not tell
  agents to read them.
- Test and gate commands in briefs and in the coordinator's own steps: `cplat quiet test-fast`, `cplat quiet quality`,
  `cplat quiet ci`, `cplat quiet lint-fix`, instead of plain `devbox run …`; a failure's log path goes to the agent.
- The reviewer prompt (Phase 4) is unchanged and still passes `SPEC_DIR` (AC-100.11).

**Done when:** the acceptance tests for AC-100.10–100.12 on these files pass.

## t7 — Agents start from the brief

**Files:** plugins/svc/agents/coder.md, plugins/svc/agents/tester.md, plugins/shared/agents/quality.md, plugins/svc-go/agents/coder.md, plugins/svc-go/agents/tester.md, plugins/svc-java/agents/coder.md, plugins/svc-java/agents/tester.md, plugins/web/agents/coder.md, plugins/web/agents/tester.md
**Covers:** AC-100.10, AC-100.12
**Goal:** coder, tester and quality agents work from the brief and run quiet commands.

**Implementation notes:**
- Replace "Read `spec.md` … and the contract in `design.md`" with: start from the brief's Criteria and Contract;
  read spec.md, plan.md or design.md only when the brief lacks a fact you need, and say which.
- Shell rule: `cplat quiet <script>` for test, quality and lint recipes; on failure read the log it names.
- Do not touch `reviewer.md`, `architect.md`, `product-manager.md` or any `model:` line.

**Done when:** the acceptance tests for AC-100.10 and AC-100.12 on the agent files pass.

## b3 — Benchmark step 3

**Files:** docs/specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md
**Covers:** AC-100.17
**Goal:** both benchmarks with steps 1–3; also record the average context per subagent call from the usage section.

**Implementation notes:**
- Common rules.

**Done when:** both rows are recorded; the step is accepted or rolled back.

## t8 — Rare branches into reference files

**Files:** plugins/svc/commands/build.md, plugins/svc/commands/ship.md, plugins/svc/commands/quick-task.md, plugins/svc/references/build-resume.md, plugins/svc/references/build-worktree-fallback.md, plugins/svc/references/build-replan.md, plugins/svc/references/build-security-red.md, plugins/svc/references/ship-gitops.md, plugins/svc/references/ship-land-red.md, plugins/svc/references/quick-task-on-main.md
**Covers:** AC-100.13, AC-100.14
**Goal:** the normal path of build, ship and quick-task loads less text; a rare branch reads its reference file and
behaves as before.

**Implementation notes:**
- Move the sections of the design's reference table verbatim (heading levels and relative links adjusted).
- Leave one line per moved branch: `<trigger> → read ${CLAUDE_PLUGIN_ROOT}/references/<file> and follow it.`
- ship.md keeps "Read `${CLAUDE_PLUGIN_ROOT}/commands/build.md`"; build's normal path must stay complete for ship.
- Do not move steps the normal path executes (cplat runs calls, gates, the PR step).
- Each of the three commands must be smaller in bytes than at `v4.5.0`.

**Done when:** the acceptance tests for AC-100.13 and AC-100.14 pass (sizes against `v4.5.0`, every moved section
present in its reference file, every reference file named by a trigger line).

## b4 — Final benchmarks

**Files:** docs/specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md
**Covers:** AC-100.15, AC-100.16, AC-100.17
**Goal:** prove the targets with all accepted steps: quick-task done, PR, gates pass, est. ≤ $0.30; build done, PR,
gates and reviewer pass, est. ≤ $1.15.

**Implementation notes:**
- Common rules. If a target is missed, record it with the per-role cost split and stop for the user; do not tune
  further inside this spec.

**Done when:** both rows meet their targets, or the miss is recorded and escalated.

## t9 — Versions, changelog, docs and ADR index

**Files:** .claude-plugin/marketplace.json, plugins/svc/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/svc-go/.claude-plugin/plugin.json, plugins/svc-java/.claude-plugin/plugin.json, plugins/web/.claude-plugin/plugin.json, docs/CHANGELOG.md, docs/unattended-delivery.md, docs/adr/README.md
**Covers:** AC-100.3, AC-100.4
**Goal:** release bookkeeping and the user-facing description of the coordinator setting.

**Implementation notes:**
- Minor bumps for svc, shared, svc-go, svc-java, web in both places (marketplace.json and plugin.json).
- CHANGELOG `[Unreleased]`: the default Sonnet coordinator (behaviour change for headless users), the settings files,
  `cplat pr open`, `cplat quiet`, `--plugins`, the moved reference files, the Python `test-fast` change, the
  benchmark results from benchmarks.md.
- `docs/unattended-delivery.md`: a "Coordinator model" section with both files, the map form, precedence and the
  three values; the benchmark `--plugins` option.
- `docs/adr/README.md`: rows for ADR-036 and ADR-037.

**Done when:** `devbox run validate` passes and `cplat spec check 100` is green.
