---
spec_id: 108-agents-get-a-compact-failure-summary-not
shape: platform
spec_hash: 94aecd47b68e
summary: "Fix rounds get a compact failure summary instead of raw log tails: a rule-based summarizer package scripts/cplat/failsum (core: segments at devbox script markers, own-code paths, dedup with counts, 20 entries / 10 excerpt lines / 80 lines with excerpts shortened first, redaction except the log path, a <log>.summary.json sidecar; one parser per template tool format: pytest, pytest-cov, ruff, ruff-format, mypy, surefire, javac, checkstyle, spotless, jacoco, go-test, go-build, golangci-lint, vitest, eslint, tsc, next-build, gitops-scripts, kustomize, kubeconform, kyverno, docker-build; anything else format: unknown with the last 40 lines); cplat quiet, cplat validate run, the pre-push devbox run ci and the red CI checks of ship land / pr wait print it (CI logs saved locally first); spec 102's no-progress signature and recovery snapshot use the summary; failure_summary: off in .platform-settings.yml or cplat quiet --raw restore today's output; agent instructions say to open the log only when the summary is not enough; a new benchmark workflow fix-rounds compares a build with summaries on and off (ADR-071)"
tasks:
  - id: t1
    title: failsum core — model, segments, own-code paths, dedup, limits, render, redaction, sidecar, normalise; the Python parsers; parser-module stubs; settings.failure_summary
    files: [scripts/cplat/failsum/__init__.py, scripts/cplat/failsum/core.py, scripts/cplat/failsum/python.py, scripts/cplat/failsum/java.py, scripts/cplat/failsum/go.py, scripts/cplat/failsum/web.py, scripts/cplat/failsum/gitops.py, scripts/cplat/failsum/docker.py, scripts/cplat/settings.py]
    covers: [AC-108.2, AC-108.3, AC-108.4, AC-108.5, AC-108.6, AC-108.7, AC-108.10]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Java and Go parsers — surefire, javac, checkstyle, spotless, jacoco; go-test, go-build, golangci-lint
    files: [scripts/cplat/failsum/java.py, scripts/cplat/failsum/go.py]
    covers: [AC-108.2, AC-108.3, AC-108.4]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: web, gitops-app and image build parsers — vitest, eslint, tsc, next-build; gitops-scripts, kustomize, kubeconform, kyverno; docker-build
    files: [scripts/cplat/failsum/web.py, scripts/cplat/failsum/gitops.py, scripts/cplat/failsum/docker.py]
    covers: [AC-108.2, AC-108.3, AC-108.4]
    parallel_safe: true
    depends_on: [t1]
  - id: t4
    title: cplat quiet and cplat validate run print the summary (--raw, the setting, the sidecar)
    files: [scripts/cplat/quiet.py, scripts/cplat/validate.py, scripts/cplat/cplat.py]
    covers: [AC-108.1, AC-108.7, AC-108.10]
    parallel_safe: true
    depends_on: [t1]
  - id: t5
    title: ship — CI logs saved and summarized in red checks, the pre-push devbox run ci summarized, spec 102 attempt and snapshot fed from the summary
    files: [scripts/cplat/ship.py, scripts/cplat/budget.py, scripts/cplat/pr.py]
    covers: [AC-108.7, AC-108.8, AC-108.9, AC-108.10]
    parallel_safe: true
    depends_on: [t1]
  - id: t6
    title: instructions and docs — agents and briefs use the summary and open the log only when needed; ADR index, guide, site page, plugin versions, CHANGELOG
    files: [plugins/component/commands/build.md, plugins/component/commands/fix.md, plugins/component/references/ship-land-red.md, plugins/component/references/build-red-rounds.md, plugins/svc/agents/coder.md, plugins/svc/agents/tester.md, plugins/svc-go/agents/coder.md, plugins/svc-go/agents/tester.md, plugins/svc-java/agents/coder.md, plugins/svc-java/agents/tester.md, plugins/web/agents/coder.md, plugins/web/agents/tester.md, plugins/shared/agents/quality.md, plugins/svc/README.md, plugins/shared/README.md, plugins/component/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, plugins/svc-go/.claude-plugin/plugin.json, plugins/svc-java/.claude-plugin/plugin.json, plugins/web/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/adr/README.md, docs/unattended-delivery.md, site/src/content/docs/concepts/agents.md, docs/CHANGELOG.md]
    covers: [AC-108.7, AC-108.10]
    parallel_safe: true
    depends_on: []
  - id: t7
    title: benchmark workflow fix-rounds — seed, two passes (summaries on, then off), the comparison in the record and the exit rule
    files: [scripts/cplat/runs_bench.py, scripts/cplat/benchmark/tasks.json, scripts/cplat/benchmark/seeds/fix-rounds.json]
    covers: [AC-108.11]
    parallel_safe: true
    depends_on: []
---

# Plan — 108 Agents get a compact failure summary, not the full log

Design: [design.md](design.md) (the contract is binding), ADR: [ADR-071](../../adr/071-a-failing-check-reaches-an-agent-as-a-rule-made-summary.md).
Two levels: t1, t6 and t7 have no dependency and share no file; t2 to t5 need t1's package and share no file with each other.

## t1 — failsum core and the Python parsers

**Files:** scripts/cplat/failsum/__init__.py, scripts/cplat/failsum/core.py, scripts/cplat/failsum/python.py, scripts/cplat/failsum/java.py, scripts/cplat/failsum/go.py, scripts/cplat/failsum/web.py, scripts/cplat/failsum/gitops.py, scripts/cplat/failsum/docker.py, scripts/cplat/settings.py
**Covers:** AC-108.2, AC-108.3, AC-108.4, AC-108.5, AC-108.6, AC-108.7, AC-108.10
**Goal:** a pure, deterministic summarizer with the design's API and byte-exact render, reading the Python templates' tools, with
the other ecosystems' modules in place for t2 and t3.

**Implementation notes:**
- `core.py`: the dataclasses and `Context` exactly as in the design; `strip_ansi`, CI-line stripping (`<job>\t<step>\t<ISO ts> `,
  `##[group]`/`##[endgroup]` dropped, `##[error]` removed), segments at `^Info: Running script "(?P<name>[^"]+)"` (confirm the exact
  marker with `devbox run` in this repo before pinning it; no marker → one segment named after the check), skip empty segments, the
  last non-empty segment always becomes a check.
- `normalise`: move `budget._NORMALISE` and `normalise` verbatim (budget keeps its copy until t5 switches it to an alias; the
  rules must stay identical, `tests/cplat/test_budget.py:718` keeps passing).
- Per check: run every parser of the registry (`python`, `java`, `go`, `web`, `gitops`, `docker`, each module's `PARSERS` in order),
  sort entries by `at`, dedup findings by (file, kind, message) with `count` and up to 10 further `lines`, never tests; `formats` =
  names of parsers that returned entries; `reported` = the largest tool total read; unknown when no entries.
- Render and limits exactly as the design (three shortening steps, `... <m> more entries not shown (log: <log>)`, the incomplete-read
  line and tail), every line through `feedback.redact` except the log path (render with a placeholder, redact, substitute).
- `summarize`, `summarize_ci` (header `command`/`exit` from the job/step columns and `Process completed with exit code`), `raw`,
  `enabled`, `sidecar`, `write_sidecar` (never raises), `read_sidecar`.
- `python.py`: parsers `pytest`, `pytest-cov`, `ruff`, `ruff-format`, `mypy` with the inputs listed in the design's table; pytest: one
  entry per FAILED/ERROR nodeid (collection errors included), `where` = the deepest own-code `path:line` of that failure, else the
  nodeid's file; excerpt = `E` lines and own-code location lines, at most 10; library frames, passing tests and progress dots never
  appear.
- `java.py`, `go.py`, `web.py`, `gitops.py`, `docker.py`: `PARSERS: tuple = ()` and a module docstring naming the formats the design
  assigns to them.
- `settings.failure_summary(repo)` as in the design (project file only; YAML `off`/`false` → off; `on`/`true`/missing → on; anything
  else `PlatformError`), and one line on it in the module docstring.
- No import of `budget`, `ship` or `runs` from `failsum` (budget imports failsum in t5).

**Done when:** the acceptance tests for AC-108.2 to AC-108.6 pass for the Python formats, the unknown-format fallback and the limits,
AC-108.10's setting tests pass, the redaction tests of AC-108.7 pass, and `uv run pytest tests/cplat/test_budget.py` stays green.

## t2 — Java and Go parsers

**Files:** scripts/cplat/failsum/java.py, scripts/cplat/failsum/go.py
**Covers:** AC-108.2, AC-108.3, AC-108.4
**Goal:** service-java and service-go failures are summarized per the design's table.

**Implementation notes:**
- `java.py`: `surefire` (the `[ERROR] Failures:`/`[ERROR] Errors:` lists for id and `file:line` of the test, `<<< FAILURE!` blocks for
  type, message and own `at` frames via `Context.own_java_frame`; total from `Tests run: …, Failures: f, Errors: e`), `javac`,
  `checkstyle`, `spotless` (one entry per listed file), `jacoco` (kind `coverage`). Strip Maven's `[ERROR] `/`[INFO] ` prefixes inside
  the parser; ignore the `-> [Help 1]` trailer and download/progress lines.
- `go.py`: `go-test` (id `<pkg>.<Test>`, subtests `Test/sub`, `file:line` from the indented `x_test.go:12:` line made own via the
  package dir, `panic:` with the first own frame, a test package's build failure as kind `compile`; total = failing tests),
  `go-build` (`# pkg` + `file:line:col: msg`), `golangci-lint` (`(<linter>)` is the kind; `N issues:` total).
- Sample logs for every format in the tests come from the template's real tool versions (maven 3.9.16 and the pom's plugin versions,
  golangci-lint 2.14.0, the template's Go).

**Done when:** the acceptance tests for AC-108.2 to AC-108.4 that use Java and Go sample logs pass.

## t3 — web, gitops-app and image build parsers

**Files:** scripts/cplat/failsum/web.py, scripts/cplat/failsum/gitops.py, scripts/cplat/failsum/docker.py
**Covers:** AC-108.2, AC-108.3, AC-108.4
**Goal:** web-nextjs, gitops-app and `docker build` failures are summarized per the design's table.

**Implementation notes:**
- `web.py`: `vitest` (id `<file> > <suite> > <test>`, own ` ❯ file:line:col` frame, total from `Tests  N failed`, coverage threshold
  lines as kind `coverage`), `eslint` stylish (file line + `l:c  error  msg  rule`; warnings only when the run failed with
  `--max-warnings`; total from `✖ N problems`), `tsc` (both output shapes), `next-build`. Ignore pnpm's `ELIFECYCLE`/`ERR_PNPM_*` trailers.
- `gitops.py`: `gitops-scripts` (the template scripts' `ERROR: <file>[: …]: <msg>` lines; render.py's drift list after `rendered
  files are out of date` as kind `render-drift`), `kustomize` (`Error:` after the `kustomize build <dir>` echo), `kubeconform`,
  `kyverno` (`POLICY VIOLATION in <dir> (<env>):` blocks, entry per failed policy/rule).
- `docker.py`: `docker-build` (BuildKit `ERROR [stage n/m] <step>` / `ERROR: failed to solve:`, `Dockerfile:<l>` as the locator, the
  `----` block as excerpt); a `next build` failure inside the image build yields both a `next-build` and a `docker-build` entry.

**Done when:** the acceptance tests for AC-108.2 to AC-108.4 that use web, gitops-app and docker sample logs pass.

## t4 — cplat quiet and cplat validate run print the summary

**Files:** scripts/cplat/quiet.py, scripts/cplat/validate.py, scripts/cplat/cplat.py
**Covers:** AC-108.1, AC-108.7, AC-108.10
**Goal:** a failing quiet or validate command prints the summary with the log path, or today's tail when summaries are off.

**Implementation notes:**
- `quiet.main`: argv `[script]` or `["--raw", script]`, else usage exit 2 as today (`["test-fast", "--extra"]` still refused);
  `settings` error → `ERROR: …` on stderr, exit 2, nothing run. Success output byte-identical to today.
- Failure on: print `failsum.summarize(...).render()` with today's `FAILED (exit …)` line as title; `write_sidecar`. Off: `failsum.raw`
  with the reason (`--raw` wins over the setting in the reason text). Exit code passes through.
- `validate.execute`: a failed check prints the summary (title = today's `FAILED (exit …): <label> (log: …)` line, check = the
  validate check name, command = the joined `command(entry)`), writes the sidecar; off → today's tail plus the `summaries: off` line.
  The rest of the loop (not started checks, evidence, `checks:` line) is unchanged.
- Module docstring of `quiet.py` and the `cplat quiet` line in `cplat.py`'s usage: `cplat quiet [--raw] <devbox-script>` — "one line
  on success, a failure summary and the log path on failure".

**Done when:** the acceptance tests for AC-108.1 and AC-108.10 pass, `tests/cplat/test_lean_briefs.py` and the spec 103 validate
tests stay green.

## t5 — ship and spec 102 use the summary

**Files:** scripts/cplat/ship.py, scripts/cplat/budget.py, scripts/cplat/pr.py
**Covers:** AC-108.7, AC-108.8, AC-108.9, AC-108.10
**Goal:** a ship fix round's brief carries the summary of each failed CI check with its saved log path, and spec 102 records the
summary's normalized messages and the summary itself.

**Implementation notes:**
- `red_summary(repo, pr, cs, failed)` per the design: one `gh run view --log-failed` per run, split by the job column, raw lines saved
  to `quiet._log_path(repo, "ci-<slug>")`, `failsum.summarize_ci` with today's `RED:` line as title; a check without a run link gets a
  header with `log: none (not a GitHub Actions run: <link>)`. `red()` returns the lines. Off → today's `failure_logs` lines plus the
  `summaries: off (…)` line after `RED:`. `ship.run_logs` (deploy phase) is unchanged.
- `land`: use `red_summary`; `budget.attempt(..., normalized=summary.normalized())` when a summary exists; on a no-progress stop
  `escalate(repo, why, "code", evidence=text, stage="ci", summary=text)`. `refused()` and the gitops path keep using `red()`.
- `escalate(..., summary=None)` passes it to `budget.snapshot`.
- `run_ci`: write the output to `quiet._log_path(repo, "ship-ci")` (stdout and stderr together, env unchanged), message = today's
  first line + the rendered summary (or today's 40-line tail plus the off line), sidecar written. `validate.record_final_gate` call
  unchanged.
- `budget.py`: `normalise = failsum.normalise` (remove the local `_NORMALISE`), `attempt(normalized=)` and `snapshot(summary=)` as in
  the design; `_attempt_cli` reads `failsum.read_sidecar(--error-file)` and passes `normalized` to `attempt`, the sidecar `text` as
  `evidence` and `summary` to `ship.escalate` / `snapshot`; without a sidecar unchanged. Docstring lines updated.
- `pr.py` docstring: exit 1 is "red, with a summary of each failed check and its saved log".
- Nothing new is written into a run record (AC-108.7).

**Done when:** the acceptance tests for AC-108.8 and AC-108.9 pass, AC-108.10's CI case passes, and `tests/cplat/test_budget.py`,
the ship land / pr wait tests and the spec 102 snapshot tests stay green (amend only assertions on the exact 40-line evidence when an
acceptance test of AC-108.9 replaces them).

## t6 — instructions and docs

**Files:** plugins/component/commands/build.md, plugins/component/commands/fix.md, plugins/component/references/ship-land-red.md, plugins/component/references/build-red-rounds.md, plugins/svc/agents/coder.md, plugins/svc/agents/tester.md, plugins/svc-go/agents/coder.md, plugins/svc-go/agents/tester.md, plugins/svc-java/agents/coder.md, plugins/svc-java/agents/tester.md, plugins/web/agents/coder.md, plugins/web/agents/tester.md, plugins/shared/agents/quality.md, plugins/svc/README.md, plugins/shared/README.md, plugins/component/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, plugins/svc-go/.claude-plugin/plugin.json, plugins/svc-java/.claude-plugin/plugin.json, plugins/web/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/adr/README.md, docs/unattended-delivery.md, site/src/content/docs/concepts/agents.md, docs/CHANGELOG.md
**Covers:** AC-108.7, AC-108.10
**Goal:** briefs hand over the summary and the log path, and every agent opens the log only when the summary is not enough.

**Implementation notes:**
- The nine agent files' shell-rule sentence ("it prints one line on success and the tail plus a log path on failure; read that log, do
  not rerun with full output"): "it prints one line on success and, on failure, a summary (each failing check, the test or `file:line`,
  the error and a short excerpt) with the log path; fix from the summary and open the log only when the summary is not enough; do not
  rerun with full output". Keep "cplat quiet" and "log" (`test_lean_briefs.py`).
- `build.md` Phase 3 step 2: "the summary and the log path `cplat quiet` printed" instead of "the output's tail and the log path", plus
  "open the log only when the summary is not enough" in the brief; same wording in Phase 2 step 3 ("with the summary `cplat validate
  run` printed"). `fix.md` Step 1: "give the agent the summary and the log path it printed". `ship-land-red.md` RED bullet: it prints a
  summary of each failed check and the path of its saved log; hand both to the coder, the log only when the summary is not enough.
  `build-red-rounds.md`: `--error-file <the log path cplat quiet printed>` (its summary is used automatically).
- `plugins/shared/README.md` and `plugins/svc/README.md`: `cplat quiet [--raw] <script>` and the summary; `docs/unattended-delivery.md`:
  a section "Failure summaries in fix rounds" after "Change-aware validation in fix rounds" (what a summary holds, where the logs are,
  `failure_summary: off`, `--raw`, the `fix-rounds` benchmark); the site concepts page sentence on `cplat quiet`.
- `docs/adr/README.md`: the ADR-071 row after 070 ("Failures reach agents as a summary made by fixed parsers in cplat (20 entries,
  10 excerpt lines, 80 lines, never a failing check dropped), the full log stays local and is opened on demand; the summary is spec
  102's failure of record; on by default, `failure_summary: off` or `cplat quiet --raw`").
- Versions (both `plugin.json` and `marketplace.json`): `component` 1.4.0 → 1.5.0, `shared` 1.0.0 → 1.1.0, `svc` 4.0.0 → 4.0.1,
  `svc-go`, `svc-java`, `web` 0.4.0 → 0.4.1 (bump from the value on the branch if another change moved it).
- `docs/CHANGELOG.md` [Unreleased]: one paragraph for spec 108 (summaries, the formats, CI logs saved locally, the setting and
  `--raw`, the benchmark workflow) and its **Plugins:** line.

**Done when:** `devbox run validate` passes, `tests/cplat/test_lean_briefs.py` and the plugin/marketplace version checks pass, and the
Markdown link check passes.

## t7 — benchmark workflow fix-rounds

**Files:** scripts/cplat/runs_bench.py, scripts/cplat/benchmark/tasks.json, scripts/cplat/benchmark/seeds/fix-rounds.json
**Covers:** AC-108.11
**Goal:** `cplat platform runs benchmark fix-rounds` runs one build with summaries and one without on a sample that starts with one
failing test and one lint finding, records both and fails only by the spec's three conditions.

**Implementation notes:**
- `tasks.json`: the `fix-rounds` workflow as in the design; `EXPECTED["fix-rounds"] = "open"`; the CLI's `choices` gain it; `--arm` and
  `--compare-validation` with it raise `PlatformError`.
- `seeds/fix-rounds.json`: arm-shaped. Build it against the pinned sample revision (`ika100/todo-api@9cba320`): spec 901 (approved,
  one criterion the sample already meets, e.g. an existing endpoint behaviour), its `plan.md` with one `done: true` task and the hash
  from `cplat spec hash 901` in a scratch clone, the AC-901 tagged test, one change in `src/` that makes exactly one existing
  non-acceptance test fail, one unused import (ruff F401); check in the scratch clone that `devbox run test-fast` has exactly one
  failure, `devbox run lint` exactly one finding, `devbox run typecheck` is green and `cplat spec check` passes.
- Two passes like `--compare-validation` (reset and `_prepare` between them); the seed goes through `stage_arm` + `push_arm`; pass `off`
  adds `.platform-settings.yml` (`failure_summary: off\n`) to the seed's files. Both passes always run.
- Per pass: `fix_rounds` from the `fix-round` events of the pass's new child records (`_children`), `fixing` from the pass usage's
  `by_role` entries ending in `:coder` / `:quality`, `total`, `gates_failed` from the children's `gates`; the record's
  `benchmark.summary_compare`, the output lines and the exit rule exactly as in the design.
- The sample's other workflows, arms and `--compare-validation` behave as today.

**Done when:** the acceptance tests for AC-108.11 pass (with the module's `run`, `_run_headless`, `trusted` and `_children` replaced),
and the spec 099/103/107 benchmark tests stay green.
