# Design — 108 Agents get a compact failure summary, not the full log

## Decisions

- **One summarizer package, `scripts/cplat/failsum/`, used by every hand-over of a failure.** `cplat quiet`, `cplat validate run`
  (the fix-round check runner, spec 103), `ship.run_ci` (the `devbox run ci` that `cplat component ship pr` runs before every push) and
  `ship.red` (red checks in `cplat component ship land`, `cplat pr wait` and the product ship's gitops PRs via `appship_merge`) all
  render through it. Fixed rules only, no model (AC-108.6). ADR: [ADR-071](../../adr/071-a-failing-check-reaches-an-agent-as-a-rule-made-summary.md).
- **One parser per tool output format, grouped by ecosystem in their own modules.** The core (segments, own-code paths, dedup,
  limits, render, sidecar) never knows a tool; each parser module exports `PARSERS`. A tool whose output changes falls back to
  `format: unknown`, which is today's output (AC-108.4).
- **A local log is split into checks at devbox's script markers.** Every `devbox run <name>` prints
  `Info: Running script "<name>" on <path>` before the script's output. The text between two markers is the check named by the
  first. A log without markers is one check named after the script. Templates chain `ci` with `&&`, so locally the last non-empty
  segment is the one that failed; it always appears, even when no parser reads it (AC-108.5: never drop a failing check).
- **CI logs are saved first, then summarized per failed check.** `gh run view <run> --log-failed` is fetched once per run, split by
  its job column, and each failed check's lines are written to the `cplat quiet` log directory before they are summarized (AC-108.8).
  A failed check that is not a GitHub Actions run still gets its header, with `log: none`.
- **The summary is the failure of record for spec 102 (AC-108.9).** `budget.normalise` moves to `failsum.normalise` (budget re-exports
  it). The no-progress signature is computed from the summary's normalized messages, and the recovery snapshot stores the whole
  summary as its excerpt. `cplat quiet` and `cplat validate run` write `<log>.summary.json` next to the log, so
  `cplat budget attempt --error-file <log>` (build-red-rounds.md) reuses exactly the printed summary.
- **Redaction covers everything but the log path.** Every summary line goes through `feedback.redact` (spec 087), except the log
  path itself: redaction turns `/Users/<name>` into `~`, which an agent's Read tool cannot open.
- **The switch is a project setting and a flag (AC-108.10).** `failure_summary: off` in the committed `.platform-settings.yml` (read
  from the project file only, as the spec says "project setting"), or `cplat quiet --raw <script>`. `--raw` is consumed by cplat and
  never reaches the shell, so ADR-037 holds. Off means today's output plus one line saying so.
- **The benchmark task is a build whose implementation is already done.** Workflow `fix-rounds`: a seed commit on the sample adds an
  approved spec 901 whose single criterion the sample already meets (tagged acceptance test, `plan.md` with its task `done: true`),
  breaks one existing non-acceptance test and adds one ruff finding. `/component:build 901` then skips Phases 1 and 2 and spends its
  coder and quality calls on fix rounds only, so "the fixing agents' calls" are exactly the `coder` and `quality` roles. The seed is an
  arm-shaped JSON file (file contents as strings, like spec 107's arms), so the platform repo's own lint never sees the seeded
  defect. The pass without summaries adds `.platform-settings.yml` with `failure_summary: off` to the seed: the setting of AC-108.10
  itself, no extra switch.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/failsum/__init__.py` | public API: `summarize`, `summarize_ci`, `raw`, `enabled`, sidecar, `normalise`; registry of parser modules | new |
| `scripts/cplat/failsum/core.py` | `Entry`, `Result`, `Check`, `Summary`, `Context`, `Parser`; ANSI/CI-prefix stripping, segments, own-code paths, dedup, limits, render | new |
| `scripts/cplat/failsum/python.py` | pytest (incl. `-q --tb=line`), pytest-cov threshold, ruff check, ruff format, mypy | new |
| `scripts/cplat/failsum/java.py` | Maven Surefire, Maven compiler, Checkstyle, Spotless, JaCoCo check | new |
| `scripts/cplat/failsum/go.py` | `go test` (incl. panics, build failures), `go build`, golangci-lint v2 | new |
| `scripts/cplat/failsum/web.py` | Vitest (incl. coverage thresholds), ESLint stylish, `tsc`, `next build` | new |
| `scripts/cplat/failsum/gitops.py` | gitops-app script `ERROR:` lines, kustomize, kubeconform, Kyverno (`check-policies.sh`) | new |
| `scripts/cplat/failsum/docker.py` | `docker build` (BuildKit) | new |
| `scripts/cplat/settings.py` | `failure_summary(repo)` | changed |
| `scripts/cplat/quiet.py` | `--raw`; failure prints the summary; writes the sidecar | changed |
| `scripts/cplat/validate.py` | a failed check prints its summary; writes the sidecar | changed |
| `scripts/cplat/ship.py` | `run_ci` logs and summarizes; `red_summary`/`red` save CI logs and summarize; `land` feeds spec 102; `escalate(summary=)` | changed |
| `scripts/cplat/budget.py` | `normalise` from failsum; `attempt(normalized=)`, `snapshot(summary=)`; `attempt --error-file` reads the sidecar | changed |
| `scripts/cplat/runs_bench.py`, `benchmark/tasks.json`, `benchmark/seeds/fix-rounds.json` | the `fix-rounds` task, two passes, the comparison | changed / new |
| plugin commands, references, agents, READMEs; `docs/unattended-delivery.md`; site concepts page | "the summary, then the log only if needed" | changed |

## Contract

### Limits and constants (`failsum`)

`MAX_ENTRIES = 20`, `MAX_EXCERPT = 10`, `MAX_LINES = 80`, `TAIL = 40`, `MIN_TAIL = 10`, `FORMAT_UNKNOWN = "unknown"`.

### Rendered summary (byte-exact)

```
<title>
== check: <name> | format: <formats> | command: <command> | exit: <exit> | log: <log> | entries: <n>
- <locator> | <kind> | <message>[ | x<count> (lines <l2>, <l3>, ...)]
    > <excerpt line>
- ... <m> more entries not shown (log: <log>)
  (the tool reports <r> failures, <n> read; last lines of the check:)
<tail line>
```

- `<title>` is the line the caller printed before this spec, unchanged: `FAILED (exit <rc>): devbox run <script> (log: <log>)` for
  `cplat quiet`; `FAILED (exit <rc>): <check label> (log: <log>)` for `cplat validate run`; `RED: <n> of <m> check(s) failed on <pr>:
  <names>` for CI; `` `devbox run ci` is red; nothing was pushed: `` for `ship.run_ci` (inside the `PlatformError` message).
- One `== check:` header per failing check, in log order (local) or in the order of `failed` (CI). `<formats>` is the comma-separated
  names of the parsers that produced entries, in registry order, or `unknown`. `<command>`: `devbox run <segment>` locally,
  `<job> / <step>` for CI (the step of the first `##[error]` line; `<job>` alone without one). `<exit>`: the command's exit code locally;
  for CI the number in `Process completed with exit code <n>`, else `?`. `<log>`: absolute path, or `none (not a GitHub Actions run:
  <link>)`. `entries: <n>` is the total before the 20-entry cut and is omitted for `format: unknown`.
- Entry `<locator>`: for a test, `<test id> at <file:line>` (`<test id> at <file>` when the log carries no own-code line, see Risks);
  for a finding, `<file:line>`. `<kind>`: the error type (`AssertionError`, `panic`, `TS2322`) or rule code (`F401`, `no-unused-vars`,
  `UnusedImports`, `errcheck`, `spotless`, `coverage`). `<message>`: the tool's message through `failsum.message`, which is `failsum.normalise` and then every remaining number as `<n>` (so "expected 204, got 200" and "…got 500" are one failure for the no-progress stop).
- Excerpt lines: raw log lines (ANSI stripped), at most 10 per entry, `    > ` prefix. For tests: the assertion/error lines and the
  own-code frames of that failure; for findings: the code frame the tool printed, if any.
- Deduplication (AC-108.3, findings only, never tests): entries with the same file, kind and message are one entry at the first
  location, `| x<count>` and up to 10 further line numbers in log order.
- `format: unknown` check: the header without `entries:`, then the last 40 lines of that check's text (raw, redacted); `(no output)`
  when it is empty. A summary of a failed command is never empty (AC-108.4).
- Incomplete read: when a parser reads a tool total (`== 2 failed ==`, `Tests run: …, Failures: f, Errors: e`, `Tests  2 failed`,
  `Found 3 errors`, `N issues`, `✖ N problems`) larger than its entries, the `(the tool reports …)` line and the check's last 40 lines
  follow its entries.
- Order of shortening when the whole text exceeds 80 lines (AC-108.5): (1) the per-entry excerpt cap goes 10 → 0, one step at a time,
  for all entries alike; (2) the tail of unknown or incomplete checks goes 40 → 10; (3) the shown entries per check go 20 → 1, the
  `... <m> more entries not shown` count growing accordingly. Titles, check headers and the `more entries` lines are never removed; a
  summary with more than ~38 failing checks may therefore exceed 80 lines.
- Redaction: every line passes `feedback.redact` except the `<log>` path strings (title, header, `more entries` line).

Example (`cplat quiet ci`, service-python):

```
FAILED (exit 1): devbox run ci (log: /Users/eike/.cache/sdlc-foundry/logs/todo-api/20261028-101500-ci.log)
== check: test | format: pytest | command: devbox run test | exit: 1 | log: /Users/eike/.cache/sdlc-foundry/logs/todo-api/20261028-101500-ci.log | entries: 1
- tests/test_todos_api.py::test_delete_todo at src/todo_api/todos/router.py:58 | AssertionError | assert <n> == <n>
    > E       assert 200 == 204
```

### Summaries off (AC-108.10)

`cplat quiet`: the title line, then `summaries: off (--raw)` or `summaries: off (.platform-settings.yml failure_summary: off)`, then
the last 40 lines (today's output). CI: today's lines (`RED: …` and the 60-line tails) with the same `summaries: off (…)` line after
the `RED:` line. `cplat validate run` and `ship.run_ci`: today's text plus that line after the title. No sidecar is written.

### `failsum` API

```python
@dataclass(frozen=True)
class Entry:
    at: int                     # index of the first log line of the entry (sort key, not rendered)
    test: bool                  # a failing/erroring test (never deduplicated) or a finding
    locator: str                # test id, or "file:line"
    where: str | None           # own-code "file:line" (or "file") of a test failure; None for findings
    kind: str
    message: str                # already normalised
    excerpt: tuple[str, ...] = ()
    count: int = 1
    lines: tuple[int, ...] = ()

@dataclass(frozen=True)
class Result:
    entries: tuple[Entry, ...]
    reported: int | None = None  # the tool's own failure count, when it prints one

class Parser(Protocol):
    name: str                                   # the header's format name: pytest, pytest-cov, ruff, ruff-format, mypy, ...
    def parse(self, lines: list[str], ctx: "Context") -> Result | None: ...   # None: nothing of this tool's failures in lines

@dataclass(frozen=True)
class Context:
    root: Path | None           # repo root: absolute paths under it become relative
    def own(self, path: str) -> str | None
        # relative own-code path, or None. Absolute paths are made relative to root, or after a runner workspace prefix
        # (".../_work/<x>/<x>/" or ".../work/<x>/<x>/"); "./" is dropped. Not own: .venv/, venv/, site-packages/, dist-packages/,
        # node_modules/, vendor/, target/, .devbox/, /usr/, /opt/, go/pkg/mod/, <frozen ...>, any path still absolute.
    def own_java_frame(self, frame: str) -> bool
        # "at a.b.C.m(C.java:12)": False for java., javax., jdk., sun., org.junit., org.opentest4j., org.mockito., org.assertj.,
        # org.springframework., org.apache.maven.; else True

def normalise(text: str) -> str                 # budget._NORMALISE rules, moved unchanged
def enabled(repo: Path) -> tuple[bool, str]     # (on, reason) from settings.failure_summary; reason "" when on
def summarize(text: str, *, title: str, check: str, command: str, exit_code: int, log: Path, root: Path | None) -> Summary
    # local log: strip ANSI, split at devbox markers, run every parser on every non-empty segment
def summarize_ci(title: str, checks: list[CiCheck], *, root: Path | None) -> Summary
    # CiCheck(name, link, log: Path | None, text: str | None); CI lines are stripped of "<job>\t<step>\t<timestamp> ",
    # "##[group]"/"##[endgroup]" lines are dropped and "##[error]" prefixes removed before parsing
def raw(title: str, text: str, reason: str, tail: int = TAIL) -> str        # the summaries-off rendering for local logs

class Summary:
    title: str
    checks: list[Check]          # Check(name, command, exit, log, formats, entries, reported, tail)
    def render(self) -> str      # the byte-exact text above, limits applied, redacted
    def normalized(self) -> str  # "\n".join("<check>|<kind>|<message>" per entry before the 20-cut,
                                 #           "<check>|unknown|<normalise(last 40 lines)>" per unknown check)

def sidecar(log: Path) -> Path                  # <log>.summary.json, e.g. 20261028-101500-ci.log.summary.json
def write_sidecar(log: Path, s: Summary) -> None            # {"text": s.render(), "normalized": s.normalized()}; never raises
def read_sidecar(log: Path) -> dict | None
```

`failsum/__init__.py` imports the parser modules in this fixed order: `python`, `java`, `go`, `web`, `gitops`, `docker`, and runs
`PARSERS` of each in that order. Entries of all parsers in one check are sorted by `at`.

### Parsers (AC-108.4), one per format, named as in the header

| Template | Tool (script) | Parser `name` | Reads |
|---|---|---|---|
| service-python, library-python | pytest (`test`, `test-fast`) | `pytest` | `FAILED`/`ERROR <nodeid> - <Type>: <msg>` summary lines; `--tb=line` lines `<path>:<n>: <Type>…`; long tracebacks (`_____ name _____`, `E   ` lines, `<path>:<n>: <Type>`); `ERROR collecting`; total `== N failed, M errors ==` |
| | pytest-cov (`test`) | `pytest-cov` | `FAIL Required test coverage of N% not reached. Total coverage: M%` → kind `coverage` |
| | ruff check (`lint`) | `ruff` | full format (`<CODE> <msg>` + ` --> <file>:<l>:<c>` + code frame) and concise (`<file>:<l>:<c>: <CODE> <msg>`); `Found N errors` |
| | ruff format (`lint`) | `ruff-format` | `Would reformat: <file>` → kind `format`; `N files would be reformatted` |
| | mypy (`typecheck`) | `mypy` | `<file>:<l>: error: <msg>  [<code>]` (+ following `note:` lines as excerpt); `Found N errors in M files` |
| service-java | Surefire (`test`, `test-fast`) | `surefire` | `[ERROR] Failures:` / `[ERROR] Errors:` lists (`<Class>.<method>:<l> <msg>`, `» <Type> <msg>`), `<<< FAILURE!` blocks with own-code `at` frames; `Tests run: t, Failures: f, Errors: e` |
| | maven-compiler (`typecheck`) | `javac` | `[ERROR] <file>:[<l>,<c>] <msg>` (+ `symbol:`/`location:` lines) |
| | Checkstyle (`lint`) | `checkstyle` | `[ERROR] <file>:[<l>(,<c>)] (<category>) <Rule>: <msg>` and `[WARN]` of the same shape when the goal failed |
| | Spotless (`lint`) | `spotless` | `The following files had format violations:` + file lines → kind `spotless`, one entry per file |
| | JaCoCo check (`test` = `verify`) | `jacoco` | `Rule violated for <scope> <name>: <counter> covered ratio is <a>, but expected minimum is <b>` → kind `coverage` |
| service-go | go test (`test`, `test-fast`) | `go-test` | `--- FAIL: <Test> (…)` with following `<file>:<l>: <msg>` lines (id `<pkg>.<Test>` from the `FAIL <pkg>` line); `panic:` with own-code frames; build failures of a test package; `FAIL` package count |
| | go build (`typecheck`) | `go-build` | `# <pkg>` followed by `<file>:<l>:<c>: <msg>` → kind `compile` |
| | golangci-lint v2 (`lint`, incl. govet) | `golangci-lint` | `<file>:<l>:<c>: <msg> (<linter>)` + code frame; `N issues:` |
| web-nextjs | Vitest (`test`, `test-fast`) | `vitest` | `FAIL <file> > <suite> > <test>` blocks, `<Type>: <msg>`, ` ❯ <file>:<l>:<c>` own frames; `Tests  N failed`; coverage `ERROR: Coverage for <metric> (<a>%) does not meet global threshold (<b>%)` → kind `coverage` |
| | ESLint stylish (`lint`) | `eslint` | a file line followed by `  <l>:<c>  error  <msg>  <rule>` lines; `✖ N problems` |
| | tsc (`typecheck`) | `tsc` | `<file>(<l>,<c>): error TS<n>: <msg>` and `<file>:<l>:<c> - error TS<n>: <msg>` |
| | next build (`build`, image build) | `next-build` | `Failed to compile.` + `<file>:<l>:<c>` + `Type error: <msg>` / module-not-found blocks |
| gitops-app | the template scripts (`render-check`, `plan-check`, `validate`, `service-crds`, `upgrade-check`) | `gitops-scripts` | `ERROR: <file>[:<where>]: <msg>` lines; render.py's drift list after `rendered files are out of date` (one entry per file, kind `render-drift`) |
| | kustomize (`validate`) | `kustomize` | `Error: <msg>` after the script's `kustomize build <dir>` line (locator `<dir>`) |
| | kubeconform (`validate`) | `kubeconform` | `<file> - <Kind> <name> is invalid: <msg>` / `failed validation: <msg>`; `Summary: …, Invalid: N, Errors: M` |
| | Kyverno (`policy-check`, `validate`) | `kyverno` | `POLICY VIOLATION in <dir> (<env>):` blocks; per indented `policy <p> -> resource <r> failed:` + `<rule>: <msg>` |
| service-python, service-java, service-go, web-nextjs | docker build (`image-build`) | `docker-build` | BuildKit `ERROR: failed to solve: <msg>` / `ERROR [<stage> <n>/<m>] <step>` with `Dockerfile:<l>` and its `----` excerpt; `process "<cmd>" did not complete successfully: exit code: <n>` |

Anything else, including the security scripts (pip-audit, detect-secrets, bandit, govulncheck, trivy, OWASP) and the cluster-gitops
template (spec changelog, 2026-10-28), is `format: unknown`.

### `cplat quiet [--raw] <devbox-script>` (AC-108.1, AC-108.10)

- Accepted argv: `[<script>]` or `["--raw", <script>]`; anything else is the usage error (exit 2) as today.
- Success: unchanged (AC-100.12).
- Failure, summaries on: `failsum.summarize(log text, title=<today's FAILED line>, check=<script>, command="devbox run <script>",
  exit_code=rc, log=<log>, root=cwd).render()`, printed; `write_sidecar(log, summary)`. Exit code passes through.
- Failure, summaries off (setting or `--raw`): `failsum.raw(...)`.
- An invalid `failure_summary` value: `ERROR: <message>` on stderr and exit 2 before the script runs.

### `.platform-settings.yml` (AC-108.10)

```yaml
failure_summary: off     # on (default) | off; YAML true/false accepted
```

`settings.failure_summary(repo: Path) -> tuple[bool, str]`: `(True, "")` when the project file or the key is missing; `(False,
".platform-settings.yml failure_summary: off")` for `off`/`false`; any other value raises `PlatformError(f"{path}: failure_summary must
be on or off, got '<value>'")`. The personal settings file is not read for this key.

### CI fix rounds (AC-108.8)

- `ship.red_summary(repo, pr, cs, failed) -> tuple[list[str], Summary | None]`; `ship.red(...)` returns its lines (callers unchanged).
- Per run of the failed checks: one `gh run view <id> -R <slug> --log-failed`. A check's lines are those whose first tab column equals
  the check name, else all lines of its run. They are written raw to `quiet._log_path(repo, "ci-<slug of check name>")` before
  summarizing.
- Summaries off: today's `failure_logs` output plus the `summaries: off (…)` line; logs are not saved.

### Spec 102 (AC-108.9)

```python
budget.normalise = failsum.normalise
budget.attempt(repo, stage, error, failing, names=None, *, normalized: str | None = None) -> str | None
    # normalized given: it is the text that is signed and stored (redacted, first 400 chars), instead of normalise(last 40 lines)
budget.snapshot(repo, stage, excerpt, criteria=(), *, summary: str | None = None) -> Path | None
    # summary given: "excerpt" = feedback.redact(summary), whole (≤ 80 lines); else as today
ship.escalate(..., summary: str | None = None)    # passes it to snapshot
```

- `ship.land` red: `attempt(..., normalized=s.normalized())`, and on a no-progress stop `escalate(..., evidence=text, summary=text)`
  where `text` is the rendered summary.
- `cplat budget attempt <stage> --error-file F`: when `failsum.read_sidecar(F)` exists it uses its `normalized` for `attempt` and its
  `text` as the evidence and snapshot summary; without one (summaries off, or another file) it behaves as today.
- `ship.run_ci` red: the log goes to `quiet._log_path(repo, "ship-ci")`, the summary (or raw text) is the `PlatformError` message, and
  the sidecar is written.

### Benchmark `cplat platform runs benchmark fix-rounds` (AC-108.11)

- `tasks.json` gets workflow `fix-rounds`: `task_version: 1`, `prompt: "/component:build 901"`, `max_runs: 2`, `max_minutes: 90`,
  `seed: "seeds/fix-rounds.json"`, no `spec_file`. `EXPECTED["fix-rounds"] = "open"`. `--arm` and `--compare-validation` are refused
  for it (`PlatformError`); it always runs two passes.
- Seed `benchmark/seeds/fix-rounds.json`, arm-shaped (`name`, `files`: repo path → content): `docs/specs/901-<slug>/spec.md` (status
  approved, one criterion the pinned sample already meets), its `plan.md` (one task, `done: true`, the spec hash of that spec), the
  tagged acceptance test, and the pinned files changed so that exactly one existing non-acceptance test fails and `ruff check` reports
  exactly one finding (mypy stays green). It is staged, committed and pushed to main like an arm (`stage_arm`, `push_arm`); the reset
  removes it.
- Pass 1 `on`: the seed as is. Pass 2 `off`: the sample reset and prepared again, the seed plus `.platform-settings.yml` with
  `failure_summary: off\n`. Both passes always run.
- Per pass: `outcome` and `result_check` (as today), `fix_rounds` (the number of `fix-round` events in the `agents` sections of the
  pass's child records, spec 089), `fixing` (`tokens`, `cost_usd`: the sum of the `by_role` entries whose role ends in `:coder` or
  `:quality` in the pass's usage window), `total` (`tokens`, `cost_usd` of the pass), `gates_failed` (gate names recorded `failed` in the
  pass's child records).
- Record: `benchmark.summary_compare = {"passes": [<pass on>, <pass off>], "verdict": null | "<reason>"}`.
- Output after today's lines, one per pass:
  `  summaries <on|off>: <outcome>, fix rounds <n>, fixing agents <tokens> tokens est. USD <cost>, total <tokens> tokens est. USD <cost>`,
  then `  summaries: <reason>` when the verdict is not null.
- Exit 1 exactly when the verdict is not null: `summaries pass not done`, `gate failed with summaries: <names>`, or
  `more fix rounds with summaries (<a>) than without (<b>)`; else 0. No savings target.

## Seed check (2026-10-28)

The seed was applied to a clone of `ika100/todo-api@9cba320` and checked through devbox: `devbox run test-fast` has exactly one
failure, `tests/unit/test_validation.py::test_parse_id` (`tests/test_ac_901.py` passes); `devbox run lint` reports exactly one
finding, F401 (`os` imported but unused); `devbox run typecheck` is clean; `cplat spec check` is OK and `cplat spec hash 901` is
`f7e886e34fd7`, the plan's `spec_hash`. So `/component:build 901` starts in Phase 3 with one failing test and one lint finding.

## Risks

- **pytest `-q --tb=line` (the Python `test-fast`) prints only the crash location.** When that is in a library, the log has no
  own-code line; the entry then names the test file from its id without a line (`<id> at tests/test_x.py`). The long traceback of
  `devbox run test` (in `ci`) carries own frames.
- **devbox's marker text is an assumption about devbox's output.** If a devbox version prints none, a `ci` log is one check named `ci`
  with every parser's entries in it; nothing is lost, only the check names are coarser. The parser tests pin the marker line; t1
  confirms it against the devbox in this repo's devbox environment.
- **Tool output drifts with versions.** A changed format degrades to `format: unknown`, today's output. Each parser has sample-log tests.
- **Fix rounds in the benchmark are spec 089's metric.** A lint hand-back to the quality agent in build Phase 3 is not a recorded fix
  round; its cost shows in the `quality` role's tokens. The comparison of rounds is therefore of coder rounds.
- **The no-progress reason (AC-102.9) still carries up to 200 characters of the normalized message to the run store.** That is spec
  102's reason text, not the summary or the log (AC-108.7).
