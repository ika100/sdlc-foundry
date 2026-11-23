# Design — 177 Triage asks reporters plainly and closes what needs no work

## Decisions

- **The script finds the missing form fields; the triager only confirms or adds to them.** A new pure module `triage_reporter.py` reads the repo's own issue forms (`.github/ISSUE_TEMPLATE/*.yml`, without `config.yml`) and compares an issue body with the `### <label>` sections GitHub renders. A form-filed issue therefore gets the same missing list on every run; for an issue filed without a form the triager picks the matching form and names the missing fields, because only reading the prose tells what it already says (AC-177.1).
- **The reporter comment is checked by the script, not trusted to the prompt.** `load_proposals` refuses a comment to a reporter outside the repo (role not `owner`, `member`, `collaborator`, A3) that names internal terms, does not thank, or does not ask for each missing field; the triager rewrites it. The sentence with the number of days and the reopen promise is appended by `actions()`, so it is always present and always states the configured number (AC-177.2).
- **Silent `needs-info` issues are proposed by the script, with a fixed final comment.** No judgement is needed, so the batch marks such an issue `handled: {"kind": "silent"}`; it needs no row, appears in the confirmation and is closed only when its number is in `act --rows` (AC-177.4).
- **Closing is `act`'s only new outward step, and only for confirmed rows.** `act` closes as `not planned` the confirmed rows of class `question`, `duplicate`, `wontfix` and the silent `needs-info` issues; every other path (`apply`, `show`, unnamed rows) still never closes. An unattended run (`CPLAT_HEADLESS=1`) refuses a close before the first write, as it refuses a priority change (spec 196), because there is no person to confirm (non-goal 1, AC-177.3).
- **A closed `needs-info` issue comes back through the same GraphQL request.** The batch query gains one alias for closed issues labelled `needs-info` (50 newest, with comments); one closed as `NOT_PLANNED` with a comment by its author after `closedAt` is queued with `state: "closed"`, and `act` reopens it before its row's labels and comment. The close keeps the `needs-info` label so this lookup finds it (AC-177.4).
- **The days are a project setting `needs_info_close_days`** in the committed `.platform-settings.yml` (default 14, an integer of at least 1), read only from the project file, because it is the repo's policy and not a person's (A2).
- **The hard rule keeps its register id `triage-never-closes`** and its text becomes "Never close an issue without the user's confirmation, because a closed issue leaves the queue unseen." (A1): the register's hard ids are pinned by the spec 168 tests, and the enforcement (`cplat issue triage`) stays the same tool.
- ADR (outlives the feature; amends point 5 of ADR-025): "Triage closes confirmed question, duplicate and wontfix issues and silent needs-info issues as not planned; comments to outside reporters use plain words." Created with `cplat adr add triage-closes-confirmed-issues --decision "<that line>"` before the build (this planning session had no shell).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/triage_reporter.py` | forms, missing fields, internal-term check, the two fixed comment texts | new |
| `scripts/cplat/settings.py` | `needs_info_close_days(repo)` | changed |
| `scripts/cplat/triage_batch.py` | query alias, `forms`, `close_after_days`, per-issue `state` and `form`, silent and reopened issues | changed |
| `scripts/cplat/triage_view.py` | row fields `missing`/`form`, comment checks, `actions()` with `close`/`reopen`, plan and overview texts | changed |
| `scripts/cplat/triage.py` | `close_one`, `reopen_one`, `refuse_unattended_close`, help texts | changed |
| `scripts/cplat/triage_act.py` | reopen, then labels and comment, then close; summary, undo | changed |
| `plugins/issue/commands/triage.md` | asks only what the user may know, comment rules, the changed hard rule | changed |

## Contract

### `triage_reporter.py` (pure, no GitHub access)

```python
PUBLIC_COMMANDS = ("/platform:doctor", "/issue:report")

def forms(root: Path) -> list[dict]
    # [{"id": "bug_report", "name": "Bug report", "fields": [{"label": "What happened", "required": True}, ...]}]
    # every *.yml / *.yaml of root/.github/ISSUE_TEMPLATE except config.yml, sorted by id; body entries of type
    # `markdown` are skipped; a missing dir or an unreadable file gives [] for it (never raises).

def form_of(body: str, forms: list[dict]) -> dict
    # {"id": str | None, "missing": [label]}: the form whose field labels match the most `### <label>` headings
    # (at least one; ties: the first by id); missing = its required fields whose section is absent, blank or
    # `_No response_`, in form order. No heading matches: {"id": None, "missing": []}.

def internal_terms(text: str) -> list[str]
    # the distinct internal terms found, in order of first appearance:
    #   spec numbers  r"\bspec\s+\d{1,4}\b" (case-insensitive), r"\b\d{3}-[a-z][a-z0-9-]+", r"\bAC-\d+", r"\bADR-\d+"
    #   labels        any triage.LABELS name in backticks; bare (word boundary, case-insensitive): needs-info,
    #                 needs-decision, needs-exploring, small-change, auto-filed, stale-premise, triaged, p0, p1, p2
    #   commands      r"(?<![\w/])/[a-z][a-z-]*:[a-z][a-z-]*" not in PUBLIC_COMMANDS; r"\bcplat\b"

def thanks(text: str) -> bool               # r"\bthank" case-insensitive

def footer(days: int) -> str
    # "If there is no answer within {days} days, this issue is closed; a comment from you here reopens the review."

def final_comment(days: int) -> str
    # "Thanks again for the report. We asked for more details {days} or more days ago and have not heard back, so this
    #  issue is closed for now. Comment here with the details and it goes back into review."
```

### Setting

`.platform-settings.yml`: `needs_info_close_days: <int >= 1>`; absent: 14. Anything else raises `PlatformError("<path>: needs_info_close_days must be a whole number of days, at least 1, got '<value>'")`. `settings.needs_info_close_days(repo: Path) -> int`.

### Batch (`batch --json`, additions to spec 176)

Top level:

- `close_after_days: int` (the setting).
- `forms: [...]` (`triage_reporter.forms` of the repo root).

Per entry of `issues`:

- `state: "open" | "closed"`.
- `form: {"id": str | None, "missing": [str]}` (`form_of` on the raw body before fencing).
- `handled` may now be `{"kind": "silent", "line": "silent <n> days: close with a final comment"}`: a `needs-info` issue, otherwise not handled, whose `reply.state` is `silent` and whose `now - reply.since` is at least `close_after_days` whole days. Such an issue is in `issues` (no longer in `skipped`); silent ones below the threshold stay in `skipped` as `silent <age>`.
- A closed issue joins `issues` with `state: "closed"` when it carries `needs-info`, its `stateReason` is `NOT_PLANNED` and its author commented after `closedAt`; it needs a row like any unhandled issue.

GraphQL: one more alias in the same request, `waiting_closed: issues(states: CLOSED, labels: ["needs-info"], first: 50, orderBy: {field: UPDATED_AT, direction: DESC})` with `number title body url createdAt closedAt stateReason authorAssociation author { login } labels(first: 30) { nodes { name } } comments(last: 50) { nodes { author { login } authorAssociation body createdAt } }`. `read()` returns it as `waiting_closed` (normalised); an answer without the alias reads as `[]`.

### Proposals rows (additions)

| Field | Rule |
|---|---|
| `missing` | `needs-info` rows: a non-empty list of strings. With a known form (the entry's `form.id`, or the row's `form`) each item is a field label of that form and the list contains every label of the entry's `form.missing`. Without any form in the repo: free text items. |
| `form` | `needs-info` row of an entry with `form.id` null while `batch.forms` is not empty: required, one of the form ids. |
| `comment` | to an entry whose `role` is not a writer, for every comment class: `internal_terms` empty. For `needs-info` to a non-writer also: `thanks` true and each `missing` item appears in it (case-insensitive). |

Errors are lines of the one `PlatformError("the proposals file is not valid", hint=...)`:

- `#N: a needs-info row needs missing (the fields to ask the reporter for)`
- `#N: a needs-info row of an issue filed without a form needs form (one of <ids>)`
- `#N: missing names "<x>", not a field of <form name>`
- `#N: missing leaves out "<x>", empty in the form`
- `#N: the comment to an outside reporter uses internal terms: <t1>, <t2>; use plain words`
- `#N: the comment to an outside reporter does not thank them`
- `#N: the comment does not ask for "<x>"`

### `actions(issue, row)` (shared by `confirm --show` and `act`)

Returns `{"add", "remove", "comment", "close": bool, "reopen": bool}`:

- `question`, `duplicate`, `wontfix`: labels as before, `close: True` unless the entry is already closed. A duplicate comment starts with `Duplicate of #<duplicate_of>` (prepended when the row's comment does not start with it), so GitHub links the original and `triage_facts.status` reads it.
- `needs-info`: the row comment + `"\n\n" + footer(close_after_days)`.
- handled `silent`: no labels (the close keeps `needs-info`), `comment = final_comment(close_after_days)`, `close: True`.
- entry `state: "closed"` and class not in the closing classes: `reopen: True`.

`confirm` lines: closing rows end in `, close as not planned`; silent: `needs-info, silent <n> days: close as not planned with a final comment`; reopen rows start with `reopen, `. `confirm --show N` adds a line `state: close as not planned` or `state: reopen` (or `state: unchanged`). Overview: a `needs-info` line adds `missing: <a>, <b>`; a reopened entry adds `reopened by the reporter`; the silent line sits in `Already handled`.

### `triage.py`

```python
def refuse_unattended_close() -> None       # CPLAT_HEADLESS=1: PlatformError("closing an issue needs the user's confirmation",
                                            #   hint="run /issue:triage in a Claude Code session")
def close_one(repo: str | None, number: int, dry_run: bool) -> Report
    # gh issue close N [-R repo] --reason "not planned"; undo "gh issue reopen N"; dry run: will_do "[outward] close as not planned"
def reopen_one(repo: str | None, number: int, dry_run: bool) -> Report
    # gh issue reopen N [-R repo]; undo "gh issue close N --reason \"not planned\""
```

`apply` (single-issue path) never closes.

### `act`

Before the first write: every named row's actions are computed; `refuse_unattended_priority` and, when any `close` is true, `refuse_unattended_close` run. Then per issue: `reopen_one` → `apply_one` (labels, comment) → `close_one`. Only issues named in `--rows` are touched. JSON `done` entries gain `closed: bool` and `reopened: bool`; summary phrases: `answered and closed`, `closed as duplicate of #N`, `explained and closed`, `closed after <n> days without an answer`, `reopened, …`; `undo` lists `#N: gh issue reopen N` per close.
