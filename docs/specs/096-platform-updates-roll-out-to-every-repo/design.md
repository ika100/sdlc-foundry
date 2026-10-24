# Design — 096 Platform updates roll out to every repo

## Decisions

- **The update is `update.resolve` + `update.execute`, called in-process on a fresh clone.** Fleet never re-implements
  a template step. It clones the repo into a temp dir, checks out the update branch, and calls
  `update.resolve(["--repo", <clone>] + (["--ref", ref] if ref else []))` and then `update.execute(req)`. The commit,
  the project-owned and repo-owned rules, the `lost` list (spec 086) and the follow-up steps are therefore exactly
  those of `/shared:update-service` (AC-096.3). Fleet creates the branch itself, so `execute` always commits on the
  current branch, also for a default branch that is not `main`/`master`. The name is the head of an existing fleet PR,
  else `update.branch_name`'s scheme (`chore/platform-update-YYYYMMDD`, then `-2`, `-3`, …) skipping every name that
  exists locally *or* as `origin/<name>` (a fresh clone has only one local branch, so `update.branch_name(clone)` alone
  would collide with a branch left on GitHub). The clone lives in a `tempfile.TemporaryDirectory` that is removed
  when the repo is finished, whatever its outcome.
- **The target is the installed platform version.** `update` renders from `PLATFORM_ROOT` and stamps
  `core.platform_version()`, so that is the only version fleet can honestly apply. `--ref <tag>` (`vX.Y.Z` or
  `X.Y.Z`) is a check, not a switch: when it differs from the installed version, fleet stops before touching any repo
  with `PlatformError("--ref v5.0.0 is not the platform this command runs (4.5.0)", hint="run it as CPLAT_REF=v5.0.0
  cplat fleet update --ref v5.0.0")`; the launcher's `CPLAT_REF` (plugins/shared/bin/cplat) then runs the platform at
  that tag. The same check applies to `--dry-run`. A `--ref` that is not `[v]X.Y.Z` is a `PlatformError` too. With a
  matching `--ref`, the ref is passed on to `update` (it ends up in the stamp's `ref:` line, as with
  `/shared:update-service --ref`). `/shared:fleet` prefixes the call with `CPLAT_REF=<tag>` when `--ref` is given,
  exactly as `/shared:update-service` does.
- **Merge only what is routine (AC-096.15/16, 7, 6).** In this order, for a repo whose update produced a commit:
  1. `lost` non-empty → `local customisation`; a major version change → `major version <M> → <N>`. Either one leaves
     the PR open *without* waiting for CI (nobody merges it automatically, so waiting buys nothing).
  2. `mergeable == CONFLICTING` → `merge conflict`.
  3. Otherwise `pr.wait(clone, url, merge=True, ...)`, the exact `cplat pr wait --merge` (stale, stuck and transient
     reruns of specs 072/079, no merge without checks). Green and merged → `merged`. Its outcomes map to reasons as in
     the contract.
- **An existing open fleet PR is rebuilt, not stacked (AC-096.8).** The update is re-run from the default branch's
  tip on a local branch named like the PR's head and force-pushed with a lease on the head's current sha. The PR then
  holds exactly one update commit against the current default branch, like a fresh one. If
  `git log --no-merges --format=%s origin/<default>..origin/<head>` lists a subject that does not start with
  `chore: update skeleton from platform `, a person worked on it: fleet does not push and leaves it open
  (`manual commits on <branch>`). Merge commits (GitHub's "Update branch") do not count. If the rebuilt tree equals
  the head's tree, nothing is pushed (no CI re-trigger).
- **One seam for GitHub, one for cloning.** Every `gh` call of fleet goes through `fleet.gh`, the clone through
  `fleet.clone`, waiting through `fleet.sleep`; merging goes through `pr.wait`. Git operations on the clone (branch,
  commit, push) are plain local `git` against `origin`, so tests clone from a local bare repo and push back into it.
  No test reaches GitHub.
- **Progress on stderr, result on stdout.** Each repo is processed inside `contextlib.redirect_stdout(sys.stderr)`, so
  the progress lines of `update` and `pr.wait` (`ship.say` prints to stdout) never mix into the table or the
  `--json` document.
- **The fleet run records itself; nested `pr wait` runs record separately.** `pr.wait` finds no ship run in the clone,
  so it records its own `pr-wait` run, as today. Fleet does not set `CPLAT_RUN_PARENT` (that would list the waits as
  `ships`). The fleet record carries each repo's PR URL, which links the two. A dry run records nothing (it changes
  nothing, like `cplat headless --dry-run`).
- No ADR: the merge policy is this spec's, and the command reuses existing patterns (Report-free table output,
  `pr wait`, the run store).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/fleet.py` | CLI, seams (`gh`, `clone`, `sleep`, `say`), target check, discovery, per-repo loop (order, failures, dry run), table / JSON report, exit code, run record | new |
| `scripts/cplat/fleet_pr.py` | one behind repo: branch, `update.execute`, push, open or update the PR (title, body), routine check, label + comment, `pr.wait --merge`, outcome | new |
| `scripts/cplat/cplat.py` | `"fleet": "fleet"` in `COMMANDS`, one usage line | changed |
| `plugins/shared/commands/fleet.md` | `/shared:fleet`: runs `cplat fleet update <ARGS>`, relays the output | new |
| `plugins/shared/README.md`, `docs/CHANGELOG.md` | command row; `[Unreleased]` bullet | changed |

## Contract

### CLI

```
cplat fleet update [--owner OWNER]... [--only OWNER/NAME]... [--ref TAG] [--timeout SECONDS] [--dry-run] [--json]
```

| Option | Meaning |
|---|---|
| `--owner` | repeatable; default: the login of `gh api user -q .login`. No login → `PlatformError("gh is not logged in", hint="gh auth login")`. |
| `--only` | repeatable `owner/name`; processes exactly these repos and ignores `--owner` (AC-096.13). A value that is not `owner/name` → `PlatformError` before anything runs. |
| `--ref` | see Decisions: must equal the installed version (`v` prefix optional). |
| `--timeout` | CI wait per PR in seconds, passed to `pr.wait` (default 3600). There is no overall limit (AC-096.17). |
| `--dry-run` | read-only: no clone, no push, no PR action, no run record (AC-096.10). |
| `--json` | stdout is exactly the JSON document below and nothing else. |

`cplat fleet` with any other subcommand is an argparse error (exit 2). Argument, `--ref` and discovery errors are
`PlatformError`s (cplat prints `ERROR:`/`fix:`, exit 1) and happen before any repo is touched.

### Seams — `scripts/cplat/fleet.py`

```python
def gh(args: list[str], *, cwd: Path | None = None, input: str | None = None, timeout: float = 60.0) -> tuple[int, str, str]:
    """subprocess `gh <args>` -> (exit code, stdout, stderr). Never raises: a missing gh is (127, "", "gh is not installed"),
    a timeout (124, "", "timeout"). Tests replace this."""
def clone(slug: str, dest: Path) -> None:
    """`gh repo clone <slug> <dest> -- --quiet` through gh(); non-zero -> PlatformError(f"clone of {slug} failed: <first stderr line>").
    Tests replace this with a `git clone <bare repo> <dest>`."""
def sleep(seconds: float) -> None: ...     # tests replace this
def say(line: str) -> None: ...            # one progress line on stderr
```

`fleet_pr` gets these through `Ctx` (below), bound as `lambda *a, **k: gh(*a, **k)` so a monkeypatched `fleet.gh` is
used.

### gh calls (exact arguments; tests fake `fleet.gh` by matching them)

| Purpose | Call | Result handling |
|---|---|---|
| login | `["api", "user", "-q", ".login"]` | stdout stripped |
| list an owner | `["repo", "list", OWNER, "--no-archived", "--source", "--json", "nameWithOwner,isArchived,isFork,defaultBranchRef", "--limit", "1000"]` | JSON list; entries with `isArchived` or `isFork` true are dropped. Non-zero → `PlatformError(f"cannot list repos of {OWNER}: <first stderr line>")` |
| one `--only` repo | `["repo", "view", SLUG, "--json", "nameWithOwner,isArchived,isFork,defaultBranchRef"]` | non-zero → row `failed: cannot read <slug>: <line>`; archived → `skipped: archived`; fork → `skipped: fork` |
| read a file | `["api", f"repos/{SLUG}/contents/{PATH}", "-H", "Accept: application/vnd.github.raw"]` (PATH `.platform-version`, `.copier-answers.yml`) | rc 0 → text. Non-zero with `404` or `Not Found` in stderr → missing. Other non-zero → row `failed: cannot read <path>: <line>` |
| open fleet PRs | `["pr", "list", "-R", SLUG, "--state", "open", "--json", "number,url,headRefName,labels", "--limit", "100"]` | entries whose `headRefName` starts with `chore/platform-update-`; the highest `number` is the fleet PR |
| create PR | `["pr", "create", "-R", SLUG, "--base", DEFAULT, "--head", BRANCH, "--title", TITLE, "--body-file", "-"]`, body on `input` | last stdout line is the URL |
| update PR | `["pr", "edit", URL, "-R", SLUG, "--title", TITLE, "--body-file", "-"]`, body on `input` | labels untouched (AC-096.8) |
| mergeable | `["pr", "view", URL, "-R", SLUG, "--json", "mergeable"]` | `MERGEABLE` \| `CONFLICTING` \| `UNKNOWN`; `UNKNOWN` is re-read up to 10 times, `fleet.sleep(3)` apart, then treated as not conflicting |
| label | `["label", "create", "platform-update: needs review", "-R", SLUG, "--color", "D93F0B", "--description", "A platform fleet update needs a person (spec 096)"]` | non-zero is ignored (the label exists) |
| add label | `["pr", "edit", URL, "-R", SLUG, "--add-label", "platform-update: needs review"]` | |
| comments | `["pr", "view", URL, "-R", SLUG, "--json", "comments"]` | the new comment is not posted when the last comment containing the marker has the same body (re-runs do not spam) |
| comment | `["pr", "comment", URL, "-R", SLUG, "--body-file", "-"]`, body on `input` | |

A failing `create`, `edit`, `label`, `comment` call ends that repo as `failed: <step>: <first stderr line>`.

### Discovery (AC-096.1, .13)

A repo is a platform repo when both files exist on its default branch and the `_src_path:` line of
`.copier-answers.yml` (quotes and trailing `/` stripped) ends in `templates/<t>` where `<t>` is a `template` of
`core.registry.load()` (the rule of `scripts/detect-shape.sh`). Without `--only`, non-platform repos are left out of
the report entirely. With `--only`, they get the row `skipped: not a platform repo`. Repos of several owners are
deduplicated and processed in `sorted(..., key=str.lower)` order of `owner/name`, one at a time, each to its end
(including its CI wait) before the next starts (AC-096.17).

The stamp version is the `^platform:\s*(\d+\.\d+\.\d+)` match of `.platform-version`; no match → `from` is `none`.

### Per-repo outcome

| Situation | outcome | reason | Notes |
|---|---|---|---|
| stamp ≥ target (`core.vtuple`) | `up to date` | – | no clone, no branch, no PR (AC-096.2) |
| update produced no commit (`Report.data` empty) | `up to date` | – | |
| dry run, behind | `would update` | – | `next` gets `would update open PR <url>` when one exists, and `major version: the PR will stay open` for a major change |
| routine, CI green, squash-merged | `merged` | – | |
| `lost` non-empty | `left open` | `local customisation` | comment names each entry (AC-096.16) |
| major `M` → `N` (`vtuple(from)[0] < vtuple(target)[0]`, or `from` is `none`) | `left open` | `major version M → N` (`unknown → N` for `none`) | comment points to the CHANGELOG (AC-096.7) |
| both of the above | `left open` | `local customisation; major version M → N` | one comment with both sections |
| `CONFLICTING` before the wait, or the merge fails and `mergeable` is then `CONFLICTING` | `left open` | `merge conflict` | |
| `pr.wait` returns `(False, lines)` | `left open` | `red CI: <names>` | names = the text after `on <url>: ` in `lines[0]` (`RED: n of m check(s) failed on <url>: a, b`, from `ship.red`) |
| `pr.wait` raises `PlatformError` starting `no CI checks` | `left open` | `no CI checks` | |
| `pr.wait` raises `PlatformError` containing `still pending` | `left open` | `CI still pending after <timeout>s` | |
| `pr.wait` raises `PlatformError` starting `merging ` (merge rejected) | `left open` | `merge failed: <first line>` | |
| `pr.wait` raises another `PlatformError` (PR closed, a `gh` call failed) | `left open` | `CI wait failed: <first line>` | |
| existing fleet PR has manual commits | `left open` | `manual commits on <branch>` | nothing pushed |
| any exception before the PR exists, or a failing PR call | `failed` | first line of `str(e)` (else the exception's class name) | the loop continues (AC-096.9) |
| a non-`PlatformError` exception after the PR exists | `failed` | as above | the row keeps the PR link |

Every `left open` repo gets the label (created when missing) and the comment. `next` (AC-096.14) is
`Report.next_steps` of the update minus the steps fleet did itself: those starting with `run the repo's checks:` and
`platform changes since your version`. It is relayed whatever the outcome.

### PR title, body and comment

Title: `chore: platform update <from> → <target>`.

Body (AC-096.3), Markdown, at most 60 000 characters (the changelog section is cut first, ending in
`… (cut; see docs/CHANGELOG.md of sdlc-foundry)`):

```
<!-- cplat-fleet -->
Platform update **<from> → <target>** by `cplat fleet update` (spec 096); the same commit `/shared:update-service` makes.

### Changed files (<n>)
- `<path>`                                   (data.changed)
### devbox.json
- kept: <entry>; …                            (data.devbox.kept, or "none")
- replaced by the template: `<entry>` (was `<was>`); …   (data.devbox.replaced, or "none")
- moved to ci-extra: …                        (only when non-empty)
- dropped gates: …                            (only when non-empty)
### Overwritten customisations (spec 086)
- `<file>`[ `<entry>`]: <where>               (data.lost, or "none")
[No baseline for <from>: every difference counts as overwritten.]   (when data.baseline is null)
### Follow-up steps
- <step>                                      (next, or "none")
### Platform changes <from> → <target>
<data.changelog, or "none recorded">
```

Comment (only for `left open`):

```
<!-- cplat-fleet -->
**The platform fleet update left this PR open:** <reason>

<one section per reason>
Review and merge it by hand, or run `cplat fleet update --only <slug>` again after a fix.
```

Sections: `local customisation` → `This update overwrote what the repo added (spec 086):` and one
`- \`<file>\`[ \`<entry>\`]: <where>` per `lost` entry. Major → `Major platform update <from> → <target> is never
merged automatically. Read the migration notes for <K>.0.0 in https://github.com/ika100/sdlc-foundry/blob/v<target>/docs/CHANGELOG.md`
(one line per major `K` with `M < K ≤ N`). Other reasons → the reason line alone.

### `fleet_pr.py`

```python
LABEL = "platform-update: needs review"
MARKER = "<!-- cplat-fleet -->"
BRANCH_PREFIX = "chore/platform-update-"
UPDATE_SUBJECT = "chore: update skeleton from platform "

@dataclass
class Ctx:
    slug: str
    clone: Path                 # fresh clone, default branch checked out, clean
    default_branch: str
    gh: Callable[..., tuple[int, str, str]]
    sleep: Callable[[float], None]
    timeout: float              # CI wait per PR

@dataclass
class Result:
    outcome: str                # "up to date" | "merged" | "left open" | "failed"
    reason: str | None
    pr: str | None              # PR URL
    next: list[str]

def open_fleet_pr(ctx: Ctx) -> dict | None: ...                 # {"number", "url", "headRefName", "labels"} or None
def new_branch(ctx: Ctx) -> str: ...                            # branch_name's scheme, free locally and on origin
def update(ctx: Ctx, old: str | None, target: str, ref: str | None) -> Result:
    """Branch, update.resolve/execute, push, open or edit the PR, decide, label/comment or pr.wait(merge=True).
    Raises only for failures before the PR exists (the caller turns them into `failed`)."""
def follow_ups(report: core.Report) -> list[str]: ...
def pr_body(old: str | None, target: str, data: dict, next_steps: list[str]) -> str: ...
def pre_wait_reasons(old: str | None, target: str, data: dict) -> list[str]: ...   # [] | ["local customisation", "major version M → N"]
def comment_body(slug: str, old: str | None, target: str, reasons: list[str], lost: list[dict]) -> str: ...
```

`pr.wait` is called as `pr.wait(ctx.clone, url, True, ctx.timeout, 20, ship.QUEUE_TIMEOUT, ctx.slug)` (module
attribute, so tests replace `pr.wait`; its merge step calls `gh` directly, so no test runs the real one).

### Report

Text (stdout):

```
Fleet update to platform <target> (owners: <a>, <b> | only: <x>, <y>)[ — dry run, nothing was changed]

  repo             from   to     outcome                        PR
  ika100/todo      4.3.0  4.5.0  merged                         https://github.com/ika100/todo/pull/12
      next: <step>
  ika100/todo-api  4.5.0  -      up to date                     -

<n> repo(s): <outcome> <count>, …
```

Columns are left-aligned to the widest cell. `to` is the target for repos that were (or would be) updated, else `-`.
`outcome` prints `<outcome>` or `<outcome>: <reason>`. Counts list only non-zero outcomes in the order `up to date`,
`would update`, `merged`, `left open`, `failed`, `skipped`. No repos → the line `no platform repos found` instead of
the table.

JSON (`--json`, stdout):

```json
{"target": "4.5.0", "ref": null, "owners": ["ika100"], "only": [], "dry_run": false,
 "repos": [{"repo": "ika100/todo", "from": "4.3.0", "to": "4.5.0", "outcome": "merged", "reason": null,
            "pr": "https://github.com/ika100/todo/pull/12", "next": []}],
 "counts": {"merged": 1}, "exit": 0}
```

Exit (AC-096.11): `1` when any repo is `left open` or `failed`, else `0` (`skipped` and `would update` do not fail).

### Run record (AC-096.12)

Not for `--dry-run`. After the arguments and the `--ref` check: `rid = runs.start("fleet", repo=None)`. After each
repo: `runs.event(rid, "repos", slug, {"from", "to", "outcome", "reason", "pr"})`. At the end:
`runs.set_section(rid, "fleet", {"target", "ref", "owners", "only", "counts"})`, then
`runs.finish(rid, outcome, escalation=...)` with outcome `failed` when any repo failed, else `escalated` with
`{"reason": "<n> repo(s) left open for review", "cause": "unknown"}` when any is left open, else `done`. A
`PlatformError` from discovery → `finish(rid, "failed")` and re-raise. All `runs` calls are the no-throw API of spec
087, so an unreachable store changes neither the report nor the exit code (at most `finish`'s one stderr line).

## Risks

- **Long runs in a Claude session:** one PR's CI wait can exceed a Bash call's limit. `/shared:fleet` starts the
  command in the background and reads its output until it ends.
- **`mergeable` stays `UNKNOWN`:** after 10 reads fleet waits for CI anyway; a conflict then shows as no checks or a
  failed merge, which is re-mapped to `merge conflict` by re-reading `mergeable`.
- **Force-pushing a fleet PR branch** loses nothing a person wrote: manual commits stop the rebuild.
