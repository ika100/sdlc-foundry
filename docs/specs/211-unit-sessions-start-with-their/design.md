# Design — 211 Unit sessions start with their instructions, less bookkeeping

## Decisions

- **The briefing is cut at print time by heading key, from one mapping in code** (`scripts/cplat/briefing.py`). No slice is stored (non-goal); the mapping holds heading keys, not text. A heading key is `Phase <N>` for `## Phase <N> — …`, `<N>.<m>` / `<N>.<m>a` for `### <N>.<m>[a] …`, and the full heading text otherwise (`cplat`, `Rules`), so a retitled phase keeps its key and a renumbered or removed one fails the guard (AC-211.3). ADR: created by task t7 with `cplat adr add unit-briefings-are-cut-from-the-build-instructions`.
- **A section's own text** runs from its heading to the line before the next `##` or `###` heading (or the end of the file); trailing blank lines are dropped. `## Phase 2` therefore is only its heading and intro; its `###` subsections are listed in the mapping one by one (A2).
- **The plugin root** substituted for `${CLAUDE_PLUGIN_ROOT}` is `core.PLATFORM_ROOT / "plugins" / "component"`, and both instruction files are read from there, so the text and every path it names come from the same checkout (`briefing.PLUGIN_ROOT`, a module constant tests replace).
- **The shape line** is `shape: ` followed by the object `cplat shape` prints (`shapecmd.route(repo)`), as one-line JSON, so it stays one line.
- **`ship start --unit` is new**; without `--unit` `ship start` is unchanged, also when `CPLAT_UNIT` is set. A build unit session calls `ship unit` (it has no ship run to start).
- **Unit-start markers are set by the briefing call and by `cplat platform runs begin build`** in a unit session, whichever comes first: in a plain build the `red-tests` session has no run record until Phase 0's `begin`. Both are idempotent.
- **A plain unit-mode build keeps one build run record across its units.** Today each unit's Phase 0 `runs begin build` abandons the previous unit's record and starts a new one, so the markers of AC-211.9 could never stand in one record. In a unit session (`CPLAT_UNIT` set) `begin` now continues the pointer's build run when it is active, unattached and of the same `--spec`, and registers the new session's claim on it (spec 099 usage stays attributed). Inside a ship nothing changes: `begin` attaches to the ship run as before.
- **Build markers only move forward.** `runs.phase` refuses a `build:*` marker of `BUILD_MARKERS` when the record already holds that marker or a later one; explicit calls go through the same rule.
- **Prompt references that a slice would lose are reworded, not allow-listed** (A3): the `land` row of the unit table ("In a build, Phase 7"), the hard rule "push only in Phase 7" in build.md's `## Rules`, and Phase 3 step 4's "stops as in Phase 2" now state the rule themselves.
- **The five `cplat platform runs phase` lines that commands now set are removed from build.md** (`build:implement`, `build:qa`, `build:verify`, `build:image`, `build:close`; their commands run in interactive builds too). `build:tests` stays in Phase 1 for the interactive build, marked as set by the unit's start in unit mode; `build:pr` stays.
- **`cplat spec test-diff` without a base** resolves its spec from `judged_specs` (the `building` specs plus the spec of the clone's unfinished ship run, spec 200), so the ship's `pr` and `land` phases, where the status is already `done`, work without a base too.
- **AC-211.1 changes the output of `ship unit`**, which AC-131.7's tests pin (`startswith("unit …")`, exact equality). t2 updates those two assertions to find the unit line among the lines; the behaviour they check stays.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/briefing.py` | unit names, the mapping, the section cutter, `build`, `problems` (the guards) | new |
| `scripts/cplat/rulescheck.py` | runs `briefing.problems` as part of `cplat platform rules check` | changed |
| `scripts/cplat/ship.py` | `ship start --unit`, `ship unit`: shape line, where the run stands, briefing | changed |
| `scripts/cplat/runs.py` | `BUILD_MARKERS`, forward-only `phase`, `mark`, `unit_started`, `build_run`, `record_gate`, `begin` continuation | changed |
| `scripts/cplat/buildcmd.py` | `build schedule` sets `build:implement` | changed |
| `scripts/cplat/mutation.py` | `spec mutate --write` sets `build:image` | changed |
| `scripts/cplat/spec.py` | `spec set-status <id> done` sets `build:close`; `test-diff` base optional | changed |
| `scripts/cplat/testdiff_base.py` | finds the spec and its latest "acceptance tests for <spec id>" commit | new |
| `scripts/cplat/quiet.py` | `quiet ci` records the gate and the stage | changed |
| `plugins/component/commands/{build,ship}.md`, `references/unit-mode.md`, `references/{build-test-approval,build-tighten,build-load-run,ship-land-red}.md` | unit sessions start from the briefing; no `$RED`; fewer bookkeeping calls | changed |

## Contract

### 1. `briefing.py` (the API the tests use)

```python
PLUGIN_ROOT: Path                       # core.PLATFORM_ROOT / "plugins" / "component"
BUILD_FILE = "commands/build.md"; UNIT_FILE = "references/unit-mode.md"
KNOWN_UNITS = ("plan", "red-tests", "batch:<id>,<id>…", "task:<id>", "verification", "land")
GENERAL = ("cplat", "Rules")            # heading keys every briefing holds, plus the general paragraph
MAPPING = {                             # A2; keys are unit kinds, `land` split by command
    "plan": (),
    "red-tests": ("Phase 0", "Phase 1"),
    "batch": ("Phase 0", "Phase 2", "2.1", "2.2", "2.3", "2.4", "2.4a"),
    "task": ("Phase 0", "Phase 2", "2.1", "2.3", "2.4", "2.4a"),
    "verification": ("Phase 0", "2.5", "2.6", "Phase 3", "Phase 4", "Phase 5", "Phase 6"),
    "land:build": ("Phase 0", "Phase 7"),
    "land:ship": (),
}

class UnknownUnit(PlatformError): ...           # message: unknown unit '<x>'; known units: <KNOWN_UNITS joined by ', '>
class BriefingUnavailable(Exception): reason: str

def kind(unit: str, command: str) -> str        # MAPPING key; `batch:` needs ≥ 1 id, `task:` exactly one; else UnknownUnit
def heading_key(heading_line: str) -> str       # "## Phase 3 — QA…" → "Phase 3"; "### 2.4a Re-plan…" → "2.4a"; "## Rules" → "Rules"
def sections(text: str) -> list[Section]        # Section(key, level, line, text) for every ## / ### heading, in file order
def build(unit: str, command: str, root: Path | None = None) -> str   # the briefing; UnknownUnit / BriefingUnavailable
def headings(unit: str, command: str, root: Path | None = None) -> list[str]   # build-instruction heading keys in the briefing, in order
def problems(root: Path | None = None) -> list[Problem]   # Problem(kind, file, line, text, message); [] when all guards pass
```

`command` is `"ship"` or `"build"`; it only matters for `land` (and `plan`, which maps to nothing either way).

**Briefing text** (`build`), blocks separated by one blank line, every `${CLAUDE_PLUGIN_ROOT}` replaced by `str(root)`:

```
briefing for unit <unit> (<command>), cut from <root>/references/unit-mode.md and <root>/commands/build.md
<the paragraph of unit-mode.md that starts "**Permissions:**", verbatim>
| Unit | What you do |
|---|---|
<the unit table row whose first cell is `<kind>` or starts with `<kind>:` (batch, task), verbatim>
<the "## Rules for every unit" section, verbatim>
<the paragraph of build.md that starts "A rule marked **Hard rule:**", verbatim>
<build.md sections, verbatim, in build.md order: "## cplat", the mapped sections, "## Rules">
Full build instructions, for a step this briefing lacks: <root>/commands/build.md
```

The last line always starts with `Full build instructions, for a step this briefing lacks:` (AC-211.6). The build-instruction headings in the briefing are exactly `GENERAL` plus `MAPPING[kind]`, in build.md order (AC-211.2); `plan` and `land` in a ship hold only `## cplat` and `## Rules`.

`BriefingUnavailable.reason` is one of: `cannot read <path>: <error>`, `heading "<key>" missing from <path>` (a mapped or general key without a section), `no row for <kind> in <path>`, `no "**Permissions:**" paragraph in <path>`, `no "## Rules for every unit" in <path>`, `no general rule paragraph in <path>`.

**Guards** (`problems`, AC-211.3 to AC-211.5). `file` is the repo-relative path of the instruction file, `line` the heading's line (0 when none):

| kind | when | message |
|---|---|---|
| `briefing-heading` | a key of `MAPPING` or `GENERAL` has no section in build.md | `mapped heading "<key>" is missing from plugins/component/commands/build.md (renamed or removed)` |
| `briefing-orphan` | a `##`/`###` section of build.md is in no `MAPPING` value and not in `GENERAL` | `section "<heading line without #>" belongs to no unit` |
| `briefing-ref` | a unit's briefing refers to a heading it does not hold | `unit <unit>: refers to "<reference>" but holds no such section` |
| `briefing-general` | a unit's briefing lacks the general paragraph, the `## Rules` section text, or a bullet of "Rules for every unit" | `unit <unit>: lacks <the general rule paragraph \| the ## Rules section \| the bullet "<first 60 chars>">` |

A reference (`briefing-ref`) is any match in the whole briefing text of `\bPhase (\d+)\b` (key `Phase <N>`; covers `Phase <N>`, `Phase <N>'s …`, `as in Phase <N>`; "Phases" does not match) or of `(?<![\w.])(\d+\.\d+a?)(?![\w.])` (key `<N>.<m>[a]`, e.g. `2.5`, `2.4a`; `4.14.1` does not match). It counts as contained when the briefing holds that heading key. No allowlist (A3). `problems` checks the units `plan` (ship and build), `red-tests`, `batch:a,b`, `task:a`, `verification`, `land` (ship and build); a unit whose briefing cannot be built is reported as `briefing-heading` or `briefing-general` by its reason instead. `problems` calls `build` through the module, so a test may replace it.

### 2. `cplat platform rules check`

Without `--only`, or with `--only` naming `plugins/component/commands/build.md`, `plugins/component/references/unit-mode.md` or a directory above them, the check adds every `briefing.problems(repo/plugins/component)` item as a failure (`FAIL <kind> <file>:<line>: <message>`, exit 1, also in `--json`).

### 3. `cplat component ship start <spec> --unit <unit>` and `cplat component ship unit`

`ship start` gets `--unit UNIT` (not with `--detach`: `ERROR: --unit cannot be combined with --detach`, exit 2). An unknown unit exits 2 before anything else runs, printing to stderr `ERROR: unknown unit '<x>'; known units: plan, red-tests, batch:<id>,<id>…, task:<id>, verification, land`, and changes no state. `ship unit` with an unknown `$CPLAT_UNIT` exits 2 with the same line. `ship unit` without `$CPLAT_UNIT` is unchanged (`not a unit session`, exit 2).

Output, in this order (stdout):

```
shape: {"shape": "...", "plugin": "...", "deployable": ..., "library": ..., "agents": {...}}
<where the run stands>
unit <unit>: done at <sha7>        | unit <unit>: open: <what is missing>
next unit: <first open unit id>    | next unit: none
                                    (blank line)
<the briefing of §1>               | briefing unavailable: <reason>; read the build instructions and the unit-mode reference in full
```

- *Where the run stands*, `ship start --unit`: the lines `ship start` prints today (claim notes, `resuming …`, `answer from …`, the branch line, the state), with the state printed as `describe(st, repo)` so it includes the units block, then the budget line. `ship unit`: `describe(st, repo)` when a ship run exists for the units file's spec; else `build <spec>:` and the units block (as `ship status` prints a build). Without a units file: the unit line reads `unit <unit>: open: no units file` and there is no `next unit:` line.
- The command for the briefing: `ship` for `ship start --unit`; for `ship unit` the units file's `command`, else `ship` when a ship state exists, else `build`.
- Both exit 0, with or without a briefing (AC-211.6). A second call in the same session prints the same and writes nothing that differs: the ship state (all keys but `updated`), `cplat-units.json` and the run record stay as they were (the unit-start marker of §5 is set only once).
- After printing, both call `runs.unit_started(repo, unit)` (§5).
- `ship unit --json` keeps its keys and adds `"shape": {…}`, `"next_unit": str | null`, `"briefing": str | null`, `"briefing_unavailable": str | null` (the reason).

### 4. `cplat quiet ci` (AC-211.7)

`runs.build_run(repo_dir) -> str | None`: the run id of `<git dir>/cplat-run.json` when its `kind` is `build` (attached or not) and its record is active; else None.

After `devbox run ci` ends (script `ci`, no arguments, also with `--raw`), and only when `build_run(cwd)` is not None:

- exit 0: `runs.record_gate(cwd, "security", "passed")` and `budget.record_stage(cwd, "ci", "passed")`; prints `recorded for build run <run id>: gate security passed, budget stage ci passed`.
- non-zero: `budget.record_stage(cwd, "ci", "failed")` only; prints `recorded for build run <run id>: budget stage ci failed`.

The line comes after the usual output; the exit code is unchanged. Without a build run nothing is recorded and the output is byte-for-byte as today. A later explicit `cplat platform runs gate security passed` or `cplat budget stage ci passed` overwrites the same key (`gates.security`, `stages.ci`), never adds a second entry.

`runs.record_gate(repo_dir, gate, result) -> bool` is the body of today's `runs gate` command (set `gates[gate]` on the pointer's run, then the budget stage of the same name) plus the marker of §5; the CLI calls it. False when there is no pointer run.

### 5. Phase markers (AC-211.9)

```python
BUILD_MARKERS = ("build:tests", "build:implement", "build:qa", "build:verify", "build:image", "build:close", "build:pr")
UNIT_MARKERS = {"red-tests": "build:tests", "batch": "build:implement", "task": "build:implement"}
def phase(run_id, name)              # unchanged, except: a name in BUILD_MARKERS is a no-op when rec["phases"] holds it or a later one
def mark(repo_dir, name) -> None     # phase(current_run(repo_dir), name); never raises
def unit_started(repo_dir, unit) -> None   # mark(repo_dir, UNIT_MARKERS[kind]) for those kinds; nothing for others; never raises
```

| Marker | Set by |
|---|---|
| `build:tests` | start of the `red-tests` unit: `ship start --unit red-tests`, `ship unit` with `CPLAT_UNIT=red-tests`, `runs begin build` with `CPLAT_UNIT=red-tests` |
| `build:implement` | start of a `batch:`/`task:` unit (same three calls), and `cplat component build schedule <spec>` |
| `build:qa` | `cplat platform runs gate acceptance passed\|failed` |
| `build:verify` | `cplat platform runs gate security passed\|failed`, and the record of §4 |
| `build:image` | `cplat spec mutate <id> --write` |
| `build:close` | `cplat spec set-status <id> done` |

`runs begin build --spec S` with `CPLAT_UNIT` set: when the pointer names an active, unattached `build` run whose record has `spec == S`, it continues that run: no `abandoned` finish, no new record, the agents section is not re-initialised, the session claim is registered (`_register_claim`), and it prints `run <run id> (continued)` and the budget line. Otherwise `begin` behaves as today. In both cases (and after attaching to a ship) it then calls `unit_started(dir, $CPLAT_UNIT)`.

### 6. `cplat spec test-diff` without a base (AC-211.8)

`base` becomes optional (`nargs="?"`); the first positional is still the base, so `files` need a base, as today. With no base:

1. Spec: among `judged_specs(root)`, the one whose id `X` matches the current branch `feature/X`; else the only one; else none.
2. Base: `git log -1 --format=%H -F --grep "acceptance tests for <spec id>" HEAD` (the full spec id; the latest such commit, as `RED=$(git log -1 … --grep 'acceptance tests for')` picked it).
3. Found: prints `base: <sha7> (acceptance tests for <spec id>)`, then runs exactly as `cplat spec test-diff <sha>` with the same options (`--task`, `--by`, `--tighten`, `--approve`, `--reason`), including the frozen base of AC-169.1 (its own `base:` line may follow) and the selection of AC-172.1 (`red` = the found commit).
4. Not found: exit 2, nothing checked, stderr `ERROR: no base: <why>; pass it: cplat spec test-diff <base>`, `<why>` one of `no building spec`, `<n> building specs and the branch <branch> names none of them`, `no commit "acceptance tests for <spec id>" on <branch>`.

`testdiff_base.resolve(root) -> tuple[str, str]` returns `(sha, spec_id)` or raises `NoBase(why)`.

### 7. Prompts (AC-211.6)

- `ship.md`: `--unit <unit>` → the session's first and only start call is `cplat component ship start <spec> --unit <unit>` (no `cplat shape`); it follows the printed briefing instead of reading build.md or unit-mode.md; the files remain the fallback the briefing names.
- `build.md`: `--unit <unit>` → first call `cplat component ship unit`, which prints the shape and the briefing; `## cplat` says so for unit sessions. Both files keep naming `references/unit-mode.md` as the source the briefing is cut from.
- `RED=$(git log …)` disappears; every `cplat spec test-diff $RED …` in the component plugin becomes `cplat spec test-diff …`.
- Phase 3: `cplat quiet ci` records the security gate and the `ci` stage itself; the session records only `gate security failed` after the last red round.
- The prompts stay within the byte baseline of `docs/rules/register.yml`; `cplat platform rules check` passes.

## Data

No new files. The run record's `phases` list gains entries from more commands (same shape); `gates` and the budget's `stages` are written by `quiet ci` with the existing keys.
