# Design — 157 Build and ship PRs start with a short summary

## Decisions

- **One module renders the block for every PR `cplat` opens.** `scripts/cplat/pr_summary.py` holds the whole contract below; `pr open`
  (`pr_open.py`), the component ship (`ship.open_pr`) and the system ship (`appship.open_pr`, `appship.entry_pr`) only call
  `pr_summary.add(...)`. So the summary reads the same in every repo and spec 158 can reuse the same facts (AC-157.1, AC-157.6).
- **No new ADR.** ADR-079 already decides that `cplat` writes PR text from records only, redacted, bounded, between markers, and never
  blocks a PR. The summary follows its decisions 1, 2, 4 and 5 unchanged. Spec 157 widens where it applies (every PR `cplat` opens),
  not how it works.
- **`runs_built.py` is not changed.** The summary imports `runs_built.find`, `runs_built.accepted_deviations`, `runs_built._section`,
  `runs_built._events`, `runs_built._same_spec` and `runs_built._spec_dir`, so the "How this was built" block keeps its content
  byte for byte (non-goal).
- **`ship._built_block` is not changed.** In a component ship, including the one a `/system:ship` starts, the "How this was built" block
  is still added only when the run recorded `approved_test_diffs` (spec 200). Spec 157 adds no other path that writes it (AC-157.6).
- **The summary is placed after every other body change.** In `pr open` that means after `{{CLOSES}}`, the WIP note and the
  how-built block. In the ship it means after `_fill_closes` and before `_built_block`. The `Closes #N` lines are then final, which
  `Why` needs, and the body `run_ci` and `gh pr edit` see already holds the block.
- **"Fixed in fix rounds" is defined from records only.** A reviewer finding of severity `not met` or `partial` counts as fixed when
  the run recorded at least one `fix-round` event and that criterion's verdict in the current `verification.md` table is `met`. The
  run records no direct link from a finding to the round that fixed it. A finding's criterion that now reads `met` after a recorded
  fix round is the closest fact the records hold (AC-157.4).
- **Closing references come from the body as sent.** These are the `Closes|Fixes|Resolves #N` lines (`pr_rules.CLOSES`), outside an
  earlier summary block. Every caller has already resolved them, and they are exactly what GitHub will close (AC-157.3).
- **Existing PRs in the system ship are not edited.** `appship.open_pr` and `entry_pr` reuse an open PR as they do today. The block
  goes into the body of each PR they create. The component ship already edits an existing PR's body when the body changed, so it
  updates the block there.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/pr_summary.py` | facts from spec, fragment, git, run record, `verification.md`; render; place at the top | new |
| `scripts/cplat/pr_open.py` | `_summary(...)` after `_how_built`; note line on failure | changed |
| `scripts/cplat/ship.py` | `_summary(...)` in `open_pr`, before `_built_block` | changed |
| `scripts/cplat/appship.py` | `open_pr(..., spec=...)` and `entry_pr` add the block to new PRs | changed |
| `scripts/cplat/appship_joint.py` | passes `spec=spec_id` to `appship.open_pr` (dev and staging PRs) | changed |

## Contract

### Python interface (`scripts/cplat/pr_summary.py`)

```python
START = "<!-- cplat:summary -->"
END = "<!-- /cplat:summary -->"
MAX_LINE = 300          # characters per rendered line, the bullet prefix included
MAX_ITEMS = 3           # closing references in Why, items in Risks and follow-ups

def render(repo: Path, *, body: str, title: str, spec: str | None, base: str) -> str
    """The block (START … END, ending in "\n"). Raises on any failure."""
def apply(body: str, block: str) -> str
    """Remove every earlier START…END block (with the newlines after it); return block + "\n" + rest.lstrip("\n")."""
def add(repo: Path, body: str, *, title: str, spec: str | None, base: str) -> tuple[str, str | None]
    """(apply(body, render(...)), None); on any exception (body unchanged, "note: summary skipped: <Type>: <message>")."""
```

`base` is the ref that `files` are counted against (`origin/<base>` when it exists, else `<base>`). The callers already compute it.

### Rendered block (AC-157.1)

```
<!-- cplat:summary -->
**Summary**
- **Changed:** <changed>
- **Why:** <why>
- **Review:** <review>
- **Risks and follow-ups:** <risks>
<!-- /cplat:summary -->

<the body as it was, leading blank lines removed>
```

There is one blank line between `END` and the old body. With an empty old body the result is the block alone. An earlier block
anywhere in the body is removed, and a duplicate is removed too, so the result holds exactly one. The "How this was built" block
stays where it was, at the end.

### Values

| Line | Rendering | AC |
|---|---|---|
| `Changed` | `text` + ` (<n> criteria of spec <NNN>, <m> files)` with a spec, else ` (<m> files)` | 157.2 |
| `Why` | the first story's `so that` clause, else closing references, else `not recorded` | 157.3 |
| `Review` | `verification <state>; <f> reviewer findings (<sev>), <x> fixed in fix rounds, <d> accepted as deviations`; without a run `verification <state>; findings not recorded` | 157.4 |
| `Risks and follow-ups` | up to 3 items joined by `; `, then `; … and <n> more`; none → `none recorded` | 157.4 |

- **Spec:** with `spec` given, `spec.find(repo, spec)`. When it cannot be found, `render` raises, so the block is skipped. It never
  falls back to the PR title while a spec is given (AC-157.2). The spec directory is that spec's directory. Without `spec` there is
  no spec directory.
- **text (Changed):**
  1. The spec's `title` front matter.
  2. Else the branch's changelog fragment's first sentence. The fragment is the first path, sorted, under `docs/changelog.d/`
     (not `README.md`, only `*.md`) among the files of the branch (see `m`). It counts only when the folder exists in `repo`. Its
     text has `**`, `__` and single `*`/`_` emphasis markers removed.
  3. Else `title`.
- **n:** `len(spec.active_acs())`. **NNN:** the leading digits of the spec id, else the id.
- **m:** `len(set(git diff --name-only <base>...HEAD) | set(paths of git status --porcelain))`. These are the branch's files plus
  those `pr open` is about to commit. There are no singular forms (`1 files`, `1 criteria`).
- **First sentence:** whitespace collapsed to single spaces. The sentence runs up to and including the first `.`, `!` or `?` that is
  followed by whitespace or the end, else the whole text.
- **so that clause (Why):** the first paragraph (lines up to the first blank line) under `## Stories`, whitespace collapsed. From the
  first `so that` to the end of that sentence, as in "first sentence", terminator included. The `## Problem` section is never read.
- **Closing references (Why):** the numbers of the body's lines matching `pr_rules.CLOSES`, in order of appearance and unique, with
  an earlier summary block removed first. Each renders as `Closes #<N>: <issue title>`. The title comes from
  `gh issue view <N> --json title -q .title` in `repo`. When that fails or prints nothing, it renders as `Closes #<N>`. At most 3 are
  joined by `; `, then `; … and <n> more`.
- **Run:** `rec = runs_built.find(runs.current_run(repo))`. It is used when `rec` is not None and `runs_built._same_spec(rec["spec"],
  spec)`. Otherwise there is no run.
- **state:** `pass` or `fail` from the first line matching `^\*\*Result:\*\*\s*(pass|fail)\b` (case-insensitive) in the spec
  directory's `verification.md`. It is `not yet` when there is no spec directory, no file or no such line.
- **f, sev:** the `finding` events of `rec` (`runs_built._events(rec)`), counted by `severity`. `sev` lists the non-zero counts as
  `<k> <severity>`, joined by `, `, in the order `not met`, `partial`, `deviation`, then any other severity alphabetically. With
  `f == 0`, `sev` is `none`, as in `0 reviewer findings (none)`.
- **x:** findings of severity `not met` or `partial` whose `criterion` reads `met` in `spec._verdicts(spec)`. It counts only when
  `rec` holds at least one `fix-round` event, else it is `0`.
- **d:** `len(runs_built.accepted_deviations(spec_dir) or [])`.
- **Risks items:** first the accepted deviations (`runs_built.accepted_deviations`, already first sentences), then the first sentence
  of each top-level item (`-`, `*` or `1.`) of `## Follow-ups` in `verification.md`. An item's continuation lines are joined and its
  `**` removed. An item reading `none` or `n/a` (case-insensitive, trailing `.` ignored) is skipped.

### Every value (AC-157.5)

- Every value from a record, file, git or `gh` goes through `feedback.redact`, then whitespace is collapsed to one line and every
  `<!--` and `-->` is removed, so no value can close the block.
- No prompt, diff or agent-written text is read. The sources are only the ones in the table above.
- A rendered line longer than `MAX_LINE` becomes `line[:MAX_LINE - 1] + "…"`.
- The `<why>` of a failure is `<ExceptionType>: <first line of the message>`. The whole note line is at most 200 characters.

### Callers

- **`pr_open.open_pr`:** right after `_how_built(...)`, it calls `pr_summary.add(repo, body_path.read_text(), title=o.title, spec=o.spec,
  base=base_ref)`. It writes the file when the body changed and appends the note to `res.notes`. The exit code is unchanged.
- **`ship.open_pr`:** after `original_body = body`, it calls `body = _summary(repo, st, title, body, body_file)` with the base
  `origin/main`, else `main`, and `spec=st["spec"]`. It writes `body_file` when changed and prints the note with `say`. Then comes
  `_built_block(...)` as today. Because `body != original_body`, an existing PR gets `gh pr edit --body-file`.
- **`appship.open_pr(repo, branch, title, body, *, spec: str)`:** for a new PR only, it sends `add(repo, body, title=<fitted title>,
  spec=spec, base="origin/main")[0]` as `--body` and prints the note. Callers pass the system spec: `publish` and `complete` pass
  `sid`, and `appship_joint` passes `spec_id` for the dev PR and the staging PR.
- **`appship.entry_pr`:** for a new PR, it takes the body from `--body-file` or from `entry_body(...)`, adds the block with `repo=wt`,
  `spec=st["spec"]` and `base="origin/main"`, and sends it with `--body`. It writes no file, because a headless session may not write
  outside the worktree.

### Output

| Case | Output |
|---|---|
| block built | unchanged output (`pr open`: `commit:`, `push:`, `pr:` lines) |
| block failed | one extra line `note: summary skipped: <why>`; body byte-for-byte unchanged; same exit code |
