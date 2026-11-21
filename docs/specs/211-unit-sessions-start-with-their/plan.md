---
spec_id: 211-unit-sessions-start-with-their
shape: platform
spec_hash: b92ec8c67c51
summary: Unit sessions get shape, run status and a briefing cut by heading from the build instructions in their first call; quiet ci, test-diff and existing commands take over gate, base and phase bookkeeping
tasks:
  - id: t1
    title: briefing.py (mapping, cutter, guards), the rules-check hook and the three reworded references
    files: [scripts/cplat/briefing.py, scripts/cplat/rulescheck.py, plugins/component/commands/build.md, plugins/component/references/unit-mode.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/unit-mode.yml]
    covers: [AC-211.1, AC-211.2, AC-211.3, AC-211.4, AC-211.5, AC-211.6]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: Forward-only build markers set by the commands, record_gate, begin continues a unit-mode build run
    files: [scripts/cplat/runs.py, scripts/cplat/buildcmd.py, scripts/cplat/mutation.py, scripts/cplat/spec.py]
    covers: [AC-211.7, AC-211.9]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: cplat spec test-diff finds its base when none is given
    files: [scripts/cplat/testdiff_base.py, scripts/cplat/spec.py]
    covers: [AC-211.8]
    parallel_safe: false
    depends_on: []
  - id: t7
    title: ADR, changelog fragment, unattended-delivery guide, measurement plan, component plugin version
    files: [docs/adr/, docs/adr/README.md, docs/changelog.d/211-unit-briefing.changed.md, docs/unattended-delivery.md, docs/specs/211-unit-sessions-start-with-their/measurements.md, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-211.10]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: ship start --unit and ship unit print shape, where the run stands and the briefing
    files: [scripts/cplat/ship.py, tests/cplat/test_ship_units_131.py]
    covers: [AC-211.1, AC-211.6, AC-211.9]
    parallel_safe: true
    depends_on: [t1, t3]
  - id: t5
    title: cplat quiet ci records the security gate and the ci stage of the build run
    files: [scripts/cplat/quiet.py]
    covers: [AC-211.7]
    parallel_safe: true
    depends_on: [t3]
  - id: t6
    title: Ship and build instructions start unit sessions from the briefing and drop the bookkeeping calls
    files: [plugins/component/commands/build.md, plugins/component/commands/ship.md, plugins/component/references/build-test-approval.md, plugins/component/references/build-tighten.md, plugins/component/references/build-load-run.md, plugins/component/references/ship-land-red.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/references/build-test-approval.yml, docs/rules/plugins/component/references/build-tighten.yml, docs/rules/plugins/component/references/build-load-run.yml, docs/rules/plugins/component/references/ship-land-red.yml]
    covers: [AC-211.6]
    parallel_safe: false
    depends_on: [t1, t2, t3, t4, t5]
human_steps:
  - After the release carrying spec 211, run journey 23, measure it with `cplat platform runs journey measure --steps`, and record both rows and the per-step comparison with journey 22 in docs/PERFORMANCE.md as measurements.md describes (a second journey when tokens land within ±10 %).
---

# Plan — 211 Unit sessions start with their instructions, less bookkeeping

[design.md](design.md) is the contract: §1 the briefing API and text, §2 the rules check, §3 the two ship commands, §4 `quiet ci`, §5 the markers, §6 `test-diff`, §7 the prompts.

Levels: t1, t3, t4, t7 → t2, t5 → t6. t3 and t4 both touch `scripts/cplat/spec.py` (different functions), so t4 is not parallel-safe. t6 edits the prompts last, once every command it tells sessions to rely on exists.

## t1 — briefing.py, the rules-check hook and the three reworded references

**Files:** scripts/cplat/briefing.py, scripts/cplat/rulescheck.py, plugins/component/commands/build.md, plugins/component/references/unit-mode.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/unit-mode.yml
**Covers:** AC-211.1, AC-211.2, AC-211.3, AC-211.4, AC-211.5, AC-211.6
**Goal:** the briefing of every unit can be printed and the guards hold on the released instructions.

**Implementation notes:**
- `briefing.py` exactly as design §1: `PLUGIN_ROOT`, `KNOWN_UNITS`, `GENERAL`, `MAPPING`, `UnknownUnit`, `BriefingUnavailable`, `kind`, `heading_key`, `sections`, `build`, `headings`, `problems`. Pure text work: no git, no run state.
- The cutter: a section is its heading line up to the next `##`/`###` line; trailing blank lines dropped; text verbatim, then `${CLAUDE_PLUGIN_ROOT}` → `str(root)`.
- `build` raises `BriefingUnavailable` with the reasons listed in §1 (unreadable file, missing key, missing row, missing paragraph or section).
- `problems` reports the four kinds of §1 with the messages given there; the reference regexes as written in §1.
- `rulescheck.check`: add the `briefing.problems(root / "plugins" / "component")` failures when `only` is None or covers build.md or unit-mode.md (§2); same `Failure` shape.
- Reword so that `problems()` is empty on the real files (A3, no allowlist): the `land` row of unit-mode.md ("In a build, Phase 7" → name the build instructions' pull request phase in words); build.md `## Rules` "push only in Phase 7, through `cplat pr open`" → "push only in the pull request phase, through `cplat pr open`", keeping the reason and `**Hard rule:**`; Phase 3 step 4 "exit 1 stops as in Phase 2" → state the stop itself (a changed or weakened test: stop and show the file and the reason; `test helper`/`type-only` line: `build-tighten.md`), with its reason clause.
- Update the register entries the rewording touches (build.yml R26 text, a new entry for the reworded Phase 3 sentence if the check asks for one; unit-mode.yml if the row is a rule sentence). Keep the prompt bytes within the baseline.

**Done when:** the acceptance tests of AC-211.2 to AC-211.5 and the briefing-text parts of AC-211.1 and AC-211.6 pass; `cplat platform rules check` passes.

## t3 — Forward-only build markers, record_gate, begin continuation

**Files:** scripts/cplat/runs.py, scripts/cplat/buildcmd.py, scripts/cplat/mutation.py, scripts/cplat/spec.py
**Covers:** AC-211.7, AC-211.9
**Goal:** the six build markers are set by the commands that start each phase, in order, once, in one run record.

**Implementation notes:**
- `runs.py`: `BUILD_MARKERS`, `UNIT_MARKERS`, the forward-only rule inside `phase` (§5), `mark`, `unit_started`, `build_run` (§4), `record_gate` (the body of today's `gate` branch of `_recording_command` plus `mark` of `build:qa` for `acceptance`, `build:verify` for `security`); the CLI `gate` calls `record_gate`.
- `begin` with `CPLAT_UNIT`: continue the pointer's active, unattached build run of the same `--spec` (no `abandoned` finish, no `_init_agents`, register the session claim, print `run <id> (continued)` and the budget line); after begin or attach call `unit_started(dir, $CPLAT_UNIT)`.
- `buildcmd.py`: the `schedule` CLI command (not the replan path) calls `runs.mark(repo, "build:implement")`.
- `mutation.py`: with `--write`, `runs.mark(root, "build:image")` after the write.
- `spec.py`: the `set-status` CLI with status `done` calls `runs.mark(root, "build:close")`. Touch nothing near `test-diff` (t4 owns it).
- All new calls never raise and never change a command's output or exit code.

**Done when:** the acceptance tests of AC-211.9 that need no ship command pass (markers by gate, schedule, mutate, set-status, begin; forward-only; explicit call accepted), and the `record_gate` part of AC-211.7; `tests/cplat/test_runs.py` stays green.

## t4 — cplat spec test-diff finds its base

**Files:** scripts/cplat/testdiff_base.py, scripts/cplat/spec.py
**Covers:** AC-211.8
**Goal:** `cplat spec test-diff` without a base behaves as with the latest "acceptance tests for <spec id>" commit, or refuses with exit 2.

**Implementation notes:**
- `testdiff_base.resolve(root) -> (sha, spec_id)`, `NoBase(why)`: spec from `judged_specs` by branch `feature/<id>`, else the only one; commit by `git log -1 --format=%H -F --grep "acceptance tests for <spec id>" HEAD` (§6).
- `spec.py`: `base` `nargs="?"`; when absent, resolve before the existing commit check, print `base: <sha7> (acceptance tests for <spec id>)`, set `ns.base` and let the existing path run unchanged, so `frozen_base`, `--approve`, `--tighten`, `--task`, `--by` and `red=given` (the found sha) apply.
- `NoBase` → stderr `ERROR: no base: <why>; pass it: cplat spec test-diff <base>`, exit 2, nothing checked.
- A given base: no change.

**Done when:** the acceptance tests of AC-211.8 pass.

## t7 — ADR, changelog, guide, measurement plan, version

**Files:** docs/adr/, docs/adr/README.md, docs/changelog.d/211-unit-briefing.changed.md, docs/unattended-delivery.md, docs/specs/211-unit-sessions-start-with-their/measurements.md, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-211.10
**Goal:** the decision, the change and the measurement method are written down.

**Implementation notes:**
- `cplat adr add unit-briefings-are-cut-from-the-build-instructions --decision "A unit session's instructions are cut at print time by heading key from build.md and unit-mode.md through one mapping in code, guarded by tests and the rules check"`; fill Status (Accepted), Context (#869: a third of unit-session calls were bookkeeping; reference read 33 times in journey 21; a knowledge graph gave no gain), Decision (design Decisions 1 to 3, no stored slice, no allowlist), Consequences (a renamed phase heading fails CI; a new section must be mapped; interactive runs unchanged). Never write the ADR file by hand; the README row comes from the command or by hand if it does not add one.
- `measurements.md`: the AC-211.10 method: journey 23 on the first release carrying 211, `cplat platform runs journey measure --steps`, per-step sums over unit sessions for the steps both journeys share, baseline journey 22 (18 unit sessions, about 21 M tokens, 9 to 36 calls each), thresholds (calls −25 %, tokens −10 %, escalations, failed verifications and failed test reviews no more than journey 22), the second-journey rule for tokens within ±10 %, and that the rows go in docs/PERFORMANCE.md.
- Changelog fragment per `docs/changelog.d/README.md` (changed): briefing from `ship start --unit` / `ship unit`, `quiet ci` records the gate, `test-diff` finds its base, markers set by commands.
- `docs/unattended-delivery.md`: one paragraph in the unit-mode section on the briefing and its fallback.
- Component plugin minor bump in `plugin.json` and `marketplace.json`.

**Done when:** `cplat spec check`, the docs checks of `devbox run quality` and `cplat platform pr-check` pass; the AC-211.10 test (measurement written down) passes.

## t2 — ship start --unit and ship unit

**Files:** scripts/cplat/ship.py, tests/cplat/test_ship_units_131.py
**Covers:** AC-211.1, AC-211.6, AC-211.9
**Goal:** a unit session's first call prints the shape, where the run stands and its briefing.

**Implementation notes:**
- `start` parser: `--unit`; refuse with `--detach`; validate with `briefing.kind` before `start_plain` (unknown → stderr line of §3, exit 2, no state change).
- Unit mode of `start_plain`: print the shape line first (`shapecmd.route`), then today's lines with `describe(st, repo)`, then the unit line, `next unit:` (`units.next_open`), a blank line and the briefing or the `briefing unavailable: …` line (§3); exit 0.
- `unit_command`: same order; status block per §3 (ship describe, else `build <spec>:` + `units.describe_lines`, nothing without a units file); command from the units file, else ship state, else `build`; `--json` adds `shape`, `next_unit`, `briefing`, `briefing_unavailable`.
- Both call `runs.unit_started(repo, unit)` after printing; read-only otherwise (no `refresh_units`), so a second call prints the same and writes nothing new.
- Update the module docstring's usage lines.
- `tests/cplat/test_ship_units_131.py`: the two `ship unit` assertions that pin the first line (`startswith`, exact equality) find the `unit task:t1: …` line among the output lines instead; nothing else in that file changes (AC-211.1 supersedes the old output shape).

**Done when:** the acceptance tests of AC-211.1, the CLI parts of AC-211.6 and the unit-start markers of AC-211.9 pass; `tests/cplat/test_ship_units_131.py` and the other ship tests stay green.

## t5 — cplat quiet ci records the gate and the stage

**Files:** scripts/cplat/quiet.py
**Covers:** AC-211.7
**Goal:** a green `cplat quiet ci` inside a build run records what the session used to record in two calls.

**Implementation notes:**
- After the run of script `ci` without arguments (also `--raw`), when `runs.build_run(cwd)` is set: green → `runs.record_gate(cwd, "security", "passed")` and `budget.record_stage(cwd, "ci", "passed")`; red → `budget.record_stage(cwd, "ci", "failed")` only; print the line of §4 after the usual output.
- No build run: no import side effects, output byte-for-byte unchanged. Exit code always the script's. Any recording error is swallowed.

**Done when:** the acceptance tests of AC-211.7 pass; the existing `quiet` tests stay green.

## t6 — Ship and build instructions start unit sessions from the briefing

**Files:** plugins/component/commands/build.md, plugins/component/commands/ship.md, plugins/component/references/build-test-approval.md, plugins/component/references/build-tighten.md, plugins/component/references/build-load-run.md, plugins/component/references/ship-land-red.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/references/build-test-approval.yml, docs/rules/plugins/component/references/build-tighten.yml, docs/rules/plugins/component/references/build-load-run.yml, docs/rules/plugins/component/references/ship-land-red.yml
**Covers:** AC-211.6
**Goal:** unit sessions no longer read the instructions or run the bookkeeping calls the commands now do; interactive runs keep the full instructions.

**Implementation notes:**
- `ship.md`: `--unit <unit>` → only `cplat component ship start <spec> --unit <unit>` (no `cplat shape`), follow the printed briefing instead of reading build.md and unit-mode.md; keep naming `references/unit-mode.md` as the source the briefing is cut from (AC-131.1's test reads it). Phase `build` and `pr`: `cplat spec test-diff --task <task>` without `RED=`.
- `build.md`: `--unit <unit>` → first call `cplat component ship unit` (it prints the shape and the briefing); `## cplat` says a unit session runs it instead of `cplat shape`. Remove `RED=$(git log …)` and every `$RED`. Remove the `runs phase` lines of `build:implement`, `build:qa`, `build:verify`, `build:image`, `build:close`; keep `build:tests` (marked as set by the unit's start in unit mode) and `build:pr`. Phase 3: `cplat quiet ci` records the security gate and the `ci` stage; only `gate security failed` after the last red round stays the session's call.
- References: `cplat spec test-diff $RED …` → `cplat spec test-diff …` in build-test-approval.md, build-tighten.md, build-load-run.md, ship-land-red.md; reword sentences that explain `$RED` as "the acceptance-tests commit `test-diff` finds itself".
- Add no `Phase <N>` or `<N>.<m>` reference that a unit's slice lacks (t1's guard runs in the rules check).
- Update register entries whose text changed; `cplat platform rules check` passes with the prompts within the byte baseline (no rebaseline).

**Done when:** the prompt parts of AC-211.6 pass (no "read" instruction before the start call for unit sessions, the fallback named, size within the baseline); `cplat platform rules check` and the existing prompt tests (`test_docs_131.py`, `test_159_batch_units.py`, `test_179_test_review.py`, `test_202_wait_detach.py`) stay green.
