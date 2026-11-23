---
spec_id: 216-the-system-ship-drives-its-repos-without
shape: platform
spec_hash: ffea11f3c8dd
summary: "`cplat system ship drive` runs the mechanical part of a system ship (publish, repos, land, complete, finish) in a detached process that starts no model; the session only plans, builds the gitops entry, runs `cplat system ship wait` and hands over; `CPLAT_SYSTEM_DRIVER=0` brings back today's loop"
tasks:
  - id: t1
    title: "`cplat system ship drive`: the detached driver and its loop"
    files: [scripts/cplat/appship_driver.py, scripts/cplat/appship.py, scripts/cplat/appship_proc.py, scripts/cplat/waits.py]
    covers: [AC-216.1, AC-216.2, AC-216.3, AC-216.4, AC-216.5, AC-216.9, AC-216.10, AC-216.11]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: "`/system:ship` with the driver: drive, wait, hand-over; today's loop as the switch-off reference; ADR and docs"
    files: [plugins/system/commands/ship.md, plugins/system/references/ship-loop.md, docs/rules/plugins/system/commands/ship.yml, docs/rules/plugins/system/references/ship-loop.yml, tests/cplat/test_186_system_ship.py, tests/cplat/test_186_attended_ask.py, tests/cplat/test_194_system_ship_wait.py, tests/cplat/test_143_waits_docs.py, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/AGENTS.md, docs/adr/README.md, docs/adr/128-a-system-ships-mechanical-loop-runs-in-cplat.md, docs/changelog.d/216-system-ship-driver.changed.md]
    covers: [AC-216.7, AC-216.10, AC-216.12]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: "`cplat system ship wait`: step lines and one result (DONE, ENTRY, WAIT, ESCALATED, STOPPED, ENDED, TIMEOUT)"
    files: [scripts/cplat/appship_wait.py, scripts/cplat/appship.py, scripts/cplat/waitdetach.py]
    covers: [AC-216.4, AC-216.5, AC-216.6, AC-216.11]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: "Stop hook: hold the owner on `cplat system ship wait`, driver steps are progress, the driver's waits do not count"
    files: [scripts/cplat/appship_state.py]
    covers: [AC-216.8]
    parallel_safe: true
    depends_on: [t1]
---

# Plan — 216 The system ship drives its repos without a model

The contract is [design.md](design.md). Level 1 runs t1 (the driver in `cplat`) and t4 (the prompt, the reference, the
register and the docs; they quote only the output words the contract fixes) at once, and they share no file. Level 2
runs t2 (the wait, which reads t1's progress file and `state.driver` and calls `appship_driver.alive`) and t3 (the Stop
hook, which reads the progress file through t1's helper) at once, and they share no file. t2 depends on t1 because both
change `appship.py` and the wait imports t1's module.

## t1 — `cplat system ship drive`: the detached driver and its loop

**Files:** scripts/cplat/appship_driver.py, scripts/cplat/appship.py, scripts/cplat/appship_proc.py, scripts/cplat/waits.py
**Covers:** AC-216.1, AC-216.2, AC-216.3, AC-216.4, AC-216.5, AC-216.9, AC-216.10, AC-216.11
**Goal:** `cplat system ship drive` checks the switch and the run, then starts or reuses one detached driver per run.
The driver applies today's `/system:ship` rules for phases `publish`, `repos` and `complete` through `cplat system ship`
subprocess steps and ends on the entry, a stop rule, an escalation or `finish`, exactly as design.md, "Contract", says.

**Implementation notes:**
- New `appship_driver.py` (module docstring as `appship_proc.py`'s): `MAX_STARTS = 2`, `PROGRESS_FILE =
  "cplat-app-ship-driver.json"`, `SWITCH = "CPLAT_SYSTEM_DRIVER"`. The seams are `spawn(gitops, run_id, starts) -> dict`,
  `alive(pid)` and `run_step(gitops, argv) -> Step` (dataclass `code, out, err`). Add `progress(gitops, st=None) -> dict
  | None`, which reads the file with the pid matching of design.md; t2 and t3 import it.
- `drive(gitops) -> int`: the condition table of design.md, in that order. Take the state lock (`appship_state._locked`)
  around the liveness check, the spawn and the `state.driver` write. Compute `starts` as the design says, escalate above
  `MAX_STARTS` with `appship_state.escalate(..., "environment")`, and print the `ESCALATED:` lines. Until t2 lands, a
  local helper prints them; t2 swaps it for `appship_wait.escalated_lines`.
- `spawn`: argv `[sys.executable, cplat.py, "system", "ship", "--repo", gitops, "drive", "--loop"]`, cwd gitops,
  `start_new_session=True`, stdin DEVNULL, stdout and stderr into the log. The environment is exactly as design.md lists.
- `loop(gitops) -> int` with the pseudocode of design.md. Each step appends to the log and rewrites the progress file
  atomically. The answer text is `"; ".join(f"{q['text']}: {q['suggested']}")` in question order (A6). The escalate
  reason is the first escalated repo's `reason` in plan order. The `TIMEOUT:` line is the first stdout line that starts
  with `TIMEOUT:`, and a `WAIT:` line is found on stderr with `--json`.
- `appship.py`: subparser `drive` with a hidden `--loop` (`argparse.SUPPRESS`) that calls `appship_driver.loop`.
  Without it, call `appship_driver.drive`. Add both to the module docstring.
- `appship_proc.alive(pid, marker="headless")`: the reused-pid check looks for `marker`. `appship_proc.spawn` pops
  `CPLAT_SYSTEM_DRIVER_RUN` from the repo session's environment.
- `waits.running`: with `CPLAT_SYSTEM_DRIVER_RUN` set, the mark's `session` is `driver:<value>`, ahead of the session
  variables.
- Leave every other `system ship` verb unchanged: the driver only calls them.

**Done when:** the acceptance tests for AC-216.1 to AC-216.3, AC-216.9 and AC-216.10 pass. The driver-side tests for
AC-216.4, AC-216.5 and AC-216.11 pass too: the stop and entry ends in the progress file, and the step sequence of every
scenario, except the `ENDED:` restart scenario, which needs t2. The tests also show that a fake `claude` is never
called. `tests/cplat/test_155_repo_sessions.py`, `test_143_shipwait.py`, `test_194_system_ship_wait.py` (its CLI tests)
and the `test_appship_*` suites stay green, and `devbox run test-fast` is green.

## t4 — `/system:ship` with the driver: drive, wait, hand-over; today's loop as the switch-off reference; ADR and docs

**Files:** plugins/system/commands/ship.md, plugins/system/references/ship-loop.md, docs/rules/plugins/system/commands/ship.yml, docs/rules/plugins/system/references/ship-loop.yml, tests/cplat/test_186_system_ship.py, tests/cplat/test_186_attended_ask.py, tests/cplat/test_194_system_ship_wait.py, tests/cplat/test_143_waits_docs.py, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/AGENTS.md, docs/adr/README.md, docs/adr/128-a-system-ships-mechanical-loop-runs-in-cplat.md, docs/changelog.d/216-system-ship-driver.changed.md
**Covers:** AC-216.7, AC-216.10, AC-216.12
**Goal:** after phase `plan`, the `/system:ship` session runs `phase publish`, `drive` and `wait` and acts on the
wait's result as design.md, "Prompt rules", says. Today's Phase `publish`/`repos`/`complete` rules live in
`references/ship-loop.md`, read only after `driver: off`. `ship.md` ends shorter, and the prompts in total do not grow.

**Implementation notes:**
- `ship.md`: replace the sections Phase `publish`, Phase `repos` and Phase `complete` with one section, "Phases
  `publish`, `repos` and `complete`", holding the design's bullets. Keep the cplat, Rules, Phase `plan` and Escalate
  sections. Write the attended-answer sentence once, with its reason.
- New `references/ship-loop.md`: a one-line purpose ("Read from `/system:ship` when `cplat system ship drive` printed
  `driver: off`"), then today's three phase sections word for word, so that AC-186.2/3/12 and AC-194.4 stay true on this
  path (spec note 2).
- Register: move the entries of the moved sentences (R4, R9, R11, R14, R16 and any other that moves) from `ship.yml`
  to the new `ship-loop.yml` with the same ids, classes and sources. Add entries for the new sentences in `ship.yml`
  (next free `R<n>`, verbatim `text`, `class: practice`, `source: spec 216`). Rules README rules 1 and 2: a reason
  clause, and no `only when`/`unless`.
- No growth: `ship.md` must end with fewer bytes than at the merge base (AC-216.7), and the prompts in total must stay
  within `baseline.prompt_bytes`. Pay for the new section by trimming the moved text out of `ship.md`. Do not run
  `cplat platform rules rebaseline`.
- Retarget the earlier prompt-structure tests to the file that now holds their rule: `test_186_system_ship.py`
  (AC-186.2/3), `test_186_attended_ask.py` (AC-186.12), `test_194_system_ship_wait.py` (the `PATH` of AC-194.4) and
  `test_143_waits_docs.py` (`ship-loop.md` carries `cplat system ship next --wait`, `ship.md` carries
  `cplat system ship wait`). Change only the path or the mapping, never an assertion.
- ADR: `cplat adr add a-system-ships-mechanical-loop-runs-in-cplat --decision "After phase plan a system ship's publish,
  repos, land and completion run in a detached cplat driver that starts no model; the session builds the gitops entry,
  waits and hands over"`. Fill in Status, Context (journey 23: coordinator 8.0 M tokens in 78 calls), Decision, and
  Consequences: it amends ADR-082 and ADR-086; the switch is `CPLAT_SYSTEM_DRIVER=0`; and the kill rule of AC-216.12 (at
  most 40 coordinator calls and 4.0 M tokens in "One spec for the whole system", no more escalations or stops than
  journey 23, else the default flips to off in the next release and the change is reverted). Mark ADR-082 and ADR-086
  "amended by" it in the index. When `cplat` assigns a number other than 128, that file replaces this task's `128-` path.
- `docs/AGENTS.md`: the `/system:ship` description names the driver and the wait. `plugins/system/README.md`: one
  sentence on the driver and the switch.
- Bump the system plugin 1.25.0 → 1.26.0 in its `plugin.json` and in `.claude-plugin/marketplace.json`.
- Changelog fragment (`changed`), in the README's style: what was wrong (journey 23: 24.4 M tokens and 51 min for the
  step, with 31 relay calls of the coordinator), what happens now, the switch, and the measure of AC-216.12.

**Done when:** the prompt-structure acceptance tests for AC-216.7 and AC-216.10 pass. `cplat platform rules check` passes
(register entries, no growth, every target resolves), and so does `cplat platform pr-check` for the fragment and the
versions. The retargeted spec 143/186/194 prompt tests pass, and `devbox run validate` is green. AC-216.12 is measured
on the first journey after the release; this task records only its rule.

## t2 — `cplat system ship wait`: step lines and one result (DONE, ENTRY, WAIT, ESCALATED, STOPPED, ENDED, TIMEOUT)

**Files:** scripts/cplat/appship_wait.py, scripts/cplat/appship.py, scripts/cplat/waitdetach.py
**Covers:** AC-216.4, AC-216.5, AC-216.6, AC-216.11
**Goal:** `cplat system ship wait [--timeout T]` prints a timed line per ended driver step and ends with exactly one
result of design.md's wait table, in its order, no later than T + 10 s.

**Implementation notes:**
- New `appship_wait.py`: `wait(gitops, timeout, interval=5.0) -> tuple[int, list[str]]` and
  `escalated_lines(st) -> list[str]`. Use `waits.now`/`waits.sleep` with a fixed `begin` and sleep `min(interval, left)`,
  as `shipwait.next_wait` does.
- Read the state with `appship_state.load_state` and the progress with `appship_driver.progress`. Print the step lines
  in the format of design.md (words up to the first option; `escalate` without its reason).
- Progress during the call means a step started or ended, or a change of `appship_state._mark(st)["phase"]`.
- Row 6 escalates through `appship_state.escalate(gitops, text, "environment")`, then reloads the state for the block.
- `appship.py`: subparser `wait` with `--timeout` (default 540) and a hidden `--interval`. Run it inside
  `waits.running("cplat system ship wait", gitops)` (a mark, no recorded seconds). `status --json` adds
  `driver_progress`. Swap t1's local escalated-lines helper for `appship_wait.escalated_lines`.
- `waitdetach.WAIT_COMMANDS`: add `("system", "ship", "wait")`.

**Done when:** the acceptance tests for AC-216.6 and the wait-side parts of AC-216.4 (`STOPPED:`) and AC-216.5
(`ENTRY:`) pass, and the whole AC-216.11 simulation passes, the killed-driver scenario included (`ENDED:`, restart,
second end escalating), in under 60 s. The spec 202 detached-wait tests stay green.

## t3 — Stop hook: hold the owner on `cplat system ship wait`, driver steps are progress, the driver's waits do not count

**Files:** scripts/cplat/appship_state.py
**Covers:** AC-216.8
**Goal:** while a driver is recorded, the Stop hook holds the owning session outside its own wait, with the next step
`cplat system ship wait`. Its own running wait lets the stop through, and the driver's steps count as progress.

**Implementation notes:**
- `next_step(st)`: with `st.get("driver")` and a phase other than `done`, return the design's text.
- `_mark`: append ` driver <n>` to `phase` (n = the ended steps in `appship_driver.progress(repo, st)`; import it inside
  the function, as the module imports its peers).
- `gate`: `waits.live(repo, session)` instead of `waits.live(repo)`. Leave the owner, non-owner and two-stop logic
  unchanged; the driver never sets `owner`.

**Done when:** the acceptance tests for AC-216.8 pass, `tests/cplat/test_appship_gate_126.py`,
`test_appship_gate_126_extra.py` and the spec 171/202 wait-gate tests stay green, and `devbox run test-fast` is green.
