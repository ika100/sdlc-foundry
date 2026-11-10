# Design — 175 A spec number means the spec and ship PRs close their issues

## Decisions

- **Resolution lives in a new module `dispatch_items.py`**, not in `dispatch_state.parse_item`: resolving a bare number needs the
  checkout's specs and the open issues (snapshot or GitHub), and `dispatch_state` stays free of repo and GitHub reads.
  `dispatch_state.parse_item` keeps the syntax of the explicit forms (still used by `dispatch_backlog._spec_record` for spec ids)
  and no longer turns a bare number into an issue key (AC-175.1).
- **Explicit forms never read GitHub.** `#<N>` / `issue-<N>` name the issue whatever its state, as in spec 167; only a bare number
  needs the open issues (A3), so a steering command with an explicit form works offline.
- **A refused item is a `PlatformError` subclass `dispatch_state.ItemRefused`** that `dispatch.main` turns into exit 2 (A5);
  `cplat.py` keeps mapping every other `PlatformError` to exit 1. The same pattern for the ship body: `ship.BodyRefused`, caught
  in `ship.main` for the `pr` verb.
- **One closing-lines function for both PR paths.** The candidate collection and `{{CLOSES}}` replacement of `pr_open._closes` move
  into two public functions (`pr_open.closes_for`, `pr_open.fill_closes`); `cplat pr open` and `cplat component ship pr` both call
  them, so the lines are identical by construction (AC-175.4, A6).
- **A spec that cannot be read refuses the ship PR** instead of silently dropping its `tracks` (as `cplat pr open` does, which stays
  unchanged): a ship PR without the spec's closing lines is exactly the #645 failure (AC-175.5).
- No ADR: both decisions are local to the dispatcher's steering verbs and the ship PR path; the non-goals keep every other command
  as it is.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/dispatch_items.py` | `resolve(repo, slug, text) -> Item`: the item form, the specs, the open issues, the refusals | new |
| `scripts/cplat/dispatch_state.py` | `ItemRefused`; `parse_form`; `parse_item` without the bare-number-is-an-issue rule | changed |
| `scripts/cplat/dispatch.py` | `skip`, `prioritize`, `resume <item>` resolve through `dispatch_items`, print the new lines, exit 2 on `ItemRefused` | changed |
| `scripts/cplat/pr_open.py` | `closes_for`, `fill_closes` extracted from `_closes` (behaviour of `cplat pr open` unchanged) | changed |
| `scripts/cplat/ship.py` | `open_pr` fills `{{CLOSES}}` and refuses a body that still has it; `BodyRefused`; exit 2 in `main` | changed |
| `docs/dispatch.md` | the item line (AC-175.2) | changed |

## Contract

### Steering items (AC-175.1 to AC-175.3)

`cplat dispatch skip <item> --reason <text>`, `cplat dispatch prioritize <item>`, `cplat dispatch resume <item>` (`resume` without
an item is unchanged). `<item>` forms, matched on the stripped text:

| Written | Form | Names |
|---|---|---|
| `#<N>`, `issue-<N>` | issue | issue #N, always; no GitHub read, its state is not checked |
| `spec-<N>`, `spec-<id>`, `0<digits>` (zero-padded, e.g. `054`), `<N>-<slug>` | spec | the spec whose number has the value N (`int` of the leading digits) |
| `<N>` (digits, no leading zero) | bare | the spec with value N, or the open issue #N, see below |
| anything else | — | refused |

**Specs** (no GitHub read): the directories `docs/specs/<id>/` of `--repo` that contain `spec.md` (any status), plus the `id`s of the
`specs` and `drafts` of the cached dispatcher snapshot (`state.json` `snapshot`, any age), so a draft spec that exists only in an open
spec PR resolves too. A spec matches N when `int(<id>.split("-", 1)[0]) == N`. Its key is `spec-<NNN>` (`f"spec-{N:03d}"`, as in spec
167); its label is `spec <id>`.

**Open issues** (bare form only): the issue numbers of the cached snapshot when it is younger than `dispatch_backlog.MAX_AGE` (300 s,
the same value as `dispatch.SNAPSHOT_AGE`; `Snapshot.age() < MAX_AGE`) and `issues` is not in its `unavailable`; otherwise one fresh read
`gh issue list [-R <owner/name>] --state open --limit 500 --json number` through `dispatch_backlog.gh`, not persisted. A failing call
(`PlatformError`, `OSError`) or an answer that is not a JSON list means "the open issues cannot be read" with the first line of the error
as `<reason>`.

**Bare number N:** spec match and N open → refused (both); spec match only → the spec; open issue only → issue #N; neither → refused;
spec match and the open issues cannot be read → refused; no spec match and the open issues cannot be read → refused.

Success: exit 0, one line on stdout, the state changed as in spec 167 (`skipped[key]`, `pinned`, `skipped`/`holds` dropped):

```
skipped: spec 154-<slug> (reason: r)        skipped: issue #154 (reason: r)
prioritized: spec 154-<slug>                prioritized: issue #154
resumed: spec 154-<slug>                    resumed: issue #154
```

Refused (`ItemRefused`): exit 2, nothing on stdout, one `ERROR:` line on stderr, `state.json` byte-for-byte unchanged (the resolution
happens before any `dispatch_state.update`). `<t>` is the item as written (stripped), `<N>` its integer value, `<NNN>` `f"{N:03d}"`:

| Case | stderr |
|---|---|
| bare, spec and open issue | `ERROR: <t> is both spec <id> and open issue #<N>: write spec-<N> or #<N>` |
| bare, neither | `ERROR: <t> is neither a spec nor an open issue: write spec-<N> or #<N>` |
| bare, spec, issues unreadable | `ERROR: <t> is spec <id>, but the open issues cannot be read (<reason>): write spec-<N> or #<N>` |
| bare, no spec, issues unreadable | `ERROR: <t> is no spec and the open issues cannot be read (<reason>): write spec-<N> or #<N>` |
| spec form, no such spec | `ERROR: <t> names no spec (no docs/specs/<NNN>-*): write spec-<N> for an existing spec or #<N> for an issue` |
| two spec directories with value N | `ERROR: <t> matches more than one spec (<id1>, <id2>): give one of them a new number` |
| not an item | `ERROR: '<t>' is not an item: write #<N> or issue-<N> for an issue, spec-<N>, <NNN> or the spec id for a spec` |

Example of AC-175.3: `ERROR: 154 is both spec 154-<slug> and open issue #154: write spec-154 or #154`.

Public interface:

```python
# dispatch_state
class ItemRefused(PlatformError): ...                     # exit 2 in dispatch.main
def parse_form(text: str) -> tuple[str, int]:            # ("issue" | "spec" | "bare", N); raises ItemRefused for other text
def parse_item(text: str) -> str:                        # key of an explicit form; a bare number raises ItemRefused
# dispatch_items (imports dispatch_state and dispatch_backlog, never dispatch)
@dataclass
class Item:
    key: str        # issue-<N> | spec-<NNN>
    label: str      # "issue #<N>" | "spec <id>"
def resolve(repo: Path, slug: str, text: str) -> Item:   # raises ItemRefused
```

### Ship PR body (AC-175.4, AC-175.5)

`cplat component ship pr --title T --body-file F [--no-spec]`, order of `ship.open_pr`:

1. feature branch, body file exists, title rule (unchanged);
2. **fill** (new): when the staged body (`core.stage_pr_body`, i.e. `.git/PR_BODY.md`) contains `{{CLOSES}}`:
   - `tracks`: when the ship state's `spec` is set, `specmod.find(repo, st["spec"]).meta["tracks"]` as integers; a `PlatformError`
     or a non-integer track means the spec cannot be read and no filling happens. When `spec` is empty or missing, no tracks
     (commits only).
   - `kept = pr_open.closes_for(repo, base_ref, tracks=tracks)`, `base_ref` `origin/main` when it exists, else `main`;
     `filled = pr_open.fill_closes(body, kept)`.
   - a body without the placeholder is used as written (nothing read).
3. **check** (new): when the body still contains `{{CLOSES}}`, raise `BodyRefused`: exit 2, stderr
   `ERROR: PR body still contains {{CLOSES}}: <reason>` and `  fix: <hint>`, where `<reason>` is
   `the ship run's spec <spec> cannot be read: <first line of the error>` (or `filling left the placeholder` for any other cause) and
   the hint is `fix the spec (cplat spec check <spec>) or write the Closes lines into the body, then run cplat component ship pr again`.
   Nothing after this point runs: no `gh pr list`, no `devbox run ci`, no `git push`, no `gh pr create` or `gh pr edit`; the body file
   is not written.
4. the filled body is written to the staged body file; the spec rule (platform repo), `PR_BODY` of `devbox run ci` and
   `gh pr create --body-file` all see the filled text. A reused open PR keeps its body (retitle only, AC-126.12).
5. the rest unchanged (gitops tasks, empty-branch check, CI, push, create or edit).

```python
# pr_open
def closes_for(repo: Path, base_ref: str, *, issues: str = "", tracks: Iterable[int] = (),
               message: str | None = None, have_gh: bool = True) -> list[int]:
    """#N of `issues`, `tracks`, `#N` in `git log <base_ref>..HEAD --format=%B` and in `message`; kept when
    `gh issue view <n> --json state -q .state` prints OPEN (never when not have_gh); ascending, unique."""
def fill_closes(text: str, kept: list[int]) -> str:
    """`{{CLOSES}}` -> "Closes #a\nCloses #b" (one per line), or "N/A" when kept is empty."""
```

Both git and gh calls of `closes_for` go through `pr_open.run` (the seam the `cplat pr open` tests already replace). `ship.open_pr`
passes `have_gh=True` (it needs gh anyway). `pr_open._closes` becomes: spec tracks (a spec that cannot be read still contributes
nothing, as today) → `closes_for` → `fill_closes`.

Example of AC-175.4: tracks `[30, 12]`, commits with `Closes #44`, #30 and #44 open, #12 closed → the placeholder becomes
`Closes #30\nCloses #44`.
