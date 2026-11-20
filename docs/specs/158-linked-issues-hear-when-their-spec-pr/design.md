# Design — 158 Linked issues hear when their spec, PR and release land

## Decisions

- One module, `scripts/cplat/milestones.py`, renders and posts every milestone comment; the commands only call it at
  their milestone and add the lines it returns to their output. One place holds the marker, the dedup, the time limits
  and the error isolation (AC-158.6, AC-158.7), so no command can post differently.
- The comment step calls `gh` through its own seam `milestones.gh`, which runs `subprocess.run` with a timeout and
  **never** `core.run`: `core.run` waits up to 5 minutes for a dropped network and up to 65 minutes for a rate limit,
  which would break the 20 s / 120 s limits (AC-158.7). A failed call is not retried; the next run of the command posts
  what is missing (dedup by marker).
- `Changed` and `Why` of a merged PR (AC-158.3, AC-158.4) are **read from the PR body's spec 157 summary block**
  (`<!-- cplat:summary -->` … `<!-- /cplat:summary -->`, the `- **Changed:**` and `- **Why:**` bullets), not computed
  again. The comment then says exactly what the PR says, and this spec depends on 157's block format only, not on its
  code. A PR without the block (opened before 157, or by hand) gives `Changed` = the PR title and `Why` = `not recorded`.
- Closing references are parsed from the PR body with GitHub's closing keywords followed by a bare `#N`
  (`close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved`, case-insensitive, optional `:`). `owner/repo#N` and
  plain `#N` mentions never match, so issues of another repository and mentioned issues get nothing (AC-158.4, AC-158.6).
  Not `closingIssuesReferences`: it also lists issues linked by hand in the UI and other repos' issues.
- A changelog fragment `<id>-….md` links issue `#<id>` only when its text contains `#<id>` (README: the entry ends with
  `(#NNN).`). The fragment name may be a spec number (`docs/changelog.d/README.md`), and a spec number must not reach an
  unrelated issue or PR with the same number.
- The release's issue step is a `cplat component release issues --version vX.Y.Z` subcommand next to `target`, `wait`
  and `gates` (AC-158.5); `cplat platform release` calls the same function after the GitHub release exists. No new
  `cplat issue …` verb, because nouns mirror the slash commands of their plugin.
- `cplat spec land` runs `publish` first (as today), so a spec that was never published gets its `spec-written` comment
  before `spec-approved`; the markers keep a published one from getting it twice.
- Platform-owned issues (labels `auto-filed`, `notify`, `retro`) and pull requests are skipped silently (Non-goals,
  AC-158.6); they are not errors, so they get no `note:` line.
- ADR (AC-158.8): milestone comments on linked issues need no per-comment OK; created by plan task t6 with `cplat adr add`
  (the architect session had no shell), next to ADR-033.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/milestones.py` | gh seam, time budget, marker dedup, post; texts and entry points for spec-written, spec-approved, pr-merged | new |
| `scripts/cplat/milestones_release.py` | issues linked to a release, release texts, close, summary line | new |
| `scripts/cplat/comprelease.py` | `release issues` subcommand | changed |
| `scripts/cplat/spec_pr.py` | `publish` posts spec-written, `land` posts spec-approved after the merge | changed |
| `scripts/cplat/pr.py` | `wait` with `--merge` posts pr-merged after a merge or an already-merged PR | changed |
| `scripts/cplat/ship.py` | `_merged` (merge and resumed already-merged) and merged gitops-task PRs post pr-merged | changed |
| `scripts/cplat/appship_merge.py` | `land` (system ship's gitops PR) posts pr-merged | changed |
| `scripts/cplat/platrelease_publish.py` | posts released + closes after the GitHub release, before the guard | changed |
| `tests/cplat/conftest.py` | autouse fixture: `milestones.gh` never reaches GitHub in tests | changed |

## Contract

### Python interface (`milestones.py`)

```python
ISSUE_LIMIT_S = 20.0        # read + post (+ close) of one issue (AC-158.7)
STEP_LIMIT_S = 120.0        # all milestone work of one command process (AC-158.7)
SKIP_LABELS = {"auto-filed", "notify", "retro"}

def gh(args: list[str], *, cwd: Path, timeout: float) -> tuple[int, str, str]:   # tests replace this
    """subprocess.run(["gh", *args], timeout=timeout); (rc, stdout, stderr); a timeout -> (124, "", "timed out after <t>s");
    gh missing -> (127, "", "gh not installed"). Never raises, never retries."""

def clock() -> float:       # tests replace this; time.monotonic()
def reset() -> None:        # forget the process's step budget (tests)

def spec_written(root: Path, spec: spec.Spec, branch: str, pr_url: str) -> list[str]
def spec_approved(root: Path, spec: spec.Spec) -> list[str]
def pr_merged(repo: Path, pr: str) -> list[str]           # pr: number or URL
def post(repo: Path, slug: str, issues: list[int], milestone: str, key: str, body: str,
         *, close: bool = False) -> tuple[list[str], dict[int, str]]
```

Every entry point **never raises** (it catches `Exception` per issue and around its own reads) and returns the output
lines to append to the command's own output, in issue order:

- `issue #<N>: <milestone> comment posted` for each comment posted;
- `note: issue comment skipped: #<N> <milestone>: <why>` for each issue whose comment (or close) failed or was cut by a
  time limit (AC-158.7); `<why>` is the first line of gh's stderr (cut to 200), `timed out after 20s`, or
  `comment step time limit (120s) reached`;
- nothing for an issue that already has the marker, a pull request, or a skipped-label issue.

`post`'s second value maps each handled issue to `posted|present|skipped|ignored` (used by the release summary).

The step budget is the time spent in gh calls, shared by every entry point the process calls (`spec land` = written +
approved within one 120 s of commenting; the CI wait between them does not count, found in verification). Each gh call gets
`timeout = min(issue deadline, step time left)`; a call with no time left is not started.

### gh calls per issue (in order; a test fake answers these)

1. `gh api repos/<slug>/issues/<N>` → JSON `{state, locked, labels[{name}], pull_request?}`. `pull_request` present or a
   label in `SKIP_LABELS` → ignored.
2. `gh api --paginate repos/<slug>/issues/<N>/comments --jq .[].body` → marker present → `present`.
3. `gh api -X POST repos/<slug>/issues/<N>/comments -f body=<text>` → `posted`.
4. release only, when step 1 said `state: open`: `gh issue close <N> -R <slug> --reason completed` (also when the comment
   was `present`, so a re-run closes what an earlier run could not).

Other reads (each also limited by `ISSUE_LIMIT_S` and the step budget):
- slug and default branch for spec milestones: `gh repo view --json nameWithOwner,defaultBranchRef`;
- the merged PR: `gh pr view <pr> --json number,url,title,body` (slug from the returned `url`);
- release: `gh pr list -R <slug> --state merged --base <default> --limit 300 --search "merged:>=<prev tag date>" --json number,title,body,url,mergeCommit`.

### Marker (AC-158.6)

The last line of every comment, exactly: `<!-- cplat:milestone <milestone> <key> -->` with
`spec-written <spec id>`, `spec-approved <spec id>`, `pr-merged <PR number>`, `released v<X.Y.Z>`. `<spec id>` is the
full folder name (`158-linked-issues-hear-when-their-spec-pr`). Dedup is a substring match of that line in any comment.

### Linked issues

| Milestone | Issues |
|---|---|
| spec-written, spec-approved | `tracks:` of the spec: ints and `"#N"` strings; anything with `/` (another repo) is dropped |
| pr-merged | closing references in the PR body (keyword + bare `#N`) |
| released | union of the closing references of the PRs whose `mergeCommit.oid` is in `git rev-list <prev>..<tag>` (`<tag>` alone without a previous tag), and, when the repo has `docs/changelog.d/`, fragments `<N>-*.md` at `<tag>` or `<tag>^` whose text contains `#<N>` |

Numbers are unique and ascending. `<prev>` is `--previous` or `git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' <tag>^`.

### Texts (all lines from records or fixed text; `<…>` filled, everything else verbatim)

Common rules: a value has newlines collapsed to spaces and Markdown emphasis (`**`, `__`, `*`, `_`, `` ` ``) kept as
written, except where noted. The planned solution is the spec's first story: the first paragraph of `## Stories`
starting with `As `, up to (excluding) `**Repos:**`, whitespace collapsed, cut to 400 characters with a final `…` (AC-158.1).
`<n>` = `len(spec.active_acs())`. Open questions = `spec.open_questions()` (unstruck).

**spec-written** (AC-158.1)

```
Spec <NNN> for this issue is written: [<spec id>](https://github.com/<slug>/blob/<branch>/docs/specs/<spec id>/spec.md), spec PR <pr url>.

Planned solution: <first story> It has <n> acceptance criteria.

Open questions you can answer here:
- <question 1>
… (at most 5)
- … and <k> more

<!-- cplat:milestone spec-written <spec id> -->
```

Without open questions the block from `Open questions you can answer here:` to the last question is the line
`No open questions.` `<NNN>` = `spec.number`.

**spec-approved** (AC-158.2)

```
Spec <NNN> approved on <YYYY-MM-DD>: [<spec id>](https://github.com/<slug>/blob/<default branch>/docs/specs/<spec id>/spec.md).

Planned solution: <first story> It has <n> acceptance criteria.

Next: the build; you will hear here when its PR merges.

<!-- cplat:milestone spec-approved <spec id> -->
```

`<YYYY-MM-DD>` = the date of the last `- <date> approved` line in the spec's `## Changelog`, else today (UTC).

**pr-merged** (AC-158.3)

```
Merged: <pr url>

- **Changed:** <Changed>
- **Why:** <Why>

Ships with the next release; you will hear here when it does.

<!-- cplat:milestone pr-merged <PR number> -->
```

`<Changed>`/`<Why>`: the text after `- **Changed:**` / `- **Why:**` inside the PR body's summary block; without a block,
the PR title / `not recorded`. Posted whether the issue is open or closed.

**released** (AC-158.4)

```
Fixed in v<X.Y.Z>.

Shipped: <what>

Get it: <how>

<!-- cplat:milestone released v<X.Y.Z> -->
```

- `<what>`: the release's changelog entry that names `#<N>` (first, below), else the `Changed` of its closing PR (from the
  summary block), else that PR's title; at most 300 characters (cut with `…`).
- Changelog entry: the section of `docs/CHANGELOG.md`, else `CHANGELOG.md`, at `origin/main` (after `git fetch origin main`;
  for a component the Phase 6 follow-up has merged it) whose `## ` heading contains `X.Y.Z`; its first bullet or paragraph
  containing `#<N>` (not `#<N><digit>`); the text is its leading bold sentence when it starts with `**…**`, else its first
  sentence, with Markdown emphasis removed.
- `<how>`: platform repo (shape `platform`): ``run `/plugin marketplace update`, then `/platform:update`.``; any other
  repo: `https://github.com/<slug>/releases/tag/v<X.Y.Z>`.
- After the comment step, an issue that was `open` is closed `--reason completed`; a closed one is left alone.

### `cplat component release issues` (AC-158.5)

```
cplat component release issues --version vX.Y.Z [--previous vA.B.C] [--repo DIR] [--json]
```

Prints the `issue …` and `note: …` lines, then one summary line:

- `## Phase 7 complete — issues closed: #42, #7 (<c> closed, <a> already closed)`: the list names every linked issue
  that was not ignored, ascending; `<c>` = closed by this run, `<a>` = already closed before it; `, <s> skipped` is added
  when any issue has a `note:` line;
- `## Phase 7 complete — no linked issues found` when none.

`--json`: `{"version", "issues": [{"number", "comment": "posted|present|skipped", "closed": "now|before|failed|no"}], "notes": [...], "summary": "<line>"}`.
Exit 0 always, also with notes (AC-158.7); exit 2 only for bad arguments (unknown tag: `ERROR: tag vX.Y.Z not found`).

`cplat platform release` prints the same lines after `release: <url>`, with the summary prefixed `release issues — `
instead of `## Phase 7 complete — `; a `note:` line there adds `  post the missing ones: cplat component release issues --version vX.Y.Z`.

### Command outputs that change

- `cplat spec publish`: text mode prints the comment lines after the URL line; `--json` adds `"issue_comments": [lines]`.
- `cplat spec land`, `cplat pr wait --merge`, `cplat component ship land`, `cplat system ship` land: the comment lines are
  appended to the lines they print today, only after a merge or an already-merged PR. Exit codes never change.

## Data

No stored state: the marker in the issue's comments is the record (A7).
