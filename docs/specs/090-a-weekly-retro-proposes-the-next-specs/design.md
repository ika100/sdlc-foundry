# Design — 090 A weekly retro proposes the next specs

## Decisions

- **Three steps, three commands, one directory.** `cplat retro --out DIR` builds the deterministic report and writes
  it to `DIR`. `cplat retro propose --dir DIR` runs headless Claude, which writes `DIR/proposals.json`.
  `cplat retro post --dir DIR` checks the proposals against that same `DIR/report.json` and posts. The agent and the
  check see the same report, so evidence can be verified exactly (AC-090.7). The weekly workflow is just these three
  calls (AC-090.12). By hand, `cplat retro` alone prints the report and writes nothing anywhere (AC-090.1).
- **The report is a pure function.** `retro_report.build(records, *, auto_issues, open_issues, specs, week, store,
  generated_at)` does no I/O. The same inputs give a byte-identical `report.json`, apart from `generated_at`
  (AC-090.2). Every GitHub and store call goes through a fakeable seam: `runs.open_store`, `runs_store.gh`, and
  `retro_github.gh` / `retro_github.tracker()`. Tests run offline.
- **Agent metrics reuse 089's aggregation verbatim.** The week's records go through
  `runs_report.aggregate_agents(..., since_days=7, now=<week end>)`, and the same call is made for the previous week.
  A row's `metrics` is exactly the 089 row's `metrics` (AC-090.4).
- **Evidence is a reference into the report, not free text.** The report carries a flat `evidence` index
  (`ref → value`). A proposal cites `{"ref", "value"}` pairs. `post` accepts a proposal only when at least one pair
  exists in the index with that value. It refuses and names the rest: one bad proposal is dropped, the report is still
  posted. ADR: [docs/adr/039-weekly-retro-evidence-checked-proposals.md](../../adr/039-weekly-retro-evidence-checked-proposals.md).
- **Public is counts, private is detail (AC-090.11).** One report, two renderings:
  - `render_private` is committed to the store. It has the repo list, escalation reason texts, check names, consumer
    spec ids and the 089 top causes.
  - `render_public` is posted. Free text from records becomes ranked placeholders (`reason 1`, `check 2`) with run ids.
    Repos appear as counts per shape. The body names no store.

  Before posting, a leak check refuses the post when the public body still contains any record `repo`, any record
  `spec`, or the store slug.
- **The schedule is installed by `cplat runs init`.** It writes a fixed workflow asset to the store repo when the file
  is missing and leaves it alone when it is present (AC-090.14). `cplat doctor` checks the file and the secrets.
- **Credentials of the workflow.** `RETRO_GH_TOKEN` is a fine-grained token: Issues read/write on the platform repo,
  Contents read/write on the store. It is the job's `GH_TOKEN`; the store repo's `GITHUB_TOKEN` cannot write issues in
  another repo. The Claude credential is `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`), or `ANTHROPIC_API_KEY`.
  Only the propose step sees it. That step runs with no GitHub token in its environment, so the agent cannot open pull
  requests or touch issues (AC-090.9).
- **The platform checkout is `main` of the platform repo.** AC-090.8 needs the current spec statuses, and the retro is the
  maintainer's own tool. A broken `main` makes the run red, which is visible.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/retro_report.py` | pure: week windows, `build`, evidence index, `render_text`, `render_private`, `render_public`, `leaks` | new |
| `scripts/cplat/retro_proposals.py` | pure: proposal schema, `validate`, `render_public_section`, `render_private_section`, `prompt` | new |
| `scripts/cplat/assets/retro-prompt.md` | the instructions for the headless proposal run | new |
| `scripts/cplat/retro_github.py` | `RetroTracker` over `gh`: auto-filed issues with comments, open issues, retro issues, create/edit/comment/close, the `retro` label | new |
| `scripts/cplat/retro.py` | `cplat retro` CLI: read the store, fetch issues, build, write DIR, propose, post, commit to the store | new |
| `scripts/cplat/retro_setup.py` | the workflow asset, `install_schedule(store, slug)`, `missing(store, slug)` | new |
| `scripts/cplat/assets/workflows/cplat-retro.yml` | the scheduled workflow installed into the store repo | new |
| `scripts/cplat/runs_store.py` | `Store.read_file(path)`, plus `GitHubStore.read_file`; a workflow-scope rejection is no write race | changed |
| `scripts/cplat/runs.py` | `init` installs the schedule | changed |
| `scripts/cplat/doctor.py` | `run_store_check(status)` (pure, shared with retro), `check_retro_schedule()` | changed |
| `scripts/cplat/cplat.py` | `"retro": "retro"`, docstring line | changed |
| `scripts/pin-actions.py` | default paths include `scripts/cplat/assets` | changed |

## Contract

### Week

- `retro_report.last_complete_week(today: date) -> str`: ISO week `"%G-W%V"` of `today - 7 days`, where `today` is
  the UTC date. On Monday 2026-10-26 it gives `2026-W43`, which runs from 2026-10-19 to 2026-10-25.
- `retro_report.week_bounds(week: str) -> tuple[datetime, datetime]`: `[Monday 00:00Z, next Monday 00:00Z)`. A record
  belongs to a week when `start <= ended_at < end`. A record without a parseable `ended_at` belongs to no week.
- `--week YYYY-Www` selects another week. A malformed week, or one that is not complete before today, is a
  `PlatformError`: `--week must be a complete ISO week before today, like 2026-W42`.

### CLI

| Command | Behaviour | Exit |
|---|---|---|
| `cplat retro [--week W] [--json] [--out DIR]` | read the store and the platform issues, build the report. It prints `render_text(report)`, or `json.dumps(report, indent=2)` with `--json`. With `--out`, it also writes `DIR/report.json`, `DIR/report.md` (`render_private`) and `DIR/prompt.md`, and deletes any stale `DIR/proposals.json` and `DIR/proposals.error`. It never writes to GitHub or the store (AC-090.1). | 0 / 1 |
| `cplat retro propose --dir DIR [--model M] [--max-minutes 20]` | run Claude to write `DIR/proposals.json`, see "Propose". Any failure writes `DIR/proposals.error` (one line: the reason). It prints `proposals: written (<s> spec(s), <p> prompt change(s))` or `proposals: not generated (<reason>)`. | always 0 |
| `cplat retro post --dir DIR` | post the report in `DIR` with its proposals, see "Post". | 0 / 1 |
| `cplat retro post [--week W]` (no `--dir`) | build the report now, as `cplat retro` does, and post it with `Proposals: not generated (no proposal step ran)`. | 0 / 1 |

Errors are `PlatformError`s, so `cplat` prints `ERROR:` and `  fix:` and exits 1.

**Store errors (AC-090.6).** These come before any GitHub write. `retro` calls `runs.store_status()`. When `state` is not
`ok`, the error is:

```
ERROR: run store not usable for the retro: <detail>
  fix: <doctor.run_store_check(status)["fix"]>
```

`<detail>` is one of:
- `CPLAT_RUNS_REPO is not set`
- `<slug> unreachable: <detail>`
- `<slug> is public`

The fix is exactly the hint `cplat doctor` prints for the store: `cplat runs init <owner/name>`, `gh repo view <slug>`,
or the `gh repo edit … --visibility private …` line. A `StoreError` from `store.read(days)` gives
`ERROR: run store <slug> cannot be read: <reason>` with fix `gh repo view <slug>`.

**Issue read errors.** A `TrackerError` while reading the platform issues gives
`ERROR: platform issues of <repo> cannot be read: <reason>` with fix `gh auth status`. A failed read is never reported
as "no data".

### Report — `scripts/cplat/retro_report.py`

```python
SCHEMA = 1
OUTCOMES = ("done", "escalated", "failed", "abandoned")
CAUSES = ("platform", "code", "decision", "environment", "unknown")
RERUN_REASONS = ("stale", "stuck", "transient")
NO_DATA = "no data for this week"
SAFE = re.compile(r"^[a-z][a-z0-9:._/-]{0,39}$")    # vocabulary that may appear publicly (kinds, outcomes, phases)

def last_complete_week(today: datetime.date) -> str: ...
def week_bounds(week: str) -> tuple[datetime.datetime, datetime.datetime]: ...
def previous_week(week: str) -> str: ...
def build(records: list[dict], *, auto_issues: list[dict], open_issues: list[dict], specs: list[dict],
          week: str, store: str, generated_at: str, malformed: int = 0) -> dict: ...
def render_text(report: dict) -> str: ...            # = render_private without the proposals section
def render_private(report: dict, proposals_md: str) -> str: ...
def render_public(report: dict, proposals_md: str) -> str: ...
def private_names(report: dict) -> dict[str, str]: ...   # repo -> "<repo>", spec -> "<spec>", store -> "<run-store>"
def leaks(text: str, report: dict) -> list[str]: ...    # which private names still occur (case-insensitive)
```

Inputs:
- `records`: parsed store lines (087 `runs_report.parse`), any week. `build` dedupes by `run_id` (first wins) and
  splits them into the covered and the previous week.
- `auto_issues`: `[{"number", "title", "url", "state", "labels", "created_at", "body", "comments": [{"created_at", "body"}]}]`.
- `open_issues`: `[{"number", "title", "labels"}]`, the open issues of the platform repo, without pull requests.
- `specs`: `[{"number": "087", "id", "title", "status", "tracks": [int]}]`, only specs whose status is not `done` and not
  `superseded`.

Output `report.json`: keys in this order. Each figure is `{"current": x, "previous": y}`, abbreviated `F` below.

```json
{
  "schema": 1,
  "week": "2026-W42", "since": "2026-10-12", "until": "2026-10-18",
  "previous_week": "2026-W41",
  "generated_at": "2026-10-19T06:00:12Z",
  "store": "acme/sdlc-runs",
  "records": {"current": 12, "previous": 9, "malformed": 0},
  "repos": {"by_shape": {"service-python": F, "unknown": F},
            "list": [{"repo": "acme/shop-api", "shape": "service-python", "runs": 5}]},
  "runs": {"ship": {"done": F, "escalated": F, "failed": F, "abandoned": F}},
  "phases": {"build": {"count": F, "median_s": F, "max_s": F}},
  "ci": {"rounds": F, "reruns": F, "rounds_per_run": F, "reruns_per_run": F},
  "escalations": {"platform": {"count": F,
                  "reasons": [{"rank": 1, "reason": "merge failed", "runs": 3, "duration_s": 5400.0,
                               "run_ids": ["20261013T…"]}]}, "code": {…}, "decision": {…}, "environment": {…}, "unknown": {…}},
  "reruns": {"by_reason": {"stale": F, "stuck": F, "transient": F},
             "by_check": [{"rank": 1, "check": "ci / test", "count": F, "run_ids": ["…"]}]},
  "issues": [{"number": 123, "title": "[auto] …", "url": "…", "state": "open", "routed": false,
              "occurrences_week": 4, "occurrences_total": 9, "signature": "platform:0123456789abcdef"}],
  "agents": {"rows": [{"agent": "svc:coder", "shape": "service-python", "model": "sonnet", "model_ids": [],
                       "runs": F, "few_runs": true, "incomplete_runs": 0,
                       "metrics": {…089 row metrics, covered week…},
                       "previous": {…089 row metrics, previous week…} | null,
                       "diff": {…same tree, numeric leaves current - previous, else null…},
                       "top_causes": [{"cause", "count", "run_id"}]}]},
  "no_data": ["runs", "agents", "issues"],
  "context": {"specs": [...], "open_issues": [...]},
  "evidence": {"records": 12, "runs.ship.escalated": 3, "...": 0}
}
```

Rules:
- **Runs (AC-090.2).** Every kind seen in either week has all four outcomes, plus `unknown` when a record has none or
  an unknown one. Kinds are sorted by name.
- **Phases.** `median_s` is `statistics.median`, `max_s` the longest. A phase without both timestamps is skipped. A week
  without the phase gives `null` for its median and max, and 0 for its count.
- **CI.** `rounds` is the sum of `ci_rounds`; `reruns` is the number of `reruns` entries. The per-run values divide by
  the week's records and are rounded to 3 places; a week without records gives `null`.
- **Escalations.**
  - Grouped by cause; all five causes are always present.
  - Within a cause, reasons are grouped by identical `strip()`ped text. They are ranked by the number of runs
    (descending), then by the total duration of those runs (`ended_at - started_at`, descending), then by text.
  - `run_ids` are sorted ascending, at most 5.
  - Ranked reasons are those of the covered week. `count` holds both weeks.
- **Reruns.** `by_reason` has the three reasons, plus `unknown` when one is missing. `by_check` ranks the covered week's
  checks by count (descending), then by name. A check seen only in the previous week is not ranked.
- **Repos.** Shape of a record = the `shape` of its first `agents` entry whose shape is not `none`, else `unknown`. A
  repo counts once per week, under the shape it has in most of its records of that week; a tie goes to the
  alphabetically first shape. `null` repos (fleet, retro) are not counted.
- **Issues (AC-090.3).**
  - Only issues with the `auto-filed` label and a body line matching `^Signature: platform:[0-9a-f]{16}$`.
  - An occurrence is the issue's creation, or a comment whose body starts with `**Occurrence `. Each is dated by its
    `created_at`.
  - `occurrences_week` counts those inside the week's bounds; `occurrences_total` counts all of them.
  - Issues with `occurrences_week == 0` are left out.
  - `routed` is true when the issue has a label in `triage.DECISION_LABELS`.
  - Sorted by `occurrences_week` (descending), then by number (ascending).
- **Agents (AC-090.4).**
  - `aggregate_agents(week_records, malformed=0, buffered=0, since_days=7, repo=None, agent=None, shape=None,
    by_version=False, store=store, now=<week end>)`, and the same for the previous week. Rows are matched by
    `(agent, shape, model)`.
  - `runs.previous` is 0 when the row has no previous match, and `previous` is then `null`.
  - `diff` mirrors `metrics`. Each numeric leaf is `round(current - previous, 3)`. It is `null` when either side is
    `null` or missing.
  - Rows keep 089's order. `few_runs` is 089's value (< 5 runs).
- **No data (AC-090.5).** `no_data` lists:
  - `"runs"` when the covered week has no records (runs, repos, phases, ci, escalations and reruns then render
    `no data for this week`);
  - `"agents"` when it has no agent rows;
  - `"issues"` when `issues` is empty.
- **Evidence index.** Every value is the covered week's number:
  - `records`
  - `runs.<kind>.<outcome>`
  - `phases.<name>.count|median_s|max_s`
  - `ci.rounds|reruns|rounds_per_run|reruns_per_run`
  - `escalations.<cause>`
  - `escalations.<cause>.reason<rank>` (its `runs`)
  - `reruns.<reason>`
  - `reruns.check<rank>`
  - `repos.<shape>`
  - `issues.#<number>` (its `occurrences_week`)
  - `agents.<agent>|<shape>|<model>.<path>`: every numeric leaf of `metrics`, joined by `.` (e.g.
    `agents.svc:coder|service-python|sonnet.fix_rounds.by_cause.ci`), plus `.runs`

  A `<kind>` or phase `<name>` that does not match `SAFE` is written as `kind<n>` / `phase<n>` (n = its 1-based position
  in sorted order), here and in `render_public`. `null` values are left out of the index.
- **Determinism.** Every dict and list above is built in a fixed order. `json.dumps(report, indent=2,
  ensure_ascii=False)` is the file. Durations are floats in seconds.

**Text renderings.** `render_text` and `render_private` share this layout. `render_public` is the same with the
substitutions in the table below.

```
<first line>
Proposals: not generated (<reason>)           ← or the proposals section (render_private / render_public only)
## Runs
| kind | done | escalated | failed | abandoned |       cells "<current> (prev <previous>)"
## Repos per shape
## Phases (median / longest)
| phase | runs | median | longest |                      durations "<m>m <ss>s" / "<h>h <mm>m", as 087
## CI
CI rounds per run 1.50 (prev 1.20) · reruns per run 0.25 (prev 0.40) · rounds 18 (prev 11) · reruns 3 (prev 4)
## Escalations
<cause>: <current> (prev <previous>)
  1. <reason text> — <n> run(s), <duration> (<run ids>)
## Reruns
by reason: stale <c> (prev <p>), stuck …, transient …
  1. <check> — <c> (prev <p>) (<run ids>)
## Platform issues
| issue | title | this week | total | state | routed |
## Agents
| agent | shape | model | runs | <metric> … |              cell "<cur> (prev <prev>, <+diff>)"; null → n/a; "few runs" after runs
---
_Generated by `cplat retro` (spec 090) at <generated_at>. Repos appear as counts per shape, runs by run id._
```

- First line (AC-090.5): `Weekly retro <week> (<since> to <until>): <n> run(s) in <r> repo(s)`, or
  `Weekly retro <week> (<since> to <until>): no runs this week` when the week has no records.
- A section listed in `no_data` prints its heading and the line `no data for this week`.
- Agent metric columns: each `avg` of the row's `metrics`, named as in 089 (`fix rounds`, `red-CI rounds`, `findings`,
  `findings after fix`, `refused test diffs`, `out-of-plan files`, `merge conflicts`, `re-plans`, `tester events`).
  Rows are grouped by role, one table per role. A diff prints with its sign, e.g. `+0.50` or `-1.00`.

| Element | private / text | public |
|---|---|---|
| repo list | table `repo · shape · runs` under "Repos per shape" | left out (counts per shape only) |
| escalation reason | the text | `reason <rank>` |
| rerun check | the check name | `check <rank>` |
| unsafe kind / phase name | the name | `kind<n>` / `phase<n>` |
| 089 top causes | `causes:` line per agent row | left out |
| issue title | the title | the title through `autoissue.scrub` with `private_names(report)` (it is already public) |

`render_public` passes the whole body through `autoissue.scrub(body, private_names(report))`; that includes
`feedback.redact`. `leaks(body, report)` must then return `[]`. Otherwise `post` raises
`PlatformError("the public retro body still names private data: <n> item(s); nothing was posted")` without naming them.

### Proposals — `scripts/cplat/retro_proposals.py`

`DIR/proposals.json`, written by the agent:

```json
{
  "specs": [
    {"title": "Merges stop failing on stale bases",
     "problem": "At most five sentences.",
     "priority": "P1",
     "spec_line": "Merges rebase on a stale base before landing",
     "evidence": [{"ref": "escalations.platform.reason1", "value": 3}, {"ref": "issues.#123", "value": 4}],
     "covers": null}
  ],
  "prompts": [
    {"agent": "svc:coder", "shape": "service-python",
     "metrics": [{"ref": "agents.svc:coder|service-python|sonnet.fix_rounds.avg", "value": 2.4}],
     "change": "Prose: what the prompt should say differently."}
  ]
}
```

`covers` is `null`, `{"spec": "087"}` or `{"issue": 123}`.

```python
MAX_SPECS, MAX_PROMPTS, MAX_SENTENCES = 5, 3, 5
PRIORITIES = ("P0", "P1", "P2")

@dataclass
class Checked:
    specs: list[dict]      # accepted, in order, each with "rank" (1..n) and the resolved "covers"
    prompts: list[dict]    # accepted, in order
    refused: list[str]     # one line per refused proposal

def load(path: Path) -> dict: ...                       # ValueError("proposals.json: <why>") when unreadable / not an object
def validate(data: dict, report: dict) -> Checked: ...
def render_public_section(checked: Checked) -> str: ...
def render_private_section(checked: Checked) -> str: ...  # public section + the refused lines
def not_generated(reason: str) -> str: ...               # "Proposals: not generated (<reason>)"
def prompt(report_dir: Path) -> str: ...                 # assets/retro-prompt.md with {dir}, {week}, limits filled in
```

`validate` checks the spec proposals in file order:
1. **Format.**
   - `title`: a non-empty single line of at most 100 characters.
   - `problem`: non-empty, at most 5 sentences. Sentences are counted by `re.split(r"(?<=[.!?])\s+", text.strip())`.
   - `priority`: one of `PRIORITIES`.
   - `spec_line`: a non-empty single line of at most 200 characters.
2. **Evidence.** It is a list. At least one item has a `ref` in `report["evidence"]` and a `value` equal to it
   (`math.isclose(a, b, abs_tol=1e-9)` for numbers). Items that do not match are dropped from the accepted proposal.
   No match at all → refused: `no evidence from this report`.
3. **Covers (AC-090.8).**
   - `{"spec": N}` must name a number in `report["context"]["specs"]`. Otherwise it is refused:
     `spec <N> does not exist or is done`.
   - `{"issue": N}` must be in `report["context"]["open_issues"]`. Otherwise it is refused:
     `#<N> is not an open issue`.
   - When `covers` is `null` and an accepted evidence ref is `issues.#N`: if a listed spec `tracks` N, `covers`
     becomes `{"spec": <that spec>}`; else, if N is open, `covers` becomes `{"issue": N}`.
4. **Limit.** After the first 5 accepted, the rest are refused: `over the limit of 5 proposed specs`. Accepted ones get
   `rank` 1..n in file order.

Prompt proposals: `agent` and `shape` must match a row in `report["agents"]["rows"]`. At least one `metrics` item must be
a matching evidence pair whose ref starts with `agents.<agent>|<shape>|`. `change` must be non-empty. After 3 accepted,
the rest are refused: `over the limit of 3 prompt proposals`.

A missing or wrongly typed list counts as empty. Each refused line has the form
`refused spec proposal <i> "<title>": <why>` or `refused prompt proposal <i> "<agent> <shape>": <why>`, where `i` is the
1-based position in the file.

Public section:

```
## Proposed specs
1. **<title>** (P1) — amends spec 087        ← or "— see #123", or nothing
   <problem>
   Evidence: `escalations.platform.reason1` = 3 (prev 1), #123 (4 this week)
   `/svc:spec <spec_line>`
## Agent prompt proposals
- **<agent>** on <shape>: <change>
  Metrics: `fix_rounds.avg` = 2.40 (prev 1.10, +1.30)
<k> proposal(s) refused (no evidence from this report, invalid, or over the limit)   ← only when k > 0
```

An empty accepted list prints `none` under its heading. The previous value comes from the report figure the ref points
to; for a ref with no previous value, it is left out.

### Propose — `cplat retro propose`

1. `DIR/report.json` is missing → error file `no report in <DIR>`.
2. Neither `CLAUDE_CODE_OAUTH_TOKEN` nor `ANTHROPIC_API_KEY` is set (non-empty) → `no Claude credential
   (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY is not set)`.
3. Run `[$CPLAT_CLAUDE or "claude", "-p", prompt(DIR), "--permission-mode", "dontAsk", "--allowedTools", "Read,Write",
   "--output-format", "text"] (+ ["--model", M])`:
   - `cwd=DIR`, timeout `--max-minutes`;
   - environment: `os.environ` without `GH_TOKEN`, `GITHUB_TOKEN`, `RETRO_GH_TOKEN`, plus `CPLAT_HEADLESS=1`;
   - log: `DIR/propose.log`.
4. The run's possible failures, each written as the error:
   - `claude is not installed on this machine` (FileNotFoundError)
   - `claude timed out after <m> min`
   - `claude exited with <code>`
   - `no proposals.json written`
   - `proposals.json: <why>` (from `load`)
5. On success, any stale `proposals.error` is removed. All output goes to stdout; the exit code is 0.

`assets/retro-prompt.md` tells the agent:
- what to read: `report.json`, `report.md`, the evidence refs, `context.specs`, `context.open_issues`;
- what to write: only `proposals.json` in this directory, in the format above, at most 5 specs and 3 prompt changes;
- every proposal cites refs with their exact value;
- prefer `covers` over a new spec;
- no repo names, spec ids of consumer repos, or text copied from the report's reason, check or cause texts in any field;
- edit no other file, run no commands.

### Post — `cplat retro post`

1. **Load.** Read `DIR/report.json`. Then:
   - `DIR/proposals.json` exists → `validate`, and print each refused line on stderr;
   - else `DIR/proposals.error` exists → `not_generated(<its first line>)`;
   - else `not_generated("no proposal step ran")`.

   A proposals file that cannot be loaded → `not_generated("proposals.json: <why>")`.
2. **Render.** `public = render_public(report, section)` and `private = render_private(report, private_section)`, then
   the leak check.
3. **Issue (AC-090.10).** Repo `autoissue.default_repo()`, title `Weekly retro <week>`.
   - `tracker().retro_issues(repo)` lists the issues labelled `retro`, state all. Titles must match
     `^Weekly retro (\d{4})-W(\d{2})$`.
   - One with this title → `edit_body(repo, number, public)`. Its state and labels are left as they are.
   - None → `create(repo, title, public, ["retro"])`. The label is created first when missing: colour `5319e7`,
     description `Weekly platform retro (spec 090)`. Never `triage`.
   - Several with this title → the lowest number is edited.
4. **Earlier issues (AC-090.13).** For every open `retro` issue whose title week is earlier than `<week>`, in ascending
   order:
   - `comment(repo, n, "Superseded by the retro for <week>: <url>")`;
   - then `close(repo, n)`.

   Issues of the same or later weeks, closed issues and issues without the label are not touched.
5. **Store (AC-090.11).** One `store.put` with message `retro: <week>`:
   - `retros/<week>.md`: `private`, with `Issue: <url>` as its second line;
   - `retros/<week>.json`: `{"report": report, "proposals": checked-or-null, "refused": [...], "issue": url}`;
   - `retros/README.md`: `# Retros`, a blank line, then the table `| Week | Report | Issue |` / `|---|---|---|`. It has
     one row per week, `| <week> | [report](<week>.md) | <url> |`, sorted by week descending. The existing file
     (`store.read_file`) is parsed, and the row for `<week>` is replaced or added.

   A `StoreError` here → `ERROR: retro posted as <url>, but the run store could not be updated: <reason>`, fix
   `cplat retro post --dir <DIR>   (replaces the issue body and retries the store)`.
6. **Print.** `retro: <url> (created|updated); closed <n> earlier retro issue(s); report in the run store`.

Order matters: every read and check (store, issues, render, leaks) happens before the first GitHub write. A failure
before step 3 posts nothing (AC-090.6, AC-090.12).

### GitHub — `scripts/cplat/retro_github.py`

```python
def gh(args: list[str], *, input: str | None = None, timeout: float = 30.0) -> tuple[int, str, str]: ...   # tests replace this

class RetroTracker(Protocol):
    def auto_issues(self, repo: str, since: str) -> list[dict]: ...   # auto-filed, state=all, updated >= since, with comments
    def open_issues(self, repo: str) -> list[dict]: ...               # [{"number", "title", "labels"}], no PRs
    def retro_issues(self, repo: str) -> list[dict]: ...              # [{"number", "title", "url", "state", "labels"}]
    def create(self, repo: str, title: str, body: str, labels: list[str]) -> str: ...   # url
    def edit_body(self, repo: str, number: int, body: str) -> str: ...                  # url
    def comment(self, repo: str, number: int, body: str) -> None: ...
    def close(self, repo: str, number: int) -> None: ...

def tracker() -> RetroTracker: ...   # GhRetroTracker(); tests replace this
```

`GhRetroTracker` makes these calls:
- `auto_issues`: `gh api --paginate "repos/{repo}/issues?labels=auto-filed&state=all&since={since}&per_page=100"`, then
  `repos/{repo}/issues/{n}/comments?per_page=100` (paginated) for each issue.
- `open_issues`: `gh api --paginate "repos/{repo}/issues?state=open&per_page=100"`.
- `retro_issues`: `gh api --paginate "repos/{repo}/issues?labels=retro&state=all&per_page=100"`.
- `create`: `gh issue create -R repo --title T --body-file - --label retro`. On "not found", it runs
  `gh label create retro … --force` and retries.
- `edit_body`: `gh issue edit N -R repo --body-file -`.
- `comment`: `gh issue comment N -R repo --body-file -`.
- `close`: `gh issue close N -R repo`.

Failures raise `autoissue.TrackerError`, through `autoissue._check` semantics. PRs (items with `pull_request`) are always
dropped. `since` is the previous week's Monday, so occurrences in both weeks are visible.

### Store transport (changed) — `scripts/cplat/runs_store.py`

- `Store.read_file(path: str, deadline: float | None = None) -> str | None` (protocol and `GitHubStore`). It runs
  `gh api repos/{slug}/contents/{path} -H "Accept: application/vnd.github.raw+json"`. A 404 gives `None`; any other
  failure raises `StoreUnreachable`.
- `_ApiError.race` is false when the text contains `workflow` (GitHub refusing a workflow file without the `workflow`
  scope is not a concurrent write).

### Schedule — `scripts/cplat/retro_setup.py`, `scripts/cplat/assets/workflows/cplat-retro.yml`

```python
WORKFLOW_PATH = ".github/workflows/cplat-retro.yml"
ASSET = Path(__file__).parent / "assets" / "workflows" / "cplat-retro.yml"
CLAUDE_SECRETS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
GH_SECRET = "RETRO_GH_TOKEN"

def workflow_text(platform_repo: str) -> str: ...      # ASSET with __PLATFORM_REPO__ replaced
def install_schedule(store, slug: str) -> list[str]: ...
def secret_names(slug: str) -> set[str] | None: ...    # runs_store.gh(["secret", "list", "-R", slug, "--json", "name"]); None if unreadable
def missing(store, slug: str) -> list[str] | None: ... # None when the secrets cannot be read
```

`install_schedule` never raises. It returns the lines `runs.init` prints before the `export` line:
- present (`read_file` gives text) → `retro schedule: present (.github/workflows/cplat-retro.yml)`. Nothing is written.
- missing → `store.put({WORKFLOW_PATH: workflow_text(autoissue.default_repo())}, "retro: weekly schedule (spec 090)")`
  → `retro schedule: added .github/workflows/cplat-retro.yml (Mondays 06:00 UTC)`.
- any exception → `WARNING: retro schedule not added: <reason>` and
  `  fix: gh auth refresh -h github.com -s workflow, then cplat runs init <slug>`.
- always last: `retro: set the secrets CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) and RETRO_GH_TOKEN in <slug>, and
  a self-hosted runner (repo variable CI_RUNNER); cplat doctor checks them`.

No line contains the word `created` (the AC-087.20 test of an existing store relies on that).

`missing` returns these entries, in this order, for what is absent:
- `no retro schedule (.github/workflows/cplat-retro.yml)`
- `no Claude credential secret (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY)`
- `no RETRO_GH_TOKEN secret`

The workflow asset (Actions pinned as everywhere; `pin-actions.py --check` covers `scripts/cplat/assets`):

```yaml
name: cplat retro
on:
  schedule:
    - cron: "0 6 * * 1"          # Mondays 06:00 UTC (AC-090.12)
  workflow_dispatch: {}
permissions:
  contents: read
concurrency:
  group: cplat-retro
  cancel-in-progress: false
jobs:
  retro:
    runs-on: ${{ vars.CI_RUNNER || 'self-hosted' }}
    timeout-minutes: 60
    env:
      GH_TOKEN: ${{ secrets.RETRO_GH_TOKEN }}
      CPLAT_RUNS_REPO: ${{ github.repository }}
      CPLAT_FEEDBACK_REPO: __PLATFORM_REPO__
      RETRO_DIR: ${{ runner.temp }}/retro
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: {repository: __PLATFORM_REPO__, ref: main, path: platform, persist-credentials: false}
      - name: report
        run: devbox run -c platform -- uv run "$GITHUB_WORKSPACE/platform/scripts/cplat/cplat.py" retro --out "$RETRO_DIR"
      - name: install Claude Code
        continue-on-error: true
        run: command -v claude || curl -fsSL https://claude.ai/install.sh | bash
      - name: proposals
        continue-on-error: true
        env:
          GH_TOKEN: ""
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: PATH="$HOME/.local/bin:$PATH" devbox run -c platform -- uv run "$GITHUB_WORKSPACE/platform/scripts/cplat/cplat.py" retro propose --dir "$RETRO_DIR"
      - name: post
        run: devbox run -c platform -- uv run "$GITHUB_WORKSPACE/platform/scripts/cplat/cplat.py" retro post --dir "$RETRO_DIR"
```

The `report` step failing skips `post`, so the run is red and no issue changes (AC-090.12). `propose` always exits 0.
`continue-on-error` covers a runner without devbox or Claude: `post` then reports "no proposal step ran" or the reason
from `proposals.error`. This asset is not a Copier template, so the `${{ }}` expressions stay unescaped.

### `cplat runs init` (changed)

After the visibility check, and after `create_private` for a new repo, `init` adds
`retro_setup.install_schedule(store, slug)` to its lines. The `export CPLAT_RUNS_REPO=…` line stays last. A public repo
still raises before anything is written. Run on an existing store that has the file, it writes nothing (AC-090.14).

### `cplat doctor` (changed)

- `run_store_check(st: runs.StoreStatus) -> dict` holds today's mapping of `check_run_store`; `check_run_store()`
  becomes `run_store_check(runs.store_status(...))`. `retro` uses the same function for its hint (AC-090.6).
- `check_retro_schedule() -> list[dict]`, appended in `run_checks` after the run store check:
  - store not configured, not private or unreachable → `[]` (the run store check already says so);
  - `missing(...)` is `None` → `warn "retro schedule"` with detail `secrets of <slug> could not be read with this gh login`;
  - missing items → `warn "retro schedule"` with detail `<slug>: <items joined by "; ">`. The fix is these parts, joined
    by ` ; `, for the items that are missing:
    - `cplat runs init <slug>`;
    - `claude setup-token, then gh secret set CLAUDE_CODE_OAUTH_TOKEN -R <slug>`;
    - `gh secret set RETRO_GH_TOKEN -R <slug>   (fine-grained: Issues read/write on <platform repo>, Contents read/write on <slug>)`;
  - else `ok "retro schedule"` with detail `<slug>: weekly retro scheduled (Mondays 06:00 UTC)`.
  - It is never `fail`.

## Data

No new local state. In the store repo:
- `retros/<week>.md`
- `retros/<week>.json`
- `retros/README.md`
- `.github/workflows/cplat-retro.yml`

Run records are unchanged; the retro writes no run record of its own. The platform repo gets one `retro` issue per week.

## Risks

- **Workflow-file writes need the `workflow` scope.** A default `gh auth login` token lacks it. `init` then warns with
  `gh auth refresh -s workflow`, and doctor keeps warning until the file exists.
- **Free text can leak through the agent.** The agent sees private text and could copy it. Scrubbing every posted field
  with the record's names and running the final leak check bound this. Text that is neither a name nor a secret (a
  paraphrased reason) is the agent's responsibility per the prompt.
- **The runner image.** The store repo needs its own ARC scale set (personal accounts have repo-level runners only,
  docs/self-hosted-runners.md) with devbox. Claude Code is installed by the workflow when missing.
- **GitHub `since` filters by `updated_at`.** An issue updated in the week by something other than an occurrence is read
  and then dropped, because it has 0 occurrences in the week.
