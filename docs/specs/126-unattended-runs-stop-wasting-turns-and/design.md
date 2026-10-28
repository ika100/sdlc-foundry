# Design — 126 Unattended runs stop wasting turns and CI rounds

## Decisions

- **The owner is the session id the run was started or resumed in (AC-126.1 to AC-126.3).** `cplat component ship start` and
  `cplat system ship start` (new run and resume) store `owner` in the run state. The id comes from `CLAUDE_CODE_SESSION_ID` (set in the Bash tool
  since Claude Code 2.1.132, ADR-035), else `CPLAT_SESSION_ID`, which `cplat headless` now exports with the `--session-id` it hands to
  `claude -p`. The Stop hook compares this with the `session_id` of its JSON input. A run without `owner` holds nobody. ADR:
  [ADR-070](../../adr/070-the-stop-hook-holds-only-the-owning-session-until-it-stops-progressing.md).
- **One pure module decides every stop, `scripts/cplat/stopgate.py`.** Both gates (`ship.gate`, `appship_state.gate`) and `cplat headless`
  call it. It decides who is held, counts stops without progress, builds the no-progress reason and chooses the cause. Each caller only
  supplies its progress mark, its code-red evidence and its wording. That is how AC-126.8 ("in the same way") holds by construction.
- **Progress is a mark compared between stops, kept in the state as `stop_gate`.** For a component ship the mark is the tip of
  `refs/heads/<feature branch>` plus the run phase. For a product ship it is `HEAD` of the gitops-app checkout plus the run phase *and each
  repo's state* (`repos.<id>.state`). A product run spends hours in phase `repos` while its repo ships move, and those moves are its
  sub-phases. Uncommitted edits never count. The old `blocks` counter and `--max-blocks` are removed: nothing reads them any more.
- **The cause of a no-progress escalation is a fixed three-step rule (AC-126.7).** Step (a) applies `escalation_rules.classify` to
  the session's last message. Step (b) uses the caller's code-red evidence. Step (c) falls back to `decision`. The cause is always passed
  to `escalate` as a given cause, so `runs.finish` records `cause_source: given` and never `unknown`. `platform` cannot come out: no rule
  yields it (AC-088.16), and (b) and (c) are fixed values.
- **The last message comes from the Stop input, then the transcript.** The hook reads `last_assistant_message` from the hook input
  first. When that is missing, it reads the last `assistant` entry with a text block in `transcript_path` (JSONL). `cplat headless`
  uses the text a session printed (`--output-format text`, the part of the log after that session's `===` header). The text is redacted
  with `feedback.redact` (the spec 087 redaction), whitespace is collapsed, and it is cut to 200 characters.
- **One rule module for PR titles and the spec rule, and CI runs it too (AC-126.11, AC-126.13, AC-126.14).** `scripts/cplat/pr_rules.py`
  uses only the standard library. It holds the title pattern, the spec rule (moved from `scripts/check-spec-required.py`), the CI
  messages, and `fit()` for titles the platform builds. The platform CI's `pr-title` job now runs `python3 scripts/check-pr-title.py`,
  and `spec-required` keeps running `scripts/check-spec-required.py`. Both are thin wrappers that load `pr_rules.py` by file path
  (`importlib.util.spec_from_file_location`, so `scripts/cplat` never shadows anything on `sys.path`). The local checks and the CI jobs
  therefore run the same code, and AC-126.14 is a table test over that code and the two entry points. Component templates keep their
  `grep` jobs with the same pattern (non-goal: no local title check there).
- **Built titles fit in 72 characters *and* 72 UTF-8 bytes.** The self-hosted runners (GitHub Free, no hosted runners) may run the
  templates' `grep -E '.{1,72}'` in a C locale, which counts bytes. A built title such as `docs(spec): <id> — <title>` carries an em
  dash. A title that fits both measures is valid under either locale. Caller-given titles are checked against the rule as written
  (characters).
- **The spec rule runs before anything expensive (AC-126.9).** `cplat component ship pr` checks the title, then the spec rule (platform repo
  only, per `.platform-settings.yml` `shape: platform`), then the gitops tasks, and only then runs `devbox run ci` and pushes. A
  refusal raises `PlatformError`, so cplat prints `ERROR: <message>`, which is the `spec-required` job's line. `--no-spec` adds the
  label `no-spec` (`gh pr create --label`, or `gh pr edit --add-label` on an open PR). Outside the platform repo `--no-spec` is ignored
  with one note line, because component repos have no such label and no spec rule.
- **`devbox run ci` gets the PR it is about to open handed in the environment.** `cplat component ship pr` runs it with `PR_TITLE`,
  `PR_BODY` and `PR_LABELS` set (the names the CI jobs use). `scripts/check-pr-local.py` checks values handed this way. Without them it
  checks the open PR of the current branch, and without either it prints the skip lines (AC-126.13).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/pr_rules.py` | title pattern and messages, `title_error`, `fit`, spec rule `spec_error`, `changed_files` (stdlib only) | new |
| `scripts/check-pr-title.py` | CI `pr-title` entry point: `PR_TITLE` → CI output, exit 0/1 | new |
| `scripts/check-spec-required.py` | CI `spec-required` entry point; `verdict` becomes an alias of `pr_rules.spec_error` | changed |
| `scripts/check-pr-local.py` | the local check in `devbox run ci`: handed values, else the open PR, else skipped | new |
| `scripts/ci-local.sh` | new step "pull request title and spec rule" | changed |
| `.github/workflows/ci.yml` | `pr-title` job: checkout + `python3 scripts/check-pr-title.py` | changed |
| `scripts/cplat/stopgate.py` | owner, progress, verdict, no-progress reason, last message, cause rule | new |
| `scripts/cplat/ship.py` | `start` claims the owner; `gate` uses stopgate; `describe` shows the session; code-red evidence; `open_pr` spec rule, `--no-spec`, retitle, PR env for `devbox run ci`; `check_title` via pr_rules | changed |
| `scripts/cplat/appship_state.py`, `appship.py` | the same for the product run; built titles through `fit` | changed |
| `scripts/cplat/headless.py` | exports `CPLAT_SESSION_ID`; progress key ignores `owner`/`stop_gate`; no-progress cause by the rule | changed |
| `scripts/cplat/pr_open.py`, `pr.py` | caller title checked by the rule; spec rule and `--no-spec` in the platform repo | changed |
| `scripts/cplat/spec_pr.py`, `gitops.py`, `upgrade.py`, `clusterrepo.py`, `fleet_pr.py` | built titles through `pr_rules.fit` (commit subject and PR title alike) | changed |

## Contract

### `stopgate.py`

```python
NO_PROGRESS_LIMIT = 2
EXCERPT = 200

def session_of_env() -> str | None
    # CLAUDE_CODE_SESSION_ID, else CPLAT_SESSION_ID; stripped; None when both are empty or unset

def claim(st: dict, session: str | None) -> None
    # start/resume: st["owner"] = session (key removed when None); st["stop_gate"] = {}

@dataclass(frozen=True)
class Verdict:
    action: str          # "silent" | "notice" | "block" | "escalate"
    no_progress: int     # the count after this stop (0 for silent/notice)

def check(st: dict, session: str | None, mark: dict) -> Verdict
    # mark = {"head": str | None, "phase": str}   (phase: the comparison key, see Progress)
    # no st["owner"]                        -> notice   (st unchanged)
    # session != st["owner"] (incl. None)   -> silent   (st unchanged)
    # owner: progress = not st.get("stop_gate") or head or phase differs from st["stop_gate"]
    #        n = 0 if progress else stop_gate["no_progress"] + 1
    #        st["stop_gate"] = {"head": ..., "phase": ..., "no_progress": n}
    #        n >= NO_PROGRESS_LIMIT -> escalate, else block

def last_message(hook_input: dict) -> str
    # hook_input["last_assistant_message"], else the text of the last assistant entry in hook_input["transcript_path"]; "" on any error

def excerpt(message: str) -> str
    # feedback.redact(message), whitespace collapsed to single spaces, stripped, first EXCERPT characters

def no_progress_reason(phase: str, message: str) -> str
    # "no progress: 2 stops in phase <phase> without a new commit or phase change"
    # + ("; last message: " + excerpt(message)) when the excerpt is not empty

def cause(message: str, code_red: bool) -> str
    # escalation_rules.classify(message).cause if a rule matches; elif code_red: "code"; else "decision"
```

### Run state (both state files)

| Key | Type | Written by |
|---|---|---|
| `owner` | session id string, absent when unknown | `start` (new run and resume) via `stopgate.claim` |
| `stop_gate` | `{"head": str \| null, "phase": str, "no_progress": int}`, `{}` after a start or resume | the gate, on the owner's stops only |

`blocks` is no longer written. `set_phase`, `open_pr` and `_done` stop resetting it, and an old state file keeps a harmless stale key.

### Stop hook answers (`cplat component ship gate`, `cplat system ship gate`)

The hook reads its JSON input from stdin (`session_id`, `cwd`, `transcript_path`, `last_assistant_message`). It prints at most one JSON
object and always exits 0. `--max-blocks` is removed. `<kind>` is `ship`/`/component:ship` or `product ship`/`/system:ship`.

| Case | Output | State |
|---|---|---|
| no state, escalated, done | nothing | unchanged |
| no `owner` (AC-126.3) | `{"systemMessage": "<kind> <spec>: unfinished in phase <phase>, no session owns it; resume it with <command> <spec>"}` | unchanged |
| `session_id` is not `owner` (AC-126.1) | nothing | unchanged (no write at all) |
| owner, below the limit (AC-126.4, AC-126.5) | `{"decision": "block", "reason": …}`. First line: `The ship run of <spec> is not finished (phase <phase>, stops without progress: <n>/2).` (product: `The product ship of <spec> …`). Then the next step and, in phase build, the build status as today, then the escalate instruction | `stop_gate` updated |
| owner, limit reached (AC-126.5, AC-126.7) | `{"systemMessage": "<kind> <spec>: escalated (<reason>); resume it with <command> <spec>"}` | escalated with `no_progress_reason`, `cause` per rule |

`cplat component ship status` prints `  session: <owner>` under the phase line. Without an owner it prints
`  session: none (resume with /component:ship <spec> to own the run)`. `cplat system ship status` does the same with `/system:ship`.
`--json` carries `owner` as it is in the state.

Python entry points: `ship.gate(repo, hook_input, run_tests=True)` and `appship_state.gate(repo, hook_input)`. The `max_blocks`
parameter is removed.

### Code-red evidence (step (b) of the cause rule)

- Component ship, phase `plan` or `build`: `cplat spec trace <spec>` has `MISS` lines, or `devbox run test-fast` is red or did not
  finish (the existing `build_status`, returned with a red flag; skipped when `run_tests` is false).
- Component ship, phase `land` or `deploy`: `gh pr checks <st.pr> --required --json bucket` has a bucket in `{fail, cancel}`. When `gh`
  fails, the evidence is not red.
- Product ship: the open PR of the gitops-app checkout's current branch (`gh pr view --json url,state`) has a red required check.
  Product phases have no tests; their red evidence is the publish or complete PR.
- Any other phase: not red.

`ship.no_progress_cause(repo: Path, st: dict, message: str, run_tests: bool = True) -> str` combines this evidence with `stopgate.cause`.
Both the component gate and `cplat headless` use it.

### Headless (AC-126.2, AC-126.7)

- Each `claude -p` session gets env `CPLAT_SESSION_ID=<the --session-id>`.
- `progress_key` ignores `updated`, `blocks`, `owner` and `stop_gate`. A new owner and the gate's bookkeeping are not progress.
- On "no progress", the reason stays `no progress: two runs in a row ended in phase <phase> with nothing changed`, plus
  `; last message: <excerpt>` when the session printed text. The cause is `ship.no_progress_cause(repo, st, message)`. The headless run
  record gets the same cause (no more `environment`).

### `pr_rules.py`

```python
TITLE_PATTERN = r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)(\(.+\))?!?: .{1,72}$"   # the pr-title job's pattern
MAX_SUBJECT = 72
NO_SPEC = "no-spec"
CLOSES = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#\d+", re.I)   # unchanged from check-spec-required.py
CODE = ("scripts/", "plugins/", "templates/")

def title_error(title: str) -> str | None
    # None when re.match(TITLE_PATTERN, title); else exactly:
    # "PR title does not follow Conventional Commits.\n  Got:     <title>\n  Pattern: type(scope): description (≤72 chars)"

def fit(title: str) -> str
    # for titles the platform builds. Splits "<type>[(<scope>)][!]: <subject>" (scope without parentheses; ValueError otherwise),
    # collapses whitespace in the subject; returns it unchanged when the subject is 1..72 characters and <= 72 UTF-8 bytes;
    # else the longest cut subject[:k].rstrip(" -—–:;,.") + "..." that satisfies both limits. The result always passes title_error.

def spec_error(body: str, labels: list[str], files: list[str]) -> str | None
    # unchanged text of check-spec-required.verdict

def changed_files(repo, base: str, head: str = "HEAD") -> list[str]
    # git diff --name-only <base>...<head>
```

CI output (the same text everywhere; cplat prints the error part after `ERROR: ` through `PlatformError`):

- `pr-title`: `ERROR: <title_error lines>` and exit 1, or `OK: PR title is valid.`
- `spec-required`: `ERROR: <spec_error>` and exit 1, or `OK: spec rule satisfied`

`scripts/check-pr-title.py` reads `PR_TITLE`. `scripts/check-spec-required.py` reads `PR_BODY`, `PR_LABELS`, `BASE_SHA` and
`HEAD_SHA`, as before.

### `scripts/check-pr-local.py` (step of `scripts/ci-local.sh`, AC-126.13)

1. When `PR_TITLE` or `PR_BODY` is set and not empty, it checks those values with `PR_LABELS`. Otherwise it reads
   `gh pr view --json title,body,labels,baseRefName,state` for the current branch. A missing `gh`, an error or a state other than `OPEN`
   means no PR: it prints `pr-title: skipped (no pull request yet)` and `spec-required: skipped (no pull request yet)` and exits 0.
2. The diff is `git diff --name-only <base>...HEAD` with `<base>` = `origin/<baseRefName or main>` when it exists, else `<baseRefName or main>`.
3. It prints `pr-title: ` + the CI output lines, then `spec-required: ` + the CI output lines. Exit 1 if either failed (both run).

### `cplat component ship pr --title T --body-file F [--no-spec]` (AC-126.9, AC-126.10, AC-126.12)

The steps run in this order:

1. Branch and body checks as today.
2. `check_title(T)`: `PlatformError(title_error)`.
3. The open PR: `gh pr list --head <branch> --state open --json number,url,title,labels`.
4. Platform repo only: labels = the open PR's labels ∪ {`no-spec` if `--no-spec`}, files = `changed_files(repo, origin/main or main)`.
   `spec_error(body, labels, files)` raises `PlatformError` with that text, before `devbox run ci` and the push, and the phase stays.
5. Gitops-task check as today, then `devbox run ci` with env `PR_TITLE=T`, `PR_BODY=<body>`, `PR_LABELS=<labels joined by ,>`.
6. Push. With an open PR: `gh pr edit <url> --title T` when its title differs, and `--add-label no-spec` when asked and missing. Without
   one: `gh pr create … --title T --body-file F` plus `--label no-spec` when asked.

`cplat pr open` (the finishing command of quick-task and fix-bug) follows the same rule. A title that `title_error` rejects is `Refused`
(exit 2) with the message. In the platform repo the spec rule runs on the body as it will be sent (`{{CLOSES}}` resolved in memory) and on
the files of `<base>...HEAD` plus the uncommitted paths that `git add -A` would commit. A refusal is exit 2 and leaves the body file and
the tree untouched. `--no-spec` adds `--label no-spec` to the create command, including the printed command of a `ready` PR.

### Built titles (AC-126.11)

Every title below goes through `pr_rules.fit` before it is used as the commit subject or the PR title: `spec_pr` (draft PR
`docs(spec): <id> — <title>`), `appship` (publish `docs(spec): <id> — product spec and plan`, completion `docs(spec): <id> done`, and
`open_pr` itself), `gitops.open_pr` (every gitops command), `upgrade.open_pr`, `clusterrepo._pr` and `fleet_pr` (create and edit).
Caller-given titles (`ship pr`, `ship gitops pr`, `system ship entry pr`, `pr open`) are checked with `title_error`, never shortened.

## Risks

- A session without `CLAUDE_CODE_SESSION_ID` (Claude Code older than 2.1.132) and outside `cplat headless` starts runs without an owner,
  and those runs never hold it. The AC-126.3 notice says so at every stop. Token usage per run (ADR-035) already needs that version.
- Escalating in plan or build runs `devbox run test-fast` once more inside the hook (up to 900 s). The hook timeout is 960 s, as today.
- Run states written before this change have no owner and hold nobody until resumed. That is accepted (AC-126.3).
- The hook's stdout must stay one JSON object. The escalation path runs `escalate` with stdout and stderr captured, as
  `appship_state.gate` already does.
