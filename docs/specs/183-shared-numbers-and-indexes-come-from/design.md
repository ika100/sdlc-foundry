# Design — 183 Shared numbers and indexes come from cplat

## Decisions

- **One scan module for shared numbers** (`refscan.py`): the git and `gh` reading that `adr.py` does today for ADRs is
  moved there, parameterised by directory, and reused for spec folders. `adr.py` keeps its public functions and
  behaviour (the #337 tests stay green). ADR: [099](../../adr/099-shared-numbers-and-indexes-are-handed-out-by-cplat.md).
- **Open PRs are read with one `gh pr list` call**, exactly as `adr.open_prs` does today; unreadable (no `gh`, non-zero
  exit, invalid JSON, timeout) is a distinct result (`None`), not an empty list, so callers can warn (A2).
- **`cplat adr add` is a plumbing command** (`cplat adr add …`, module `adrcmd.py`), not a verb under `spec`, because an
  ADR is not a spec artefact; `cplat spec adr-next` stays as it is.
- **The ADR template is a file of the platform** (`scripts/cplat/assets/adr-template.md`), MADR sections in the layout of
  the recent platform ADRs; component repos get the same template through `cplat`.
- **Replacement is checked inside `check()`**: the index of other specs is built only when the spec's criteria contain a
  `(replaces …)` marker, so a full `cplat spec check` stays as fast as today and `approve`, `ci` and `list --detail`
  get the rule for free (A9: approval already refuses an unstruck target).
- **A superseded line keeps the old text after a colon**, and `ac_hash` reads it back as the original criterion, so
  striking a criterion through does not drift the old spec's `spec_hash`; a plan task covering a superseded criterion
  is not an error. Without this, AC-183.5's "passes when struck through" would fail on the old spec's own plan.
- **`cplat spec new --from-plan` strikes the replaced criterion itself** (AC-183.8): the system planner writes a repo's
  criteria into the plan and never edits a component repo, and spec 147 lets no product-manager rewrite the slice, so
  cplat is the only writer in "the same change". The product-manager strikes by hand (Edit), following the format
  reference.
- **A closed stdout ends the run with 141**: `cplat.main` catches `BrokenPipeError` around the whole dispatch (also
  `_resolve`'s help output), points fd 1 at `/dev/null` so the interpreter's final flush cannot print "Exception ignored",
  and returns 141 before the crash handler (`_file_crash`) is reached.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/refscan.py` | base ref, pushed branches' entries of a directory, open PR file paths (tri-state) | new |
| `scripts/cplat/adr.py` | ADR numbers and clashes, now on `refscan` | changed |
| `scripts/cplat/specnumbers.py` | next spec number across refs and PRs; spec number clashes of this branch | new |
| `scripts/cplat/adrcmd.py` | `cplat adr add`: validate, number, write ADR, append index row | new |
| `scripts/cplat/assets/adr-template.md` | the ADR template | new |
| `scripts/cplat/spec_replace.py` | `(replaces …)` / `superseded by` parsing, the replacement check, the strike helper | new |
| `scripts/cplat/spec.py` | `new` uses `specnumbers`; `check` CLI adds number clashes; `check()` adds replacement errors; `AC.superseded_by`; `ac_hash` normalisation; trace output; `new_from_plan` strikes | changed |
| `scripts/cplat/cplat.py` | `adr` plumbing entry; `BrokenPipeError` → 141 | changed |

## Contract

### `refscan` (internal, used by `adr`, `specnumbers`)

```python
def base(root: Path) -> str | None                     # "origin/main", else "main", else None
def entries_at(root: Path, ref: str, directory: str) -> list[str]       # `git ls-tree --name-only <ref>:<directory>`
def other_branches(root: Path, directory: str) -> dict[str, list[str]]  # every refs/remotes/origin/* except origin/main,
                                                                        # origin/HEAD and origin/<current branch>
def open_pr_paths(root: Path) -> dict[str, list[str]] | None            # {"#659": ["docs/specs/176-x/spec.md", ...]}
    # `gh pr list --state open --limit 100 --json number,headRefName,files`, timeout 60 s, cwd=root;
    # the PR whose headRefName is the current branch is left out; None when gh is missing, exits non-zero,
    # prints invalid JSON or times out. No fetch, no other network call (A1).
```

### `cplat spec new` (AC-183.1)

- Number = 1 + max over: spec folders in the working tree (also broken ones), folders under `docs/specs/` at the base
  ref, at every other pushed branch, folders named in the open PRs' file paths (`docs/specs/<NNN>-<slug>/…`), and legacy
  `STORY-NNN` ids in `docs/backlog.md`. A folder name counts when it matches `^\d{3,}-`.
- Stdout unchanged: the new `docs/specs/<NNN>-<slug>/spec.md` path (and claim notes).
- When `open_pr_paths` is `None`: exactly one line on **stderr**, exit 0:
  `WARNING: open PRs were not checked (could not read them with gh); spec <NNN> comes from main and the pushed branches`
- `specnumbers.next_number(root) -> tuple[int, str | None]` (number, warning or None).

### `cplat spec check` (AC-183.2)

- Mine = spec folders in the working tree that the base ref does not have. Empty → no scan, no `gh` call.
- For each mine folder `<NNN>-<a>`, every other folder `<NNN>-<b>` (b ≠ a) found at the base ref, on another pushed
  branch (not counting folders the base also has), or in an open PR's files is an error under the key `docs/specs`:
  `ERROR: docs/specs: spec <NNN> (<NNN>-<a>) is also used on <where> (<NNN>-<b>); take a new number from `cplat spec new``
  with `<where>` = `origin/<branch>` (or the base ref) or `open PR #<n>`. One error per (number, place).
- PRs unreadable while mine is non-empty: one line `WARNING: open PRs were not checked for spec numbers (could not read
  them with gh)`; branches are still checked. A number only this branch uses: no error. Exit 1 on any error, as today.

### `cplat adr add <slug> --decision "<one line>" [--offline]` (AC-183.3)

- `slug` must match `^[a-z0-9]+(-[a-z0-9]+)*$`; `--decision` after collapsing whitespace (newlines included) to single
  spaces must be non-empty; no file `docs/adr/<NNN>-<slug>.md` may exist for any number. Any violation: exit 1,
  `ERROR: <reason>` on stderr (`slug '<s>' must be lowercase words joined by hyphens`, `--decision is empty`,
  `slug '<s>' is already used by docs/adr/<file>`), nothing written. A missing `--decision` is an argparse error (exit 2).
- Number = `adr.next_number(root, with_prs=not offline)` (the value `cplat spec adr-next` prints).
- Writes `docs/adr/<NNN>-<slug>.md` from the template (creates `docs/adr/` if missing):

  ```markdown
  # ADR-<NNN>: <Title>                      <- slug with hyphens as spaces, first letter upper-cased

  **Status:** Proposed (<YYYY-MM-DD>)

  ## Context

  <!-- why a decision is needed: the forces and constraints -->

  ## Decision

  <decision>

  ## Consequences

  <!-- what becomes easier or harder, what a later change must keep -->
  ```

- Index `docs/adr/README.md`: inserts one line `| [<NNN>](<NNN>-<slug>.md) | <decision> |` (a `|` in the decision
  written as `\|`) directly after the last line of the last Markdown table (a line starting with `|`); every other byte
  of the file is unchanged, including a trailing newline. A file without a table gets `\n| ADR | Decision |\n|---|---|\n`
  and the row appended. No file (A4): created as
  `# Architecture decision records\n\n| ADR | Decision |\n|---|---|\n<row>\n`.
- Stdout: one line, the ADR's path relative to the repo, `docs/adr/<NNN>-<slug>.md`. Exit 0.

### Replaced criteria (AC-183.5, AC-183.6)

- Marker: an active criterion line whose text ends with `(replaces AC-<NNN>.<n>)`, optionally followed by `(smoke)`:
  `\(replaces (AC-\d{3,}\.\d+)\)(\s*\(smoke\))?\s*$`.
- Superseded line: `- ~~**AC-<NNN>.<n>**~~ superseded by AC-<MMM>.<m> on <YYYY-MM-DD>[: <old criterion text>]`;
  parsed by `^\s*[-*]\s+~~\*\*(AC-\d{3,}\.\d+)\*\*~~\s+superseded by (AC-\d{3,}\.\d+)`. It is withdrawn for every
  count (`active_acs`, plan coverage, trace, `list`, `detail`, chain, `budget`); `AC.superseded_by` holds the new id.
- `check()` errors on the replacing spec (status other than `superseded`):
  - target active: `<new> replaces <old>, which is still active; strike it through in docs/specs/<old-spec>/spec.md as
    "~~**<old>**~~ superseded by <new> on <date>: <old text>" with one Changelog line`
  - target missing (no spec with that number, or no such id): `<new> replaces <old>, which does not exist`
  - target struck through (withdrawn or superseded): no error.
- `check_plan`: a task covering a superseded criterion is not an error; `ac_hash` hashes a superseded line that carries
  `: <old text>` as `- **<old>** <old text>`, so the old spec's `spec_hash` does not change.
- `cplat spec trace <id>`: after the active criteria, one line per superseded criterion, not counted in `<k>/<n>`, no
  effect on the exit code: `superseded <old>  superseded by <new>`. `--json` adds `"superseded": {"<old>": "<new>"}`
  (omitted when empty).
- `spec_replace.strike(spec_dir, old, new) -> bool`: rewrites the old criterion's line to the superseded form with today's
  date and its old text, adds `- <date> <old> superseded by <new>` to that spec's Changelog, keeps its status; False when
  the line is not an active criterion. `new_from_plan` calls it for each `(replaces …)` of the slice whose target spec
  is in this repo, and prints nothing extra.

### Closed pipe (AC-183.7)

Any `cplat …` whose stdout reader closes early: exit status 141, zero bytes on stderr, no `autoissue`/`feedback` call.
`cplat shape | head -1` under `set -o pipefail` returns 141.
