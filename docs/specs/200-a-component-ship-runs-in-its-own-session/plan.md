---
spec_id: 200-a-component-ship-runs-in-its-own-session
shape: platform
spec_hash: b8f086b02b97
summary: "An interactive `/component:ship` hands the run to its own detached `cplat headless` process (`ship start --detach`), waits with `ship wait` (`WAIT:`/`ENDED:`/`ESCALATED:`), relays questions and prints the report from `ship status`; a test-helper-only fix in any fix round is recorded, not escalated"
tasks:
  - id: t1
    title: "`ship start --detach` hands the run to a detached headless process"
    files: [scripts/cplat/ship_handoff.py, scripts/cplat/ship.py, scripts/cplat/supervisor.py, scripts/cplat/budget.py]
    covers: [AC-200.1, AC-200.2, AC-200.4, AC-200.5]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: "`cplat spec test-diff` judges the ship run's spec and accepts a new helper with `--tighten`"
    files: [scripts/cplat/spec.py, scripts/cplat/testdiff_select.py]
    covers: [AC-200.7]
    parallel_safe: true
    depends_on: []
  - id: t5
    title: "Ship instructions: hand-off, report from `ship status`, helper rule in every fix round"
    files: [plugins/component/commands/ship.md, plugins/component/references/ship-handoff.md, plugins/component/references/ship-finish.md, plugins/component/references/ship-land-red.md, plugins/component/commands/build.md, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/references/ship-handoff.yml, docs/rules/plugins/component/references/ship-finish.yml, docs/rules/plugins/component/references/ship-land-red.yml, docs/rules/plugins/component/commands/build.yml, plugins/component/README.md, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/AGENTS.md, docs/adr/README.md, docs/adr/112-an-interactive-component-ship-runs-in-its-own-headless-session.md, docs/changelog.d/200-component-ship-own-session.changed.md]
    covers: [AC-200.1, AC-200.2, AC-200.5, AC-200.6, AC-200.7]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: "`ship wait` reports units, `WAIT:` on progress, `ENDED:`, questions and the log"
    files: [scripts/cplat/shipwait.py]
    covers: [AC-200.3, AC-200.4]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: "Stop hook holds the shipping session; `ship status` report; `ship pr` writes the How-this-was-built block"
    files: [scripts/cplat/ship.py, scripts/cplat/ship_handoff.py, scripts/cplat/ship_report.py]
    covers: [AC-200.6, AC-200.7]
    parallel_safe: true
    depends_on: [t1]
---

# Plan — 200 A component ship runs in its own session

The contract is [design.md](design.md). Level 1 runs t1 (the hand-off in `cplat`), t4 (the test-diff check) and t5 (the
prompt and docs text, which quotes only the output words the contract fixes) at once; they share no file. Level 2 runs
t2 (the wait, which reads t1's `headless` state and calls `ship_handoff.alive` and `ship_handoff.escalated_lines`) and t3
(the Stop hook, the report and the PR block, which extend t1's `ship_handoff.py` and `ship.py`) at once; they share no file.

## t1 — `ship start --detach` hands the run to a detached headless process

**Files:** scripts/cplat/ship_handoff.py, scripts/cplat/ship.py, scripts/cplat/supervisor.py, scripts/cplat/budget.py
**Covers:** AC-200.1, AC-200.2, AC-200.4, AC-200.5
**Goal:** `cplat component ship start <spec> --detach` runs today's `start()` and then starts `cplat headless
"/component:ship <spec> [--no-merge] [--full]"` detached, records it in the ship state and prints `headless: pid <pid>,
log <path>`; a live process is reused, an ended one is started once more, a headless session never spawns, and an answer
reaches the headless session as `answer from the shipping session: <text>`.

**Implementation notes:**
- New `ship_handoff.py` (module docstring as `appship_proc.py`'s): `MAX_STARTS = 2`, `HANDOFF_FILE = "cplat-ship-handoff.json"`,
  `command(spec_id, flags)`, `spawn(repo, spec_id, flags, parent_run, starts, answer) -> dict` and `alive(pid)` (delegates
  to `appship_proc.alive`) as the test seams; `in_headless()` (`CPLAT_HEADLESS` or `CPLAT_UNIT`); `read_file`/`write_by`
  for the handoff file; `escalated_lines(st) -> list[str]` (the wait's `ESCALATED:` lines, design.md); `detach(repo, ns)
  -> int` with the six-step order of design.md, "`ship start … --detach`".
- `spawn`: argv, cwd, log name, `start_new_session`, and the environment exactly as design.md lists (drop the session and
  answer variables, set `CPLAT_RUN_PARENT` to the ship run id; with an answer `CPLAT_SHIP_ANSWER` and
  `CPLAT_SHIP_ANSWER_FROM=shipping session`).
- `ship.main` `start`: add `--detach`, `--full` and `--answer`; `--answer` without `--detach` → exit 2 with
  `ERROR: --answer needs --detach`; `--detach` → `ship_handoff.detach`. Without `--detach` the output is unchanged.
- `ship.start()`: keyword `detach=False`. With it: `stopgate.claim(st, None)`, no answer recorded from the environment,
  `_open_budget(..., session_invocation=False)`. Always: on a resumed run whose state has `headless` while
  `CPLAT_HEADLESS` is set, skip `runs.link_parent`, so the ship run stays the parent of the headless run (AC-200.1).
- `ship.start()` answer: record `{"at", "text", "from"}` with `from` = `$CPLAT_SHIP_ANSWER_FROM` or `system ship`; print
  `answer from the <from>: <text>`. `describe`: `  headless: pid <pid>, log <log>` when set; the answer line uses the
  entry's `from` (default `system ship`); a `next=True` keyword so `detach` prints `next: cplat component ship wait` instead.
- `ship.finish`: also remove the handoff file.
- `budget.open_root`: keyword `session_invocation: bool = True`; `False` counts no invocation for the interactive session.
- `supervisor.drive`: skip `ship.finish` when the state has `headless` (the shipping session archives it, design.md).

**Done when:** the acceptance tests for AC-200.1, AC-200.2 and AC-200.5 pass, the `start --detach` parts of AC-200.4
pass (the respawn with `starts: 2`), `tests/cplat/test_155_repo_sessions.py` and the existing ship tests stay green, and
`devbox run test-fast` is green.

## t4 — `cplat spec test-diff` judges the ship run's spec and accepts a new helper with `--tighten`

**Files:** scripts/cplat/spec.py, scripts/cplat/testdiff_select.py
**Covers:** AC-200.7
**Goal:** in the `pr` and `land` phases (spec status `done`) `cplat spec test-diff $RED` still judges the spec's frozen
acceptance tests, so a helper-only change gets the `test helper (defines no test)` verdict and a changed test is refused;
`--tighten` records a helper that is new since the red commit.

**Implementation notes:**
- One function `judged_specs(root)` in `spec.py`: the `building` specs plus the spec of the clone's ship run
  (`<git common dir>/cplat-ship.json`, phase not `done`), read as JSON without importing `ship`; a missing or broken file
  adds nothing. Use it in `test_diff` for both the frozen-file path (`testdiff_select.frozen_files`) and the fallback selection.
- `tighten_test_change`: a file absent at `base` that exists now, defines no test (`_test_names` empty) and names no
  criterion id (`AC_ANY`) → accepted and recorded through `approve_test_change(..., kind="tightened")`; any other new or
  deleted file stays `new or deleted file`.
- Leave `tightening` unchanged: a removed or renamed test, a new skip, fewer assertions or changed criterion ids are refused.
- Update the `test_diff` docstring (which specs it judges).

**Done when:** the acceptance tests for AC-200.7 that exercise `cplat spec test-diff` pass (a helper-only change in a
`land` fix round accepted and recorded, a changed assertion refused), and the existing spec 165/171/172 test-diff tests
stay green.

## t5 — Ship instructions: hand-off, report from `ship status`, helper rule in every fix round

**Files:** plugins/component/commands/ship.md, plugins/component/references/ship-handoff.md, plugins/component/references/ship-finish.md, plugins/component/references/ship-land-red.md, plugins/component/commands/build.md, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/references/ship-handoff.yml, docs/rules/plugins/component/references/ship-finish.yml, docs/rules/plugins/component/references/ship-land-red.yml, docs/rules/plugins/component/commands/build.yml, plugins/component/README.md, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/AGENTS.md, docs/adr/README.md, docs/adr/112-an-interactive-component-ship-runs-in-its-own-headless-session.md, docs/changelog.d/200-component-ship-own-session.changed.md
**Covers:** AC-200.1, AC-200.2, AC-200.5, AC-200.6, AC-200.7
**Goal:** the interactive `/component:ship` hands off, waits, relays escalations and prints the report as design.md,
"Prompt rules", says; every fix round settles a helper-only change without a stop; the prompts do not grow.

**Implementation notes:**
- `ship.md`: the `start` call with `--detach` (not for `--here`/`--unit`; add `--here` to the description's usage and
  the Arguments line); a `headless: pid` line → `${CLAUDE_PLUGIN_ROOT}/references/ship-handoff.md`; Escalate: apply an
  `answer from the shipping session:` line like the system ship's (extend R11, do not add a second sentence).
- New `references/ship-handoff.md` with the text of design.md, "Prompt rules"; each rule sentence with a reason clause of
  at least 3 words and no `only when`/`unless`/`except` (rules README, rules 1–2). The shipping session asks the person,
  which `ship.md`'s "Never ask the user" does not cover: say so in the reference (it relays, it does not decide).
- `ship-finish.md`: the rows come from the `report:` block of `cplat component ship status` (both paths); drop the
  per-row source descriptions that block now carries.
- `ship-land-red.md`, `ship.md` phase `pr`, `build.md` Phase 4 fix rounds: after the fix, `cplat spec test-diff $RED
  --task <task>` (`RED=$(git log -1 --format=%H --grep 'acceptance tests for')`); a `test helper`/`type-only` line →
  `build-tighten.md`'s last paragraph without asking; exit 1 otherwise → escalate cause `decision` as a changed test.
- No growth: the changed and new prompt files together total at most their bytes before (rule 6); pay for
  `ship-handoff.md` by trimming `ship.md` and `ship-finish.md`. Do not run `cplat platform rules rebaseline`.
- Register: one entry per new or changed rule sentence (next free `R<n>`, verbatim `text`, `class`, `source: spec 200`);
  new files `ship-handoff.yml` (and `ship-finish.yml` when a rule sentence lands there).
- ADR: `cplat adr add an-interactive-component-ship-runs-in-its-own-headless-session --decision "An interactive
  /component:ship hands its run to its own detached cplat headless process and only waits, relays questions and reports"`;
  fill Status, Context, Decision, Consequences from design.md's Decisions and link design.md. When `cplat` assigns a
  number other than 112, that file takes the place of this task's `112-` path.
- `docs/AGENTS.md`: the `/component:ship` diagram notes the hand-off (interactive: one `cplat headless` process, the
  session waits). `plugins/component/README.md`: one sentence on the hand-off and `--here`.
- Bump the component plugin 1.20.0 → 1.21.0 in its `plugin.json` and in `.claude-plugin/marketplace.json`.
- Changelog fragment (`changed`), the README's style: bold summary ending `(#NNN).` with the PR number, what was wrong
  (5.7–8.6 M tokens of the main session for "Ship the spec"; the J16-1 stop) and what happens now; mention `--here`.

**Done when:** the prompt-structure acceptance tests for the covered criteria pass, `cplat platform rules check` passes
(register entries, no growth, every target resolves), `devbox run validate` is green, and the existing prompt tests
(`tests/cplat/test_143_waits_docs.py` and the ship.md structure tests) still pass.

## t2 — `ship wait` reports units, `WAIT:` on progress, `ENDED:`, questions and the log

**Files:** scripts/cplat/shipwait.py
**Covers:** AC-200.3, AC-200.4
**Goal:** `cplat component ship wait` follows design.md's wait table: a fixed deadline, `WAIT:` with exit 0 on progress,
`TIMEOUT:` with exit 2 without, `ESCALATED:` with questions and the log, `ENDED:` for a dead handed-off process and an
`environment` escalation for the second one.

**Implementation notes:**
- Keep `begin` fixed; `progressed` is set by a phase change, a rise in the done-unit count (`units._read`, read only) or
  a moved `refs/heads/<branch>`, each compared with the first poll; sleep `min(interval, left)`.
- Unit lines `HH:MM:SS ship <spec>: unit <unit> done`; phase lines unchanged (they end with the phase).
- `ESCALATED:` lines from t1's `ship_handoff.escalated_lines(st)`.
- Handed off (`st["headless"]`): `ship_handoff.alive(pid)` false → reload the state; still neither done nor escalated →
  `starts < MAX_STARTS` returns `ENDED:` (exit 1), else `ship.escalate(..., "environment")` and the escalated lines.
- `TIMEOUT:` adds `log: <log>` when handed off. Keep the `(code, lines)` return; the result line's first word
  (`REACHED:`, `ESCALATED:`, `ENDED:`, `WAIT:`, `TIMEOUT:`) is what t3's `_wait_command` maps to the record's result word.
- Update the module docstring's `component ship wait` lines.

**Done when:** the acceptance tests for AC-200.3 and the wait parts of AC-200.4 pass, and the AC-143.8 tests in
`tests/cplat/test_143_shipwait.py` (which this criterion replaces and the contract keeps compatible) stay green.

## t3 — Stop hook holds the shipping session; `ship status` report; `ship pr` writes the How-this-was-built block

**Files:** scripts/cplat/ship.py, scripts/cplat/ship_handoff.py, scripts/cplat/ship_report.py
**Covers:** AC-200.6, AC-200.7
**Goal:** while a handed-off run is unfinished the Stop hook holds the shipping session with the next step
`cplat component ship wait` (a running wait holds the count, AC-171.8); `ship status` of a done run prints the report data
both paths use; a tightening recorded in a CI fix round shows in the PR's "How this was built" block.

**Implementation notes:**
- `ship_handoff.gate(repo, st, hook_input) -> dict | None` as design.md, "Stop hook"; its counter lives in the handoff
  file, never in `cplat-ship.json`. `ship.gate` calls it after the escalated/done check when the hook's `session_id` equals
  the handoff file's `by`; the owner path is unchanged.
- `_done`: store `st["deploy_lines"]` (the lines before the human steps) on every path that sets phase `done`
  (deploy, `--no-merge` land, platform `not deployable`).
- New `ship_report.py`: `data(repo, st) -> dict` (keys of design.md's `report` object; criteria from the spec's active
  criteria and `spec.verification_result`; patches from the deps state's `patched` bumps; human steps from `plan_meta`)
  and `lines(data) -> list[str]` (the `report:` block).
- `ship status`: phase `done` → print the block after `describe`; `--json` adds `report`.
- `ship._wait_command`: map the last line's first word to `reached`, `escalated`, `ended`, `progress`, `timeout`.
- `open_pr`: before `run_ci`, apply `runs_built.pr_section(repo, st["spec"])` to the body with `runs_built.apply`; for a
  reused PR also `gh pr edit <pr> --body-file <body>`; an exception becomes a `note:` line via `say`, never a failure.

**Done when:** the acceptance tests for AC-200.6 pass (both paths give the report the same data; the hook holds the
shipping session and names the wait) and the AC-200.7 test of the PR block passes; `tests/cplat/test_ship*.py` and the
spec 126/171 Stop-hook tests stay green.
