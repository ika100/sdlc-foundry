# Design — 089 Agent quality is measured per agent and shape

## Decisions

- **Two record sections plus one status object, all in the 087 record.** `agents` (one entry per agent × shape ×
  model) and `replans` hold the evidence. `agent_metrics` says which metrics this run measured and whether recording
  was complete. They live in the active record of the `build` run, or of the ship run the build attached to. They change
  in place through one new generic mutator, `runs.mutate`, and reach the store once, at `finish` (AC-087.21).
  Readers that don't know them ignore them. ADR-032 already provides for later sections, so there is no new ADR. This
  design.md is the binding contract for specs 090 (retro) and 094 (re-plan on conflict).
- **Events are the source of truth. `counts` is derived from them.** Each entry keeps its events (kind, task, path,
  cause, ...). `counts` is recomputed from the events and `agent_metrics.measured` after every change. The report
  re-derives everything from `events`, so a hand-edited or older `counts` never misleads it.
- **"Not measured" is recorded, never inferred from a 0 (AC-089.9).** `agent_metrics.measured` lists the metrics whose
  observation point this run reached. Every recording call marks its own metric measured. A call without events (for
  example `tester` with no ids, or a green land) marks it measured with 0. A metric missing from `measured` has the
  count `null` in every entry. A record without `agent_metrics` (pre-089, or a ship that never built) measured nothing.
- **cplat records what cplat sees, the prompt records the rest.** Recording happens in code wherever cplat itself
  makes the observation:
  - `cplat ship land` sees the red or green PR CI (AC-089.5).
  - `cplat spec test-diff` sees the refused diff (AC-089.7).
  - `merged` computes the out-of-plan files from git and the plan (AC-089.2).
  - `conflict` reads the unmerged paths from git (AC-089.3).
  - `findings` parses `verification.md` (AC-089.6).

  Only judgement calls come from the build prompt through `cplat runs agent <event>`: which agent was spawned, a
  hand-back's cause, which deviations the reviewer judged not acceptable, which tests failed for the wrong reason.
- **Attribution is by routing, not by guess.** An agent's name is what `cplat shape` routes the role to
  (`shapecmd.route`). `model` is the `model:` line of that agent's definition
  (`plugins/<plugin>/agents/<role>.md` under `core.PLATFORM_ROOT`). `model_id` is only what the orchestrator passes
  with `--model-id`. The entry key is `agent|shape|model`, so a later call that knows the `model_id` fills in the same
  entry. Red PR CI always goes to the shape's coder, never to quality or security (AC-089.5). Every task of one build
  shares the shape's coder entry, so a review finding counts once per criterion and cycle, and the covering tasks are
  listed on the event (AC-089.6).
- **Recording never stops a build (AC-089.10).** Every `runs_agents` function and `cplat runs agent` swallow all
  errors and exit 0. That includes argparse errors: `SystemExit` is caught, so a malformed call never exits 2. When an
  event is malformed, or cannot be written, `runs.mark_incomplete` sets `agent_metrics.complete = false` and appends
  the problem. It also appends the problem to a side file that `runs.finish` merges, so a record whose active file
  could not be written still says it is incomplete. The CLI prints one `WARNING:` line on stderr, never on stdout.
- **The report is a second aggregate over the same store read.** `cplat runs report --agents` reuses 087's read,
  window, `--repo` filter and `run_id` dedupe. The aggregation is a pure function in `runs_report.py`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/runs_agents.py` | identity (routing + model alias), the `agents` / `replans` / `agent_metrics` sections, every recording function, counts, `cplat runs agent` CLI | new |
| `scripts/cplat/runs.py` | `mutate`, `current_run`, `mark_incomplete` (+ merge in `finish`), redaction exemption for `spec` in the new sections, `begin` initialises the sections, `runs agent` delegation, `report --agents/--by-version/--agent/--shape` | changed |
| `scripts/cplat/runs_report.py` | `select` (window, repo, dedupe; shared with 087's `aggregate`), `aggregate_agents`, `render_agents_text` | changed |
| `scripts/cplat/ship.py` | `land` records red-CI rounds and the green conclusion | changed |
| `scripts/cplat/spec.py` | `test-diff --by --task` records refusals | changed |
| `scripts/cplat/cplat.py` | docstring line | changed |
| `plugins/svc/commands/build.md`, `plugins/svc/commands/ship.md`, `plugins/app/commands/build.md` | the `cplat runs agent` calls | changed |

## Contract

### Record sections

All three are top-level, non-reserved sections of the 087 record (schema 1). They appear in the order they were first
written. `runs begin build` writes them empty, so even a build that stops in Phase 0 has `agents: []`, `replans: []`
and an `agent_metrics` object (AC-089.1).

#### `agent_metrics`

```json
{"schema": 1, "complete": true, "measured": ["fix_rounds", "out_of_plan"], "problems": []}
```

| Field | Meaning |
|---|---|
| `schema` | `1` |
| `complete` | `false` once any recording call failed or was malformed (AC-089.10). It never returns to `true`. |
| `measured` | Sorted, unique metric keys whose observation point this run reached (see Metrics). |
| `problems` | At most 10 short strings, first ones kept, e.g. `malformed: fix-round cause 'lint'`, `write failed: OSError: ...`. |

#### `agents` entry

```json
{
  "id": "svc:coder|service-python|sonnet",
  "agent": "svc:coder",
  "shape": "service-python",
  "model": "sonnet",
  "model_id": "claude-sonnet-4-5-20250929",
  "counts": {
    "fix_rounds": {"lint/type": 1, "test": 0, "ci": 1, "verification": 0},
    "red_ci": 1,
    "findings": {"first": {"not met": 1, "partial": 0, "deviation": 0},
                 "after fix": {"not met": 0, "partial": 0, "deviation": 0}},
    "refused_test_diffs": null
  },
  "events": [
    {"id": "fix-round:1", "kind": "fix-round", "cause": "lint/type", "task": "t2"},
    {"id": "fix-round:2", "kind": "fix-round", "cause": "ci", "task": null},
    {"id": "red-ci:1", "kind": "red-ci", "check": "test (pytest + coverage)", "checks": ["test (pytest + coverage)"]},
    {"id": "finding:1", "kind": "finding", "criterion": "AC-089.3", "severity": "not met", "pass": "first",
     "cycle": 1, "tasks": ["t2", "t4"]}
  ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `id` | str | `<agent>\|<shape>\|<model>`. It is unique within the section. |
| `agent` | str | The routed name, e.g. `svc:coder`, `web:tester`, `svc:architect`, `shared:quality`. |
| `shape` | str | From `cplat shape` detection. `none` when the repo has no shape (detection fails). |
| `model` | str | The `model:` alias of the agent definition. `unknown` when the definition or the line is missing. |
| `model_id` | str \| null | The last non-null `--model-id` given for this entry. |
| `counts` | obj | Derived; one key per metric of the agent's role (Metrics table). The value is `null` when the metric is not in `agent_metrics.measured`. Roles without metrics have `{}`. |
| `events` | list | In the order they happened. Every event has `id` (`<kind>:<n>`, where n numbers events of that kind across the whole `agents` section from 1) and `kind`. |

The role is the part of `agent` after `:`.

**Event kinds** (the fields beyond `id` and `kind`):

| kind | in the entry of | fields | AC |
|---|---|---|---|
| `out-of-plan` | architect | `task`, `path` | .2 |
| `merge-conflict` | architect | `spec`, `task`, `with` (str \| null), `paths` (list), `author` `{"agent", "model", "model_id"}`, `outcome` `re-planned` \| `resolved` \| `escalated` | .3 |
| `re-plan` | architect | `task`, `conflict` (the `merge-conflict` event id) | .14 |
| `fix-round` | coder | `cause` `lint/type` \| `test` \| `ci` \| `verification`, `task` (str \| null) | .4 |
| `red-ci` | coder | `check` (the first failed check's name: the cause), `checks` (every failed check's name, in the watch's order) | .5 |
| `finding` | coder | `criterion` (str \| null), `task` (str \| null, only for a deviation named by task), `severity` `not met` \| `partial` \| `deviation`, `pass` `first` \| `after fix`, `cycle` (int ≥ 1), `tasks` (the covering tasks) | .6 |
| `refused-test-diff` | coder or quality | `file`, `reason`, `task` (str \| null) | .7 |
| `tester` | tester | `reason` `untraced` \| `wrong failure`, `criterion` (str \| null), `test` (str \| null) | .8 |

**Natural keys** (idempotent upserts: a repeated call updates the event instead of adding one):
- out-of-plan: (task, path)
- finding: (cycle, severity, criterion or task)
- tester: (reason, criterion or test)
- refused-test-diff: (file, task)

`merge-conflict`, `re-plan`, `fix-round` and `red-ci` always add a new event.

**`counts` per role:**

| Role | `counts` keys |
|---|---|
| `architect` | `out_of_plan` int, `merge_conflicts` int, `conflicts_resolved` int (conflicts whose outcome is `resolved`; null with `merge_conflicts`), `replans` int |
| `coder` | `fix_rounds` `{"lint/type", "test", "ci", "verification"}`, `red_ci` int, `findings` `{"first": {"not met", "partial", "deviation"}, "after fix": {...}}`, `refused_test_diffs` int |
| `quality` | `refused_test_diffs` int |
| `tester` | `tester_events` `{"untraced", "wrong failure"}` |
| any other | `{}` (the entry still records participation) |

#### `replans` entry (AC-089.14)

```json
{"id": "re-plan:1", "spec": "089-agent-quality-is-measured-per-agent-and", "task": "t3", "agent": "svc:architect",
 "model": "opus", "model_id": null, "conflict": "merge-conflict:1"}
```

`id` equals the `re-plan` event's id in the architect entry. `conflict` is the id of the task's latest `merge-conflict`
event, or `null` when the task has none.

#### Metrics and when they are measured

| Metric key | Role | Marked measured by |
|---|---|---|
| `out_of_plan` | architect | `merged`, `conflict` |
| `merge_conflicts` | architect | `merged`, `conflict` |
| `replans` | architect | `merged`, `conflict`, `replan` |
| `fix_rounds` | coder | `merged`, `fix-round`, `findings` |
| `red_ci` | coder | `ship land` reaching a green or red conclusion, `red_ci()` |
| `findings` | coder | `findings` |
| `refused_test_diffs` | coder, quality | every `cplat spec test-diff` run (pass or refuse) |
| `tester_events` | tester | `tester` (also with no ids) |

Each recording call also ensures the entry of the agent it counts against, so that agent "took part" (AC-089.1).
`merged` ensures the architect's and the coder's entries.

#### Redaction

`runs.finish` redacts every string, as in 087. Two exceptions are added to the identifiers: `spec` inside
`agents[].events[]` and inside `replans[]`, because spec ids are often 40+ characters and would become
`<long-string>`. Event ids are short (`<kind>:<n>`), so the link from `replans[].conflict` to the event survives
redaction. Long test names in `tester` events may be redacted. That is the 087 rule, accepted.

### Python API — `scripts/cplat/runs.py` (additions)

```python
def mutate(run_id: str | None, change: Callable[[dict], None]) -> str:
    """Apply `change` to the active record under the lock. "ok" | "none" (run_id None, unknown or finished: no-op)
    | "error" (change or write raised; nothing written). Never raises."""

def current_run(repo_dir: Path) -> str | None:
    """run_id of the pointer `<git common dir>/cplat-run.json` when that run is still active, else attach_point(repo_dir).
    Never raises."""

def mark_incomplete(run_id: str | None, section: str, problem: str) -> None:
    """Append {"section", "problem"} as one JSON line to `<state_dir>/active/<run_id>.incomplete.jsonl` (plain append,
    no lock), then try mutate(...) to set rec[section]["complete"] = False and append the problem (≤ 10).
    Never raises."""
```

Changes to existing behaviour:
- `finish`: before redaction, each line of `<run_id>.incomplete.jsonl` sets `rec[section]["complete"] = False` and adds
  the problem (unique, ≤ 10, creating `{"schema": 1, "complete": False, "measured": [], "problems": []}` when the
  section is missing). The file is deleted with the active file.
- `_scrub`: also exempt the chains `("agents", "events", "spec")` and `("replans", "spec")`.
- `cplat runs begin <kind>`: for `kind == "build"` (own or attached run), `runs_agents.init(rid)` (lazy import).
- `main`: `argv[0] == "agent"` → `return runs_agents.main(argv[1:])`.
- `report` gets `--agents`, `--by-version`, `--agent NAME`, `--shape SHAPE`. Without `--agents`, any of the other three
  raises `PlatformError("--by-version, --agent and --shape need --agents", hint="cplat runs report --agents ...")`.
  Configuration, unreachable store and window are exactly as in 087.

### Python API — `scripts/cplat/runs_agents.py`

Every public function takes `run_id: str | None` first (None, unknown or finished → no-op), never raises, and prints
nothing. A malformed argument → `runs.mark_incomplete(run_id, "agent_metrics", "malformed: <what>")` and nothing else.
`mutate(...) == "error"` → `mark_incomplete(..., "write failed: <ExceptionName>: <msg>")`.

```python
SECTION, REPLANS, STATUS = "agents", "replans", "agent_metrics"
METRICS = ("out_of_plan", "merge_conflicts", "replans", "fix_rounds", "red_ci", "findings", "refused_test_diffs",
           "tester_events")
ROLE_METRICS = {"architect": ("out_of_plan", "merge_conflicts", "replans"),
                "coder": ("fix_rounds", "red_ci", "findings", "refused_test_diffs"),
                "quality": ("refused_test_diffs",), "tester": ("tester_events",)}
FIX_CAUSES = ("lint/type", "test", "ci", "verification")
SEVERITIES = ("not met", "partial", "deviation")
TESTER_REASONS = ("untraced", "wrong failure")
CONFLICT_OUTCOMES = ("re-planned", "resolved", "escalated")

def identity(repo: Path, role: str, model_id: str | None = None) -> dict:
    """{"agent", "shape", "model", "model_id"}. role is a role (`coder`) or a full name (`web:coder`). A role is resolved
    through shapecmd.route(repo)["agents"]; when routing fails, shape = "none" and agent = "shared:<role>" for quality
    and security, else "svc:<role>". model = the `model:` frontmatter of PLATFORM_ROOT/plugins/<plugin>/agents/<role>.md,
    else "unknown"."""

def init(run_id) -> None                      # creates agents [], replans [], agent_metrics (only those missing)
def spawned(run_id, repo: Path, role: str, *, model_id: str | None = None) -> None   # ensure entry; set model_id
def merged(run_id, repo: Path, task: str, since: str, helpers: Sequence[str] = ()) -> None
def conflict(run_id, repo: Path, task: str, *, with_task: str | None = None, paths: Sequence[str] | None = None,
             outcome: str = "escalated", spec: str | None = None) -> str | None     # returns the event id
def conflict_outcome(run_id, repo: Path, task: str, outcome: str) -> None
def replan(run_id, repo: Path, task: str, *, model_id: str | None = None) -> None
def fix_round(run_id, repo: Path, cause: str, *, task: str | None = None) -> None
def red_ci(run_id, repo: Path, checks: Sequence[str]) -> None          # [] = a green conclusion: measured, no event
def findings(run_id, repo: Path, cycle: int, *, deviations: Sequence[str] = (), spec: str | None = None) -> None
def tester(run_id, repo: Path, *, untraced: Sequence[str] = (), wrong_failures: Sequence[str] = ()) -> None
def refused_test_diff(run_id, repo: Path, files: Sequence[tuple[str, str]], *, by: str = "coder",
                      task: str | None = None) -> None                   # [(file, reason)]; [] = passed: measured
def main(argv: list[str]) -> int                                           # always 0
```

Behaviour that is not obvious from the signatures:
- **`merged`** runs `git -C repo diff --name-only <since>..HEAD`. It reads the task's `files` from the plan of the
  record's `spec` (`spec.find(repo, spec).plan`). A changed path is in plan when one of these holds:
  - it equals a listed file,
  - it matches a listed glob (`fnmatch`, with `**` matching across `/`),
  - it lies under a listed directory (an entry ending in `/`).

  Each other path that is not in `helpers` becomes an `out-of-plan` event in the architect's entry. A git failure, or
  an unknown task or spec → malformed.
- **`conflict`**: `paths` defaults to `git -C repo diff --name-only --diff-filter=U` (so call it before `git merge
  --abort`). `with_task` defaults to the task with `done: true` in the plan whose `files` share the most paths with the
  conflict; a tie goes to the later task in plan order; none → `null`. `author` is the architect entry's identity at
  that moment. `spec` defaults to the record's `spec`.
- **`conflict_outcome`** sets `outcome` on the task's latest `merge-conflict` event. If the task has none, the call is
  malformed.
- **`replan`** adds the `re-plan` event and the `replans` entry. It sets the linked conflict's outcome to `re-planned`
  and applies `model_id` to the architect entry.
- **`findings`** reads `docs/specs/<spec>/verification.md` (spec = argument, else the record's `spec`):
  - It reads the criteria table. In each row whose first cell is an `AC-` id, the verdict cell (lowercased, stripped)
    `not met` or `partial` becomes a `finding`.
  - Each `deviation` value is an AC id (tasks = the plan tasks covering it) or a task id (`criterion` null,
    `task` = it, `tasks` = [it]).
  - `pass` is `first` for cycle 1 and `after fix` for later cycles.
  - A missing file or a table without AC rows → malformed.
- **`red_ci`** counts against `identity(repo, "coder")`.
- **`refused_test_diff`** counts against `identity(repo, by)`. `by` is `coder` or `quality`; any other value is
  malformed.

### CLI — `cplat runs agent` (always exit 0, nothing on stdout)

The run is `runs.current_run(--dir)`, default `.`: the build's pointer, else the repo's unfinished ship run.

| Command | Calls |
|---|---|
| `cplat runs agent spawned <role> [--model-id ID]` | `spawned` |
| `cplat runs agent merged <task> --since <rev> [--helper PATH]...` | `merged` |
| `cplat runs agent conflict <task> [--with TASK] [--path P]... [--outcome escalated\|re-planned] [--spec S]` | `conflict` (default outcome `escalated`) |
| `cplat runs agent conflict-outcome <task> <re-planned\|resolved\|escalated>` | `conflict_outcome` |
| `cplat runs agent replan <task> [--model-id ID]` | `replan` |
| `cplat runs agent fix-round <lint/type\|test\|ci\|verification> [--task T]` | `fix_round` |
| `cplat runs agent findings --cycle N [--deviation AC-or-task]... [--spec S]` | `findings` |
| `cplat runs agent tester [--untraced AC]... [--wrong-failure TEST]...` | `tester` |

Every subcommand takes `--dir D`. Choices are validated in code, not by argparse, so a bad value is "malformed", not
exit 2. Any parse error (`SystemExit`) → `mark_incomplete` on the current run. Whenever a call marks the run incomplete,
it prints one line on stderr:

```
WARNING: agent metric not recorded (<problem>); this run's agent metrics are marked incomplete
```

### In-code recording

- **`ship.land`**: after `wait_checks` returns, in `try/except Exception: pass`:
  - red → `runs_agents.red_ci(st.get("run_id"), repo, [c["name"] for c in failed])`;
  - green → `runs_agents.red_ci(st.get("run_id"), repo, [])`.

  Reruns (087 `reruns`) never reach this point as red, so they are never counted (AC-089.5). `merge_gitops` and
  `deploy` record nothing for agents. The return value, the stdout and the exit code are unchanged.
- **`cplat spec test-diff <base> [files] [--by coder|quality] [--task T]`**: after the existing output, `rid =
  runs.current_run(root)`, then `runs_agents.refused_test_diff(rid, root, [(f, why) for f, (ok, why) in result.items()
  if not ok], by=ns.by, task=ns.task)`, wrapped. `--by` defaults to `coder` and is not validated by argparse. The
  output and the exit code (0/1) are unchanged. `spec.test_diff()` itself records nothing.

### Report — `cplat runs report --agents [--by-version] [--agent NAME] [--shape SHAPE] [--since DAYS] [--repo R] [--json]`

```python
def select(records, *, since_days, repo, now) -> list[dict]   # 087's window + repo filter + run_id dedupe, reused by aggregate()
def aggregate_agents(records, *, malformed: int, buffered: int, since_days: int, repo: str | None, agent: str | None,
                     shape: str | None, by_version: bool, store: str, now: datetime.datetime) -> dict
def render_agents_text(agg: dict) -> str
```

The rules:
- **Rows.** A row is (agent, shape, model), plus `platform_version` with `--by-version`. A record counts for a row when
  its `agents` list holds an entry with that key. A record without `agents` (pre-089) is in no row. Entries without a
  string `agent`, `shape` or `model` are skipped.
- **Filters.**
  - `--agent NAME` keeps rows whose `agent == NAME`. A NAME without `:` matches the role (the part after `:`).
  - `--shape` keeps rows whose `shape` equals it.
- **Measured runs per metric.** These are the row's records whose `agent_metrics.measured` holds the metric. Per-run
  values come from the entry's `events` (not `counts`). `avg = sum / measured runs`, rounded to 3 decimals. Zero
  measured runs → `avg: null` and every per-cause value `null` (AC-089.9).
- **Metrics.** A row has exactly the metrics of its role (`ROLE_METRICS`). Other roles have `metrics: {}`.
- **`merge_conflicts.resolved_share`** = conflicts with outcome `resolved` / all conflicts in the measured runs,
  rounded to 3 decimals. It is `null` when there are none (AC-089.14).
- **`rework`** = the sum of the row's metric `avg` values (null counts 0), plus `findings.after_fix.avg`, rounded to 3
  decimals. `replans` counts besides `merge_conflicts`.
- **Sort.** Rows go by `rework` descending, then `agent`, `shape`, `model` ascending. With `--by-version`, each
  (agent, shape, model) group is placed by its highest `rework`, and inside the group the versions ascend
  (`core.vtuple`; unparseable versions last, by text). That keeps before and after a release side by side
  (AC-089.12).
- **`few_runs`**: `runs < 5`.
- **`incomplete_runs`**: the row's records with `agent_metrics.complete == false`.
- **`top_causes`** (AC-089.13). There is one label per event:
  - `out-of-plan <pattern>`
  - `merge-conflict <pattern>` for each distinct pattern of its `paths`
  - `fix-round <cause>`
  - `red-ci <check>`
  - `<severity> <criterion or task>`, e.g. `not met AC-089.3`
  - `refused-test-diff <file>`
  - `untraced <criterion>`
  - `wrong failure <test>`

  `re-plan` events give no label. A path's pattern is `<parent>/*<suffix>`, or `*<suffix>` at the root, or
  `<parent>/*` without a suffix. For example, `scripts/cplat/runs.py` → `scripts/cplat/*.py`. Labels are counted per
  event. The top 3 are taken by count descending, then label ascending. `run_id` is the most recent record with that
  label (largest `ended_at`, then largest `run_id`). Every label, and the row's `agent`, `shape`, `model` and
  `model_ids`, go through `feedback.redact` and are cut to 200 characters.

`--json` prints exactly this document and nothing else on stdout (`json.dumps(agg, indent=2)`):

```json
{
  "window": {"since": "2026-09-24", "until": "2026-10-24", "days": 30, "repo": null, "agent": null, "shape": null,
             "by_version": false, "store": "ika100/sdlc-runs", "records": 42, "malformed": 0},
  "rows": [
    {
      "agent": "svc:coder", "shape": "service-python", "model": "sonnet", "platform_version": null,
      "model_ids": ["claude-sonnet-4-5-20250929"],
      "runs": 12, "few_runs": false, "incomplete_runs": 0, "rework": 2.917,
      "metrics": {
        "fix_rounds": {"runs": 12, "avg": 1.25,
                       "by_cause": {"lint/type": 0.5, "test": 0.5, "ci": 0.25, "verification": 0.0}},
        "red_ci": {"runs": 3, "avg": 0.667},
        "findings": {"runs": 11, "avg": 0.364,
                     "by_severity": {"not met": 0.182, "partial": 0.182, "deviation": 0.0},
                     "after_fix": {"avg": 0.091, "by_severity": {"not met": 0.091, "partial": 0.0, "deviation": 0.0}}},
        "refused_test_diffs": {"runs": 12, "avg": 0.0}
      },
      "top_causes": [
        {"cause": "fix-round test", "count": 6, "run_id": "20261020T101500Z-3f9c2a71"},
        {"cause": "not met AC-089.3", "count": 2, "run_id": "20261019T090000Z-0a1b2c3d"}
      ]
    },
    {
      "agent": "svc:architect", "shape": "service-python", "model": "opus", "platform_version": null,
      "model_ids": [], "runs": 3, "few_runs": true, "incomplete_runs": 1, "rework": 1.333,
      "metrics": {
        "out_of_plan": {"runs": 3, "avg": 1.0},
        "merge_conflicts": {"runs": 3, "avg": 0.333, "resolved_share": 0.0},
        "replans": {"runs": 3, "avg": 0.0}
      },
      "top_causes": [{"cause": "out-of-plan scripts/cplat/*.py", "count": 2, "run_id": "20261018T080000Z-77aa88bb"}]
    },
    {
      "agent": "web:tester", "shape": "web-nextjs", "model": "sonnet", "platform_version": null, "model_ids": [],
      "runs": 1, "few_runs": true, "incomplete_runs": 0, "rework": 0.0,
      "metrics": {"tester_events": {"runs": 0, "avg": null, "by_reason": {"untraced": null, "wrong failure": null}}},
      "top_causes": []
    }
  ],
  "buffered": 0
}
```

The metric objects per role:
- architect: `out_of_plan {runs, avg}`, `merge_conflicts {runs, avg, resolved_share}`, `replans {runs, avg}`
- coder: `fix_rounds {runs, avg, by_cause}`, `red_ci {runs, avg}`, `findings {runs, avg, by_severity, after_fix {avg,
  by_severity}}`, `refused_test_diffs {runs, avg}`
- quality: `refused_test_diffs {runs, avg}`
- tester: `tester_events {runs, avg, by_reason}`

`platform_version` is `null` without `--by-version`. `window.records` counts the records in the window after `--repo`.

Text form (testers may rely on these lines and substrings; averages print with 2 decimals, `null` prints `n/a`):

```
Agents <since> to <until> (<days> days) in <store>[, repo <repo>][, agent <agent>][, shape <shape>]: <records> record(s); <malformed> malformed line(s) skipped
<agent> <shape> <model>[ <platform_version>]: <runs> run(s)[, few runs][, <k> incomplete], rework <x.xx>
  out-of-plan files <a> · merge conflicts <a> (resolved <p>%|n/a) · re-plans <a>
  fix rounds <a> (lint/type <a>, test <a>, ci <a>, verification <a>) · red-CI rounds <a> · findings <a> (not met <a>, partial <a>, deviation <a>; after fix <a>) · refused test diffs <a>
  tester events <a> (untraced <a>, wrong failure <a>)
  causes: <count>× <label> (<run_id>); …
Buffered locally, not included: <n> record(s) (cplat runs flush)
```

Each row prints only the metric line of its role. The quality role prints `refused test diffs <a>`. Other roles print
no metric line. The causes line prints `causes: none` when there are none. No rows → the line `  none` after the
header.

### Build prompt calls (`plugins/svc/commands/build.md`)

| Where | Call |
|---|---|
| Every subagent spawn, all phases | `cplat runs agent spawned <role> [--model-id <id>]` (the id only when the orchestrator knows it) |
| Phase 1, after the trace and red checks | `cplat runs agent tester [--untraced <AC>]... [--wrong-failure <test>]...`, also with no ids |
| Phase 2.4, before each merge or sequential coder | `PRE=$(git rev-parse HEAD)` |
| Merge conflict, before `git merge --abort` | `cplat runs agent conflict <task>` (then escalate as today) |
| After a clean merge, or a sequential task's commit | `cplat runs agent merged <task> --since $PRE [--helper <path>]...` |
| `cplat spec test-diff $RED` | add `--task <task>` in Phase 2, and `--by quality` in Phase 3 when the quality agent changed files in that round |
| Hand-back to a coder | `cplat runs agent fix-round <cause> [--task <task>]`: Phase 2 quality → `lint/type`, Phase 2 / 2.5 tests → `test`, Phase 3 tests red → `ci`, Phase 4 not met → `verification` |
| Phase 4, after each reviewer pass | `cplat runs agent findings --cycle <n> [--deviation <AC or task>]...` (deviations the reviewer judged not acceptable) |

`ship.md`:
- In Phase `plan`, after the architect returns: `cplat runs agent spawned architect [--model-id <id>]`.
- `cplat ship pr` red `devbox run ci` handed to the coder → `fix-round ci`.
- `land` RED needs no call: cplat records it.

`app/commands/build.md`: the per-repo `/svc:build` records its agents as `/svc:build` does (one sentence in the repo
agent instructions).

Spec 094 calls `conflict <task> --outcome re-planned`, then `replan <task>`, and after the re-run
`conflict-outcome <task> resolved` (or `escalated`).

## Data

No new storage. Sections in the 087 record. One new local file per active run,
`<state_dir>/active/<run_id>.incomplete.jsonl`, which `finish` deletes.

## Risks

- **Prompt-driven calls can be skipped by the orchestrator.** That leaves zero events with the metric measured. It is
  mitigated by recording in code wherever cplat sees the signal. The other calls are one line each, next to the
  action they record.
- **`shapecmd.route` runs `detect-shape.sh` on every call** (≈10 ms). That is acceptable for tens of calls per build.
- **Long test names** (40+ word characters) are redacted to `<long-string>` in `wrong failure` labels. The 087
  redaction is required, and the criterion id usually carries the meaning.
- **A plan author from an earlier session** has `model_id: null`. The alias is still known from the definition.
