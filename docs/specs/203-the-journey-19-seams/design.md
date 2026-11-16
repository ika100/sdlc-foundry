# Design — 203 The journey 19 seams

Three independent fixes in `cplat`; no prompt, plugin or template changes (A8), so no rules-register entry and no plugin
version bump.

## Decisions

- **The hand-off resolves the kube context once, before `ship.start`, and hands it on twice: in the ship state
  (`st["context"]`) and as `CPLAT_KUBE_CONTEXT` in the headless process's environment** (A1, A2). The state makes a restart
  reuse it without the session passing it again; the environment makes every `cplat` call of the headless run and of its
  unit sessions see it through the existing `settings.kube_context`, so deploy, smoke and the local port lookup (spec 199)
  agree. `ship deploy` also reads `st["context"]` directly, so a unit session that drops the variable still finds it.
- **Only `--context` is checked against the kubeconfig** (AC-203.2). A configured or environment context that is not
  there is passed on as today, and deploy reports what it finds; refusing it would break a session whose kubeconfig is
  written later. `k3d-<system>-local` is only chosen when the kubeconfig has it, by definition.
- **The system names for `k3d-<system>-local` are the `applications/*` folders of the linked gitops-apps** (read through
  `smoke._app_dirs`, as `ship.dev_namespace` does), asked only when no earlier source gave a context. No current-context
  guess (non-goal).
- **Units are re-derived at every unit boundary from the committed plan, keyed on task ids, files and dependencies**
  (A4, A5). The units file stores `plan_key`; the supervisor calls `units.reschedule` before it picks the next unit. Done
  task units are kept as they are and their tasks are left out of the new derivation, so a done unit is never regrouped
  into a new batch and run again (AC-203.3); every other task unit is derived as today, so a unit whose task set changed
  gets a new id and therefore a fresh entry (AC-203.4). This reuses `units.prepare`, which already merges stored entries
  by unit id; a fresh units file derives exactly as before.
- **`parallel_safe` is not part of `plan_key`** (A5 names ids, files and dependencies only). A `parallel_safe`-only edit
  takes effect at the next change that alters the key, or at the next `prepare` (a restart).
- **After a reschedule the run's budget is rescaled** (`budget.rescale`, as after the plan unit), because a run whose plan
  grew must not stop on a session budget sized for the old plan (AC-203.3: "neither escalates nor stops").
- **`cplat next` reads its sources in daemon threads under a 20 s per-source and a 60 s total deadline** (A7). The first
  group of sources runs at once, so a slow one costs at most 20 s; a source without an answer is abandoned and listed
  under `unavailable`. Bounding each `gh`/`git`/lock call separately would touch most of `needs`, `runlist` and
  `dispatch_*` and still miss a lock wait; one deadline at the source boundary covers every kind of block the spec names.
- **The call that blocked in journeys 17 and 19** (A7), from reading the code (the journey logs were not available to the
  architect; t1 confirms against them when they are): every `gh` call of `needs` (`needs.gh`, used by `_drafts` — one
  `gh api` per spec folder — and `_triage`) goes through `core.run` with **no timeout**, and `core.run` **waits up to
  65 min for a GitHub rate limit** (`RATE_LIMIT_MAX_WAIT`) and **up to 5 min for a dropped network**
  (`NETWORK_RETRY_MAX_WAIT`), printing its wait only on stderr. A journey runs many CI waits on one account, so the
  rate-limit wait is the likely hold. Second candidate: the inherited stdin of every child (`core.run`,
  `runs_store.gh`), through which `gh`, `git` or `ssh` can wait for a person.
- **`cplat next` gives its children no input and no prompts** (AC-203.6): before any source is read it points fd 0 at
  `/dev/null` and sets `GIT_TERMINAL_PROMPT=0`, `GH_PROMPT_DISABLED=1` and (unless set) `GIT_SSH_COMMAND="ssh -o
  BatchMode=yes"`. A program that reads stdin gets EOF; one that opens `/dev/tty` is told not to prompt; anything else is
  caught by the deadline.
- **An abandoned source ends the process hard** (`os._exit` after flushing stdout), because the abandoned thread may hold
  a lock or a child that interpreter shutdown or an `atexit` handler would wait for. It goes through the seam
  `nextcmd.hard_exit(code)`, which tests replace.
- No ADR: each decision extends the design of an existing spec (131 units, 192 `cplat next`, 200 hand-off) and does not
  outlive this feature as a new cross-cutting pattern.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/shipcontext.py` | resolve, check and describe the kube context of a hand-off | new |
| `scripts/cplat/ship_handoff.py` | `detach`: resolve before `start`, record, pass to `spawn`, print the line | changed |
| `scripts/cplat/ship.py` | `start` parser `--context`; `deploy` reads `st["context"]`; docstring | changed |
| `scripts/cplat/units.py` | `plan_key`, done units kept in the derivation, `reschedule` | changed |
| `scripts/cplat/supervisor.py` | reschedule before each unit; escalate a plan that fails its check | changed |
| `scripts/cplat/nextstate.py` | sources under deadlines (`SOURCE_SECONDS`, `TOTAL_SECONDS`) | changed |
| `scripts/cplat/nextcmd.py` | no input, prompt-free environment, `hard_exit` | changed |

## Contract

### `cplat component ship start <spec> --detach [--context C]` (AC-203.1, AC-203.2)

- New option `--context C` on `ship start`. Without `--detach`: exit 2, stderr `ERROR: --context needs --detach`
  (as `--answer`). In a headless session (`NOT_HANDED_OFF` path) it is ignored.
- Resolution, `shipcontext.resolve(repo, given, recorded) -> (name | None, source | None)`, first hit wins:

  | # | Source | `source` text printed |
  |---|---|---|
  | 1 | `--context C` | `--context` |
  | 2 | `st["context"]["name"]` of the same spec's run (a restart, AC-203.2) | `recorded at the hand-off` |
  | 3 | `CPLAT_KUBE_CONTEXT` of the calling session | `CPLAT_KUBE_CONTEXT` |
  | 4 | `KUBE_CONTEXT` of the calling session | `KUBE_CONTEXT` |
  | 5 | `kube_context:` in `.platform-settings.yml`, then the user settings file (`settings.kube_context`) | `kube_context in the project settings` / `kube_context in the user settings` |
  | 6 | `k3d-<system>-local` for the first `<system>` (gitops-apps in `.platform-app.yml` order, folders sorted) that the kubeconfig lists | `local cluster of <system>` |

  Empty or whitespace values are skipped. Row 2 applies only when `--context` is not given (a `--context` naming another
  context replaces the recorded one).
- Check: with `--context C`, `shipcontext.contexts()` (`kubectl config get-contexts -o name`, 10 s timeout; the seam tests
  replace; `None` when kubectl is missing or fails) must contain `C`; otherwise `ship start --detach` raises before
  `ship.start` and before any spawn: exit 1, one line `ERROR: kube context C is not in the kubeconfig` (no hint line), no
  state change, no process.
- State: `st["context"] = {"name": <name or null>, "source": <source text or null>}`, written with `st["headless"]`.
- Process: `spawn(..., context=<name>)` sets `CPLAT_KUBE_CONTEXT=<name>` in the child's environment when a name was
  resolved (the session's own `CPLAT_KUBE_CONTEXT` is replaced, not dropped). Every respawn (second `--detach`, resume after
  `ENDED:`, `--detach --answer`) resolves again with row 2 and so gets the same name.
- Output (`_handed_off`, also when a live process is reused): the line directly after `headless: pid <pid>, log <log>`:
  - `context: <name> (<source>)`, or
  - `context: none (dev is not checked; pass --context <kube-context>)`.

### `cplat component ship deploy` without `--context` (AC-203.1)

Context order: `--context`, the system ship's `product.context` (unchanged), **`st["context"]["name"]`** (new; prints
`kube context: <name> (recorded at the hand-off)`), then `settings.kube_context` (which sees the `CPLAT_KUBE_CONTEXT` the
hand-off set). With a context the deploy checks Argo CD health of `<service>-dev`, runs the dev smoke and records it in the
run (`st["smoke"]`, the run record's `smoke` section), so `ship status` shows `smoke: passed …` or a failed row. Without
any context the existing "not run" path is unchanged.

### Units after a plan change (AC-203.3, AC-203.4)

- `units.plan_key(sp) -> str | None`: the first 12 hex digits of SHA-256 of
  `json.dumps(sorted([id, sorted(files), sorted(depends_on)] for each task), separators=(",", ":"))`; `None` when the
  committed tree has no plan. `title`, prose, `covers`, `done`, `parallel_safe` and every other key do not change it.
- Units file: new top-level key `plan_key` (written by every `prepare`; `VERSION` stays 1; a file without it is read as
  unknown).
- Derivation `_ids_from(sp, keep)`: `keep` is the ordered list of stored `task:`/`batch:` units with status `done` whose
  tasks all still exist in the committed plan. Result: `plan`, `red-tests`, the kept units in their stored order, then the
  units of every task not covered by a kept unit (dependencies on tasks outside that set dropped, levels and batches as
  today), `verification`, `land`. With nothing kept (a fresh file) the result equals today's.
- `units.reschedule(repo, command, spec_id) -> dict | None`:
  - `None` when the `plan` unit is not done, the committed tree has no plan, or `plan_key` equals the stored one;
  - a stored key of `None` → `prepare` and `None` (a file from before this spec, nothing printed);
  - otherwise `specmod.check_plan(sp, *sp.plan)` on the committed spec; errors → `{"error": <first error>}` and nothing
    written;
  - else `prepare(repo, command, spec_id)` and `{"old": [ids], "new": [ids]}`; `None` when the ids did not change (the key
    is still stored).
- `supervisor.drive` calls it before each `units.next_open`:
  - `{"error": e}` → reason `plan.md does not check after a change: <e>`, escalated with cause `code` through
    `ship.escalate` in a ship run (as the no-progress path chooses), else `units.escalate`; the run ends
    `needs you: <reason>` with `EXIT_STOPPED`; no unit starts.
  - `{"old", "new"}` → prints `plan changed: units <old, comma-joined> -> <new, comma-joined>`, appends the same line to
    `summary.log` (`HH:MM HEADLESS <repo>: <spec> plan changed: …`), calls `budget.rescale(rid, repo, [spec])`, then picks
    the next unit from the new list.
- A replaced unit's id is new, so its entry starts with `sessions: 0`, `stalls: 0`, `status: open`. A kept or unchanged
  unit keeps every field.
- `cplat component build schedule <spec>` is unchanged: it derives its batches from the plan on each call, so it shows a
  changed plan at once.

### `cplat next` and `cplat next --json` (AC-203.5, AC-203.6)

- Constants `nextstate.SOURCE_SECONDS = 20`, `nextstate.TOTAL_SECONDS = 60` (tests may lower them).
- `nextstate.collect` reads its sources through `_within(name, kinds, fn, deadline)`: `fn` runs in a
  `threading.Thread(daemon=True)`, joined for `min(SOURCE_SECONDS, total deadline - now)` seconds. No answer → the source is
  added with `src.fail(name, "no answer within 20 s", kinds)` (the number is `SOURCE_SECONDS`) and the call returns the
  source's empty default; an exception is listed as today.
- Sources (name, kinds hidden, default), group 1 started together: `repo` (shape, local specs; `[]`; `None`/`{}`),
  `runs` (`runlist.collect`; `["escalation"]`; `[]`), `github` (`needs.collect`/`collect_repo`; `["approve", "answer",
  "triage"]`; empty doc), `github` (release items; `["release"]`; `[]`), `dispatcher` (`dispatch_view.status_doc` and the
  parked count; `["budget", "stuck"]`; none/0), `notifications` (channels; `[]`; `None`). Group 2 after group 1: the
  notifier state files (`notifications`, `[]`), then the in-memory steps (estimates, drafts, `what`, running rows).
- JSON: an abandoned source is one `unavailable` entry `{"source": "<name>", "error": "no answer within 20 s", "kinds":
  [...]}`; the screen names it as AC-192.4 says (never "Nothing is waiting", offers "Try again"). Exit 0.
- `nextcmd._next`, before `collect`: `os.dup2(<fd of os.devnull, read-only>, 0)`; `os.environ` gets
  `GIT_TERMINAL_PROMPT=0`, `GH_PROMPT_DISABLED=1` and `GIT_SSH_COMMAND` = `ssh -o BatchMode=yes` when unset.
- When `collect` abandoned a source (`state["abandoned"]` is true), `_next` prints, flushes stdout and stderr and calls
  `hard_exit(0)` (`os._exit`); otherwise it returns 0 as today. `cplat next answer` is unchanged.
