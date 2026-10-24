# Design — 088 Platform failures become deduplicated issues

## Decisions

- **One filing module, reused by 091 and 092:** `scripts/cplat/autoissue.py`. Callers build a `Draft`. `autoissue.file()`
  redacts it, deduplicates by signature, applies the cap, files or keeps it pending, and records the result with
  `runs.filed()`. The module never prints: it returns an `Outcome` whose `lines` the caller prints (stdout for
  `ship escalate`, stderr for a crash). ADR: [docs/adr/033-auto-filed-issues-with-signatures.md](../../adr/033-auto-filed-issues-with-signatures.md).
- **The cause is the orchestrator's word** (non-goal: no heuristics). Only `cplat ship escalate --cause platform`
  files. `code`, `decision` and `environment` only record (AC-088.2). A missing or unknown cause is recorded as
  `unknown` with a message (AC-088.3). It is no longer an argparse error. This changes 087's
  `test_the_cause_must_be_one_of_the_known_ones`; see Risks.
- **The filing happens inside `ship.escalate`, before `save_state`.** `save_state` → `_record` → `runs.finish` ends
  the active record, and `runs.filed` only writes to an active record. Filing first means the `filed` entry is part of
  the escalated record. A pending filing then leaves the run through 087's `filings.jsonl` and comes back as a
  follow-up line.
- **Crashes file only inside a recorded run** (AC-088.4). `cplat.main`'s `except Exception` branch asks
  `runs.current(Path.cwd())`. That returns the run id only when an **active** record exists in this machine's run state.
  The candidates are, in order: the repo's ship run (`attach_point`), the `cplat runs begin` pointer, and
  `$CPLAT_RUN_PARENT`. Requiring an active record keeps tests (isolated `CPLAT_RUNS_DIR`) and manual commands out,
  even in a repo that has a ship state.
- **Open duplicates come from the issue list, closed ones from search.** The REST list
  `repos/{repo}/issues?labels=auto-filed&state=open` is read without a search-index delay, so a repeat within one minute
  finds the first issue (AC-088.7). Closed issues are older, and search finds them reliably. Every candidate is
  verified by its exact `Signature:` body line.
- **Idempotent per run and signature** (087's retry contract). Before it acts, `file()` checks two things. An issue
  whose body names this run id is this run's own new issue: it returns `new` and does nothing. An occurrence comment
  that names this run id is this run's own `+1`: it returns `+1` and does nothing. So a retry after a lost response
  never files twice.
- **The cap counts per machine and target repo,** in a local ledger next to the run state. 088 has one target repo,
  so this is "per machine". 091 and 092 file in many repos and must not share one budget. `cap` and `window` are
  parameters (092: per poll).
- **Tests never reach GitHub.** All GitHub access goes through `autoissue.tracker()`, which returns a `Tracker`
  (tests replace it with a fake). `GhTracker` builds on `autoissue.gh()`, which tests may also replace. The clock is
  `autoissue.now()` and `autoissue.monotonic()`. An autouse fixture in `tests/cplat/conftest.py` installs a tracker
  that raises `TrackerError("tests never call GitHub")`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/autoissue.py` | signature and normalisation, redaction with private names, `Draft` → title/body/comment, dedupe, cap ledger, `file()`, `retry_filing()` (087 filer), crash drafts, `Tracker` / `GhTracker` | new |
| `scripts/cplat/runs.py` | `current(repo_dir)`; a `suppressed` result gets `note: "suppressed by #<n>"` in `filed` (also when it comes from a retry) | changed |
| `scripts/cplat/ship.py` | `escalate(..., command=, evidence=, report=)` coerces the cause and files for `platform`; CLI `--cause` free text, `--command`, `--evidence-file`; output lines; the gate's escalate hint names `--cause` | changed |
| `scripts/cplat/cplat.py` | the crash branch files through `autoissue.file_crash` inside a recorded run | changed |
| `scripts/cplat/triage.py` | `auto-filed` in `LABELS` | changed |
| `plugins/svc/commands/ship.md` | Escalate: the cause decides; `platform` is filed automatically, no `/shared:report-issue` offer | changed |
| `tests/cplat/conftest.py` | autouse: fake tracker, `CPLAT_AUTO_ISSUES` and `CPLAT_FEEDBACK_REPO` unset | changed |

## Contract

### Configuration

| Setting | Meaning |
|---|---|
| `CPLAT_AUTO_ISSUES=off` | Nothing is sent. `off`, `0`, `false` and `no` (case-insensitive) all switch it off. Anything else, or unset, means on (AC-088.13). Read at call time. |
| `CPLAT_FEEDBACK_REPO=<owner>/<name>` | Target repo for `platform` issues, default `ika100/sdlc-foundry`. Read at call time (`autoissue.default_repo()`), not at import (AC-088.13). |

### Signature (AC-088.5, AC-088.6)

```python
KINDS = ("platform", "smoke", "alert")
KIND_LABELS = {"platform": ["bug"], "smoke": ["smoke-failure"], "alert": ["alert"]}
BASE_LABELS = ["triage", "auto-filed"]
SIGNATURE_LINE = re.compile(r"^Signature: (platform|smoke|alert):[0-9a-f]{16}$", re.M)

def normalise(text: str, names: dict[str, str] | None = None) -> str: ...
def raw_signature(kind: str, *parts: str) -> str:
    """f"{kind}:{sha256('\n'.join(parts).encode()).hexdigest()[:16]}"; ValueError for a kind not in KINDS."""
def signature(kind: str, *parts: str, names: dict[str, str] | None = None) -> str:
    """raw_signature(kind, *(normalise(p, names) for p in parts))"""
```

`normalise` applies these steps in this order. Each step is a regex substitution, and every replacement is a fixed
placeholder:

| # | What | Replacement |
|---|---|---|
| 1 | `feedback.redact(text)` | (its placeholders) |
| 2 | each key of `names`, longest first, literal and case-insensitive | its value (`<repo>`, `<spec>`, `<branch>`, `<run-store>`) |
| 3 | URLs `https?://\S+` | `<url>` |
| 4 | image digests `sha256:[0-9a-f]{64}` | `<hash>` |
| 5 | ISO dates and datetimes `\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z\|[+-]\d{2}:?\d{2})?)?`, compact `\d{8}T\d{6}Z`, clock times `\b\d{1,2}:\d{2}(:\d{2})?\b` | `<date>` / `<date>` / `<time>` |
| 6 | paths: `~`, `.` or `..` optional, then two or more `/segment`, or `segment(/segment)+` (`[\w.@+-]` per segment). This also covers `owner/name` and `feature/…` branches | `<path>` |
| 7 | spec ids `\b\d{3}-[a-z][a-z0-9-]*\b` | `<spec>` |
| 8 | durations `\b\d+(\.\d+)?\s?(ms\|s\|secs?\|seconds?\|m\|mins?\|minutes?\|h\|hrs?\|hours?)\b` | `<duration>` |
| 9 | versions `\bv?\d+\.\d+(\.\d+)*([-+][\w.]+)?\b` (the platform version included) | `<version>` |
| 10 | hex hashes, 7–64 chars with at least one digit and one letter `a-f`: `\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}\b` | `<hash>` |
| 11 | issue and PR refs `#\d+` | `#<n>` |
| 12 | any other digit run `\d+` | `<n>` |
| 13 | whitespace runs → one space, then `strip()` | |

Case is kept, so text that differs only in letter case gives different signatures. The inputs per source:

| Source | `parts` | Function |
|---|---|---|
| `ship escalate --cause platform` | `(command, phase, reason)`. The evidence is not an input. | `signature("platform", ..., names=private_names(...))` |
| crash (AC-088.4) | `(command, exception type name, innermost frame)`, with no normalisation, because they hold no volatile parts | `raw_signature("platform", ...)` |
| 091 / 092 | their own, in their specs | `signature("smoke" \| "alert", ...)` |

Crash parts:
- `command` is `cplat <argv[0]>`. When `argv[0]` is in `SUBCOMMAND_GROUPS = {"ship", "spec", "runs", "triage", "compose",
  "addon", "secret", "pr", "shape"}`, the first later token that matches `^[a-z][a-z-]*$` and is not the value of a
  preceding `--option` is added (`cplat ship land`).
- The innermost frame is the last traceback frame whose file is inside `scripts/cplat/`, as
  `<path relative to scripts/cplat, POSIX>:<function>` (`ship.py:land`). It has no line number. When there is no such
  frame, it is `<outside>:<function of the last frame>`.

### Redaction (AC-088.9, AC-088.11)

```python
DEFAULT_BRANCHES = {"main", "master", "trunk", "develop"}

def private_names(repo: str | None, spec: str | None, branch: str | None) -> dict[str, str]:
    """{"<owner/name>": "<repo>", "<spec id>": "<spec>", "<branch>": "<branch>"} for the values that are set
    (a branch in DEFAULT_BRANCHES is skipped), plus {runs.configured_repo(): "<run-store>"} when a run store is configured."""

def scrub(text: str, names: dict[str, str] | None = None) -> str:
    """feedback.redact, then names (longest first, literal, case-insensitive), then every line starting with
    optional whitespace + "Signature:" becomes "Signature (quoted):", so the body keeps exactly one signature line."""
```

Every string that goes into a title, body or comment goes through `scrub` with the draft's `names`. That covers the
reason, the command, the phase, the evidence, the environment lines and any extra sections. No URL or slug of the run
store ever appears. The run id appears as plain text.

### Python API — `scripts/cplat/autoissue.py`

```python
CAP = 10                        # new issues per window, per machine and target repo (AC-088.14)
WINDOW_S = 24 * 3600
TIMEOUT_S = 20.0                # total budget of one file() call
RESULTS = ("new", "+1", "suppressed", "pending", "off")
EXTRA_LABELS = {"auto-filed": (...), "smoke-failure": (...), "alert": (...)}   # colour, description for GhTracker

def now() -> datetime.datetime: ...        # UTC; tests replace this (cap window, comment date)
def monotonic() -> float: ...              # tests replace this (timeout budget)
def default_repo() -> str: ...             # $CPLAT_FEEDBACK_REPO or "ika100/sdlc-foundry"
def enabled() -> bool: ...                 # CPLAT_AUTO_ISSUES, see Configuration

@dataclass
class Draft:
    kind: str                              # platform | smoke | alert
    signature: str                         # from signature() / raw_signature()
    reason: str                            # one line; the title is built from it
    command: str
    phase: str
    evidence: str = ""                     # tail: last 80 lines, then last 6000 chars (feedback.tail)
    run_id: str | None = None
    shape: str = "none"
    repo: str | None = None                # target; None → default_repo()
    names: dict[str, str] = field(default_factory=dict)            # private_names(...)
    environment: list[str] | None = None   # None → filled at render: feedback.diagnostics(Path.cwd())
    sections: list[tuple[str, str]] = field(default_factory=list)  # extra (heading, text) for 091/092, after Evidence
    labels: list[str] | None = None        # None → BASE_LABELS + KIND_LABELS[kind]
    def to_payload(self) -> dict: ...      # JSON-safe, environment rendered; stored in filings.jsonl (local only)
    @classmethod
    def from_payload(cls, payload: dict) -> "Draft": ...

@dataclass
class Issue:
    number: int
    url: str
    state: str                             # "open" | "closed"
    labels: list[str]
    created_at: str                        # ISO
    closed_at: str | None
    body: str

@dataclass
class Outcome:
    result: str                            # one of RESULTS
    signature: str
    url: str | None                        # issue (new), comment (+1), the wontfix issue (suppressed), None (pending/off)
    number: int | None                     # issue number when known
    lines: list[str]                       # what the caller prints

class TrackerError(Exception): ...         # str(e) is the short reason printed after "not filed: "

class Tracker(Protocol):
    def find(self, repo: str, signature: str, timeout: float) -> list[Issue]: ...
    def comments(self, repo: str, number: int, timeout: float) -> list[str]: ...   # comment bodies, oldest first
    def create(self, repo: str, title: str, body: str, labels: list[str], timeout: float) -> str: ...   # issue URL
    def comment(self, repo: str, number: int, body: str, timeout: float) -> str: ...  # comment URL

def gh(args: list[str], *, input: str | None = None, timeout: float = 10.0) -> tuple[int, str, str]: ...  # tests replace
class GhTracker: ...                        # implements Tracker over gh()
def tracker() -> Tracker: ...               # tests replace this; default GhTracker()

def render(draft: Draft, *, closed: Issue | None = None) -> tuple[str, str]: ...   # (title, body)
def render_comment(draft: Draft, occurrence: int) -> str: ...
def file(draft: Draft, *, run_id: str | None = None, timeout: float = TIMEOUT_S, cap: int = CAP,
         window: float = WINDOW_S, record: bool = True) -> Outcome:
    """Never raises. With record=True and a run_id, calls runs.filed(run_id, signature, url, result,
    filer="autoissue", payload={"draft": draft.to_payload(), "cap": cap, "window": window}) for new / +1 / suppressed / pending.
    run_id defaults to draft.run_id."""
def retry_filing(entry: dict, timeout: float) -> tuple[str, str]:
    """087's filer: file(Draft.from_payload(entry["payload"]["draft"]), run_id=entry["run_id"], timeout=timeout,
    cap=..., window=..., record=False). Raises RuntimeError(reason) for pending or off (the entry stays pending);
    returns (url, result) otherwise."""
def crash_draft(argv: list[str], exc: BaseException, run_id: str, cwd: Path) -> Draft: ...
def file_crash(argv: list[str], exc: BaseException, run_id: str, cwd: Path) -> Outcome: ...  # file(crash_draft(...), run_id=run_id)
```

### `file()` algorithm

1. `repo = draft.repo or default_repo()`. `enabled()` false → `Outcome("off", ...)`: the lines are the draft
   (`## Draft issue for <repo>`, blank line, `**<title>**   (labels: a, b, c)`, blank line, body), then
   `Automatic filing is off (CPLAT_AUTO_ISSUES=off); nothing was sent. Run /shared:report-issue to file it; nothing is sent without your OK.`
   Nothing is recorded and no tracker call is made.
2. `issues = tracker().find(repo, signature)`, keeping only issues whose body matches `^Signature: <signature>$`.
3. An issue whose body contains the line `- run id: <run_id>` → `new` with that issue (idempotent retry).
4. Open issues exist → `target` = the oldest by `(created_at, number)`. Read its `comments`. A comment containing
   `- run: \`<run_id>\`` → `+1` with that issue, and no new comment. Otherwise `occurrence = 2 +` the number of comments
   starting with `**Occurrence `, then `comment(...)` → `+1` (never capped, AC-088.7, .14).
5. Only closed issues → `last` = the one with the latest `closed_at`. If `wontfix` is among its labels →
   `suppressed`, url = its URL, and nothing is sent (AC-088.8). Otherwise new, with `closed=last`.
6. New: the ledger counts entries for `repo` with `at > now() - window`. A count of `cap` or more → `pending`, reason
   `cap of <cap> new issues per <window as "24 h" for 86400, else "<n> s"> reached`. Otherwise `create(...)`, append
   `{"at", "repo", "signature", "url"}` to the ledger, and the result is `new`.
7. A `TrackerError` anywhere → `pending` with `str(e)`. Any other exception → `pending` with `<Type>: <msg>`.
   Each tracker call gets `timeout = min(10, deadline - monotonic())`. Below 1 s left → `pending`, reason `timed out`.

Ledger: `runs.state_dir() / "autoissue-ledger.jsonl"`, one JSON object per line. A write drops entries older than the
largest window seen (at least `WINDOW_S`). Writes are under an `fcntl` lock on `runs.state_dir() / ".autoissue.lock"`.

### Output lines (`Outcome.lines`)

| Result | Line |
|---|---|
| new | `issue: <issue url> new` |
| +1 | `issue: <issue url> +1` (the issue URL, not the comment URL; `Outcome.url` is the comment URL) |
| suppressed | `issue: not filed again: suppressed by #<n> (wontfix) <issue url>` |
| pending (failure) | `issue: not filed: <reason>; kept pending, retried at the next run store flush` |
| pending (cap) | `issue: not filed: cap of 10 new issues per 24 h reached; kept pending, retried once the 24-hour window allows it` |
| off | the draft lines and the hint (step 1) |

None of these lines offers `/shared:report-issue`, except `off`.

### Issue title and body (AC-088.6, .8, .10, .11)

Title: `"[auto] " + one_line(scrub(reason))`, where `one_line` is the first line with whitespace collapsed. A title
longer than 100 characters becomes `title[:99] + "…"` (exactly 100).

Body, in this order (the arrows are annotations, not part of the body):

~~~markdown
Seen again after #<n> was closed.          ← only with closed=<n>; this line, then one blank line

## Reason
<scrub(reason)>

## Command and phase
- command: `<scrub(command)>`
- phase: `<scrub(phase)>`

## Evidence
````text
<scrub(feedback.tail(evidence))>            ← "(none)" when empty
````

## <heading>                                ← one per extra section (091/092)
<scrub(text)>

## Environment
- shape: <shape>
- platform: <version>                       ← then the other feedback.diagnostics lines: OS, python, this repo, plugins, tools

## Run
- run id: <run_id>                          ← "- run id: none" without a run

_Filed automatically by cplat (spec 088). Secrets, e-mail addresses, home directories, repo, spec and branch names were removed._

Signature: platform:0123456789abcdef
~~~

Labels: `triage`, `auto-filed`, `bug` (kind `platform`). `GhTracker.create` handles a label error ("not found") by
creating the missing labels once and retrying. It uses `triage.LABELS` for colour and description, and
`autoissue.EXTRA_LABELS` for `smoke-failure` and `alert`. The issue is never filed without its labels: dedupe depends
on `auto-filed`.

Occurrence comment (AC-088.7):

~~~markdown
**Occurrence <n>** of `<signature>`

- date: <now() UTC, YYYY-MM-DD>
- platform: <core.platform_version()>
- shape: <shape>
- run: `<run_id>`
- reason: <one_line(scrub(reason))>
~~~

### `GhTracker` over `gh()`

| Method | gh call |
|---|---|
| `find` | (1) `gh api --paginate "repos/{repo}/issues?labels=auto-filed&state=open&per_page=100"`, without pull requests. (2) `gh api -X GET search/issues -f "q=repo:{repo} is:issue in:body \"Signature: {signature}\"" -f per_page=100`. Results are joined by number. `state`, `labels[].name`, `created_at`, `closed_at` and `body` come from the JSON. |
| `comments` | `gh api --paginate "repos/{repo}/issues/{n}/comments?per_page=100"` → `[c["body"]]` |
| `create` | `gh issue create -R {repo} --title T --body-file - --label L…` (body on stdin) → the last stdout line |
| `comment` | `gh issue comment {n} -R {repo} --body-file -` → the last stdout line |

Error mapping → `TrackerError`:
- `gh` not on PATH → `gh is missing`.
- Exit 4, or stderr mentioning `gh auth login` → `gh is not logged in`.
- A timeout → `timed out`.
- Any other non-zero exit → `GitHub refused: <last stderr line>`.

`gh()` never raises. A timeout gives `(124, "", "timeout")`, a missing binary `(127, "", "gh is missing")`.

### `runs.py` additions

```python
def current(repo_dir: Path) -> str | None:
    """The recorded run a command in repo_dir runs inside, or None. Candidates in order: attach_point(repo_dir), the
    `cplat runs begin` pointer's run_id, $CPLAT_RUN_PARENT. The first one with an active record (active(rid) is not None)
    wins. Never raises."""
```

`filed(run_id, signature, url, "suppressed")` stores `{"signature", "url", "result": "suppressed", "note": "suppressed by #<n>"}`,
where `<n>` is the trailing number of `url`. `_retry_filings` sets the same `note` when a retry returns `suppressed`,
both in the active record and in the follow-up line. Other results have no `note` key (AC-088.8).

### `cplat ship escalate`

```
cplat ship escalate <reason…> [--cause C] [--command CMD] [--evidence-file F|-]
```

- `--cause` is free text, default none. `ESCALATION_CAUSES = ("platform", "code", "decision", "environment")`.
  Anything else, including `unknown` and an absent flag, is stored as `unknown` and prints (AC-088.3):
  - absent: `cause missing: recorded as unknown; allowed causes: platform, code, decision, environment`
  - other: `cause '<value>' is not known: recorded as unknown; allowed causes: platform, code, decision, environment`
- `--command` defaults to `/svc:ship`. The phase is the ship state's `phase`.
- `--evidence-file`: the file's text, or stdin for `-`. A file that cannot be read gives empty evidence.
- Python: `escalate(repo, reason, cause=None, *, command=None, evidence="", report: list[str] | None = None) -> dict`.
  For `platform` it builds the `Draft` before `save_state`:
  - `signature("platform", command, phase, reason, names=private_names(runs.repo_slug(repo), st["spec"], st["branch"]))`
  - `shape` from `core.read_stamp(repo).get("shape", "none")`
  - `environment` from `feedback.diagnostics(repo)`

  It then calls `autoissue.file(draft, run_id=st["run_id"])` (after `_ensure_run`) and appends the outcome's lines to
  `report`. Filing never raises and never changes the exit code (0) (AC-088.12).
- CLI output: `ship <spec>: escalated (<reason>); the session may stop. Resume with /svc:ship <spec>`, followed by the
  cause message (if any) and the outcome lines.
- The stop gate's text names the flag: ``run `cplat ship escalate '<reason>' --cause <platform|code|decision|environment>`, then stop.``

### Crash hook — `cplat.main`

In the `except Exception as e` branch, after the `ERROR: unexpected failure …` line:
- Run `rid = runs.current(Path.cwd())`, wrapped in `try/except Exception`.
- `rid` set → `autoissue.file_crash(argv, e, rid, Path.cwd())`, and each outcome line goes to stderr. The
  `This looks like a platform bug…` hint is printed only when the result is `off` (inside its lines).
- No `rid`, or the hook itself failed → today's hint, unchanged.
- The exit code stays 70. `CPLAT_DEBUG` still re-raises, after the filing.

`crash_draft`:
- reason: `cplat <command> crashed: <Type>: <first line of str(e)>`.
- evidence: the last 20 lines of `traceback.format_exception(e)`, joined.
- phase: the last open phase of `runs.active(rid)`, or `none`.
- names: `private_names(record repo, record spec, current git branch of cwd)`.
- shape: `core.read_stamp(cwd)`.

### Triage

`triage.LABELS["auto-filed"] = ("c5def5", "Filed automatically by the platform (spec 088)")`. `setup-labels` creates
it. `list` already shows any open issue with `triage` and no decision label (AC-088.10).

## Data

- Local, under `runs.state_dir()`:
  - `autoissue-ledger.jsonl` (cap ledger)
  - `.autoissue.lock`
  - pending filings in 087's `filings.jsonl`, with `filer: "autoissue"` and `payload: {"draft", "cap", "window"}`
- Run record: the `filed` entries (087 schema) plus `note` for `suppressed`.
- Nothing new in the run store schema.

## Risks

- **087's test `tests/cplat/test_runs.py::test_the_cause_must_be_one_of_the_known_ones`** expects `--cause bogus` to
  exit through argparse. AC-088.3 requires `unknown` plus a message. The tester of 088 rewrites that test. AC-087.16's
  text is unchanged: an unknown cause still ends up as `unknown`.
- **Search tokenisation** of `"Signature: platform:<hex>"` is GitHub's. Only closed issues depend on it. The open path
  uses the issue list. A missed closed issue files a new issue without the "Seen again" link, and the next repeat
  converges on it.
- **Pending filings need a run store.** 087's `flush` retries them only after a reachable private store. Without one
  they stay in `filings.jsonl`, and doctor's `run store` check shows the pending count.
- **A label removed in triage:** an open issue without `auto-filed` is still found through search, but with index delay.
- **Escalation time:** filing has 20 s, then `runs.finish` has its own 20 s. A down network costs at most 40 s on an
  escalation that stops the session anyway.
