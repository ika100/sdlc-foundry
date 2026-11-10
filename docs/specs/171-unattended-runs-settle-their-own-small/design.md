# Design — 171 Unattended runs settle their own small problems

## Decisions

- **One landing module for both merge paths.** `cplat component ship land` and `cplat pr wait --merge` (and through it
  `cplat dispatch land`) get the merge, the post-merge cleanup, the head guard and the generated-file regeneration from
  one new module, `scripts/cplat/land_merge.py`, because today the two paths already diverge (`pr.py` knows #371, `ship.py`
  does not) and every fix would otherwise be made twice. ADR: [092](../../adr/092-a-land-settles-what-has-an-obvious-answer.md).
- **`gh pr merge` runs without `--delete-branch`.** gh's local half (switch to the base branch, delete the branch) is
  what fails in a worktree after GitHub merged (#622, #371). The land deletes the remote branch through the API and does
  the local steps itself, each failure a `WARNING:` line (AC-171.3).
- **The head the lock reads is the head the merge carries.** `merge_lock._known` stores a head it had to read in
  `watch.head`, so `--match-head-commit` always guards the merge; a refused merge whose PR head moved goes back to wait for
  the new head's checks (AC-171.4).
- **Generated files are a fixed registry with a generated region.** `docs/backlog.md` is only partly generated (the
  block between the spec-index markers). Its hand-written rest is merged as text (`git merge-file` of the three stages
  with the block cut out), then the generator fills the block; a conflict in the hand part is a person's decision like any
  other (AC-171.6, A5, A6).
- **Running waits mark themselves in the checkout's git dir.** The Stop hook cannot see processes of the session, so
  each `cplat` wait writes `<git dir>/cplat-waits/<pid>.json` while it runs; the hook reads the live ones (AC-171.8, A8).
  ADR: [093](../../adr/093-running-cplat-waits-are-visible-to-the-stop-hook.md).
- **`test-diff` names a helper, the prompt acts on the name.** The check, not the model, tells a test helper (a changed
  file that defines no test) from a test, so the build's rule is one deterministic branch: a `test helper` line goes to
  `--tighten` without asking; `tightening` keeps refusing a lost assertion, test or criterion id (AC-171.7, A7).
- **The preflight's minimum is two rules in the committed file.** `Bash(cplat *)`-like and `Read(~/.claude/plugins/**)`-like
  allow rules (A2). A missing file keeps its spec 131 message unchanged (AC-131.11 pins it).
- **The platform repo's allowlist is checked against the library template by a script**, `scripts/check-settings.py`,
  run by `devbox run validate`, `scripts/ci-local.sh` and the `validate-shapes` CI job (AC-171.2, A1).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/preflight.py` | `_no_allowlist`: the two minimum allow rules (AC-171.1) | changed |
| `.claude/settings.json` | the library template's allow and ask rules (AC-171.2) | changed |
| `scripts/check-settings.py` | platform allowlist ⊇ template allowlist (AC-171.2) | new |
| `scripts/cplat/land_merge.py` | merge, cleanup, head guard, regeneration, the settle loop (AC-171.3, .4, .6) | new |
| `scripts/cplat/merge_lock.py` | `_known` stores the read head in `watch.head` (AC-171.4) | changed |
| `scripts/cplat/ship.py` | land: push ahead, settle through `land_merge`, cleanup; gate: running waits (AC-171.3–.6, .8) | changed |
| `scripts/cplat/pr.py` | `pr wait --merge` through `land_merge`; the wait marks itself running (AC-171.3, .4, .6, .8) | changed |
| `scripts/cplat/waits.py` | `running()` and `live()`; `record()` marks itself running (AC-171.8) | changed |
| `scripts/cplat/stopgate.py` | `check(..., waiting=)`, `wait_line()` (AC-171.8) | changed |
| `scripts/cplat/appship_state.py` | the system ship gate passes running waits (AC-171.8) | changed |
| `scripts/cplat/house_rules.py` | `--body-file` through `core.git_path`, read errors as one line (AC-171.9) | changed |
| `scripts/cplat/spec.py` | `--tracks` extends; `test-diff` names test helpers (AC-171.7, .10) | changed |
| `plugins/component/commands/build.md`, `references/build-tighten.md` | a `test helper` line → `--tighten` without asking (AC-171.7) | changed |

## Contract

### Preflight (AC-171.1)

`preflight._no_allowlist(repo)` reads `<repo>/.claude/settings.json` only (the committed layer):

- File missing: unchanged (`<repo> has no committed allowlist (.claude/settings.json): run /platform:update or cplat adopt`).
- File present: `MINIMUM = ("Bash(cplat *)", "Read(~/.claude/plugins/**)")`. The first is satisfied by any allow rule `r`
  with `matches(r, "cplat spec check")` (so `Bash(cplat *)`, `Bash(cplat:*)`, `Bash`, `Bash(*)`); the second by `Read`,
  `Read(**)` or a `Read(<glob>)` whose glob (`**` any characters, `*` no `/`; a leading `~` or the home directory both
  accepted) matches `~/.claude/plugins/cache/sdlc-foundry/component/1.0.0/commands/ship.md`. An unreadable or invalid file
  counts as no allow rules.
- Each unsatisfied minimum is missing; the failure is `Failure("no-repo-allowlist", detail)` with
  `detail = "<missing rules joined by ' and '> not allowed by <repo>/.claude/settings.json: add to permissions.allow (the library template's allowlist has it), or run /platform:update"`.
  The printed line therefore starts `preflight failed: no-repo-allowlist: Bash(cplat *)` (or `Read(~/.claude/plugins/**)`
  when only that is missing). Order of checks, exit 1, the `environment` escalation, 0 invocations and $0 are the spec 131
  path in `headless.py`, unchanged. `check_repo` (system ship repos) uses the same function.

### Platform allowlist (AC-171.2)

- `.claude/settings.json` of the platform repo keeps `$schema` and `worktree` and gains `permissions.allow` and
  `permissions.ask` holding every rule of `templates/library-python/.claude/settings.json` (same strings, template order);
  no `defaultMode`, `extraKnownMarketplaces` or `enabledPlugins` (A1).
- `python3 scripts/check-settings.py [--root DIR]`: for each `kind` in `allow`, `ask`, each template rule absent from the
  platform file prints `ERROR: .claude/settings.json lacks the library template's <kind> rule "<rule>"`; then
  `FAILED: <n> rule(s) missing` and exit 1. Otherwise `OK: .claude/settings.json holds the library template's <a> allow and <k> ask rules`,
  exit 0. An unreadable or invalid file is one `ERROR: <path>: <reason>` line and exit 1. Standard library only.

### Landing (AC-171.3, .4, .5, .6) — `scripts/cplat/land_merge.py`

```python
GENERATED: dict[str, Generated]      # "docs/backlog.md" -> Generated(start=spec.START, end=spec.END, write=spec.write_index)
MAX_REGEN_ROUNDS = 3

class Unresolvable(merge_lock.Conflict)   # stays a person's decision; the message contains "rebase is a human decision"
class MergeFailed(PlatformError)          # GitHub refused the merge for another reason (not a conflict, not a moved head)

@dataclass
class Rounds: used: int = 0               # one per land invocation

@dataclass
class Settled:
    status: str                           # "merged" | "red"
    lines: list[str]; cs: list[dict]; failed: list[dict]
    sha: str = ""                         # the merge commit
    updated: bool = False                 # the branch head changed on GitHub (catch-up or regeneration)

def await_head(watch, sha, polls=merge_lock.HEAD_POLLS) -> bool  # until GitHub's headRefOid == sha; then watch.head = sha
def wait_green(repo, url, watch, timeout, interval, rounds, run) -> tuple[str, list[dict], list[dict], list[str]]
def merge(repo, url, head, run) -> tuple[str, str]                # ("merged", sha) | ("head-moved", new_head) | ("conflicting", "")
def cleanup(repo, url, run) -> list[str]                          # WARNING lines only
def regenerate(repo, url, watch, rounds, run) -> list[str]        # the one "regenerated …" line; raises Unresolvable
def settle(repo, url, watch, timeout, interval, rounds, run, before_merge=None) -> Settled
```

`run` is the caller's `run` (`ship.run` / `pr.run`, looked up at call time, so existing test fakes keep working); `gh`
calls go through `ship.gh`.

**`merge(repo, url, head, run)`** runs `gh pr merge <url> --squash` plus `--match-head-commit <head>` when `head` is known
(never `--delete-branch`). Exit 0 → `("merged", mergeCommit.oid)`. Exit ≠ 0 → `gh pr view <url> --json state,mergeable,headRefOid,mergeCommit`:
`MERGED` → `("merged", oid)`; `headRefOid != head` → `("head-moved", headRefOid)`; `mergeable == "CONFLICTING"` →
`("conflicting", "")`; otherwise `MergeFailed(f"merging {url} failed: {last line of gh's output}")`, whose hint never
mentions conflicts (ship: `read the error, then run cplat component ship land again`; pr: `read the error, then run the
wait again`; a draft keeps ship's `gh pr ready` hint).

**`cleanup(repo, url, run)`**, after every merge (also an "already merged" one), never raises; each failure is one line
`WARNING: <step> failed: <last non-empty line of the error, else "exit <code>">`:

1. `deleting the remote branch <head>`: `gh api -X DELETE repos/<slug>/git/refs/heads/<headRefName>`; an answer saying the
   reference does not exist (GitHub deleted it) is no warning; skipped for a PR from a fork.
2. The local steps run only when the checkout's origin slug is the PR's slug. `<base>` is the PR's `baseRefName`.
   - `<base>` checked out in another worktree (`git worktree list --porcelain`, a `branch refs/heads/<base>` entry whose
     path is not this checkout's top level): no switch, no pull, and the local feature branch is not deleted while it is
     checked out here; no warning for any of these (A3).
   - Otherwise: `switching to <base>` (`git switch -q <base>`, skipped when already on it); only if that worked,
     `updating <base>` (`git pull -q --ff-only`) and `deleting the local branch <head>` (`git branch -D -q <head>`, only when
     the ref exists).

The merge line stays `merged <url-or-pr> (squash)`; the warnings follow it. No line of a merged land mentions merge
conflicts or `ship escalate`. Exit 0.

**Head guard (AC-171.4).** `merge_lock._known` sets `watch.head = head` when `watch.head` was `None` and it read one.
`settle` passes `watch.head` to `merge`; `head-moved` prints `  the head of <url> moved to <sha7> before the merge: waiting
for its checks`, waits through `wait_green`, and starts the loop again (catch-up, merge). Nothing merges on a head whose
checks were not waited for.

**`wait_green`** wraps `ship.wait_checks` the way `pr._watch` does today (again while a push moved the head during the
last poll) and turns `ship.Conflicting` into `regenerate(...)` followed by another wait.

**`settle`** (inside the merge lock):

```
loop:
    try caught = merge_lock.catch_up(repo, url, watch, timeout, interval)
    except Unresolvable: raise
    except merge_lock.Conflict: lines += regenerate(...); status = wait_green(...); red -> return; continue
    caught red -> return Settled("red", ...)
    if before_merge: ok, more = before_merge(); not ok -> return Settled("red", ...)   # ship: gitops PRs, draft → ready
    kind, value = merge(repo, url, watch.head, run)
    merged      -> return Settled("merged", lines + [merged line] + cleanup(...), sha=value)
    head-moved  -> wait_green(...); red -> return; continue
    conflicting -> regenerate(...); wait_green(...); red -> return; continue
```

**`regenerate(repo, url, watch, rounds, run)`** (AC-171.6):

1. `rounds.used += 1`; above `MAX_REGEN_ROUNDS` → `Unresolvable(f"{url} still conflicts with {base} after 3 regeneration rounds: rebase is a human decision")`.
2. Preconditions, else `Unresolvable(f"{url} conflicts with {base}: rebase is a human decision ({why})")`: the checkout's
   origin slug is the PR's; the current branch is the PR's `headRefName`; no staged or unstaged change to tracked files.
3. `git fetch -q origin <base> <head>`; the local branch fast-forwards to `origin/<head>` when behind (diverged →
   Unresolvable). `pre = git rev-parse HEAD`.
4. `git merge --no-ff --no-commit origin/<base>` (no commit yet, so the commit below carries the sign-off). Unmerged
   paths = `git diff --name-only --diff-filter=U`.
   - A path not in `GENERATED` → `git merge --abort`, then `Unresolvable(f"{url} conflicts with {base} in {paths}: rebase is a human decision")`.
   - Each generated path: stages `:1:`, `:2:`, `:3:` with the region between `start` and `end` replaced by one placeholder
     line, merged with `git merge-file -p`; a conflict there → `git merge --abort` and Unresolvable naming
     `<path> outside its generated block`. Clean → write the merged text with the placeholder back to `start…end`, run
     `write(repo)`, `git add <path>`.
   - `git commit -s --no-edit` (with `core.git_identity` fallbacks), then `git push -q origin <head>` (never force). A
     refused push → `git reset -q --hard <pre>` and `PlatformError(f"pushing the regenerated merge of {url} failed: {err}")`.
   - A merge with no unmerged path is committed and pushed the same way.
5. `await_head(watch, <the pushed sha>)`, then return one line:
   `regenerated <path>[, <path>] after merging <base> into <head> (round <n>/3)` (or `merged <base> into <head> without a
   conflict (round <n>/3)`).

A land that stops on an Unresolvable conflict leaves the feature branch at `pre`, with no merge in progress. `ship land`
keeps its hint for it: `merge conflicts with main: rebase is a human decision; cplat component ship escalate 'merge failed'`;
`pr wait` keeps `a conflict with main is a human decision`. `pr.MergeFailed` becomes `land_merge.MergeFailed` (an alias in
`pr.py`), so `dispatch_units.land` still reports `merge-failed`.

**Push ahead (AC-171.5)**, `ship.push_ahead(repo, st, pr, watch) -> str | None`, the first step of `_land`, before any
check is read:

1. `git fetch -q origin <branch>`; `head = headRefOid` of the PR; `n = git rev-list --count <head>..refs/heads/<branch>`.
   `n == 0` → `None`.
2. The checkout must be on `<branch>`; then `run_ci(repo, {PR_TITLE, PR_BODY, PR_LABELS})` with the PR's own title, body
   and labels (`gh pr view --json title,body,labels`); a red `devbox run ci` raises its own error as in `ship pr` (nothing
   pushed, no checks judged).
3. `git push -q origin <branch>` (no force, the open PR reused). Refused, or not on the branch →
   `say("  push of <branch> failed: <reason>")` and `PlatformError(f"local commits not pushed: {n} commit(s) ahead of the PR head",
   hint=f"cplat component ship pr --title '<the PR title>' --body-file {core.PR_BODY}")`. Exit 1; no check is read.
4. Success → line `pushed <n> local commit(s) to <branch>: waiting for the checks of <sha7>`; `land_merge.await_head(watch,
   sha)` (a head GitHub does not show after the polls is a `PlatformError`, no checks judged); the first `wait_green` then
   judges only that head, and a green that belongs to another head is waited for again.

### Stop hook (AC-171.8)

`waits.py`:

```python
WAITS_DIR = "cplat-waits"
@contextlib.contextmanager
def running(command: str, cwd: Path | None = None): ...   # writes <git dir of cwd>/cplat-waits/<pid>.json, removes it on exit
def live(repo: Path) -> list[str]: ...                     # commands of live marks, oldest first; dead-pid marks removed
```

Mark file: `{"pid": <int>, "command": "<command>", "started_at": "<ISO-8601 local, seconds>"}`. A process is live when
`os.kill(pid, 0)` succeeds or raises `PermissionError`. No git dir (not a checkout) → no mark, no error. `record(repo,
name, body)` runs `body` inside `running(f"cplat {name}", Path.cwd())`; `pr.main` (the `wait` subcommand) inside
`running(f"cplat pr wait {pr}{' --merge' if merge else ''}", Path.cwd())`; `ship.main` (`land`) inside
`running("cplat component ship land", Path.cwd())`. `pr.wait()` called in-process by the dispatcher marks nothing.

`stopgate.py`:

```python
@dataclass(frozen=True)
class Verdict: action: str; no_progress: int; waiting: str | None = None

def check(st, session, mark, running=0, waiting: list[str] | None = None) -> Verdict
def wait_line(v: Verdict) -> str   # f"waiting: {v.waiting}; stops without progress: {v.no_progress}/{NO_PROGRESS_LIMIT}"
```

Order in `check`: owner rules as today; running background agents → `wait` as today; then `waiting` non-empty →
`progress = not prev or head/phase changed`, `n = 0 if progress else prev["no_progress"]` (never + 1),
`st["stop_gate"] = {head, phase, no_progress: n}`, `Verdict("block", n, ", ".join(waiting))`. Without waits: unchanged
(AC-126.4, AC-126.5).

Both gates (`ship.gate`, `appship_state.gate`) pass `waits.live(repo)`; a block with `verdict.waiting` has the reason

```
waiting: <command>[, <command>]; stops without progress: <n>/2
The ship run of <spec> is not finished (phase <phase>); the wait above is still running.
Next: read its result when it ends (a blocking read of its background task, never a polling loop), then go on from it.
```

(`The product ship of <spec> …` for the system gate.) The keep-going and escalate sentence follows as today.

### pr-check (AC-171.9)

`house_rules.main`: `path = core.git_path(repo, ns.body_file)` (a `.git/…` path is the checkout's own git dir, as in
`cplat pr open` and `cplat component ship pr`); `path.read_text()` raising `OSError` (missing, a directory, unreadable)
or `UnicodeDecodeError` prints `ERROR: body file <F as given>: <reason>` to stdout and returns 1. `<reason>` is
`does not exist`, `is a directory` or the exception's `strerror`/message. No traceback, no auto-filed issue (the
crash path of `cplat.py` is never reached).

### --tracks (AC-171.10)

`cplat spec new`: `--tracks` is `type=int, nargs="*", action="extend", default=None`; the values are de-duplicated in
first-given order (`list(dict.fromkeys(...))`) before `new()` writes `tracks:` and before `claim.claim` claims each for
`feature/<spec id>`.

### Test helpers (AC-171.7)

`spec.test_diff`: a refused file whose old and new content both define no test (`_test_names` empty on both sides)
reports `why = "test helper (defines no test): <the reason it was refused>"`; the CLI line is
`<file>: changed — test helper (defines no test): <reason>`, exit 1 as today. `--tighten <file> --task <task> --reason '<why>'`
is unchanged: `tightening` accepts a helper that keeps its criterion ids and assertion count and adds no skip, records it
as `tightened`, and the run record's `approved_test_diffs` entry (`kind: tightened`) puts it in the PR's "How this was
built" block with the file, task and reason (AC-165.3). The build prompt: a `test helper` line → `--tighten` for that
file without asking the user; its exit 1 stops as a changed test does today.

## Risks

- **A blocked stop during a long wait can loop.** Each block costs one model turn; the reason tells the session to read
  the background task's output with a blocking read, which takes the turn until the wait ends. The wait's own timeout
  (ADR-082, 540 s default; `pr wait` 3600 s) and the budget bound it.
- **Fixtures of existing tests.** Several spec 131 fixtures commit a `.claude/settings.json` without `cplat` or `Read`
  rules, and two tests pin the old `gh pr merge … --delete-branch` argv and the #371 line; the tasks that change the
  behaviour update those fixtures and assertions (listed in their `files`).
- **`git merge-file` on the hand part** of `docs/backlog.md` is conservative: any overlapping hand edit is a conflict and
  stops as today.
