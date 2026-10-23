# Design — 087 Every run is recorded in a private run store

## Decisions

- **One file per run in a private GitHub repo, written in one commit through the Git Data API.** A record is stored at
  `runs/<YYYY>/<MM>/<DD>/<run_id>.json` (day = `ended_at`, UTC). Each file holds exactly one JSON line. A flush builds
  one tree over the current branch head (`base_tree`), adds every buffered record as a file, commits it, and moves the
  branch with a non-forced ref update. A concurrent writer from another machine makes the ref update fail as "not a
  fast forward". The flush then re-reads the head and retries (at most 3 times). Two writers never touch the same path,
  so nothing is lost (AC-087.8). A record flushed twice (an interrupted flush) lands on the same path with
  byte-identical content, so the store holds it exactly once per `run_id`. The reader also dedupes by `run_id`.
  A write takes 1 visibility call plus 5 Git Data calls, whatever the batch size, so it fits the 20 s budget. Appending
  to a shared JSONL through the Contents API was rejected: every concurrent write conflicts on the file's sha, and a
  1000-record flush would need 1000 PUTs.
  ADR: [docs/adr/032-private-run-store.md](../../adr/032-private-run-store.md).
- **An in-progress run lives in a local per-run file, never in the store** (AC-087.21, non-goal "no start or heartbeat
  records"). Steps change the active record in place. `finish` turns it into the one line that gets written.
- **Local state is per user, not per clone:** `$CPLAT_RUNS_DIR`, default `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/runs`.
  Runs of all repos, worktrees and kinds (fleet and retro, which belong to no repo) share one buffer and one doctor count.
- **The ship run owns nested runs.** `cplat pr wait` and `/svc:build` attach to the unfinished ship run of the repo they
  run in (found through `cplat-ship.json`). Headless and product-ship drive ship runs in child processes and pass their
  own `run_id` in `CPLAT_RUN_PARENT`. A ship run started under that variable adds itself to the parent's `ships` list.
- **Recording never changes a run.** Every `runs.*` mutator catches all exceptions and returns quietly. `finish` prints at
  most one line, on **stderr**, because the Stop hook (`cplat ship gate`) speaks JSON on stdout. It never raises and
  never changes an exit code.
- **Taking over a ship run is explicit:** `cplat ship start <other-spec> --take-over` ends an unfinished, unescalated run
  of another spec as `abandoned` and starts the new one. Without the flag, start still refuses, and its hint now names
  the flag. `--take-over` keeps its spec-082 meaning (move the issue claim) and adds this one. Both mean "the user said
  this session takes over". `cplat ship finish` of an unfinished, unrecorded run also records it `abandoned`.
- **The escalation cause is an input, not a guess:** `cplat ship escalate <reason> [--cause C]`, default `unknown`.
  Classifying causes is spec 088's job.
- **Pending filings are retried through a named filer.** 088 owns filing. This spec stores the pending entry with the
  filer's module name and calls it back once per flush.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/runs.py` | the record API (start, mutate, finish), local state (active records, buffer, pending filings, lock), flush orchestration, `cplat runs` CLI | new |
| `scripts/cplat/runs_store.py` | the transport: `Store` protocol, `GitHubStore` over `gh api` (visibility, create, write one commit, read days) | new |
| `scripts/cplat/runs_report.py` | parse store lines, dedupe, merge follow-ups, aggregate, render text and JSON | new |
| `scripts/cplat/ship.py` | run id in the ship state, phases and end records from `save_state`, take-over, `escalate --cause`, CI rounds and reruns in `CheckWatch` / `wait_checks` / `RunWatch` | changed |
| `scripts/cplat/pr.py` | `pr wait` starts a `pr-wait` run or attaches to the ship run | changed |
| `scripts/cplat/headless.py` | one `headless` record per invocation; `CPLAT_RUN_PARENT` for its sessions | changed |
| `scripts/cplat/doctor.py` | the `run store` check | changed |
| `scripts/cplat/cplat.py` | `"runs": "runs"` in `COMMANDS`, a docstring line | changed |
| `plugins/svc/commands/build.md`, `ship.md` | `cplat runs begin/phase/end` in build, `--cause` and `--take-over` in ship | changed |
| `tests/cplat/conftest.py` | autouse: `CPLAT_RUNS_DIR=<tmp>`, `CPLAT_RUNS_REPO` unset, so no test touches the user's buffer or GitHub | changed |

## Contract

### Configuration

| Setting | Meaning |
|---|---|
| `CPLAT_RUNS_REPO=<owner>/<name>` | the store. Unset means not configured. A value that is not `owner/name` counts as not configured. |
| `CPLAT_RUNS_DIR=<path>` | local state directory (tests, unusual setups). |
| `CPLAT_HEADLESS=1` | set by `cplat headless` for its sessions (exists today). Runs started under it get `mode: headless`. |
| `CPLAT_RUN_PARENT=<run_id>` | set by `cplat headless` (and later product-ship) for its sessions. |

### Record (schema 1)

One JSON object, serialised with `json.dumps(record, ensure_ascii=False, separators=(",", ":"))` and one trailing `\n`.
Key order is the order below; section keys follow in the order they were added.

| Field | Type | Notes |
|---|---|---|
| `schema` | int | `1` |
| `run_id` | str | `<started UTC %Y%m%dT%H%M%SZ>-<8 lowercase hex>`, e.g. `20261023T101500Z-3f9c2a71` (25 chars, sortable, below the 40-char `redact` threshold). Fixed at `start`, so every retry writes the same id. |
| `kind` | str | `ship`, `build`, `headless`, `pr-wait`, `fleet`, `retro`, `product-ship`, or any other `^[a-z][a-z0-9-]*$` (open-ended, AC-087.23). |
| `repo` | str \| null | `owner/name` from `git remote get-url origin`; otherwise the directory name; `null` for kinds without a repo. |
| `spec` | str \| null | full spec id (`087-every-run-...`) or `null`. |
| `platform_version` | str | `core.platform_version()`. |
| `mode` | str | `interactive` \| `headless`. |
| `started_at`, `ended_at` | str | UTC, `%Y-%m-%dT%H:%M:%SZ`. |
| `phases` | list | `[{"name", "started_at", "ended_at"}]` in start order. Every phase still open at `finish` gets `ended_at = ended_at` of the run. |
| `ci_rounds` | int | CI waits that reached a conclusion (green or red). |
| `reruns` | list | `[{"check", "reason"}]`, reason `stale` \| `stuck` \| `transient`. |
| `escalation` | obj \| null | `{"reason", "cause"}`, cause `platform` \| `code` \| `decision` \| `environment` \| `unknown` (any other value is stored as `unknown`). |
| `filed` | list | `[{"signature", "url", "result"}]`, result `new` \| `+1` \| `suppressed` \| `pending` (`url` is `null` while pending). One entry per signature. |
| `outcome` | str | `done` \| `escalated` \| `failed` \| `abandoned`. |
| `resumes` | str \| null | `run_id` of the escalated run this one continues. |
| `parent` | str \| null | `run_id` of the headless or product-ship run that drove this one. |
| *sections* | any | Kind-specific fields and later specs' sections. Headless: `command` (str), `sessions` (int), `stop_reason` (`done` \| `escalated` \| `out of runs` \| `quiet window` \| `error`), `ships` (list of `run_id`). Product-ship: `ships`. 089+: `agents`, `smoke`, `patches`, … |

**Redaction (AC-087.10).** At `finish`, every string value anywhere in the record goes through `feedback.redact()` and is
then cut to 500 characters. That covers sections added by later specs too. The only exceptions are the identifier
fields `run_id`, `resumes`, `parent`, `ships[]`, `repo`, `spec`, `platform_version`, `started_at`, `ended_at`,
`phases[].started_at/ended_at` and `filed[].url`. The API has no parameter for logs, diffs or issue text.

**Follow-up line** (AC-087.22). Stored at `runs/<YYYY>/<MM>/<DD>/<run_id>.filed.<sha1(signature)[:12]>.json`, with the day taken from `at`:

```json
{"schema":1,"followup":"filed","run_id":"…","signature":"…","url":"https://github.com/…/issues/12","result":"new","at":"2026-10-24T08:00:00Z"}
```

### Python API — `scripts/cplat/runs.py`

All mutators take `run_id: str | None`. `None` or an unknown or finished id is a no-op. Mutators never raise and print
nothing. All changes happen under an exclusive `fcntl` lock on `<dir>/.lock`.

```python
SCHEMA = 1
KINDS = ("ship", "build", "headless", "pr-wait", "fleet", "retro", "product-ship")   # documentation; any valid kind works
OUTCOMES = ("done", "escalated", "failed", "abandoned")
CAUSES = ("platform", "code", "decision", "environment", "unknown")
RERUN_REASONS = ("stale", "stuck", "transient")
FILED_RESULTS = ("new", "+1", "suppressed", "pending")
BUFFER_CAP = 1000
BUDGET_SECONDS = 20.0
RESERVED = {"schema", "run_id", "kind", "repo", "spec", "platform_version", "mode", "started_at", "ended_at", "phases",
            "ci_rounds", "reruns", "escalation", "filed", "outcome", "resumes", "parent"}
FILERS: dict[str, Callable[[dict, float], tuple[str, str]]] = {}   # name → retry(entry, timeout) -> (url, result)

def utcnow() -> datetime.datetime: ...            # tests replace this
def monotonic() -> float: ...                     # tests replace this
def state_dir() -> Path: ...                      # $CPLAT_RUNS_DIR or ${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/runs
def configured_repo() -> str | None: ...          # $CPLAT_RUNS_REPO if it matches ^[\w.-]+/[\w.-]+$
def open_store(slug: str) -> runs_store.Store: ...   # tests replace this with an in-memory Store
def repo_slug(repo_dir: Path) -> str | None: ...  # owner/name of origin, else the directory name; never raises

# --- lifecycle ---
def start(kind: str, *, repo: str | None = None, spec: str | None = None, mode: str | None = None,
          resumes: str | None = None, parent: str | None = None, run_id: str | None = None,
          started_at: str | None = None) -> str | None:
    """Create <dir>/active/<run_id>.json and return the run_id (None only if even that failed).
    mode defaults to "headless" when $CPLAT_HEADLESS is set, else "interactive"; parent defaults to $CPLAT_RUN_PARENT.
    run_id/started_at let a caller re-create the active record of a run it already knows (a ship state from before
    this spec, or a lost active file). Calls link_parent(run_id)."""

def link_parent(run_id: str | None) -> None:
    """If $CPLAT_RUN_PARENT is set: set this run's parent, add run_id to the parent's `ships` (once), and if
    $CPLAT_HEADLESS is set, set this run's mode to "headless". Ship calls it on every `ship start`, so a ship run
    resumed by a headless session is listed and marked as well."""

def active(run_id: str | None) -> dict | None: ...    # a copy of the in-progress record

def attach_point(repo_dir: Path) -> str | None:
    """run_id of the repo's ship run when it is unfinished (phase != done, not escalated) and has a run_id;
    a nested `pr wait` or build records into it (AC-087.5)."""

# --- in place, until finish (AC-087.21) ---
def phase(run_id, name: str) -> None:
    """Open phase `name`. No-op when the open phase of the same level already has that name. Level = name.count(":").
    Opening a phase closes the open phase of its level and every deeper one (`build` closes `build:qa`; `build:qa`
    closes `build:verify` but not `build`)."""
def ci_round(run_id) -> None: ...                                  # ci_rounds += 1
def rerun(run_id, check: str, reason: str) -> None: ...            # append {check, reason}; an unknown reason is ignored
def event(run_id, section: str, key: str, data: dict) -> None:
    """Upsert into list `section` the object with "id" == key: a new key appends {"id": key, **data}; a known key
    updates that object in place (dict.update), so the record holds each event once, in its last state."""
def set_section(run_id, name: str, value) -> None: ...            # replace a section; a RESERVED name is ignored
def add_to(run_id, name: str, item, *, unique: bool = False) -> None: ...   # append to a list section
def filed(run_id, signature: str, url: str | None, result: str, *, filer: str | None = None,
          payload: dict | None = None) -> None:
    """Upsert `filed` by signature. result == "pending": also upsert (run_id, signature) into <dir>/filings.jsonl
    with filer (a FILERS key, or a module in scripts/cplat whose retry_filing(entry, timeout) is used) and payload
    (local only, never written to the store)."""

def finish(run_id, outcome: str, *, escalation: dict | None = None, fields: dict | None = None) -> str | None:
    """End the run: close open phases, set ended_at/outcome/escalation (+ `fields`, non-reserved top-level keys),
    redact, add the line to the buffer (cap, drop oldest), delete the active file, then flush(budget=what is left of
    BUDGET_SECONDS since finish was called). Returns and prints (stderr) the one warning line when this record is
    still in the buffer afterwards or records were dropped; otherwise None. Never raises."""

# --- buffer → store ---
@dataclass
class FlushResult:
    store: str | None          # slug, or None when not configured
    problem: str | None        # None | "unset" | "public" | "unreachable" | "budget"
    detail: str                # human text for the problem ("" when none)
    written: int               # records written by this flush
    followups: int             # follow-up lines written by this flush
    buffered: int              # records + follow-ups left in the buffer
    dropped: int               # dropped by the cap during this call (finish only)
    pending: int               # pending filings left

def flush(*, budget: float = BUDGET_SECONDS, strict: bool = False) -> FlushResult:
    """(1) configured? (2) store.visibility() == "private"? (3) retry each pending filing once while at least half the
    budget is left: success → in place in the active record if the run is still active, else a follow-up line into the
    buffer; the filings entry is removed only after success. (4) write the buffer in ended_at order (follow-ups by `at`),
    200 per commit, removing each written batch from the buffer by key. strict=True (the CLI) raises PlatformError for
    unset / public / unreachable instead of returning it."""

def buffered_count() -> int: ...
def pending_count() -> int: ...

@dataclass
class StoreStatus:
    slug: str | None
    state: str                 # "unset" | "public" | "unreachable" | "ok"
    detail: str
    buffered: int
    pending: int

def store_status(timeout: float = 10.0) -> StoreStatus: ...   # for doctor; one visibility call, never raises

def init(slug: str) -> list[str]: ...   # AC-087.20; raises PlatformError for a public repo or a gh failure
```

Local files under `state_dir()`:

| File | Content |
|---|---|
| `active/<run_id>.json` | the in-progress record: schema-1 fields so far, open phases with `ended_at: null` |
| `buffer.jsonl` | finished records and follow-up lines not yet in the store, one per line. Key: `run_id` for records, `run_id + "/" + signature` for follow-ups. Adding an existing key replaces it. |
| `filings.jsonl` | pending filings `{"run_id", "signature", "filer", "payload", "since"}` |
| `.lock` | `fcntl.flock` target |

**Cap (AC-087.19).** After each add, if the buffer holds more than 1000 lines, the lines with the oldest
`ended_at`/`at` are dropped until 1000 are left. The number dropped is reported in the warning.

**Warning line (AC-087.7, .9, .19).** One line on stderr, only from `finish`:

```
WARNING: run record buffered locally (<why>); <n> record(s) buffered[; <d> oldest dropped (the buffer keeps 1000)]
```

`<why>` is one of the following:
- `no run store: set CPLAT_RUNS_REPO=<owner/name>, see cplat runs init`
- `run store <slug> unreachable: <short reason>`
- `run store <slug> is public; records are only written to a private repo`
- `run store <slug>: no time left within 20 s`
- `recording failed: <ExceptionName>: <msg>` (an unexpected bug; the run still ends normally)

**Time bound (AC-087.7).** `finish` measures from its own entry. Every `gh` call gets
`timeout = min(10, deadline - monotonic())` and no call starts with less than 1 s left. Pending filings are only
retried while at least half the budget is left.

**Pending filings (AC-087.22).** A filer is called as `retry(entry, timeout) -> (url, result)`, where entry is
`{"run_id", "signature", "payload"}`. It raises on failure. Each flush tries each entry once. The entry is removed only
after success. The filer gets `run_id`, so spec 088 can make a retried +1 idempotent per run (for example by marking its
comment with the run_id): "at most once per run and signature".

### Transport — `scripts/cplat/runs_store.py`

```python
class StoreError(Exception): ...
class StoreMissing(StoreError): ...        # 404: no such repo, or no access
class StoreUnreachable(StoreError): ...    # gh missing, not logged in, timeout, 5xx, rejected write

def gh(args: list[str], *, input: str | None = None, timeout: float = 10.0) -> tuple[int, str, str]:
    """subprocess `gh <args>` → (exit code, stdout, stderr); tests replace this. A timeout is (124, "", "timeout")."""

class Store(Protocol):
    slug: str
    def visibility(self, deadline: float | None = None) -> str: ...      # "private" | "public" | "internal"
    def create_private(self) -> None: ...
    def put(self, files: dict[str, str], message: str, deadline: float | None = None) -> None: ...
    def read(self, days: list[datetime.date], deadline: float | None = None) -> list[tuple[str, str]]: ...

class GitHubStore:   # implements Store
    def __init__(self, slug: str): ...

def record_path(record: dict) -> str: ...  # runs/YYYY/MM/DD/<run_id>.json, or the .filed.<sha12>.json form for a follow-up line
```

`GitHubStore` calls:

| Method | gh calls |
|---|---|
| `visibility` | `gh api repos/{slug}` → `.visibility` (fallback `.private`), and it caches `.default_branch`. 404 → `StoreMissing`. Any other failure → `StoreUnreachable`. |
| `create_private` | `gh repo create {slug} --private --add-readme --description "sdlc-foundry run records (private)"` |
| `put` | (1) `GET repos/{slug}/git/ref/heads/{branch}` → head sha. On 404/409 (empty repo): `PUT repos/{slug}/contents/README.md` once, then again. (2) `GET repos/{slug}/git/commits/{sha}` → tree sha. (3) `POST repos/{slug}/git/trees` `{"base_tree", "tree": [{"path", "mode": "100644", "type": "blob", "content"}]}`. (4) `POST repos/{slug}/git/commits` `{"message", "tree", "parents": [sha]}`. (5) `PATCH repos/{slug}/git/refs/heads/{branch}` `{"sha", "force": false}`. On 422/409 in (5): start again from (1), at most 3 attempts, then `StoreUnreachable("concurrent writes")`. JSON bodies go through `--input -`. |
| `read` | `gh api graphql` with up to 40 aliases per query, `d<i>: object(expression: "HEAD:runs/YYYY/MM/DD") { ... on Tree { entries { name object { ... on Blob { text } } } } }`. A missing day dir is `null` and is skipped. Returns `(path, text)` pairs. |

### CLI — `cplat runs`

| Command | Behaviour | Exit |
|---|---|---|
| `cplat runs init <owner/name>` | missing → create it private, print `created <slug> (private)`, then the config line. Exists and private → print only the config line. Exists and not private → `ERROR: <slug> is public: the run store must be private; nothing was changed` with fix `gh repo edit <slug> --visibility private --accept-visibility-change-consequences, or choose another name`. The config line is exactly `export CPLAT_RUNS_REPO=<slug>   # add this to your shell profile`. | 0 / 1 |
| `cplat runs flush` | `flush(strict=True, budget=120)`. Prints `flushed <w> record(s) and <f> follow-up(s) to <slug>; <b> left in the buffer; <p> pending filing(s)`. | 0 / 1 |
| `cplat runs report [--json] [--since DAYS] [--repo owner/name]` | see Report. DAYS is an int ≥ 1, default 30. | 0 / 1 |
| `cplat runs begin <kind> [--spec S] [--dir D]` | for markdown commands (`/svc:build`). If `attach_point(D)` returns a run, write the pointer `{"run_id": <ship>, "kind": <kind>, "attached": true}` and print `run <id> (attached to ship <spec>)`. Otherwise end a stale own pointer's run as `abandoned`, `start(kind, repo=repo_slug(D), spec=S)`, write `{"run_id", "kind", "attached": false}` and print `run <id>`. Pointer: `<git common dir of D>/cplat-run.json`. | always 0 |
| `cplat runs phase <name> [--dir D]` | `phase(pointer.run_id, name)` | always 0 |
| `cplat runs end --outcome O [--reason R] [--cause C] [--dir D]` | attached → only delete the pointer. Otherwise `finish(run_id, O, escalation={"reason": R, "cause": C or "unknown"} if O == "escalated" else None)` and delete the pointer. | always 0 |

Errors of `report` and `flush` (AC-087.15) are `PlatformError`s, so `cplat` prints `ERROR: …` and `  fix: …` and exits 1:
- not configured: `no run store configured (CPLAT_RUNS_REPO is not set)` with fix
  `cplat runs init <owner/name>, then set CPLAT_RUNS_REPO=<owner/name>`.
- unreachable: `run store <slug> is unreachable: <reason>` with fix
  `gh repo view <slug>   (is gh logged in, and may it read the repo?)`.
- public (flush only): `run store <slug> is public; records are only written to a private repo` with fix
  `gh repo edit <slug> --visibility private --accept-visibility-change-consequences`.

### Report — `scripts/cplat/runs_report.py`

```python
def parse(texts: list[str]) -> tuple[list[dict], list[dict], int]:
    """Lines of the store files → (records, follow-ups, malformed line count). A non-empty line that is not a JSON object
    is malformed. A line with "followup" is a follow-up. Any other object is a record, whatever its schema or kind."""
def aggregate(records: list[dict], followups: list[dict], *, malformed: int, buffered: int, since_days: int,
              repo: str | None, store: str, now: datetime.datetime) -> dict: ...
def render_text(agg: dict) -> str: ...
```

Rules:
- Window: `ended_at >= now - since_days` (UTC). The days read are `now.date() - since_days … now.date()`. `--repo`
  keeps `record["repo"] == repo`.
- Dedupe by `run_id`: the first record seen wins. A record without a `run_id` is counted once as is.
- Merging follow-ups: the matching record's `filed` entry with that signature (or a new entry) takes the follow-up's
  `url` and `result`.
- Missing or unknown values count as `"unknown"`: a missing `kind` or `outcome`, an escalation without `cause`, and a
  rerun without `reason` or `check`. Unknown fields are ignored. A phase without both timestamps is skipped.
- Duration of a phase = `ended_at - started_at` in seconds. Median = `statistics.median`. p90 = nearest rank:
  `sorted(d)[ceil(0.9 * n) - 1]`.
- Escalation reasons: grouped by identical text after `strip()`. Top 10 by count descending, then by text ascending.

`--json` prints exactly this document and nothing else on stdout (AC-087.18):

```json
{
  "window": {"since": "2026-09-23", "until": "2026-10-23", "days": 30, "repo": null, "store": "ika100/sdlc-runs",
             "records": 42, "malformed": 1},
  "runs": {"ship": {"done": 30, "escalated": 4}, "pr-wait": {"failed": 2}},
  "phases": {"build": {"count": 30, "median_s": 1520.0, "p90_s": 3100.0}},
  "causes": {"platform": 2, "unknown": 2},
  "escalations": [{"reason": "merge failed", "count": 3}],
  "reruns": {"by_reason": {"stuck": 3, "transient": 5}, "by_check": {"ci / test": 6}},
  "filed": {"new": 1, "+1": 2, "suppressed": 0, "pending": 0},
  "buffered": 5
}
```

`filed` always has all four result keys. A result outside them is counted under its own name.

The text form prints the same aggregates in this order. Testers may rely on these lines and substrings:

```
Runs <since> to <until> (<days> days) in <store>[, repo <repo>]: <records> record(s); <malformed> malformed line(s) skipped
Runs per kind and outcome:
  <kind>: <outcome> <n>, <outcome> <n>
Phases (median / p90):
  <name>: <median> / <p90> (n=<count>)
Escalations per cause: <cause> <n>, …
Top escalation reasons:
  <count>  <reason>
Reruns by reason: <reason> <n>, …
Reruns by check: <check> <n>, …
Filed issues: new <n>, +1 <n>, suppressed <n>, pending <n>
Buffered locally, not included: <n> record(s) (cplat runs flush)
```

Durations print as `<m>m <ss>s`, or `<h>h <mm>m` from one hour up. An empty group prints `none`.

### Integration points

**`ship.py`**
- The state gets `run_id`, `recorded` (bool) and `cause`. `_ensure_run(repo, st)`: when there is no `run_id`, or its
  active record is gone and it is not yet recorded, `runs.start("ship", repo=runs.repo_slug(repo), spec=st["spec"],
  run_id=st.get("run_id"), started_at=<st["started"] as UTC>)`.
- `save_state` calls `_record(repo, st)` before writing, in a `try/except Exception: pass`. It runs `_ensure_run`, then
  `runs.phase(rid, st["phase"])`. If `recorded` is not set:
  - `st["escalated"]` → `runs.finish(rid, "escalated", escalation={"reason": st["escalated"], "cause": st.get("cause") or "unknown"})`.
  - `phase == "done"` → `runs.finish(rid, "done")`.
  - In both cases `recorded = True`.

  This covers `set_phase`, `_done`, `land --no-merge`, `escalate` and the gate giving up (AC-087.1, .16).
- `start`: when the same spec's state is escalated, a new run starts: `run_id = runs.start(..., resumes=<old run_id>)`
  and `recorded = False` (AC-087.16). An unfinished, unescalated state of another spec with `take_over=True` →
  `runs.finish(old_rid, "abandoned")`, then the new state (AC-087.3). Without `take_over` it raises as today, and the hint
  adds `or take it over: cplat ship start <spec> --take-over`. Every `start` ends with `runs.link_parent(run_id)`.
- `escalate(repo, reason, cause="unknown")` stores `cause`. The CLI adds `--cause {platform,code,decision,environment,unknown}`.
- `finish`: a state that is not recorded → `runs.finish(rid, "abandoned")` before archiving.
- `CheckWatch(repo, pr, queue_timeout, run_id=None)` and `RunWatch(..., run_id=None)`.
  - `runs.rerun(self.run_id, <check names of that run, sorted, joined by ", ">, reason)` where a rerun happens:
    stale → `stale`, a cancelled-and-rerun queued run → `stuck`, a transient failure → `transient`. `RunWatch`'s
    cancel and rerun → `stuck` with check `pin-dev`.
  - `wait_checks` calls `runs.ci_round(watch.run_id)` once when it returns green or red (AC-087.4).
  - `land`, `merge_gitops` and `deploy` pass `st.get("run_id")`.

**`pr.py`** — `rid = runs.attach_point(repo)`. When there is none, `own = runs.start("pr-wait", repo=slug or
runs.repo_slug(repo))`. The watch gets `run_id=rid or own`. With `own`: green, merged or already merged →
`finish(own, "done")`. Red, a timeout or any `PlatformError` → `finish(own, "failed")`, then re-raise. Exit codes are
unchanged (AC-087.5).

**`headless.py`** — after the argument checks and not for `--dry-run`:
`rid = runs.start("headless", repo=runs.repo_slug(repo), mode="headless")`. Each session runs with
`CPLAT_RUN_PARENT=rid` (besides `CPLAT_HEADLESS=1`). At the end, `runs.finish(rid, outcome,
fields={"command": prompt, "sessions": runs, "stop_reason": reason})`; `ships` was filled by the children (AC-087.6).

| Ends with | stop_reason | outcome |
|---|---|---|
| `shipped …` or `finished` | `done` | `done` |
| `needs you: …`, or no progress (it escalates) | `escalated` | `escalated` |
| `stopped after N runs`, or the time budget used up | `out of runs` | `failed` |
| inside the quiet window with `--no-wait` | `quiet window` | `abandoned` |
| `claude exited with N`, or an exception | `error` | `failed` (the exception is re-raised) |

**`doctor.py`** — `check_run_store()` is added to `run_checks`. It maps `runs.store_status()` as follows (AC-087.11):
- `unset` → `warn "not configured"`, fix `cplat runs init <owner/name>`.
- `public` → `fail "<slug> is public: records are only written to a private repo"`, fix `gh repo edit … --visibility private …`.
- `unreachable` → `warn "<slug> unreachable: <detail>"`.
- `buffered or pending` → `warn "<slug>: <b> buffered record(s), <p> pending filing(s)"`, fix `cplat runs flush`.
- otherwise `ok "<slug>"`.

The check's name is `run store`. Only `public` is ever `fail`.

**`/svc:build`** (markdown) — Phase 0 runs `cplat runs begin build --spec <id>`. Each later phase starts with
`cplat runs phase build:<tests|implement|qa|verify|image|close|pr>`. The Final Report ends with
`cplat runs end --outcome done`. A stop that needs the user runs `cplat runs end --outcome escalated --reason '<why>'`.
A hard failure runs `--outcome failed`. Inside `/svc:ship` the same calls attach to the ship run (AC-087.5).

## Data

No database. Local JSON and JSONL files under `state_dir()`. Store files are under `runs/` in the private repo. A record
must never be written anywhere in the platform repo.

## Risks

- **`CPLAT_RUNS_REPO` invisible to Claude sessions** (the variable was exported in a profile the Bash tool does not
  read). Records then buffer, and doctor and the warning line say so. Nothing is lost up to 1000 records.
- **GraphQL `Tree.entries` on a very busy day** returns all entries in one response. Day directories keep this to tens of files.
- **Two `--take-over` meanings**: both need the user's word; ship.md says so.
- **Pre-087 ship states** have no `run_id`. `_ensure_run` creates one from `started`, so a run in flight at upgrade time
  still gets a record.
