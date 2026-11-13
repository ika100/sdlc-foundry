# Design — 197 The journey 13 seams

## Decisions

- **The reviewed step reads commit subjects itself** instead of `git log --grep="acceptance tests for <spec id>"`, because
  the tester's documented subject `test(<slug>): acceptance tests for AC-<NNN>.1–AC-<NNN>.<n>` carries no spec id
  (A1). The rule lives in `testreview.py` only; `cplat spec test-diff`, `testdiff_select` and the build unit check
  (`units._acceptance_commit`) keep their own rules (non-goal) (AC-197.1).
- **A merged-away task resolves through the run record's `task-merge` events**, followed to the end of the chain, and
  the finding is recorded on the final task with a `note` (A2). The plan no longer knows the old id, the run record
  does, so no plan field is added (AC-197.2).
- **One helper in `model.py` owns the Grafana location** (`grafana_url`, `grafana_location`), next to `_url`, and both
  share a new `local_port()`, so the port rule of component URLs and of Grafana can never drift (A3). `system set` and
  `system status` call it (AC-197.3, AC-197.4).
- **The web release step gains `--no-git-checks`**: pnpm 11's own `pnpm version` refuses a dirty tree before it looks
  at `--no-git-tag-version`, and the step runs after the changelog is written, so reordering the steps would not make
  the documented step work in the state the AC fixes (A5). If the scratch-repo test shows pnpm 11.22.0 rejects the flag,
  the coder uses `devbox run -- pnpm pkg set version=<NEXT_DEV>` instead and names it in the task report (AC-197.5).
- **Generated repos get their per-test limits from `scripts/gate.sh`**, the platform-owned wrapper every Python, Java and
  Go `test`/`test-fast` recipe already runs through, and only through environment variables, so no build file, recipe
  or argv changes and `/platform:update` carries it to existing repos (A9) (AC-197.6 to AC-197.8):
  - pytest: a stdlib-only plugin `scripts/pytest_limit/platform_test_limit.py` (no pytest-timeout dependency, because
    `pyproject.toml` is project-owned), loaded with `PYTEST_ADDOPTS=-p platform_test_limit` and its own directory on
    `PYTHONPATH` (prepended, as spec 185's quiet does, so no `scripts/*.py` module shadows a repo's own).
  - Maven: `MAVEN_ARGS=-Djunit.jupiter.execution.timeout.default=120s` (Maven 3.9 reads `MAVEN_ARGS`; Surefire and
    Failsafe pass user properties into the forked JVM, where JUnit reads them as configuration parameters; the default
    covers test and lifecycle methods).
  - Go: `GOFLAGS=-timeout=5m` (go test's per-binary limit; a `-timeout` on the command line overrides GOFLAGS).
- **Java uses JUnit's `SAME_THREAD` timeout mode** (the default): it interrupts the test after 120 s. `SEPARATE_THREAD`
  would also stop code that ignores interrupts, but it runs the test body in another thread, which breaks Spring's
  thread-bound test transactions and would change passes of suites without a hung test (AC-197.6's last clause). A test
  stuck in code that ignores interrupts (a plain blocking socket read) still runs until `cplat quiet`'s 9-minute limit.
- **A repo's own limit wins** (A9): gate.sh adds nothing for a runner where the repo already sets one (see Contract), and
  the pytest plugin steps aside where pytest-timeout is configured.
- **The cross-cutting part gets an ADR** in t6 (`cplat adr add`): generated repos bound test time through gate.sh
  (120 s per Python/Java test, 5 min per Go package), extending [ADR-108](../../adr/108-test-time-is-bounded.md).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/testreview.py` | `_acceptance(repo, spec, head)` subject rule; `commit` uses it | changed |
| `scripts/cplat/runs_agents.py` | `_merged_into(rec)`, `_resolve(map, tid)`; `findings` records merged-away deviations | changed |
| `scripts/cplat/model.py` | `local_port()`, `grafana_url(host)`, `grafana_location(host)`; `_url` uses `local_port()` | changed |
| `scripts/cplat/systemset.py` | Grafana line and `grafana_url` | changed |
| `scripts/cplat/status.py` | `grafana_url` in the observability cell, its table text | changed |
| `plugins/web/agents/release.md`, `docs/rules/plugins/web/agents/release.yml` | the version step, its register entry | changed |
| `templates/gitops-app/scripts/gate.sh` (+ 6 synced copies) | the per-runner limit variables | changed |
| `templates/service-python/scripts/pytest_limit/platform_test_limit.py` (+ copy in library-python) | the pytest plugin | new |
| `scripts/sync-template-copies.py` | the plugin's copy pair | changed |

## Contract

### Reviewed step (AC-197.1)

```python
# testreview.py
def _acceptance(repo: Path, sp, head: str = "HEAD") -> list[str]
    # non-merge commits in _range(repo, head), newest first, whose SUBJECT
    #   contains "acceptance tests for", does not contain "reviewed acceptance tests for", and
    #   contains sp.id  or  matches (?<![\w-])AC-<sp.number>\.
```

`commit` calls `_acceptance` where it called `_find(repo, sp.id, ACCEPTANCE_MSG, "HEAD")`; when it is empty it raises
the existing `PlatformError("no commit 'acceptance tests for <spec id>' on this branch", hint=…)` (exit 1, no commit).
`reviewed_commit` and the reviewed subject `test(<number>): reviewed acceptance tests for <spec id>` are unchanged.

### Merged-away deviation (AC-197.2)

`findings`: for each `--deviation d` that is no AC id and not a plan task id, look `d` up in the map
`{ev["task"]: ev["into"]}` of every `task-merge` event in `rec0["agents"][*]["events"]`; follow it while the target is
itself a key (a visited set stops a cycle). When the final target `t` is a plan task, record:

```json
{"criterion": null, "task": "t3", "severity": "deviation", "pass": "first", "cycle": 1, "tasks": ["t3"],
 "note": "named as t1 (merged into t3)"}
```

No problem is recorded, so no WARNING and the metrics stay complete. Otherwise (no merge entry, or the chain ends
outside the plan) the existing `malformed: deviation '<d>'` problem is recorded. Natural key unchanged
(`cycle, severity, task`).

### Grafana location (AC-197.3, AC-197.4)

```python
# model.py
GRAFANA_HOST = "grafana.localhost"
GRAFANA_ELSEWHERE = "answers only at grafana.localhost on that cluster's Gateway (no public URL)"
def local_port() -> int                      # LOCAL_HTTP_PORT when all digits, else DEFAULT_LOCAL_PORT (8088)
def grafana_url(host: str | None) -> str | None
    # f"http://grafana.localhost:{local_port()}/" when host ends with ".localhost", else None
def grafana_location(host: str | None) -> str  # grafana_url(host) or GRAFANA_ELSEWHERE
```

The host is the environment's `host` template as written (e.g. `{component}.{system}-dev.localhost`); no host counts as
non-local.

`cplat system set --env E --observability V`:
- `V == "lgtm"`: host = `--host` when given, else `environments.E.host`. Text output (dry run and real run, with or
  without `--pr`): after the report, an empty line and `Grafana: <grafana_location(host)>`, e.g.
  `Grafana: http://grafana.localhost:8088/` or
  `Grafana: answers only at grafana.localhost on that cluster's Gateway (no public URL)`.
- `V in ("none", "off")`: no Grafana line.
- `--json` (every path where `--observability` was given, the no-op path included): top-level `"grafana_url"`: the URL,
  or `null` (non-local, `none`, `off`). Without `--observability` the key is absent.

`cplat system status`: an environment gets an `observability` resource cell when it has an observability block and
either has instances (as today) or `ui: lgtm`. For `ui: lgtm` the cell is
`{"argo": "<state>", "grafana_url": "<url>" | null}`; other cells have no `grafana_url` key. Table text of such a cell:
`argo <state>  Grafana <grafana_location(host)>`.

### Web release version step (AC-197.5)

```bash
devbox run -- pnpm version <NEXT_DEV> --no-git-tag-version --no-git-checks
```

The prose gets a reason clause (the step runs with the new `CHANGELOG.md` uncommitted, which pnpm would otherwise
refuse); register entry `R10`, `class: practice`, `source: spec 197`, `text` a quote of that sentence. The prompt's
bytes do not grow (rule 6): tighten other sentences of the same file and update their register `text`.

### Per-test limits (AC-197.6 to AC-197.8)

`gate.sh tests <gate> <runner> -- <command>`, before running the command; argv is never changed:

| runner | applies when | sets | skipped when |
|---|---|---|---|
| pytest | `scripts/pytest_limit/platform_test_limit.py` exists | `PYTHONPATH=<abs>/scripts/pytest_limit[:<old>]`, `PYTEST_ADDOPTS=<old> -p platform_test_limit` | never (the plugin decides) |
| maven | always | `MAVEN_ARGS=<old> -Djunit.jupiter.execution.timeout.default=120s` | `junit.jupiter.execution.timeout.default` appears in the command's args, `$MAVEN_ARGS`, `$MAVEN_OPTS`, `pom.xml` or `src/test/resources/junit-platform.properties` |
| go | always | `GOFLAGS=<old> -timeout=5m` | `-timeout` appears in `$GOFLAGS` (one on the command line wins over GOFLAGS by itself) |
| vitest | — | nothing | — |

pytest plugin (stdlib + pytest only, no Jinja delimiters `{{`, `{%`, `{#`, because both Python templates render every
file through Jinja):

```python
LIMIT_S = 120
def pytest_runtest_protocol(item, nextitem)   # hookwrapper: arms SIGALRM (setitimer) for setup+call+teardown, disarms after
```

- Steps aside (arms nothing) for the whole session when pytest-timeout is active with a timeout > 0 (its `--timeout`
  option, `timeout` ini value or `PYTEST_TIMEOUT`), and for a test with a `timeout` marker; also where `signal.SIGALRM`
  is missing, outside the main thread, or when SIGALRM already has a non-default handler (another tool owns it).
- On expiry the handler raises `pytest.fail.Exception(f"Timeout (>120s): {item.nodeid} ran past the per-test limit of 120 s")`
  and re-arms for another `LIMIT_S`, so a teardown that also blocks is stopped too. pytest reports the test in its
  `FAILED`/`ERROR` line with that text; the run goes on with the next test and exits 1.
- The previous handler and timer state are restored after each test, so a suite without a hung test behaves as before.

Maven/JUnit report: `<method>() timed out after 120 seconds` for the test in Surefire's summary; Go:
`panic: test timed out after 5m0s` followed by `running tests:` and the test name, the package `FAIL`s, the run exits
non-zero.
