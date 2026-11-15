# Design — 200 A component ship runs in its own session

## Decisions

- **The hand-off is `cplat component ship start <spec> --detach`** (A1). `start()` runs unchanged first, so every refusal,
  the claim, the take-over and the branch switch stay what they are; only after it returns is `cplat headless
  "/component:ship <spec> [--no-merge] [--full]"` started detached in the clone (AC-200.1). The process code reuses spec
  155's pattern (`appship_proc.spawn`/`alive`): a new module `ship_handoff.py` with the same two seams, so tests replace
  `ship_handoff.spawn` and `ship_handoff.alive` and no real `claude` runs.
- **cplat refuses to hand off from a headless session, not the prompt** (AC-200.2, A2). With `CPLAT_HEADLESS` or
  `CPLAT_UNIT` set, `--detach` is ignored, nothing is spawned, and the line `headless: not handed off (this session runs
  under cplat headless)` is printed before today's output. The ship instructions always pass `--detach` except for `--here`
  and `--unit`, and go on with the phases when this line (or no `headless:` line) appears. So a headless session can never
  start another process, whatever its prompt says.
- **Run tree: the interactive ship run is the parent** (AC-200.1, A9). The detach call's `start()` creates or resumes the
  ship run R as today (mode `interactive`, it claims the interactive session's calls). The headless process gets
  `CPLAT_RUN_PARENT=R`, so its `headless` run H is R's child and its sessions are H's own (`runs_usage` mode `own`). Each
  token is counted once: the interactive session's calls belong to R, the headless sessions' to H. To keep the tree
  acyclic, `ship.start()` does not call `runs.link_parent` on a resumed run whose state has `headless` while
  `CPLAT_HEADLESS` is set (today that would make R a child of H). The spawned environment drops `CLAUDE_CODE_SESSION_ID`,
  `CPLAT_SESSION_ID`, `CPLAT_UNIT`, `CPLAT_HEADLESS`, `CPLAT_SYSTEM_DIR` and any `CPLAT_SHIP_ANSWER*` before it sets its own,
  so the headless run is never tied to the interactive session.
- **One budget, the size of a headless ship by hand** (AC-200.1). R is the root and opens the ledger with the `--budget`
  options (H, a child, opens none: AC-102.2). The detach call counts no invocation for the interactive session
  (`budget.open_root(..., session_invocation=False)`), so the headless sessions use the invocations exactly as they would by hand.
- **The interactive side never writes `cplat-ship.json` while the process lives.** The ship state gets one new key,
  `headless`, written once right after the spawn (the child needs seconds before its first `ship start`). The shipping
  session's own data (its session id and its Stop-hook counter) lives in a separate file
  `<git common dir>/cplat-ship-handoff.json`, so the two processes never overwrite each other's state.
- **A process that ends early is started once more** (AC-200.4, A6), as AC-155.5: `MAX_STARTS = 2` per ship run id.
  `ship wait` reports the first early end as `ENDED:`; the coordinator runs `ship start --detach` again, which spawns with
  `starts: 2`. The wait escalates the second early end with cause `environment`.
- **A handed-off run is archived by the shipping session** (AC-200.6), as a linked run is archived by the system ship
  (ADR-086): `supervisor.drive` skips `ship.finish` when the state has `headless`. The shipping session reads
  `cplat component ship status`, prints the report and runs `cplat component ship finish`.
- **The report comes from one function for both paths** (AC-200.6). `ship status` of a `done` run prints a `report:` block
  (and `--json` a `report` object) built by `ship_report.data(repo, st)`. Deploy now keeps its result lines in the state
  (`deploy_lines`), so nothing the report needs lives only in a session's output. `ship-finish.md` builds the table from that
  block in the in-session ship and in the hand-off, so both print the same rows from the same data.
- **The answer reaches the headless session through the environment** (AC-200.5, A8), as spec 186's system-ship answer:
  `--detach --answer TEXT` spawns with `CPLAT_SHIP_ANSWER=TEXT` and `CPLAT_SHIP_ANSWER_FROM=shipping session`; the detach call
  itself records no answer. `start()` records `{"at", "text", "from"}` and prints `answer from the <from>: <text>`
  (`from` defaults to `system ship`, so the system ship's wording is unchanged).
- **The shipping session takes a suggested answer only for cause `decision`** (AC-200.5, A7), mirroring
  [ADR-104](../../adr/104-a-system-ship-answers-an-escalated-repo-while-others-run.md): every question has a suggestion and
  the person said in this session to take them. Any other cause is reported and nothing is resumed.
- **The test-helper rule reaches every unit through the check, and the check reaches land** (AC-200.7, A10).
  `cplat spec test-diff` judged only `building` specs; after build Phase 6 the spec is `done`, so in `pr` and `land` the
  check saw nothing and a CI fix round had no verdict to follow (J16-1). It now also judges the spec of the clone's
  unfinished ship run. `--tighten` accepts a helper file that did not exist at the red commit when it defines no test and
  names no criterion id. `ship-land-red.md`, the `pr` phase and build's verification rounds run the same test-diff step as
  build Phase 2 step 2. `cplat component ship pr` now also writes the "How this was built" block (spec 133) into the body
  of a new or reused PR, so a tightening recorded in a fix round shows on the PR.
- **The hand-off text lives in a new reference** `plugins/component/references/ship-handoff.md`, read only when `ship start`
  printed `headless: pid …`, so the headless unit sessions, which load `ship.md`, do not pay for it. The prompts must not
  grow (AC-200.5, rule 6 of `docs/rules/README.md`): the plan pays for the new file by trimming `ship.md` and `ship-finish.md`.
- **ADR:** a new decision record "An interactive component ship runs in its own headless session" (it changes how every
  `/component:ship` runs and builds on ADR-028, ADR-075 and ADR-086). It is created in plan task t5 with
  `cplat adr add`, because the architect run that wrote this design had no shell.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/ship_handoff.py` | `detach` (the `--detach` path of `ship start`), `command`, `spawn`/`alive` seams, handoff file, `gate` for the shipping session | new |
| `scripts/cplat/ship.py` | `start` flags `--detach --answer --full`; no re-parenting under headless; `describe` `headless:` line and answer source; `gate` delegates to `ship_handoff.gate`; `_done` keeps `deploy_lines`; `status` report; `ship pr` writes the "How this was built" block; `finish` removes the handoff file | changed |
| `scripts/cplat/ship_report.py` | `data(repo, st) -> dict`, `lines(data) -> list[str]` | new |
| `scripts/cplat/shipwait.py` | `ship_wait`: unit lines, `WAIT:`, `ENDED:`, second end escalates, questions and log in `ESCALATED:`/`TIMEOUT:` | changed |
| `scripts/cplat/supervisor.py` | no `ship.finish` for a handed-off run | changed |
| `scripts/cplat/budget.py` | `open_root(..., session_invocation=True)` | changed |
| `scripts/cplat/spec.py`, `scripts/cplat/testdiff_select.py` | test-diff judges the ship run's spec; `--tighten` accepts a new helper | changed |
| `plugins/component/commands/ship.md`, `references/ship-handoff.md` (new), `references/ship-finish.md`, `references/ship-land-red.md`, `commands/build.md` | hand-off, report, helper rule in every fix round | changed |

## Contract

### `cplat component ship start <spec> --detach [--no-merge] [--full] [--take-over] [--budget K=V]... [--answer TEXT]`

`--full` is also accepted without `--detach` (no effect there). `--answer` without `--detach` exits 2 with
`ERROR: --answer needs --detach`.

Order of checks:

1. `CPLAT_HEADLESS` or `CPLAT_UNIT` set → print `headless: not handed off (this session runs under cplat headless)`, then
   behave exactly as `ship start` without `--detach` (exit codes and output as today). Nothing is spawned.
2. The ship state is for `<spec>`, has `headless`, and `alive(headless.pid)`:
   - run not escalated → no `start()`, no state write. Write the handoff file's `by` (this session), print
     `headless: pid <pid>, log <log>`, then `describe` without its `next:` line, then `next: cplat component ship wait`. Exit 0.
   - run escalated (the process is still ending) → wait up to 60 s for it to end, then go on with step 3; still alive →
     exit 1, `ERROR: the headless session of <spec> (pid <pid>) is still ending` with hint `run the same command again`.
3. The ship state is for `<spec>`, phase `done` → print `headless: run is done; log <log>` (log when known), `describe`;
   exit 0; nothing spawned.
4. `start()` as today (every refusal: same message, same hint, exit 1, nothing spawned). In detach mode it claims no owner
   (`stopgate.claim(st, None)`), records no answer, and counts no session invocation. Then `on_branch` as today.
5. `starts` = `headless.starts + 1` when the state's `headless.run_id` equals the run id now and that process is dead,
   else 1. `starts > MAX_STARTS` (2) → `ship.escalate(repo, "headless session ended twice in phase <phase>; log <log>",
   "environment")`, print the `ESCALATED:` lines of the wait (below), exit 1.
6. `spawn` → save `st["headless"]`, write the handoff file, print `headless: pid <pid>, log <log>`, `describe` without its
   `next:` line, `next: cplat component ship wait`. Exit 0. An `OSError` from spawn → exit 1, `ERROR: cannot start cplat
   headless: <error>`, the state gets no `headless`.

Spawned process: `cwd` the clone, `stdin` `/dev/null`, `stdout`+`stderr` appended to the log, `start_new_session=True`:

```
[sys.executable, <cplat.py>, "headless", *("--plugin-dir", d for d in $CPLAT_PLUGIN_DIRS),
 "/component:ship <spec id>" + (" --no-merge" if no_merge) + (" --full" if full)]
env: os.environ minus CLAUDE_CODE_SESSION_ID, CPLAT_SESSION_ID, CPLAT_UNIT, CPLAT_HEADLESS, CPLAT_SYSTEM_DIR,
     CPLAT_SHIP_ANSWER, CPLAT_SHIP_ANSWER_FROM; plus CPLAT_RUN_PARENT=<ship run id>
     and, with --answer, CPLAT_SHIP_ANSWER=<text>, CPLAT_SHIP_ANSWER_FROM=shipping session
log: headless.log_dir(clone) / "<YYYY-MM-DD_HHMMSS>-ship.log"
```

### Ship state (`<git common dir>/cplat-ship.json`), new keys

```json
"headless": {"pid": 4242, "log": "/…/headless/<repo>/2026-11-15_101500-ship.log",
             "started": "2026-11-15T10:15:00", "starts": 1, "run_id": "<ship run id at spawn>",
             "flags": ["--no-merge", "--full"]},
"answers": [{"at": "…", "text": "…", "from": "shipping session"}],
"deploy_lines": ["<each line deploy returned when it set phase done>"]
```

`answers[].from` is `system ship` when `CPLAT_SHIP_ANSWER_FROM` is unset. `describe` prints
`  headless: pid <pid>, log <log>` when `headless` is set, and `  answer from the <from>: <text>` for the last answer.
`ship finish` removes the handoff file with the state.

### Handoff file (`<git common dir>/cplat-ship-handoff.json`), written only by the shipping session

```json
{"spec": "<spec id>", "by": "<session id or null>", "gate": {"phase": "build", "head": "<sha>", "units_done": 3, "no_progress": 0}}
```

### `cplat component ship wait [--repo DIR] [--phase P] [--timeout T]` (T default 540; replaces AC-143.8)

Polls every 5 s; the deadline is fixed at the call's start; the call ends no later than T + 10 s after it started.

| Outcome | When | Lines after the progress lines | Exit |
|---|---|---|---|
| no run | the clone has no ship state | `ERROR: no ship run in <dir>` + hint (stderr) | 1, at once |
| reached | phase `P` or a later one (default `done`; an archived state counts) | `REACHED: ship <spec> is in phase <phase>` | 0 |
| escalated | the state is escalated | `ESCALATED: ship <spec>: <reason> (cause <cause>)`, one `question: <text> (suggested: <answer>)` per question (`(no suggestion)` when none), `log: <log>` when handed off, `resume it with /component:ship <spec>` | 1 |
| ended | handed off, `alive(pid)` false, run neither done nor escalated (state read again after the check), `starts < 2` | `ENDED: headless session ended in phase <phase>; log <log>`, `resume it with cplat component ship start <spec> --detach` | 1 |
| ended twice | as `ended` with `starts >= 2` | escalates (`headless session ended twice in phase <phase>; log <log>`, cause `environment`), then the `escalated` lines | 1 |
| progress | T ran out and a phase, a unit checkpoint or a feature-branch commit was new during the call | exactly one line `WAIT: run still going, progress in the last <T>s; run the same wait again` | 0 |
| timeout | T ran out, nothing new during the call | `TIMEOUT: ship <spec> is still in phase <phase> after <T>s of waiting (in it for <duration>)`, `log: <log>` when handed off, `run the same wait again` | 2 |

- `<T>` is `int(T)`; `<duration>` is `waits.duration`.
- Progress lines, printed as they happen: `HH:MM:SS ship <spec>: phase <phase>` at the start and each phase change (the
  line ends with the phase, as AC-143.8's tests read it), and `HH:MM:SS ship <spec>: unit <unit> done` when a unit of
  `<git dir>/cplat-units.json` turns done. The wait only reads the units file (no `refresh_units`).
- Progress during the call = the phase changed, the count of done units rose, or `refs/heads/<branch>` moved, each
  compared with the first poll of this call.
- `waits.record` result words: `reached`, `escalated`, `ended`, `progress`, `timeout`; an own run finishes `done` for
  `reached` and `progress`.

### Stop hook (`cplat component ship gate`) for the shipping session

Before today's owner logic, after the escalated/done check: when the state has `headless` and the hook's `session_id`
equals the handoff file's `by`, `ship_handoff.gate` answers:

- a `cplat` wait runs in the checkout (`waits.live`) → `{"decision": "block", "reason": …}` naming the wait, the count held
  (AC-171.8);
- else, with the mark (phase, feature head, done units) compared with the file's `gate`: progress resets the count, none adds
  one. Count below `stopgate.NO_PROGRESS_LIMIT` → block with `The ship run of <spec> runs in its own headless session (pid
  <pid>, log <log>), phase <phase>.` and `Next: cplat component ship wait, then act on its result (/component:ship,
  hand-off).` At the limit → `{"systemMessage": "ship <spec> runs headless (pid <pid>, log <log>); check it with cplat
  component ship wait"}`: the session may stop, nothing is escalated, because the run itself is not stuck.
- The headless sessions (the owner) get today's gate unchanged.

### `cplat component ship status` report (phase `done`)

Text, after today's lines:

```
report:
  plan: <n> tasks
  build: <total>/<total> criteria met (verification.md: pass) | verification.md: <fail|missing>
  pr: <url>, merged after <fix_rounds + 1> CI round(s) | <url>, green, not merged (--no-merge)
  merge: <sha>
  deploy: <line>                          (one per deploy_lines entry)
  smoke (dev): <st.smoke.row or ->
  promotion (staging): <st.staging.row without its "Promotion (staging): " prefix, or ->
  smoke (staging): <st.staging.smoke.row or ->
  dependency patches: none | <package> <from> → <to> (<advisories>)[, major bump]   (one line each)
  human steps: none | - [ ] <step>                                                   (one line each)
```

`--json` adds `"report": {"plan_tasks": int, "criteria_total": int, "verification": "pass"|"fail"|null, "pr": str|null,
"merged": bool, "ci_rounds": int, "merge_sha": str|null, "deployed": str|null, "deploy_lines": [str], "smoke_dev": str|null,
"promotion_staging": str|null, "smoke_staging": str|null, "dependency_patches": [{"package", "from", "to", "advisories",
"major"}], "human_steps": [str]}`. A run not `done` has no `report`. Dependency patches are the `patched` bumps of the
clone's deps state (`cplat deps report`'s source).

### `cplat spec test-diff` (AC-200.7)

- The specs judged are those with status `building` plus the spec of the clone's ship run when its phase is not `done`
  (the default file selection and the frozen-file selection of spec 172 both use this set).
- `--tighten <file>` for a file absent at the red commit: accepted (`<file>: tightened by an agent, recorded`) when it
  defines no test (`_test_names` empty) and names no criterion id; otherwise refused `new or deleted file` as today.
- Unchanged: a change that removes or renames a test, adds a skip, lowers the assertion count or changes the criterion
  ids is refused (exit 1); the coordinator escalates it with cause `decision` as a changed test.

### `cplat component ship pr`

Before the push, the body gets the "How this was built" block (`runs_built.pr_section(repo, spec)` applied with
`runs_built.apply`); a reused PR's body is updated with `gh pr edit <pr> --body-file <body>`. A failure to build the block
is a `note:` line and never fails the call.

## Prompt rules (binding text for t5)

`ship.md`, `## cplat`: `cplat component ship start <spec> --detach [--no-merge] [--full] [--take-over]` (without `--detach`
for `--here` and `--unit`). A `headless: pid` line → read `references/ship-handoff.md` and follow it; nothing else in
`ship.md` applies, because the headless session does every phase.

`ship-handoff.md`: start no subagent and no step of plan, build, PR, land or deploy, because their context would fill this
session. Run `cplat component ship wait` in the foreground and act on its result: `WAIT:` or `TIMEOUT:` → the same wait
(after three `TIMEOUT:` in a row show their lines and stop; the run goes on); `ENDED:` → `ship start <spec> --detach
[flags]`, then wait; `REACHED:` → Finish of `ship.md` (status, finish, `ship-finish.md`); `ESCALATED:` cause `decision`
→ every question suggested and the person said in this session to take suggested answers: resume with
`--detach --answer '<the suggested answers>'`; otherwise ask the person each question word for word and resume with their
answer; any other cause → the Escalate report (reason, status, decision), nothing resumed.

`ship.md` Escalate: an `answer from the shipping session:` line is applied like `answer from the system ship:`.
`ship-land-red.md` (and the `pr` phase's CI fix, build Phase 4's fix rounds): after the coder's fix, `cplat spec test-diff
$RED --task <task>`; a `test helper (defines no test)` or `type-only` line → `build-tighten.md`'s last paragraph without
asking; exit 1 otherwise → escalate cause `decision` as a changed test.
