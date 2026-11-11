---
spec_id: 184-parallel-ships-do-not-stop-each-other
shape: platform
spec_hash: "5608e1ed0c78"
summary: Usage-limit pauses instead of stops, one repo slot pool shared with the dispatcher, land settles ADR-index and rule-register conflicts, land reads its CI logs, changed templates linted locally, env-prefixed devbox commands allowed
tasks:
  - id: t1
    title: Usage-limit detection, reset time and pause schedule (usagelimit)
    files: [scripts/cplat/usagelimit.py]
    covers: [AC-184.1, AC-184.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Pause minutes leave the budget ledger
    files: [scripts/cplat/budget.py]
    covers: [AC-184.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Repo slots as flock files beside the merge lock (run_slot)
    files: [scripts/cplat/run_slot.py]
    covers: [AC-184.8, AC-184.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: Environment-prefixed devbox commands from the spec folder (envprefix)
    files: [scripts/cplat/envprefix.py]
    covers: [AC-184.10]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: Land allowlist reads the saved CI logs and gh run view --log-failed
    files: [scripts/cplat/preflight.py]
    covers: [AC-184.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: ADR index and rule register resolvers with renumbering (land_resolve)
    files: [scripts/cplat/land_resolve.py]
    covers: [AC-184.6, AC-184.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: Lint the templates a branch changes, locally and in the smoke jobs
    files: [scripts/template-lint.py, scripts/ci-local.sh, .github/workflows/ci.yml, devbox.json]
    covers: [AC-184.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: Guide and changelog fragment
    files: [docs/unattended-delivery.md, docs/changelog.d/184-parallel-ships-do-not-stop-each-other.added.md]
    covers: [AC-184.2, AC-184.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: Land merge resolves ADR-index and rule-register conflicts
    files: [scripts/cplat/land_merge.py]
    covers: [AC-184.6, AC-184.7]
    parallel_safe: true
    depends_on: [t6]
    done: true
  - id: t10
    title: Unit mode pauses at the usage limit without stalls or counted sessions
    files: [scripts/cplat/supervisor.py, scripts/cplat/units.py]
    covers: [AC-184.1, AC-184.2, AC-184.3]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
  - id: t11
    title: cplat headless takes a slot, pauses in the legacy loop, wires the new allowlist parts
    files: [scripts/cplat/headless.py]
    covers: [AC-184.1, AC-184.2, AC-184.3, AC-184.4, AC-184.8, AC-184.10]
    parallel_safe: true
    depends_on: [t1, t2, t3, t4, t5]
    done: true
  - id: t12
    title: The dispatcher counts and shows manual slot holders
    files: [scripts/cplat/dispatch_cycle.py, scripts/cplat/dispatch_view.py]
    covers: [AC-184.9]
    parallel_safe: true
    depends_on: [t3]
    done: true
---

# Plan — 184 Parallel ships do not stop each other

Contract and decisions: [design.md](design.md). Level 1: t1–t8 (new modules, the budget, preflight, the template lint,
docs). Level 2: t9 (land wiring), t10 (unit mode), t11 (headless), t12 (dispatcher). No two tasks of a level share a file.

## t1 — Usage-limit detection, reset time and pause schedule (usagelimit)

**Files:** scripts/cplat/usagelimit.py
**Covers:** AC-184.1, AC-184.2 (the decision both drivers call)
**Goal:** one module that tells from a finished session whether it hit the usage limit, when it resets, how long the run
waits and when it must stop instead.

**Implementation notes:**
- `Hit`, `detect`, `Pause`, `Pauser` and the constants exactly as in design.md, Contract, "Usage-limit pause".
- `detect` reads only the last non-empty line for the message; silent = `output.strip() == ""` and `seconds < 60`.
- Reset parsing: `|<unix seconds>` at the line end; `resets [at] [<Mon> <d>[,] [at]] <h>[:<mm>][am|pm] [(<zone>)]` as the
  next such moment at or after `ended`, zone through `zoneinfo` (unknown zone: local), result local and naive.
- `Pauser.pause`: with reset, wait to `reset + 60 s`, line `paused: usage limit, resumes at <reset+1min>`; without,
  `BACKOFF_MINUTES[i]` then 60, line `paused: usage limit, next try at <now+wait>`; times `%Y-%m-%d %H:%M`.
- Cap: `total_seconds + wait > 360 min` returns `stop` (`STOP_PREFIX` + reset time or `unknown`), `seconds` 0.
- `pause` adds the wait to `total_seconds` only when it does not stop; `resumed()` resets the backoff index, not the total.
- No I/O and no sleeping here; the drivers sleep.

**Done when:** unit tests of `detect` (both message forms, the `resets` variants with and without zone, a mention of
the limit in an earlier line not counted, silent short/long) and of the schedule (5, 10, 20, 40, 60, 60 …; the cap with
and without a reset time) pass; the AC-184.1/2 acceptance tests pass after t10 and t11.

## t2 — Pause minutes leave the budget ledger

**Files:** scripts/cplat/budget.py
**Covers:** AC-184.3 (budget `minutes`)
**Goal:** a paused stretch never uses up the run's `minutes` budget.

**Implementation notes:**
- `add_pause(run_id, minutes)`: on the ledger `find(run_id)` returns, add to `current["paused_minutes"]` under the lock
  (`_modify`); never raises; no-op without a ledger or `current`.
- `used_of`: subtract `current.paused_minutes` from the live minutes (never below `carried.minutes`).
- `_fold_previous`: subtract the folded root's `paused_minutes` from its (end − start) before carrying.
- `on_finish` carries `used_of`'s minutes already, so it needs no change; check it with a test.
- Nothing else in the module changes.

**Done when:** a test opens a ledger, adds a pause, and `used_of` and a continued ledger (`_fold_previous`) both leave
the pause out; the budget tests stay green.

## t3 — Repo slots as flock files beside the merge lock (run_slot)

**Files:** scripts/cplat/run_slot.py
**Covers:** AC-184.8, AC-184.9 (the pool both `headless` and the dispatcher read)
**Goal:** at most `slots` unattended runs per repo on one machine, across worktrees and clones.

**Implementation notes:**
- API, file names, lines and environment variable exactly as in design.md, Contract, "Repo slots".
- Paths from `dispatch_state.state_root()` / `slug_dir`, slug from `dispatch_state.slug_of(repo)` (the merge lock's key).
- `total(repo)`: `dispatch_state.load(slug)["steering"]["slots"]` when a valid int ≥ 1, else `dispatch_policy.load(repo)`
  `values["slots"]`, a `PlatformError` from a broken file read as 1. Do not import `dispatch_cycle` (it imports this module).
- `held`: non-blocking `fcntl.flock` on slots 1..total; the stale line when the left-over JSON's pid is gone
  (`os.kill(pid, 0)` → `ProcessLookupError`); JSON written with `dispatch_state.write_json`; `CPLAT_SLOT` set and restored.
- Waiting: name the oldest live holder (`since`), print again only when it changes, `sleep(POLL_SECONDS)` through a
  module-level `sleep` tests replace; no timeout. `wait=False` raises `SlotBusy` with the `slot busy: …` text.
- Nested run: `os.environ["CPLAT_SLOT"]` starting with `<slug>#` yields `None` without a lock or a line.
- `holders(slug)`: read the JSONs of slots 1..`dispatch_state.MAX_SLOTS`, keep those whose pid runs.
- The lock file stays open (and locked) for the whole `with`; never pass it to a child process.

**Done when:** tests with two processes (or two `held` contexts with separate descriptors) show the second waits and then
starts after the first ends, `wait=False` raises with the line, a JSON with a dead pid is taken over with the stale line,
and `slots: 2` in `.platform/dispatch.yml` admits two.

## t4 — Environment-prefixed devbox commands from the spec folder (envprefix)

**Files:** scripts/cplat/envprefix.py
**Covers:** AC-184.10
**Goal:** a verification command a plan names as `NAME=value devbox run <script>` is allowed verbatim, anything else of
that form is listed as not allowed.

**Implementation notes:**
- `REFUSED_NAMES`, `REFUSED_PREFIXES`, `candidates`, `verdict`, `commands` as in design.md, Contract,
  "Environment-prefixed commands".
- `candidates`: inline spans between single backticks, first word `^[A-Za-z_][A-Za-z0-9_]*=`, at least one more word;
  the span is kept verbatim (outer spaces stripped), because the rule must equal what the session runs.
- `verdict`: chaining/substitution check on the raw text first (`;`, `&&`, `||`, `|`, `$(`, backtick, newline), then
  split with `shlex`; names uppercase and not refused; then exactly `devbox`, `run`, a script word, optional args.
- `commands`: `git show <units.feature_head(repo, id)>:docs/specs/<id>/plan.md` and `design.md`; a missing file is
  empty; results de-duplicated in order (plan before design).
- No import of `headless` (headless imports this module).

**Done when:** unit tests cover the allowed example (`TEST_FAKE_DELAY=2 devbox run test-fast`), each refusal kind of the
criterion (another program, each chain token, lowercase name, each refused name and prefix), and reading only the
committed files.

## t5 — Land allowlist reads the saved CI logs and gh run view --log-failed

**Files:** scripts/cplat/preflight.py
**Covers:** AC-184.4
**Goal:** a land session can read why its check went red, and nothing more of `gh run`/`gh api`.

**Implementation notes:**
- `run_allowlist(command, branches, log_dirs=())`: for `LAND_COMMANDS` append `Read(<dir>/**)` per log dir and the three
  `gh run view` rules of design.md, Contract, "Land allowlist", after the land rules; order stable, de-duplicated.
- New helper `log_dir_rule(path: Path) -> str`: `Read(~/…/**)` when under `Path.home()`, else `Read(//<abs>/**)`.
- New helper `ci_log_dir(repo: Path) -> Path`: `${XDG_CACHE_HOME:-~/.cache}/sdlc-foundry/logs/<repo.name>` (the folder
  `quiet._log_path` writes; do not create it).
- `refused_rules` unchanged; `/component:build` unchanged.
- `_self_check`: include a log dir and assert no refused rule matches the new samples.

**Done when:** a test of `run_allowlist` for ship, system ship and build shows exactly the new rules where expected and no
`gh run rerun|cancel|delete|watch` or `gh api` rule; the AC-184.4 acceptance test passes after t11 (dry-run output).

## t6 — ADR index and rule register resolvers with renumbering (land_resolve)

**Files:** scripts/cplat/land_resolve.py
**Covers:** AC-184.6, AC-184.7 (the resolution itself)
**Goal:** the two id-keyed files that conflict on every parallel land are merged as the union of both sides, the branch's
clashing number renumbered.

**Implementation notes:**
- `Context`, `Outcome`, `Refused`, `handles`, `resolve(repo, path, ctx, run)` as in design.md, Contract, "Index conflicts
  on land"; stages through `git show :1:/:2:/:3:<path>` with the given `run` (a missing stage is empty).
- Stage 2 is the branch (ours), stage 3 is `origin/<base>` (theirs): the merge runs on the PR branch.
- ADR index: mask rows with one placeholder, `git merge-file -p` the rest (conflict → `Refused`), union rows by linked file,
  renumber clashes (`git mv`, title, row, references in `ctx.changed`), sort by number, write; count references as defined.
- Files the branch added = `git ls-tree --name-only <ours> docs/adr/` minus the same at `<base>`; main's numbers from
  `<theirs>`.
- Rule register: split header/entries by the `- id: R<n>` line; header through `merge-file`; entries by id per design.md;
  renumber branch-added clashes to max+1 in the merged file; references in `ctx.changed` outside `docs/rules/`; theirs'
  order then the branch's additions.
- `Refused` messages name the path and the part (`… outside its table`, `… outside its id-keyed entries`,
  `… entry R7 changed on both sides`).
- Text and git plumbing only; no `gh`, no push, no commit (t9 does those).

**Done when:** unit tests on a temporary git repo with a real conflicting merge cover: union without a clash; one and
two ADR clashes with the exact lines and counts; a rows-both-changed refusal; a register union; an `R14` clash renumbered
with references; a header conflict and `register.yml` refused.

## t7 — Lint the templates a branch changes, locally and in the smoke jobs

**Files:** scripts/template-lint.py, scripts/ci-local.sh, .github/workflows/ci.yml, devbox.json
**Covers:** AC-184.5
**Goal:** a template lint error fails `devbox run ci` with the file, line and rule, and CI prints the same lines.

**Implementation notes:**
- `scripts/template-lint.py` (stdlib only, runnable by `python3` and `uv run`): the two forms, the render, the lint table,
  the parsers and every output line exactly as in design.md, Contract, "Template lint"; parsers as functions a test can
  import by path.
- Render data per template = the `--data` of its CI smoke job with `lint-`/`lint_` names (python: `module_name`).
- `scripts/ci-local.sh`: a step `lint of the templates this branch changes (spec 184)` running
  `uv run scripts/template-lint.py --changed`, before the cplat tests.
- `ci.yml`: the python smoke step calls the script in place of `ruff check` / `ruff format --check`; the java step in place
  of `mvn -B -q spotless:check checkstyle:check`; the web step in place of `pnpm lint`; go keeps the action. Add
  `scripts/template-lint\.py` to the `shared` regex of the `changes` job, and update its comment.
- `devbox.json`: add go (1.26, = `templates/service-go/copier.yml`), `golangci-lint`, a JDK 21 and `maven`.
- No template file changes (the Jinja escaping stays untouched).

**Done when:** parser tests (one sample per tool, including Checkstyle's `ConstantName` line) and a `--changed` test on a
temporary git repo (no template changed → nothing rendered; a changed `templates/x/` file selected) pass; `actionlint` and
`scripts/pin-actions.py --check` pass.

## t8 — Guide and changelog fragment

**Files:** docs/unattended-delivery.md, docs/changelog.d/184-parallel-ships-do-not-stop-each-other.added.md
**Covers:** AC-184.2, AC-184.8 (the lines and commands a person sees, documented)
**Goal:** someone running unattended knows what `paused: usage limit`, `environment pause`, `waiting for a slot` and
`slot busy` mean and what to do.

**Implementation notes:**
- In the guide: a short section "Several runs and the usage limit": the slot pool (`slots` in `.platform/dispatch.yml`,
  shared with the dispatcher and every worktree), `--no-wait`, the stale-slot line; the pause schedule and the 360-minute
  cap; running the same command again after `environment pause`; the land's ADR/rule renumbering lines.
- Name only commands and files that exist (`scripts/check-docs.py`); no spec numbers in the guide prose.
- Fragment format per `docs/changelog.d/README.md`.

**Done when:** `scripts/check-links.py` and `scripts/check-docs.py` pass.

## t9 — Land merge resolves ADR-index and rule-register conflicts

**Files:** scripts/cplat/land_merge.py
**Covers:** AC-184.6, AC-184.7
**Goal:** a land that merges `main` and conflicts only in the ADR index or a rule register finishes by itself.

**Implementation notes:**
- In `regenerate`, replace the `others` check: a path is `GENERATED`, or `land_resolve.handles(path)`, else
  `Unresolvable` as today.
- Build `land_resolve.Context` once per round: `base` = `git merge-base HEAD origin/<base>` before the merge, `ours` =
  `pre`, `theirs` = `origin/<base>`, `changed` = `git diff --name-only <base> <pre>`, `next_adr` =
  `lambda: adr.next_number(repo)`.
- `land_resolve.Refused` → `Unresolvable(f"{url} conflicts with {base} in {reason}: rebase is a human decision")`, merge
  aborted (the existing `except BaseException` path).
- `git add` every `Outcome.written`; after all paths, when a `docs/rules/` file was resolved, `rulescheck.check(repo)` must
  be ok, else `Unresolvable` with its first failure's message.
- Return the outcome lines after the round line; the commit (`-s`), push (no force), `await_head` and the caller's
  `wait_green` stay as they are; `Rounds.used`/`MAX_REGEN_ROUNDS` unchanged (the shared limit of 3).

**Done when:** the AC-184.6 and AC-184.7 acceptance tests pass and the spec 171/178 land tests stay green.

## t10 — Unit mode pauses at the usage limit without stalls or counted sessions

**Files:** scripts/cplat/supervisor.py, scripts/cplat/units.py
**Covers:** AC-184.1, AC-184.2, AC-184.3 (unit mode)
**Goal:** a ship or build in unit mode waits out the usage limit and goes on with the same unit; paused sessions never
count as stalls, invocations or minutes.

**Implementation notes:**
- `units.end_session(..., paused=False)`: with `paused` and no checkpoint, status open and hold None with `stalls`
  unchanged; with a checkpoint as today.
- `drive`: one `usagelimit.Pauser` per run; time each session with `h.clock()`; right after the session,
  `hit = usagelimit.detect(h.last_message(log, start), seconds, h.clock())`, then `units.end_session(..., paused=hit is not None)`.
- The escalation check (`_escalated`) keeps its place and wins over a pause.
- On a hit: `budget.count_invocation(rid, -1)`, `sessions -= 1` (also in `state`), `pause = pauser.pause(hit, h.clock())`;
  `pause.stop` → `end(pause.stop, h.EXIT_STOPPED)` without `ship.escalate`/`units.escalate`; else print the line,
  `h.sleep(pause.seconds)`, `budget.add_pause(rid, pause.seconds / 60)`, move `begin` forward when set, `continue`.
- A checkpoint in a paused session is still handled (plan rescale, verification grace) before the pause.
- No hit: `pauser.resumed()`; the stall rule as today (it now only sees real sessions).
- The summary line of a paused session says `paused: usage limit`.

**Done when:** the AC-184.1–3 acceptance tests in unit mode pass, including the 179 case (two empty sessions, then a
checkpoint, then the next unit).

## t11 — cplat headless takes a slot, pauses in the legacy loop, wires the new allowlist parts

**Files:** scripts/cplat/headless.py
**Covers:** AC-184.1, AC-184.2, AC-184.3, AC-184.4, AC-184.8, AC-184.10
**Goal:** every non-dry-run run holds a repo slot; the legacy loop pauses like unit mode; the allowlist carries the CI-log
rules and the allowed env-prefixed commands; the block lists the refused ones.

**Implementation notes:**
- Slot: after the `--dry-run` return, before `runlog.start`, enter `run_slot.held(repo, prompt, wait=not ns.no_wait)`
  (an `ExitStack` around the rest of `main`); `SlotBusy` → print its message, return 1.
- Allowlist: `preflight.run_allowlist(command, branches, log_dirs)` with `preflight.ci_log_dir(repo)` (and each
  `system_clones` path's log dir for `/system:ship`); for `UNIT_COMMANDS` with ids add `Bash(<cmd>)` for
  `envprefix.commands(repo, ids)[0]`; `allowlist_block(allow, deny, not_allowed=())` prints `not allowed: <command>` lines
  after `refused:`, also in `--dry-run`.
- Unit mode `make_cmd`: recompute `envprefix.commands` per call; print `run allowlist: added <command>` for each new one.
- `_drive`: the same pause sequence as t10 (no units file: keep `last` unchanged on a pause, `runs -= 1`,
  `count_invocation(rid, -1)`, `begin` moved forward, `budget.add_pause`); `pause.stop` → result and exit 1 without
  `ship.escalate`; `pauser.resumed()` after a normal session.
- `stop_of`: `environment pause:` → `("environment", "escalated")`; in `main`'s `finally`, that reason gets
  `esc = {"reason": result, "cause": "environment"}` (run record and dispatch result).
- Docstring and `--no-wait` help: the slot, the pause, the stop.

**Done when:** the AC-184.1–3 acceptance tests for the legacy loop, AC-184.4 and AC-184.10 (dry-run output) and AC-184.8
pass.

## t12 — The dispatcher counts and shows manual slot holders

**Files:** scripts/cplat/dispatch_cycle.py, scripts/cplat/dispatch_view.py
**Covers:** AC-184.9
**Goal:** a manual `cplat headless` in the repo takes a dispatcher slot, and `plan`/`status` say so.

**Implementation notes:**
- `dispatch_cycle._schedule` and `_record`: `manual = [h for h in run_slot.holders(slug) if h.unit is None]`; running count
  = dispatcher units running + `len(manual)` (pass placeholder rows without `slot` to `free_numbers`).
- `dispatch_view.slots_doc` / `status_doc`: add `manual` rows and count them in `running`/`free` (plan) and in
  `slots: <n> of <total> in use` (text); one `  held by <command> (manual)  pid …  since …  <checkout>` line per holder
  in `render_status` and in the plan's text.
- Do not count holders whose `unit` is set: their unit files already count.

**Done when:** the AC-184.9 acceptance test passes (a fake headless holding a slot through `run_slot.held`; no two runs
in one repo beyond `slots`), and the spec 167 dispatcher tests stay green.
