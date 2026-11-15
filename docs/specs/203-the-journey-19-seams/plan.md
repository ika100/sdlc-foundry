---
spec_id: 203-the-journey-19-seams
shape: platform
spec_hash: b61b09230c95
summary: "The ship hand-off resolves, records and passes a kube context so the headless deploy checks dev and runs the smoke; a changed committed plan reschedules the units at the next unit boundary; `cplat next` reads its sources under 20 s / 60 s deadlines with no input"
tasks:
  - id: t1
    title: "`cplat next` returns within 60 s and never waits for input"
    files: [scripts/cplat/nextstate.py, scripts/cplat/nextcmd.py]
    covers: [AC-203.5, AC-203.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "A changed committed plan reschedules the units before the next unit"
    files: [scripts/cplat/units.py, scripts/cplat/supervisor.py]
    covers: [AC-203.3, AC-203.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: "The ship hand-off resolves, records and passes the kube context"
    files: [scripts/cplat/shipcontext.py, scripts/cplat/ship_handoff.py, scripts/cplat/ship.py, docs/changelog.d/203-the-journey-19-seams.fixed.md]
    covers: [AC-203.1, AC-203.2]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 203 The journey 19 seams

The contract is [design.md](design.md). The three fixes share no file and no interface, so all three tasks run at once in
one level. No prompt, plugin or template changes (spec A8): no rules-register entry, no plugin version bump.

## t1 — `cplat next` returns within 60 s and never waits for input

**Files:** scripts/cplat/nextstate.py, scripts/cplat/nextcmd.py
**Covers:** AC-203.5, AC-203.6
**Goal:** `cplat next` and `cplat next --json` exit 0 within 60 s in total and 20 s per source, whatever a source does (a
`gh` call that never returns, a lock another process holds, an unreadable run state, a child that wants input), and name
each silent source under `unavailable` with `no answer within 20 s`.

**Implementation notes:**
- The call that blocked (spec A7; design.md, Decisions): `needs.gh` → `core.run(["gh", …])` with no timeout, inside which
  `core.run` waits up to 65 min for a rate limit (`RATE_LIMIT_MAX_WAIT`) or 5 min for the network; second candidate the
  inherited stdin. First check this against the journey 17/19 logs when they are at hand (`~/Dev/demo-run*/`, the
  hand-over's stderr) and name what they show in the PR body; the fix below covers either.
- `nextstate`: `SOURCE_SECONDS = 20`, `TOTAL_SECONDS = 60`; `_within(name, kinds, fn, default, deadline)` with a daemon
  `threading.Thread`, the error text `f"no answer within {SOURCE_SECONDS} s"`; record abandonment in a flag the result
  carries as `state["abandoned"]`.
- Restructure `collect` into group 1 (started together: `repo`, `runs`, `github` needs, `github` release, `dispatcher`
  status doc and parked count, `notifications` channels) and group 2 (notifier state files under `_within`, then the
  in-memory steps), with the sources, kinds and defaults of design.md. Keep the existing `try`/`src.fail` behaviour for
  exceptions; `src.fail` is called from the main thread only.
- `_running`: split the dispatcher read (a group-1 source) from the run-row part (in memory), so a silent dispatcher
  leaves the run rows.
- `nextcmd._next`: before `collect`, point fd 0 at `/dev/null` and set `GIT_TERMINAL_PROMPT=0`, `GH_PROMPT_DISABLED=1`,
  `GIT_SSH_COMMAND` (default `ssh -o BatchMode=yes`); after printing, `hard_exit(0)` when `state["abandoned"]`.
  `hard_exit(code)`: flush stdout and stderr, `os._exit(code)` (the test seam).
- Leave `needs`, `runlist`, `core.run` and `cplat next answer` unchanged (non-goal: no faster sources, no cache); update
  both module docstrings (the deadlines, `hard_exit`).

**Done when:** the acceptance tests for AC-203.5 and AC-203.6 pass (a faked `gh` that sleeps, a held lock, an unreadable
state, a child that reads stdin), the spec 192 `cplat next` tests stay green, and `devbox run test-fast` is green.

## t2 — A changed committed plan reschedules the units before the next unit

**Files:** scripts/cplat/units.py, scripts/cplat/supervisor.py
**Covers:** AC-203.3, AC-203.4
**Goal:** when the committed plan's task ids, files or dependencies change during a unit-mode build or ship (also a repo of
a system ship, which runs the same supervisor), the next unit is chosen from units derived again from that plan: done
units stay done, changed units start fresh, a plan that fails its check escalates with cause `code`.

**Implementation notes:**
- `units.plan_key(sp)` as design.md; `prepare` writes `plan_key` into the units file.
- `_ids_from(sp, keep=())`: the kept done `task:`/`batch:` units (design.md, "Derivation") go after `red-tests`; the other
  tasks are levelled with their dependencies trimmed to that set (`specmod.topo_levels` rejects unknown ids) and batched by
  `_task_units` as today. `prepare` computes `keep` from the stored entries (status `done`, every task still in the plan)
  before it builds `entries`; a fresh file passes no `keep`, so its result is unchanged.
- `units.reschedule(repo, command, spec_id)` with the return values of design.md; the plan check on the committed spec
  (`_committed`) runs before anything is written.
- `supervisor.drive`: call `units.reschedule` at the top of the `while True` loop, before `next_open`. `{"error"}` →
  escalate as design.md (ship vs build as the no-progress path chooses) and `end(f"needs you: {reason}", EXIT_STOPPED)`;
  `{"old", "new"}` → the `plan changed:` line on stdout and in `summary.log`, then `budget.rescale(rid, repo, [spec])`.
- `_finished` keeps treating a task that left the plan as finished; after a reschedule no unit names such a task.
- Leave `buildcmd.schedule` unchanged; it derives its batches per call (the AC-203.3 schedule check needs no change there).
- Update the `units` module docstring (plan key, reschedule).

**Done when:** the acceptance tests for AC-203.3 and AC-203.4 pass (an added `t0` runs before its dependants with done
units not run again, a merged and a removed task, a text-only edit that changes no unit, a plan that fails its check), the
spec 131/159/163/186 unit and supervisor tests stay green, and `devbox run test-fast` is green.

## t3 — The ship hand-off resolves, records and passes the kube context

**Files:** scripts/cplat/shipcontext.py, scripts/cplat/ship_handoff.py, scripts/cplat/ship.py, docs/changelog.d/203-the-journey-19-seams.fixed.md
**Covers:** AC-203.1, AC-203.2
**Goal:** `ship start --detach` resolves one kube context in the order of design.md, refuses an unknown `--context`,
records it in the ship state, passes it to the headless process and prints `context: …` after the `headless:` line; the
headless `ship deploy` without `--context` uses it, so the dev smoke runs and is recorded.

**Implementation notes:**
- New `shipcontext.py` (module docstring as `localport.py`'s): `contexts() -> set[str] | None` (`kubectl config
  get-contexts -o name`, 10 s timeout, stdin `/dev/null`; the seam), `resolve(repo, given, recorded) -> (name, source)`
  with the six rows of design.md (row 6 through `ship.gitops_apps` and `smoke._app_dirs`, asked only when rows 1–5 give
  nothing), `line(name, source) -> str` (the two `context:` forms).
- `ship_handoff.detach`: after the `in_headless` check and before `ship.start`, resolve (recorded = `st["context"]["name"]`
  when `st["spec"] == sp.id`); a `--context` not in `contexts()` → `PlatformError("kube context C is not in the
  kubeconfig")` with no hint. After `start`, set `st["context"]`; `spawn(..., context=name)` sets `CPLAT_KUBE_CONTEXT`.
- `_handed_off`: the `context:` line right after `headless: pid …`, also on the reused-live-process path (from the state).
- `ship.main`: `--context` on `start`; without `--detach` → exit 2, `ERROR: --context needs --detach`.
- `ship.deploy`: after `product.context`, take `(st.get("context") or {}).get("name")` and say `kube context: <name>
  (recorded at the hand-off)`; then `settings.kube_context` as today.
- Docstrings: `ship.py`'s `ship start` usage line (`[--detach] [--context C]`), `ship_handoff.py`'s (the context).
- Changelog fragment `fixed`, the README's style: one bold summary per fix of this spec (J19-1 context, J19-2 reschedule,
  J19-3 `cplat next` deadlines), each what was wrong and what happens now.

**Done when:** the acceptance tests for AC-203.1 and AC-203.2 pass (faked `kubectl`, `gh` and `claude`: every source row,
a restart keeps the context, `none` without one, an unknown `--context` starts nothing), the spec 200 hand-off tests and
the ship deploy tests stay green, and `devbox run test-fast` is green.
